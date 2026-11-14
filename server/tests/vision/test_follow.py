"""Tests for the follow controller (app/vision/follow.py). Pure logic: no camera, robot or network."""

from __future__ import annotations

import math

import pytest

from app.vision.follow import (
    CameraGeometry,
    FollowConfig,
    FollowController,
    feet_point,
    ground_distance,
    shoulder_gap,
)
from app.vision.types import Box, DriveCommand, Keypoint, Person, TargetState, TargetStatus

DT = 1.0 / 15.0  # the tuned detection rate

CFG = FollowConfig()  # the defaults: phone tilted up, ground plane off

# A camera pitched down so the feet stay visible: easy numbers for the ground-plane tests.
CAM_DOWN = CameraGeometry(height_m=0.40, tilt_deg=-15.0, vfov_deg=60.0, hfov_deg=80.0)
CFG_GROUND = FollowConfig(camera=CAM_DOWN, use_ground_plane=True)


def y_for_distance(cam: CameraGeometry, d: float, point_height_m: float = 0.0) -> float:
    """Inverse of CameraGeometry.ground_distance: the image row of a point d meters away."""
    below_horizon = math.atan((cam.height_m - point_height_m) / d)
    below_axis = below_horizon + math.radians(cam.tilt_deg)
    return 0.5 + math.tan(below_axis) / (2.0 * math.tan(math.radians(cam.vfov_deg) / 2.0))


def kp(x: float, y: float, conf: float = 0.9) -> Keypoint:
    return Keypoint(x, y, conf)


def person(cx: float = 0.5, d: float | None = None, w: float | None = None, gap: float | None = None,
           shoulders: str = "both", y1: float = 0.0, y2: float = 1.0,
           extra: dict[str, Keypoint] | None = None) -> Person:
    """A person centered at cx, seen from the tilted-up camera (box clipped top and bottom).

    d: true distance; sets the shoulder gap (k_shoulder / d) and a box width that agrees with
    it (target_box_w at d_target), unless `gap` / `w` override them. shoulders: "both",
    "left" (right one hidden) or "none". Without d and gap there are no shoulder keypoints."""
    if d is not None:
        gap = CFG.k_shoulder_m / d if gap is None else gap
        w = CFG.target_box_w * CFG.d_target_m / d if w is None else w
    w = CFG.target_box_w if w is None else w
    kps: dict[str, Keypoint] = {}
    if gap is not None and shoulders != "none":
        kps["left_shoulder"] = kp(cx + gap / 2, 0.3)  # the person's left is image right
        if shoulders == "both":
            kps["right_shoulder"] = kp(cx - gap / 2, 0.3)
    kps.update(extra or {})
    return Person(box=Box(cx - w / 2, y1, cx + w / 2, y2), score=0.9, keypoints=kps)


def ankles(y_left: float, y_right: float, conf_left: float = 0.9, conf_right: float = 0.9) -> dict[str, Keypoint]:
    return {"left_ankle": kp(0.45, y_left, conf_left), "right_ankle": kp(0.55, y_right, conf_right)}


def locked(p: Person, reacquired: bool = False) -> TargetState:
    return TargetState(status=TargetStatus.LOCKED, person=p, last_seen_cx=p.box.cx, reacquired=reacquired)


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


def test_default_shoulder_constant_matches_its_derivation():
    # 0.37 m shoulders, 67 deg hfov: 0.37 / (2 tan 33.5 deg) = 0.279 m.
    assert CFG.k_shoulder_m == pytest.approx(0.37 / (2 * math.tan(math.radians(CFG.camera.hfov_deg / 2))), abs=0.005)


def test_too_close_width_follows_the_target_width():
    assert CFG.target_box_w == 0.45
    assert CFG.too_close_w == pytest.approx(0.60)  # max(0.55, 0.45 + 0.15)
    assert FollowConfig(target_box_w=0.28).too_close_w == pytest.approx(0.55)
    assert FollowConfig(too_close_box_w=0.7).too_close_w == 0.7


# ---------------------------------------------------------------------------
# Feet: ankles only, both of them, well inside the frame
# ---------------------------------------------------------------------------


def test_feet_need_both_confident_ankles_and_use_the_lower_one():
    p = person(extra=ankles(0.80, 0.85))
    assert feet_point(p) == pytest.approx(0.85)


@pytest.mark.parametrize("ank", [
    ankles(0.80, 0.85, conf_right=0.3),  # one not confident
    {"left_ankle": kp(0.45, 0.80)},  # one missing
    ankles(0.80, 0.96),  # one too near the bottom edge
    ankles(0.80, 1.10),  # one extrapolated below the frame
])
def test_feet_none_without_two_good_ankles(ank):
    assert feet_point(person(extra=ank)) is None


def test_box_bottom_is_never_the_feet():
    # The old bug: a box ending at 0.95 (the thighs, with the phone tilted up) was read as the floor.
    p = person(y2=0.95)
    assert feet_point(p) is None
    assert ground_distance(p, CFG_GROUND) is None


def test_ground_distance_from_ankles_uses_ankle_height():
    d_true = 1.5
    y = y_for_distance(CAM_DOWN, d_true, point_height_m=CFG_GROUND.ankle_height_m)
    p = person(extra=ankles(y - 0.02, y))
    assert ground_distance(p, CFG_GROUND) == pytest.approx(d_true)


def test_ground_plane_is_off_by_default():
    assert CFG.use_ground_plane is False
    y = y_for_distance(CAM_DOWN, 1.5, point_height_m=CFG.ankle_height_m)
    p = person(extra=ankles(y, y))
    assert ground_distance(p, FollowConfig(camera=CAM_DOWN)) is None


# ---------------------------------------------------------------------------
# The safety bug: box bottom must not drive the robot into the person
# ---------------------------------------------------------------------------


def test_box_bottom_at_0_95_without_ankles_does_not_drive_forward():
    # Person at the target distance, tilted-up view: box from the head to the thighs (y2 = 0.95).
    p = person(d=CFG.d_target_m, y2=0.95)
    cmd = run(FollowController(CFG), locked(p), 30)
    assert cmd.v == pytest.approx(0.0, abs=1e-9)
    assert cmd.distance_m == pytest.approx(CFG.d_target_m)  # from the shoulders, not the box bottom


def test_thigh_box_that_reads_far_on_the_ground_plane_still_backs_off():
    # Ground plane ON, camera pitched down: a box ending at the row of a floor point 2.5 m away,
    # but the person is really close (box wider than the too-close width). The old code drove
    # forward here; now the box bottom is ignored and the width says back off.
    y2 = y_for_distance(CAM_DOWN, 2.5)
    p = Person(box=Box(0.15, 0.0, 0.85, y2), score=0.9)
    ctrl = FollowController(CFG_GROUND)
    assert ground_distance(p, CFG_GROUND) is None
    cmd = run(ctrl, locked(p), 30)
    assert cmd.v == pytest.approx(CFG_GROUND.v_back, abs=1e-6)
    assert cmd.reason == "too close: backing off"
    assert cmd.distance_m is None


def test_ground_plane_takes_part_when_on_and_ankles_are_good():
    # Shoulders and box say the target distance; good ankles say 0.5 m: the closer one wins.
    y = y_for_distance(CAM_DOWN, 0.5, point_height_m=CFG_GROUND.ankle_height_m)
    p = person(d=CFG.d_target_m, extra=ankles(y, y))
    cmd = run(FollowController(CFG_GROUND), locked(p), 30)
    assert cmd.v == pytest.approx(CFG.v_back, abs=1e-6)
    assert cmd.distance_m == pytest.approx(0.5)


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
    right = run(FollowController(CFG), locked(person(cx=0.75, d=CFG.d_target_m)), 1)
    left = run(FollowController(CFG), locked(person(cx=0.25, d=CFG.d_target_m)), 1)
    assert right.w < 0
    assert left.w > 0


def test_turn_is_capped():
    cmd = run(FollowController(FollowConfig(k_w=10.0)), locked(person(cx=0.9, d=2.0)), 60)
    assert cmd.w == pytest.approx(-CFG.w_max, abs=1e-6)


def test_far_drives_forward_and_is_capped():
    cmd = run(FollowController(CFG), locked(person(d=4.0)), 60)
    assert cmd.v == pytest.approx(CFG.v_max, abs=1e-6)
    assert cmd.distance_m == pytest.approx(4.0)


def test_twice_as_far_gives_the_tuned_speed():
    cmd = run(FollowController(CFG), locked(person(d=2 * CFG.d_target_m)), 60)
    assert cmd.v == pytest.approx(CFG.k_v, abs=1e-6)  # 0.35 m/s when twice as far as wanted
    assert cmd.distance_m == pytest.approx(2 * CFG.d_target_m)


def test_too_close_by_shoulders_backs_off():
    cmd = run(FollowController(CFG), locked(person(d=0.5, w=0.5)), 30)  # box alone isn't too close
    assert cmd.v == pytest.approx(CFG.v_back, abs=1e-6)
    assert cmd.reason == "too close: backing off"
    assert cmd.distance_m == pytest.approx(0.5)


def test_box_width_alone_without_keypoints():
    narrow = run(FollowController(CFG), locked(person(w=CFG.target_box_w / 2)), 60)
    assert narrow.distance_m is None
    assert narrow.v == pytest.approx(CFG.k_v, abs=1e-6)  # half the target width = twice as far
    at_target = run(FollowController(CFG), locked(person(w=CFG.target_box_w)), 30)
    assert at_target.v == 0.0
    wide = run(FollowController(CFG), locked(person(w=0.65)), 30)
    assert wide.v == pytest.approx(CFG.v_back, abs=1e-6) and wide.reason == "too close: backing off"


# --- closer of the two cues ---


def test_box_wins_when_it_says_closer():
    # Shoulders say 2 m (twice too far), the box says right at the target: hold still.
    cmd = run(FollowController(CFG), locked(person(d=2.0, w=CFG.target_box_w)), 30)
    assert cmd.v == pytest.approx(0.0, abs=1e-9)
    assert cmd.distance_m is None  # the box cue won; it measures no meters


def test_shoulders_win_when_they_say_closer():
    # Box says twice too far, the shoulders say the target distance: hold still.
    cmd = run(FollowController(CFG), locked(person(d=CFG.d_target_m, w=CFG.target_box_w / 2)), 30)
    assert cmd.v == pytest.approx(0.0, abs=1e-9)
    assert cmd.distance_m == pytest.approx(CFG.d_target_m)
    # ...and shoulders saying too close beat a narrow box that says far.
    close = run(FollowController(CFG), locked(person(d=0.5, w=0.15)), 30)
    assert close.v == pytest.approx(CFG.v_back, abs=1e-6) and close.reason == "too close: backing off"


def test_speed_follows_the_closer_cue():
    # Shoulders 3 m (ratio 2), box 1.5x too far (ratio 0.5): v = k_v * 0.5.
    cmd = run(FollowController(CFG), locked(person(d=3.0, w=CFG.target_box_w / 1.5)), 60)
    assert cmd.v == pytest.approx(CFG.k_v * 0.5, abs=1e-6)


# --- sideways ---


def test_turned_sideways_uses_box_only_and_never_drives_forward():
    ctrl = FollowController(CFG)
    run(ctrl, locked(person(cx=0.7, d=2.0)), 10)  # acquired facing the robot, 2 m away
    # Same box (same distance), shoulder gap down to 40%: turned sideways. The box says too far.
    side = locked(person(cx=0.7, d=2.0, gap=0.4 * CFG.k_shoulder_m / 2.0))
    cmd = run(ctrl, side, 30, t0=1.0)
    assert cmd.v == pytest.approx(0.0, abs=1e-6)
    assert cmd.w < 0  # still turns toward them
    assert cmd.reason == "following: sideways, turn only"


def test_sideways_still_backs_off_when_the_box_is_too_close():
    ctrl = FollowController(CFG)
    run(ctrl, locked(person(d=1.0, w=0.65)), 5)
    cmd = run(ctrl, locked(person(d=1.0, w=0.65, gap=0.05)), 30, t0=1.0)
    assert cmd.v == pytest.approx(CFG.v_back, abs=1e-6) and cmd.reason == "too close: backing off"


def test_walking_away_is_not_sideways():
    ctrl = FollowController(CFG)
    run(ctrl, locked(person(d=1.0)), 10)
    cmd = run(ctrl, locked(person(d=2.0)), 60, t0=1.0)  # gap and box both halve
    assert cmd.v == pytest.approx(CFG.k_v, abs=1e-6)
    assert cmd.reason == "following"


def test_one_shoulder_missing_never_drives_forward():
    cmd = run(FollowController(CFG), locked(person(cx=0.7, d=2.0, shoulders="left")), 30)
    assert cmd.v == pytest.approx(0.0, abs=1e-6)
    assert cmd.w < 0
    assert cmd.reason == "following: sideways, turn only"
    assert cmd.distance_m is None


def test_reacquired_resets_the_shoulder_reference():
    ctrl = FollowController(CFG)
    run(ctrl, locked(person(d=1.0)), 5)  # reference: frontal at 1 m
    narrow_gap = person(d=2.0, gap=0.4 * CFG.k_shoulder_m / 2.0)
    # Without a new lock this pose reads as sideways...
    assert run(ctrl, locked(narrow_gap), 1, t0=1.0).reason == "following: sideways, turn only"
    # ...after a re-acquire it becomes the new reference.
    assert ctrl.update(locked(narrow_gap, reacquired=True), 2.0).reason == "following"


def test_box_cut_at_the_side_never_drives_forward():
    p = Person(box=Box(0.0, 0.0, 0.12, 1.0), score=0.9)  # narrow because it's half out of frame
    cmd = run(FollowController(CFG), locked(p), 30)
    assert cmd.v == 0.0
    assert cmd.w > 0  # still turns left to bring them into view


# --- smoothing and modes ---


def test_smoothing_is_0_6_previous_plus_0_4_new():
    ctrl = FollowController(CFG)
    w_cmd = -CFG.k_w * (0.75 - 0.5)
    s = locked(person(cx=0.75, d=CFG.d_target_m))
    assert ctrl.update(s, 0.0).w == pytest.approx(0.4 * w_cmd)
    assert ctrl.update(s, DT).w == pytest.approx(0.6 * 0.4 * w_cmd + 0.4 * w_cmd)


def test_smoothing_has_the_same_time_constant_at_any_frame_rate():
    s = locked(person(cx=0.75, d=3.0))
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
    s = locked(person(cx=0.75, d=CFG.d_target_m))
    run(ctrl, s, 30)
    ctrl.reset()
    assert ctrl.update(s, 100.0).w == pytest.approx(0.4 * -CFG.k_w * 0.25)


def test_turn_only_and_camera_back():
    far = locked(person(cx=0.75, d=3.0))
    turn_only = run(FollowController(FollowConfig(turn_only=True)), far, 30)
    assert turn_only.v == 0.0 and turn_only.w < 0
    back = run(FollowController(FollowConfig(camera_back=True)), far, 30)
    forward = run(FollowController(CFG), far, 30)
    assert forward.v > 0
    assert back.v == pytest.approx(-forward.v) and back.v < 0
    assert back.w == pytest.approx(forward.w)


# ---------------------------------------------------------------------------
# Controller: lost and idle
# ---------------------------------------------------------------------------


def moving(ctrl: FollowController, cx: float = 0.75) -> DriveCommand:
    """Drive the controller to a steady forward + turning state; returns the last command."""
    return run(ctrl, locked(person(cx=cx, d=3.0)), 30)


def test_brief_dropout_coasts_instead_of_stopping():
    ctrl = FollowController(CFG)
    before = moving(ctrl)
    assert before.v > 0 and before.w < 0
    t = 30 * DT
    v = before.v
    for i in range(4):  # 4 frames = 0.27 s < coast_s
        cmd = ctrl.update(lost(i * DT + 0.01, last_seen_cx=0.75), t + i * DT)
        v *= 0.6
        assert cmd.reason == "lost: coasting"
        assert cmd.v == pytest.approx(v)
        assert cmd.w == pytest.approx(before.w)  # turn held
        assert cmd.distance_m is None


def test_coast_decay_is_frame_rate_scaled():
    a, b = FollowController(CFG), FollowController(CFG)
    v0 = moving(a).v
    moving(b)
    t = 30 * DT  # both last saw the person at t - DT
    a.update(lost(0.0, 0.75), t)
    fast = a.update(lost(DT, 0.75), t + DT)  # two frames of DT
    slow = b.update(lost(DT, 0.75), t + DT)  # one frame of 2 DT
    assert fast.v == pytest.approx(v0 * 0.6 ** 2)
    assert slow.v == pytest.approx(v0 * 0.6 ** 2)


def test_lost_off_centre_searches_that_way_right_after_coasting():
    ctrl = FollowController(CFG)
    before = moving(ctrl, cx=0.75)  # turning right
    t = 30 * DT
    first = ctrl.update(lost(CFG.coast_s + 0.01, last_seen_cx=0.2), t)  # no idle hold first
    assert first.reason == "lost: searching left"
    assert first.v == 0.0
    assert first.w == pytest.approx(0.6 * before.w + 0.4 * CFG.search_w)  # smoothed from the current turn
    for i in range(1, 25):
        cmd = ctrl.update(lost(CFG.coast_s + 0.01 + i * DT, last_seen_cx=0.2), t + i * DT)
        assert cmd.v == 0.0 and cmd.reason == "lost: searching left"
    assert cmd.w == pytest.approx(CFG.search_w, rel=1e-3)

    right = FollowController(CFG).update(lost(0.5, last_seen_cx=0.8), 0.0)
    assert right.w < 0 and right.reason == "lost: searching right"


def test_lost_near_the_centre_holds_still():
    ctrl = FollowController(CFG)
    moving(ctrl)
    cmd = ctrl.update(lost(CFG.coast_s + 0.05, last_seen_cx=0.6), 10.0)
    assert (cmd.v, cmd.w, cmd.reason) == (0.0, 0.0, "lost: holding")
    cmd = ctrl.update(lost(1.5, last_seen_cx=0.6), 11.0)
    assert (cmd.v, cmd.w, cmd.reason) == (0.0, 0.0, "lost: holding")


def test_search_gives_up_after_2_s():
    assert CFG.search_for_s == 2.0
    ctrl = FollowController(CFG)
    moving(ctrl)
    still = ctrl.update(lost(1.95, last_seen_cx=0.1), 10.0)
    assert still.reason == "lost: searching left" and still.w > 0
    gave_up = ctrl.update(lost(2.0, last_seen_cx=0.1), 10.0 + DT)
    assert (gave_up.v, gave_up.w, gave_up.reason) == (0.0, 0.0, "lost: gave up")
    centre = FollowController(CFG).update(lost(2.5, last_seen_cx=0.5), 0.0)
    assert (centre.v, centre.w, centre.reason) == (0.0, 0.0, "lost: gave up")


def test_idle_is_zero():
    ctrl = FollowController(CFG)
    moving(ctrl)
    cmd = ctrl.update(TargetState(status=TargetStatus.IDLE), 5.0)
    assert (cmd.v, cmd.w, cmd.reason, cmd.distance_m) == (0.0, 0.0, "idle", None)


def test_follow_does_not_import_the_drive_bridge():
    import app.vision.follow as follow

    with open(follow.__file__) as f:
        assert "drive_bridge" not in f.read()
