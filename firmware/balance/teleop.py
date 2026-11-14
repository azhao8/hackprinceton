#!/usr/bin/env python3
"""Drive the balancing robot from the laptop keyboard over Wi-Fi.

Uses the team contract: UDP port 4210, JSON {"t":"cmd","v":..,"w":..,"mode":"drive"} at 20 Hz,
and shows the robot's {"t":"tel",...} telemetry. Standard library only.

Run:   python3 teleop.py                 (finds the robot as balancebot.local)
       python3 teleop.py 172.20.10.5     (or give the IP the robot printed on the serial port)

Keys:  g          start balancing while you hold it upright
       p          park: lean onto the kickstand, motors off
       u          self stand-up from the kickstand: disabled while the phone is mounted
       w / s      faster forward / backward (steps of 0.05 m/s, max 0.3)
       a / d      turn left / right (steps of 0.25 rad/s, max 1.5)
       space      stop: speed and turn to 0, it holds position
       l / r      turn exactly 90 degrees left / right (gyro)
       x          motors off
       q          quit (also turns the motors off)
If this program stops sending for 0.3 s, the robot stops driving and holds position by itself.
"""
import curses
import json
import socket
import sys
import time

HOST = sys.argv[1] if len(sys.argv) > 1 else "balancebot.local"
PORT = 4210


def main(stdscr):
    curses.curs_set(0)
    stdscr.nodelay(True)
    try:
        ip = socket.gethostbyname(HOST)
    except OSError:
        raise SystemExit(f"Can't find {HOST}. Pass the robot's IP instead: python3 teleop.py <ip>")
    addr = (ip, PORT)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)

    v = w = 0.0
    tel, tel_time, msg = {}, 0.0, "Hold it upright and press g to start balancing."
    last_send = 0.0
    while True:
        k = stdscr.getch()
        if k in (ord("q"), ord("Q")):
            sock.sendto(b'{"t":"cmd","v":0,"w":0,"mode":"idle"}', addr)
            break
        elif k in (ord("w"), curses.KEY_UP):
            v = min(round(v + 0.05, 2), 0.3)
        elif k in (ord("s"), curses.KEY_DOWN):
            v = max(round(v - 0.05, 2), -0.3)
        elif k in (ord("a"), curses.KEY_LEFT):
            w = min(round(w + 0.25, 2), 1.5)
        elif k in (ord("d"), curses.KEY_RIGHT):
            w = max(round(w - 0.25, 2), -1.5)
        elif k == ord(" "):
            v = w = 0.0
        elif k in (ord("g"), ord("G")):
            v = w = 0.0
            sock.sendto(b"g", addr)
            msg = "Sent g (start balancing)."
        elif k == ord("u"):                             # self stand-up ("G") is disabled while the phone is mounted
            msg = "Self stand-up is disabled with the phone on. Hold it upright and press g."
        elif k == ord("p"):
            v = w = 0.0
            sock.sendto(b"P", addr)
            msg = "Parking on the kickstand."
        elif k in (ord("x"), ord("X")):
            v = w = 0.0
            sock.sendto(b"x", addr)
            msg = "Sent x (motors off)."
        elif k == ord("l"):
            sock.sendto(b"L", addr)
            msg = "Turning 90 left."
        elif k == ord("r"):
            sock.sendto(b"R", addr)
            msg = "Turning 90 right."

        now = time.time()
        if now - last_send >= 0.05:                     # 20 Hz keeps the robot's 300 ms watchdog fed
            sock.sendto(json.dumps({"t": "cmd", "v": v, "w": w, "mode": "drive"}).encode(), addr)
            last_send = now
        try:
            while True:
                data, _ = sock.recvfrom(512)
                tel, tel_time = json.loads(data), now
        except (BlockingIOError, ValueError):
            pass

        stdscr.erase()
        stdscr.addstr(0, 0, f"Robot {HOST} ({ip}:{PORT})")
        stdscr.addstr(2, 0, f"Command:  speed {v:+.2f} m/s   turn {w:+.2f} rad/s")
        if tel:
            age = now - tel_time
            stdscr.addstr(3, 0, f"Robot:    state {tel.get('state')}   fault {tel.get('fault')}   "
                                f"pitch {tel.get('pitch', 0):+.1f} deg   x {tel.get('x', 0):+.2f} m   "
                                f"yaw {tel.get('yaw', 0):+.0f} deg   ({age*1000:.0f} ms ago)")
        else:
            stdscr.addstr(3, 0, "Robot:    no telemetry yet")
        stdscr.addstr(5, 0, "g start (hold it upright)   p park   w/s speed   a/d turn   space stop   l/r 90 deg   x motors off   q quit")
        stdscr.addstr(7, 0, msg)
        stdscr.refresh()
        time.sleep(0.01)


if __name__ == "__main__":
    curses.wrapper(main)
