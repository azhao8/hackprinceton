#!/usr/bin/env python3
"""Check the laptop-robot link: do commands reach the robot, how fast, how many get lost?

Sends {"t":"cmd","seq":N,"mode":"balance"} 20 times a second and watches the "ack" in the robot's
telemetry. "balance" never starts the motors: when the robot isn't balancing it does nothing, and
when it is, it means "stop and hold here". Still, only run it when someone is at the robot.
Standard library only.

Run:   python3 linktest.py                       Wi-Fi (UDP 4210), finds balancebot.local
       python3 linktest.py --udp 172.20.10.5     Wi-Fi, by IP
       python3 linktest.py --serial              USB; finds /dev/cu.usbmodem* (stop drive.py first)
       python3 linktest.py --serial /dev/cu.usbmodem1101 --seconds 10

It prints the last command acknowledged, the round-trip lag, and PASS if the last command got through.
The robot echoes only its latest seq, so skipped numbers can mean timing as well as loss.
Over USB the robot only sends JSON telemetry when asked, so this sends "J" after every command.
"""
import argparse
import glob
import json
import os
import select
import socket
import statistics
import sys
import termios
import time

RATE_HZ = 20
PORT = 4210


class UdpLink:
    def __init__(self, host):
        self.addr = (socket.gethostbyname(host), PORT)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setblocking(False)

    def send(self, text, ask_tel=False):  # the robot sends telemetry by itself at 20 Hz over Wi-Fi
        self.sock.sendto(text.encode(), self.addr)

    def lines(self, timeout):
        out = []
        r, _, _ = select.select([self.sock], [], [], timeout)
        while r:
            data, _ = self.sock.recvfrom(2048)
            out.append(data.decode(errors="replace"))
            r, _, _ = select.select([self.sock], [], [], 0)
        return out


class SerialLink:
    def __init__(self, path):
        self.fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        a = termios.tcgetattr(self.fd)
        a[0] = 0; a[1] = 0; a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL; a[3] = 0
        a[4] = a[5] = termios.B115200
        termios.tcsetattr(self.fd, termios.TCSANOW, a)
        self.buf = b""

    def send(self, text, ask_tel=False):
        os.write(self.fd, (text + "\n" + ("J" if ask_tel else "")).encode())

    def lines(self, timeout):
        r, _, _ = select.select([self.fd], [], [], timeout)
        if r:
            try:
                self.buf += os.read(self.fd, 4096)
            except BlockingIOError:
                pass
        *done, self.buf = self.buf.split(b"\n")
        return [d.decode(errors="replace").strip() for d in done]


def parse_tel(line):
    if not line.startswith("{"):
        return None
    try:
        msg = json.loads(line)
    except json.JSONDecodeError:
        return None
    return msg if msg.get("t") == "tel" else None


def run(link, seconds):
    sent = {}          # seq -> time sent
    lags = []          # seconds, for each seq first seen as ack
    best_ack = 0
    tel_count = 0
    no_ack_field = False
    seq = 0
    period = 1.0 / RATE_HZ
    end = time.time() + seconds
    next_send = time.time()
    while time.time() < end + 0.5:            # half a second extra to collect the last acks
        now = time.time()
        if now >= next_send and now < end:
            seq += 1
            link.send(json.dumps({"t": "cmd", "seq": seq, "mode": "balance"}, separators=(",", ":")), ask_tel=True)
            sent[seq] = now
            next_send += period
        for line in link.lines(max(0.0, min(next_send - time.time(), 0.02))):
            tel = parse_tel(line)
            if tel is None:
                continue
            tel_count += 1
            if "ack" not in tel:
                no_ack_field = True
                continue
            ack = int(tel["ack"])
            if ack > best_ack:
                if ack in sent:
                    lags.append(time.time() - sent[ack])
                best_ack = ack
    return seq, best_ack, tel_count, lags, no_ack_field


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--udp", nargs="?", const="balancebot.local", metavar="HOST", help="Wi-Fi (default)")
    g.add_argument("--serial", nargs="?", const="auto", metavar="PORT", help="USB serial")
    ap.add_argument("--seconds", type=float, default=5.0)
    args = ap.parse_args()

    if args.serial:
        path = args.serial
        if path == "auto":
            ports = sorted(glob.glob("/dev/cu.usbmodem*"))
            if not ports:
                sys.exit("No /dev/cu.usbmodem* found. Is the robot plugged in?")
            path = ports[0]
        link, where = SerialLink(path), path
    else:
        host = args.udp or "balancebot.local"
        link, where = UdpLink(host), f"{host}:{PORT}"

    print(f"Link test over {where} for {args.seconds:.0f} s ({RATE_HZ} commands a second, mode balance)...")
    sent, best_ack, tel_count, lags, no_ack_field = run(link, args.seconds)

    print(f"  sent {sent} commands, got {tel_count} telemetry messages")
    if tel_count == 0:
        print("FAIL: no telemetry at all. Wrong address or port, robot off, or (USB) drive.py still holds the port.")
        return 1
    if no_ack_field and best_ack == 0:
        print("FAIL: telemetry has no \"ack\". The robot runs firmware from before seq/ack; upload the current balance.ino.")
        return 1
    if best_ack == 0:
        print("FAIL: telemetry arrives but ack stays 0. Commands are not reaching the robot.")
        return 1
    print(f"  last ack {best_ack} of {sent} sent; {len(lags)} different acks seen")
    if lags:
        lags_ms = sorted(x * 1000 for x in lags)
        p95 = lags_ms[min(len(lags_ms) - 1, int(len(lags_ms) * 0.95))]
        print(f"  round-trip lag: median {statistics.median(lags_ms):.0f} ms, 95% under {p95:.0f} ms")
    ok = best_ack == sent
    print("PASS" if ok else "FAIL: the latest commands never got acknowledged; the link is dropping or lagging.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
