"""Follow-me runner: camera or clip -> YOLO pose -> target lock -> follow controller -> drive.py.

Run it yourself in Terminal (macOS only gives the camera to programs a person starts):

    cd server
    uv run python -m app.vision.run --source 0            # live camera, dry run (never drives)
    uv run python -m app.vision.run --source clip.mov     # a recorded clip
    uv run python -m app.vision.run --source 0 --drive    # posts to drive.py /auto (see below)

Keys in the window: F = lock onto the person nearest the center / let go,
Space = let go and stop, S = save a snapshot, Q or Esc = quit.

--drive sends speed and turn to John's drive.py (http://127.0.0.1:8765/auto) on the
same Mac. drive.py only passes them to the robot while Follow is ON on its page,
held keys override, and X stops it. Only use --drive when someone is at the robot
and ready to catch it (team safety rule, firmware/README.md "Safety rules").
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import cv2
import numpy as np

from .detector import YoloPoseDetector
from .drive_bridge import DriveBridge
from .follow import CameraGeometry, FollowController, FollowConfig
from .frames import open_source
from .tracking import TargetLock
from .types import DriveCommand, Frame, Person, TargetState, TargetStatus

# Body points worth drawing from 40 cm up (hips down), and the leg lines between them.
LEG_POINTS = ("left_hip", "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle")
LEG_LINES = (("left_hip", "left_knee"), ("left_knee", "left_ankle"),
             ("right_hip", "right_knee"), ("right_knee", "right_ankle"))

GREEN, GRAY, ORANGE, WHITE, RED = (60, 220, 60), (160, 160, 160), (0, 165, 255), (255, 255, 255), (60, 60, 230)


def _px(x: float, y: float, w: int, h: int) -> tuple[int, int]:
    return int(x * w), int(y * h)


def draw_person(img: np.ndarray, p: Person, color: tuple[int, int, int], thick: int) -> None:
    h, w = img.shape[:2]
    cv2.rectangle(img, _px(p.box.x1, p.box.y1, w, h), _px(p.box.x2, p.box.y2, w, h), color, thick)
    for a, b in LEG_LINES:
        ka, kb = p.keypoint(a), p.keypoint(b)
        if ka and kb:
            cv2.line(img, _px(ka.x, ka.y, w, h), _px(kb.x, kb.y, w, h), color, 2)
    for name in LEG_POINTS:
        k = p.keypoint(name)
        if k:
            cv2.circle(img, _px(k.x, k.y, w, h), 5, color, -1)


def draw_overlay(img: np.ndarray, people: list[Person], state: TargetState, cmd: DriveCommand,
                 fps: float, det_ms: float, mode: str) -> None:
    h, w = img.shape[:2]
    target = state.person if state.status == TargetStatus.LOCKED else None
    for p in people:
        if p is not target:
            draw_person(img, p, GRAY, 2)
    if target is not None:
        draw_person(img, target, GREEN, 5)
    cv2.line(img, (w // 2, 0), (w // 2, h), WHITE, 1)  # center line

    status = state.status.value.upper()
    if state.status == TargetStatus.LOST:
        status += f" {state.lost_for_s:.1f}s"
    dist = f"{cmd.distance_m:.2f} m" if cmd.distance_m is not None else "? m"
    lines = [
        f"{mode}   {fps:4.1f} fps   detector {det_ms:3.0f} ms   people {len(people)}",
        f"target: {status}   distance {dist}",
        f"v {cmd.v:+.2f} m/s   w {cmd.w:+.2f} rad/s   {cmd.reason}",
        "F lock/unlock   Space stop   S snapshot   Q quit",
    ]
    color = {TargetStatus.LOCKED: GREEN, TargetStatus.LOST: ORANGE}.get(state.status, WHITE)
    for i, text in enumerate(lines):
        y = 34 + i * 34
        cv2.putText(img, text, (14, y), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 5, cv2.LINE_AA)
        cv2.putText(img, text, (14, y), cv2.FONT_HERSHEY_SIMPLEX, 0.9, color if i == 1 else WHITE, 2, cv2.LINE_AA)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", default="0", help="camera number (0, 1, ...) or a video file path")
    ap.add_argument("--rotate", choices=["left", "right", "180"], help="if people show up sideways")
    ap.add_argument("--drive", action="store_true", help="POST commands to drive.py /auto (someone at the robot!)")
    ap.add_argument("--turn-only", action="store_true", help="only turn toward the target, never drive forward/back")
    ap.add_argument("--camera-back", action="store_true", help="the camera faces the robot's back (Wago side)")
    ap.add_argument("--follow", action="store_true", help="lock onto the center person as soon as one is seen")
    ap.add_argument("--height-m", type=float, default=None, help="camera height above the floor (default from CameraGeometry)")
    ap.add_argument("--tilt-deg", type=float, default=None, help="camera tilt, up positive (default from CameraGeometry)")
    ap.add_argument("--no-window", action="store_true", help="print instead of showing a window")
    args = ap.parse_args(argv)

    geo_kw = {}
    if args.height_m is not None:
        geo_kw["height_m"] = args.height_m
    if args.tilt_deg is not None:
        geo_kw["tilt_deg"] = args.tilt_deg
    controller = FollowController(FollowConfig(camera=CameraGeometry(**geo_kw), turn_only=args.turn_only,
                                               camera_back=args.camera_back))
    lock = TargetLock()
    detector = YoloPoseDetector()
    print("Warming up the detector (the first run on the GPU takes several seconds)...")
    detector.detect(Frame(t=0.0, index=-1, image=np.zeros((1080, 1920, 3), dtype=np.uint8)))
    bridge = DriveBridge(dry_run=not args.drive)
    mode = ("DRIVE" if args.drive else "DRY RUN") + (" turn-only" if args.turn_only else "")
    if args.drive:
        print("DRIVE mode: posting to drive.py /auto. It only moves the robot while Follow is ON on the drive page.")
        print("Someone must be at the robot. Press X on the drive page to stop it.")

    snap_dir = Path.cwd()
    want_engage = args.follow
    fps, last_t, det_ms = 0.0, None, 0.0
    try:
        with open_source(args.source, rotate=args.rotate) as src:
            while True:
                frame = src.read_next(timeout=2.0)
                if frame is None:
                    print("No more frames (camera stopped or the clip ended).")
                    break
                dets = detector.detect(frame)
                det_ms = 0.8 * det_ms + 0.2 * dets.latency_s * 1000

                if want_engage and lock.state.status == TargetStatus.IDLE:
                    lock.engage(dets, frame.image)
                state = lock.update(dets, frame.image) if lock.state.status != TargetStatus.IDLE else lock.state

                cmd = controller.update(state, frame.t)
                target = state.person if state.status == TargetStatus.LOCKED else None
                bridge.send(cmd, found=target is not None,
                            cx=target.box.cx if target else 0.5, h=target.box.w if target else 0.0)

                if last_t is not None and frame.t > last_t:
                    fps = 0.9 * fps + 0.1 / (frame.t - last_t) if fps else 1 / (frame.t - last_t)
                last_t = frame.t

                if args.no_window:
                    if frame.index % 15 == 0:
                        print(f"{state.status.value:7s} people={len(dets.people)} v={cmd.v:+.2f} w={cmd.w:+.2f} {cmd.reason}")
                    continue
                view = frame.image.copy()
                draw_overlay(view, dets.people, state, cmd, fps, det_ms, mode)
                cv2.imshow("Miguel.exe follow", view)
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), 27):
                    break
                if key == ord("f"):
                    if lock.state.status == TargetStatus.IDLE:
                        want_engage = True
                    else:
                        want_engage = False
                        lock.disengage()
                        controller.reset()
                if key == ord(" "):
                    want_engage = False
                    lock.disengage()
                    controller.reset()
                    bridge.stop()
                if key == ord("s"):
                    path = snap_dir / f"follow-{time.strftime('%H%M%S')}.debug.jpg"
                    cv2.imwrite(str(path), view)
                    print(f"Saved {path}")
    finally:
        bridge.close()  # sends a final zero command, then ends the sender thread
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
