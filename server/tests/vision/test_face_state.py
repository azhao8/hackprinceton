"""FaceEvents: the phone face's gaze target and follow events, from Perception + the follow command."""

import numpy as np

from app.vision.face_state import FaceEvents, gaze_point
from app.vision.follow import WAITING_REASON
from app.vision.types import Box, Detections, DriveCommand, Frame, Keypoint, Person, TargetState, TargetStatus
from app.vision.worker import Perception

PERSON = Person(Box(0.3, 0.2, 0.5, 0.9), 0.9)


def perception(status: TargetStatus, at: float = 0.0, person: Person | None = PERSON) -> Perception:
    frame = Frame(t=at, index=int(at * 100), image=np.zeros((4, 4, 3), dtype=np.uint8))
    target = TargetState(status, person=person if status is TargetStatus.LOCKED else None)
    return Perception(frame=frame, detections=Detections(at, frame.index, 4, 4, []), target=target,
                      engage_pending=False, engaged_seq=1, latency_s=0.0, fps=12.0, published_at=at)


def kinds(face: FaceEvents, steps) -> list:
    """Run (status, reason, now) steps with Follow on; return the event kinds in order."""
    out, last_id = [], 0
    for status, reason, now in steps:
        cmd = DriveCommand(0.0, 0.0, reason) if reason else None
        ev = face.update(perception(status, at=now), True, cmd, now)["event"]
        if ev and ev["id"] != last_id:
            assert ev["id"] > last_id
            last_id = ev["id"]
            out.append(ev["kind"])
    return out


L, LOST, IDLE = TargetStatus.LOCKED, TargetStatus.LOST, TargetStatus.IDLE


def test_idle_without_vision_or_with_follow_off():
    face = FaceEvents()
    assert face.update(None, True, None, 0.0) == {"status": "idle", "target": None, "event": None}
    assert face.update(perception(L), False, None, 0.0) == {"status": "idle", "target": None, "event": None}


def test_found_then_lost_then_reacquired_gives_found_again_with_increasing_ids():
    face = FaceEvents()
    assert kinds(face, [(IDLE, "engaging", 0.0), (L, "following", 0.1), (L, "following", 0.2),
                        (LOST, "lost: coasting", 0.3), (LOST, "lost: searching left", 0.4),
                        (L, "following", 0.5)]) == ["found", "lost", "found"]
    snap = face.snapshot()
    assert snap["status"] == "locked" and snap["event"] == {"id": 3, "kind": "found"}


def test_target_only_while_locked_and_the_same_input_never_repeats_an_event():
    face = FaceEvents()
    p = perception(L, at=1.0)
    a = face.update(p, True, None, 1.0)
    b = face.update(p, True, None, 1.0)   # polled again (the phone, the dashboard, the tick)
    assert a == b and a["status"] == "locked" and a["event"] == {"id": 1, "kind": "found"}
    assert a["target"] == {"cx": 0.4, "cy": 0.305, "w": 0.2}   # no face keypoints: 15% down the box
    assert face.update(perception(LOST, at=1.1), True, None, 1.1)["target"] is None


def test_too_close_is_debounced():
    face = FaceEvents(too_close_every_s=3.0)
    tc, ok = "too close: backing off", "following"
    got = kinds(face, [(L, ok, 0.0), (L, tc, 0.1), (L, tc, 0.2),   # stays too close: once
                       (L, ok, 0.5), (L, tc, 0.6),                  # flickers back within 3 s: no
                       (L, ok, 3.5), (L, tc, 3.6)])                 # again after 3 s: yes
    assert got == ["found", "too_close", "too_close"]


def test_too_close_needs_follow_on():
    face = FaceEvents()
    assert face.update(perception(L), False, DriveCommand(0, 0, "too close: backing off"), 0.0)["event"] is None


def test_gave_up_fires_once_per_command_even_after_follow_stops():
    face = FaceEvents()
    face.update(perception(L, at=0.0), True, DriveCommand(0.2, 0, "following"), 0.0)
    face.update(perception(LOST, at=1.0), True, DriveCommand(0, 0.5, "lost: searching left"), 1.0)
    gave_up = DriveCommand(0.0, 0.0, "lost: gave up")
    ev = face.update(perception(LOST, at=7.0), True, gave_up, 7.0)["event"]
    assert ev == {"id": 3, "kind": "gave_up"}
    # The skill has ended (Follow off) but its last command is still the same one: no second event.
    snap = face.update(perception(IDLE, at=7.1), False, gave_up, 7.1)
    assert snap["status"] == "idle" and snap["event"] == {"id": 3, "kind": "gave_up"}
    # The next run gives up again: a new command, a new event.
    assert face.update(None, False, DriveCommand(0.0, 0.0, "lost: gave up"), 20.0)["event"]["id"] == 4


def test_waiting_fires_once_per_wait_and_found_when_they_come_back():
    face = FaceEvents()
    wait = WAITING_REASON
    got = kinds(face, [(L, "following", 0.0),
                       (LOST, "lost: coasting", 0.1), (LOST, "lost: searching right", 0.5),
                       (LOST, wait, 2.1), (LOST, wait, 2.2), (LOST, wait, 30.0),   # waits: once
                       (L, "following", 31.0),                                     # back: found
                       (LOST, "lost: holding", 32.0), (LOST, wait, 34.0),          # again: once more
                       (L, "following", 40.0)])
    assert got == ["found", "lost", "waiting", "found", "lost", "waiting", "found"]


def test_waiting_needs_follow_on_and_the_person_lost():
    face = FaceEvents()
    wait = DriveCommand(0.0, 0.0, WAITING_REASON)
    assert face.update(perception(LOST), False, wait, 0.0)["event"] is None
    face.update(perception(L, at=1.0), True, DriveCommand(0.1, 0.0, "following"), 1.0)
    # A command from the frame before they came back must not say "waiting" after "found".
    assert face.update(perception(L, at=1.1), True, wait, 1.1)["event"]["kind"] == "found"


def test_stale_vision_while_locked_counts_as_lost():
    face = FaceEvents(stale_after_s=1.0)
    p = perception(L, at=0.0)
    assert face.update(p, True, None, 0.5)["status"] == "locked"
    snap = face.update(p, True, None, 2.0)       # no new frame for 2 s
    assert snap["status"] == "lost" and snap["target"] is None and snap["event"]["kind"] == "lost"
    # A stale lock from before Follow started never says "found".
    assert FaceEvents().update(p, True, None, 5.0) == {"status": "idle", "target": None, "event": None}


def test_gaze_uses_confident_face_keypoints_and_unmirrors():
    kp = {"nose": Keypoint(0.42, 0.25, 0.9), "left_eye": Keypoint(0.44, 0.23, 0.8),
          "right_eye": Keypoint(0.40, 0.23, 0.8), "left_ear": Keypoint(0.9, 0.9, 0.1)}   # low conf: ignored
    person = Person(Box(0.3, 0.2, 0.5, 0.9), 0.9, kp)
    assert gaze_point(person) == {"cx": 0.42, "cy": 0.237, "w": 0.2}
    assert gaze_point(person, mirrored=True)["cx"] == 0.58
