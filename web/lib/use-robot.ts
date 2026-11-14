"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { FakeRobot } from "./fake-robot";
import { parseServerMessage, type ClientMessage, type Telemetry } from "./messages";

/** Where telemetry comes from. "sample" is the in-browser fake robot. */
export type Connection = "sample" | "connecting" | "open" | "closed";

export interface Sample {
  /** performance.now() when the message arrived, ms. */
  at: number;
  /** Pitch in degrees, for display. */
  pitchDeg: number;
  vl: number;
  vr: number;
}

export interface RobotView {
  connection: Connection;
  telemetry: Telemetry | null;
  history: Sample[];
  /** performance.now() when this view was taken, ms. */
  now: number;
  /** Arrival time of the latest telemetry, ms, or null if none yet. */
  lastAt: number | null;
}

/** Set NEXT_PUBLIC_SERVER_WS_URL to use the server; unset uses sample telemetry. */
export const SERVER_WS_URL = process.env.NEXT_PUBLIC_SERVER_WS_URL || null;

export const HISTORY_S = 10;

export function radToDeg(rad: number): number {
  return (rad * 180) / Math.PI;
}
const RENDER_MS = 50; // UI refresh, independent of how fast telemetry arrives
const FAKE_HZ = 50; // the robot sends telemetry about 50 times a second
const RECONNECT_MS = 1000;

const EMPTY_VIEW: RobotView = {
  connection: SERVER_WS_URL ? "connecting" : "sample",
  telemetry: null,
  history: [],
  now: 0,
  lastAt: null,
};

export function useRobot() {
  const [view, setView] = useState<RobotView>(EMPTY_VIEW);
  const [estop, setEstop] = useState(false);
  const [sendFailed, setSendFailed] = useState(false);
  const sendRef = useRef<(msg: ClientMessage) => boolean>(() => false);

  useEffect(() => {
    let connection: Connection = EMPTY_VIEW.connection;
    let latest: Telemetry | null = null;
    let lastAt: number | null = null;
    const history: Sample[] = [];

    const record = (tel: Telemetry) => {
      const at = performance.now();
      latest = tel;
      lastAt = at;
      history.push({ at, pitchDeg: radToDeg(tel.pitch), vl: tel.vl, vr: tel.vr });
      const cutoff = at - HISTORY_S * 1000;
      let drop = 0;
      while (drop < history.length && history[drop].at < cutoff) drop++;
      if (drop > 0) history.splice(0, drop);
    };

    let stopSource: () => void;

    if (!SERVER_WS_URL) {
      const robot = new FakeRobot(Date.now());
      sendRef.current = (msg) => {
        robot.receive(msg);
        return true;
      };
      const tick = setInterval(() => record(robot.step(1 / FAKE_HZ)), 1000 / FAKE_HZ);
      stopSource = () => clearInterval(tick);
    } else {
      const url = SERVER_WS_URL;
      let ws: WebSocket | null = null;
      let retry: ReturnType<typeof setTimeout> | undefined;
      let stopped = false;

      const connect = () => {
        connection = "connecting";
        const socket = new WebSocket(url);
        ws = socket;
        socket.onopen = () => {
          connection = "open";
        };
        socket.onmessage = (event) => {
          if (typeof event.data !== "string") return;
          const msg = parseServerMessage(event.data);
          if (msg?.t === "tel") record(msg);
        };
        socket.onclose = () => {
          connection = "closed";
          if (!stopped) retry = setTimeout(connect, RECONNECT_MS);
        };
      };

      sendRef.current = (msg) => {
        if (ws?.readyState !== WebSocket.OPEN) return false;
        ws.send(JSON.stringify(msg));
        return true;
      };
      connect();
      stopSource = () => {
        stopped = true;
        clearTimeout(retry);
        ws?.close();
      };
    }

    const render = setInterval(() => {
      setView({ connection, telemetry: latest, history: history.slice(), now: performance.now(), lastAt });
    }, RENDER_MS);

    return () => {
      clearInterval(render);
      stopSource();
      sendRef.current = () => false;
    };
  }, []);

  /** Turn the e-stop on or off. Returns false if the message couldn't be sent. */
  const setEStop = useCallback((on: boolean) => {
    const sent = sendRef.current({ t: "estop", on });
    setSendFailed(!sent);
    if (sent) setEstop(on);
    return sent;
  }, []);

  return { ...view, estop, sendFailed, setEStop };
}
