"""Tests for the follow controller (app/vision/follow.py) and the drive bridge (app/vision/drive_bridge.py).

The bridge tests only talk to a throwaway HTTP server on an ephemeral port on 127.0.0.1,
never to drive.py's port 8765 or the robot.
"""

from __future__ import annotations

import json
import math
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.vision.drive_bridge import DEFAULT_URL, DriveBridge
from app.vision.follow import CameraGeometry, FollowConfig, FollowController, feet_point
from app.vision.types import Box, DriveCommand, Keypoint, Person, TargetState, TargetStatus

DT = 1.0 / 15.0  # the tuned detection rate

# A camera pitched down so the feet stay visible from 0.4 m out: easy numbers for the controller tests.
CAM = CameraGeometry(height_m=0.40, tilt_deg=-15.0, vfov_deg=60.0, hfov_deg=80.0)
CFG = FollowConfig(camera=CAM)


def y_for_distance(cam: CameraGeometry, d: float, point_height_m: float = 0.0) -> float:
    """Inverse of CameraGeometry.ground_distance: the image row of a floor point d meters away."""
    below_horizon = math.atan((cam.height_m - point_height_m) / d)
    below_axis = below_horizon + math.radians(cam.tilt_deg)
    return 0.5 + math.tan(below_axis) / (2.0 * math.tan(math.radians(cam.vfov_deg) / 2.0))


def person(cx: float = 0.5, d: float | None = None, w: float = 0.2, y2: float | None = None,
           ankles: dict[str, Keypoint] | None = None) -> Person:
    """A person centered at cx whose box bottom is at distance d (or at y2 given directly)."""
    if y2 is None:
        y2 = y_for_distance(CAM, d) if d is not None else 1.0
    return Person(box=Box(cx - w / 2, 0.0, cx + w / 2, y2), score=0.9, keypoints=ankles or {})


def locked(p: Person) -> TargetState:
    return TargetState(status=TargetStatus.LOCKED, person=p)


def lost(lost_for_s: float, last_seen_cx: float) -> TargetState:
    return TargetState(status=TargetStatus.LOST, lost_for_s=lost_for_s, last_seen_cx=last_seen_cx)


def run(ctrl: FollowController, state: TargetState, frames: int, t0: float = 0.0) -> DriveCommand:
    cmd = None
    for i in range(frames):
        cmd = ctrl.update(state, t0 + i * DT)
    return cmd


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


def test_known_angle_gives_known_distance():
    cam = CameraGeometry(height_m=0.40, tilt_deg=0.0, vfov_deg=60.0)
    # A point 15 deg below the axis (= below the horizon, no tilt).
    y = 0.5 + math.tan(math.radians(15)) / (2 * math.tan(math.radians(30)))
    assert cam.ground_distance(y) == pytest.approx(0.40 / math.tan(math.radians(15)))
    # The bottom edge of the frame is half the FOV (30 deg) below the axis.
    assert cam.ground_distance(1.0) == pytest.approx(0.40 / math.tan(math.radians(30)))


def test_tilt_up_is_subtracted():
    # Pitched UP 10 deg: a point 25 deg below the axis is 15 deg below the horizon.
    cam = CameraGeometry(height_m=0.40, tilt_deg=10.0, vfov_deg=60.0)
    y = 0.5 + math.tan(math.radians(25)) / (2 * math.tan(math.radians(30)))
    assert cam.ground_distance(y) == pytest.approx(0.40 / math.tan(math.radians(15)))


def test_point_height_shortens_the_drop():
    cam = CameraGeometry(height_m=0.40, tilt_deg=0.0, vfov_deg=60.0)
    assert cam.ground_distance(1.0, point_height_m=0.08) == pytest.approx(0.32 / math.tan(math.radians(30)))


def test_horizon_and_above_give_none():
    cam = CameraGeometry(height_m=0.40, tilt_deg=0.0, vfov_deg=60.0)
    assert cam.ground_distance(0.5) is None  # on the horizon
    assert cam.ground_distance(0.3) is None  # above it
    assert cam.ground_distance(0.505) is None  # just below it: too close to trust (and too far)
    # Pitched up 10 deg: below the optical axis but still above the horizon.
    assert CameraGeometry(tilt_deg=10.0, vfov_deg=60.0).ground_distance(0.55) is None


def test_out_of_range_gives_none():
    cam = CameraGeometry(height_m=0.40, tilt_deg=-60.0, vfov_deg=60.0)
    assert cam.ground_distance(1.0) is None  # 90 deg down: 0 m, closer than any sane estimate


def test_bearing_is_left_positive():
    cam = CameraGeometry(hfov_deg=60.0)
    assert cam.bearing_rad(0.5) == pytest.approx(0.0)
    assert cam.bearing_rad(1.0) == pytest.approx(-math.radians(30))
    assert cam.bearing_rad(0.0) == pytest.approx(math.radians(30))


def test_feet_prefer_lowest_confident_ankle_over_box_bottom():
    p = person(y2=0.9, ankles={
        "left_ankle": Keypoint(0.45, 0.80, 0.9),
        "right_ankle": Keypoint(0.55, 0.85, 0.9),
    })
    fp = feet_point(p)
    assert fp is not None and fp.from_ankle and fp.y == pytest.approx(0.85)


def test_feet_ignore_low_confidence_and_off_frame_ankles():
    p = person(y2=0.9, ankles={
        "left_ankle": Keypoint(0.45, 0.95, 0.2),  # not confident
        "right_ankle": Keypoint(0.55, 1.10, 0.9),  # extrapolated below the frame
    })
    fp = feet_point(p)
    assert fp is not None and not fp.from_ankle and fp.y == pytest.approx(0.9)


def test_cut_off_box_without_ankles_gives_none():
    p = person(y2=0.99)
    assert feet_point(p) is None
    assert FollowController(CFG).distance_to(p) is None


def test_distance_from_ankle_uses_ankle_height():
    d_true = 1.5
    y = y_for_distance(CAM, d_true, point_height_m=CFG.ankle_height_m)
    p = person(y2=0.99, ankles={"left_ankle": Keypoint(0.5, y, 0.9)})
    assert FollowController(CFG).distance_to(p) == pytest.approx(d_true)


# ---------------------------------------------------------------------------
# Controller: locked
# ---------------------------------------------------------------------------


def test_centered_at_target_distance_is_still():
    cmd = run(FollowController(CFG), locked(person(cx=0.5, d=CFG.d_target_m)), 20)
    assert cmd.v == pytest.approx(0.0, abs=1e-9)
    assert cmd.w == pytest.approx(0.0, abs=1e-9)
    assert cmd.reason == "following"
    assert cmd.distance_m == pytest.approx(CFG.d_target_m)


def test_small_offsets_are_in_the_dead_zones():
    cmd = run(FollowController(CFG), locked(person(cx=0.55, d=CFG.d_target_m * 1.05)), 20)
    assert cmd.v == 0.0 and cmd.w == 0.0


def test_target_right_turns_right_and_left_turns_left():
    right = run(FollowController(CFG), locked(person(cx=0.8, d=CFG.d_target_m)), 1)
    left = run(FollowController(CFG), locked(person(cx=0.2, d=CFG.d_target_m)), 1)
    assert right.w < 0
    assert left.w > 0


def test_turn_is_capped():
    cmd = run(FollowController(FollowConfig(camera=CAM, k_w=10.0)), locked(person(cx=0.95, d=1.5)), 60)
    assert cmd.w == pytest.approx(-CFG.w_max, abs=1e-6)


def test_far_drives_forward_and_is_capped():
    cmd = run(FollowController(CFG), locked(person(d=4.0)), 60)
    assert cmd.v > 0
    assert cmd.v == pytest.approx(CFG.v_max, abs=1e-6)
    assert cmd.v <= CFG.v_max
    assert cmd.distance_m == pytest.approx(4.0)


def test_twice_as_far_gives_the_tuned_speed():
    cmd = run(FollowController(CFG), locked(person(d=2 * CFG.d_target_m)), 60)
    assert cmd.v == pytest.approx(CFG.k_v, abs=1e-6)  # 0.35 m/s when twice as far as wanted


def test_too_close_backs_off():
    cmd = run(FollowController(CFG), locked(person(d=0.5)), 30)
    assert cmd.v < 0
    assert cmd.v == pytest.approx(CFG.v_back, abs=1e-6)
    assert cmd.reason == "too close: backing off"
    assert cmd.distance_m == pytest.approx(0.5)


def test_smoothing_is_0_6_previous_plus_0_4_new():
    ctrl = FollowController(CFG)
    w_cmd = -CFG.k_w * (0.8 - 0.5)
    s = locked(person(cx=0.8, d=CFG.d_target_m))
    assert ctrl.update(s, 0.0).w == pytest.approx(0.4 * w_cmd)
    assert ctrl.update(s, DT).w == pytest.approx(0.6 * 0.4 * w_cmd + 0.4 * w_cmd)


def test_smoothing_has_the_same_time_constant_at_any_frame_rate():
    s = locked(person(cx=0.8, d=3.0))
    fast = FollowController(CFG)
    for i in range(4):  # 4 frames at 15 Hz
        a = fast.update(s, i * DT)
    slow = FollowController(CFG)
    slow.update(s, 0.0)
    b = slow.update(s, 3 * DT)  # the same 0.2 s in 2 frames
    assert b.v == pytest.approx(a.v)
    assert b.w == pytest.approx(a.w)


def test_reset_forgets_smoothing():
    ctrl = FollowController(CFG)
    s = locked(person(cx=0.8, d=CFG.d_target_m))
    run(ctrl, s, 30)
    ctrl.reset()
    assert ctrl.update(s, 100.0).w == pytest.approx(0.4 * -CFG.k_w * 0.3)


def test_unknown_distance_falls_back_to_box_width():
    ctrl = FollowController(CFG)
    narrow = run(ctrl, locked(person(w=CFG.target_box_w / 2)), 60)  # feet cut off: y2 = 1.0
    assert narrow.distance_m is None
    assert narrow.v == pytest.approx(CFG.k_v, abs=1e-6)  # half the target width = twice as far
    at_target = run(FollowController(CFG), locked(person(w=CFG.target_box_w)), 30)
    assert at_target.v == 0.0
    wide = run(FollowController(CFG), locked(person(w=0.7)), 30)
    assert wide.v < 0 and wide.reason == "too close: backing off"


def test_box_cut_at_the_side_never_drives_forward():
    p = Person(box=Box(0.0, 0.0, 0.12, 1.0), score=0.9)  # narrow because it's half out of frame
    cmd = run(FollowController(CFG), locked(p), 30)
    assert cmd.v == 0.0
    assert cmd.w > 0  # still turns left to bring them into view


def test_turn_only_and_camera_back():
    far = locked(person(cx=0.8, d=3.0))
    turn_only = run(FollowController(FollowConfig(camera=CAM, turn_only=True)), far, 30)
    assert turn_only.v == 0.0 and turn_only.w < 0
    back = run(FollowController(FollowConfig(camera=CAM, camera_back=True)), far, 30)
    forward = run(FollowController(CFG), far, 30)
    assert back.v == pytest.approx(-forward.v) and back.v < 0
    assert back.w == pytest.approx(forward.w)


# ---------------------------------------------------------------------------
# Controller: lost and idle
# ---------------------------------------------------------------------------


def test_lost_holds_then_searches_toward_last_side_then_gives_up():
    ctrl = FollowController(CFG)
    run(ctrl, locked(person(cx=0.8, d=3.0)), 20)  # moving and turning

    hold = ctrl.update(lost(0.2, last_seen_cx=0.2), 2.0)
    assert (hold.v, hold.w, hold.reason) == (0.0, 0.0, "lost: holding")

    t = 2.0
    for i in range(30):  # searching: ramps up to the search turn rate, never drives
        t += DT
        cmd = ctrl.update(lost(0.6 + i * DT, last_seen_cx=0.2), t)
        assert cmd.v == 0.0 and cmd.w > 0 and cmd.reason == "lost: searching left"
    assert cmd.w == pytest.approx(CFG.search_w, rel=1e-3)

    right = FollowController(CFG).update(lost(1.0, last_seen_cx=0.8), 0.0)
    assert right.w < 0 and right.reason == "lost: searching right"

    gave_up = ctrl.update(lost(CFG.lost_hold_s + CFG.search_for_s + 0.1, last_seen_cx=0.2), t + DT)
    assert (gave_up.v, gave_up.w, gave_up.reason) == (0.0, 0.0, "lost: gave up")


def test_idle_is_zero():
    ctrl = FollowController(CFG)
    run(ctrl, locked(person(cx=0.8, d=3.0)), 20)
    cmd = ctrl.update(TargetState(status=TargetStatus.IDLE), 5.0)
    assert (cmd.v, cmd.w, cmd.reason, cmd.distance_m) == (0.0, 0.0, "idle", None)


# ---------------------------------------------------------------------------
# Drive bridge
# ---------------------------------------------------------------------------


@pytest.fixture
def server():
    """A throwaway HTTP server on an ephemeral 127.0.0.1 port that records POST bodies."""
    received: list[tuple[str, str, dict]] = []
    got = threading.Event()
    delay = {"s": 0.0}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n))
            time.sleep(delay["s"])
            received.append((self.path, self.headers.get("Content-Type"), body))
            got.set()
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *args):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = httpd.server_address[1]
    assert port != 8765
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield {"url": f"http://127.0.0.1:{port}/auto", "received": received, "got": got, "delay": delay}
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_default_bridge_is_dry_run():
    assert DriveBridge().dry_run is True
    assert DEFAULT_URL == "http://127.0.0.1:8765/auto"


def test_dry_run_never_touches_the_network(server):
    bridge = DriveBridge(url=server["url"], dry_run=True)
    bridge.send(DriveCommand(v=0.2, w=-0.3), found=True, cx=0.7, h=0.25)
    bridge.stop()
    bridge.close()
    assert not server["got"].wait(0.3)
    assert server["received"] == []
    assert bridge._thread is None
    assert list(bridge.history) == [
        {"v": 0.2, "w": -0.3, "found": True, "cx": 0.7, "h": 0.25},
        {"v": 0.0, "w": 0.0, "found": False, "cx": 0.5, "h": 0.0},
        {"v": 0.0, "w": 0.0, "found": False, "cx": 0.5, "h": 0.0},
    ]


def test_real_mode_posts_the_exact_payload(server):
    bridge = DriveBridge(url=server["url"], dry_run=False, timeout_s=2.0)
    bridge.send(DriveCommand(v=0.2, w=-0.3, reason="following", distance_m=2.0), found=True, cx=0.7, h=0.25)
    assert bridge.wait_idle(3.0)
    bridge.stop()
    assert bridge.wait_idle(3.0)
    assert server["received"] == [
        ("/auto", "application/json", {"v": 0.2, "w": -0.3, "found": True, "cx": 0.7, "h": 0.25}),
        ("/auto", "application/json", {"v": 0.0, "w": 0.0, "found": False, "cx": 0.5, "h": 0.0}),
    ]
    assert (bridge.posted, bridge.errors) == (2, 0)
    bridge.close()


def test_send_never_blocks_and_latest_command_wins(server):
    server["delay"]["s"] = 0.3  # a slow bridge
    bridge = DriveBridge(url=server["url"], dry_run=False, timeout_s=2.0)
    start = time.monotonic()
    for i in range(10):
        bridge.send(DriveCommand(v=0.01 * i, w=0.0), found=True, cx=0.5, h=0.2)
    assert time.monotonic() - start < 0.1
    assert bridge.wait_idle(3.0)
    bodies = [b for _, _, b in server["received"]]
    assert 1 <= len(bodies) <= 2  # the one in flight (maybe) and the newest; the rest were replaced
    assert bodies[-1]["v"] == pytest.approx(0.09)
    bridge.close()


def test_network_error_does_not_raise():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()  # nothing listens here now: connection refused
    assert port != 8765
    bridge = DriveBridge(url=f"http://127.0.0.1:{port}/auto", dry_run=False, timeout_s=0.2)
    bridge.send(DriveCommand(v=0.1, w=0.0), found=True, cx=0.5, h=0.2)
    assert bridge.wait_idle(3.0)
    assert (bridge.posted, bridge.errors) == (0, 1)
    bridge.stop()
    bridge.close()
    assert bridge.errors >= 2


def test_timeout_counts_as_an_error(server):
    server["delay"]["s"] = 0.5
    bridge = DriveBridge(url=server["url"], dry_run=False, timeout_s=0.1)
    bridge.send(DriveCommand(v=0.1, w=0.0), found=True, cx=0.5, h=0.2)
    assert bridge.wait_idle(3.0)
    assert (bridge.posted, bridge.errors) == (0, 1)
    bridge.close(timeout_s=0.0)
