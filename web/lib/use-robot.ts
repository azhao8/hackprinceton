"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { FakeRobot } from "./fake-robot";
import { parseServerMessage, type AgentEvent, type ClientMessage, type MemoryView, type Status, type Telemetry } from "./messages";

/** "sample" is the in-browser fake robot (NEXT_PUBLIC_SERVER_WS_URL=sample). */
export type Connection = "sample" | "connecting" | "open" | "closed";

export interface Sample {
  /** performance.now() when the message arrived, ms. */
  at: number;
  /** Pitch, degrees. */
  pitch: number;
  vl: number;
  vr: number;
}

export interface RobotView {
  connection: Connection;
  telemetry: Telemetry | null;
  status: Status | null;
  history: Sample[];
  /** performance.now() when this view was taken, ms. */
  now: number;
  /** Arrival time of the latest telemetry, ms, or null if none yet. */
  lastAt: number | null;
  /** The voice agent's latest events (newest last), since this page connected. */
  agent: AgentEvent[];
  /** What Miguel knows, after the page asked for it (memory_get) or changed it. */
  memory: MemoryView | null;
}

/** The server's WebSocket. Default: the server on this laptop. "sample" uses the in-browser fake robot. */
export const SERVER_WS_URL = process.env.NEXT_PUBLIC_SERVER_WS_URL || "ws://localhost:8080/ws";
const SAMPLE = SERVER_WS_URL === "sample";

export const HISTORY_S = 10;
const RENDER_MS = 50; // UI refresh, independent of how fast telemetry arrives
const FAKE_HZ = 20;
const RECONNECT_MS = 1000;

const EMPTY_VIEW: RobotView = {
  connection: SAMPLE ? "sample" : "connecting",
  telemetry: null,
  status: null,
  history: [],
  now: 0,
  lastAt: null,
  agent: [],
  memory: null,
};

export function useRobot() {
  const [view, setView] = useState<RobotView>(EMPTY_VIEW);
  const [sendFailed, setSendFailed] = useState(false);
  const sendRef = useRef<(msg: ClientMessage) => boolean>(() => false);

  useEffect(() => {
    let connection: Connection = EMPTY_VIEW.connection;
    let latest: Telemetry | null = null;
    let status: Status | null = null;
    let lastAt: number | null = null;
    const history: Sample[] = [];
    let agent: AgentEvent[] = [];
    let memory: MemoryView | null = null;

    const record = (tel: Telemetry) => {
      const at = performance.now();
      latest = tel;
      lastAt = at;
      history.push({ at, pitch: tel.pitch, vl: tel.vl, vr: tel.vr });
      const cutoff = at - HISTORY_S * 1000;
      let drop = 0;
      while (drop < history.length && history[drop].at < cutoff) drop++;
      if (drop > 0) history.splice(0, drop);
    };

    let stopSource: () => void;

    if (SAMPLE) {
      const robot = new FakeRobot(Date.now());
      sendRef.current = (msg) => {
        robot.receive(msg);
        return true;
      };
      const tick = setInterval(() => record(robot.step(1 / FAKE_HZ)), 1000 / FAKE_HZ);
      stopSource = () => clearInterval(tick);
    } else {
      let ws: WebSocket | null = null;
      let retry: ReturnType<typeof setTimeout> | undefined;
      let stopped = false;

      const connect = () => {
        connection = "connecting";
        const socket = new WebSocket(SERVER_WS_URL);
        ws = socket;
        socket.onopen = () => {
          connection = "open";
          socket.send(JSON.stringify({ t: "memory_get" }));
        };
        socket.onmessage = (event) => {
          if (typeof event.data !== "string") return;
          const msg = parseServerMessage(event.data);
          if (msg?.t === "tel") record(msg);
          else if (msg?.t === "status") status = msg;
          else if (msg?.t === "agent") agent = [...agent.slice(-39), msg];
          else if (msg?.t === "memory") memory = msg;
          else if (msg?.t === "agent_clear") agent = [];
        };
        socket.onclose = () => {
          connection = "closed";
          status = null;
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
      setView({ connection, telemetry: latest, status, history: history.slice(), now: performance.now(), lastAt, agent, memory });
    }, RENDER_MS);

    return () => {
      clearInterval(render);
      stopSource();
      sendRef.current = () => false;
    };
  }, []);

  /** Send one message to the server. Returns false (and shows a warning) if there's no connection. */
  const send = useCallback((msg: ClientMessage) => {
    const sent = sendRef.current(msg);
    setSendFailed(!sent);
    return sent;
  }, []);

  return { ...view, sendFailed, send };
}
