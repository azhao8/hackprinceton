"""PeopleRegistry: saved looks, matching, persistence. Synthetic people from the tracking tests."""

from __future__ import annotations

import json
import threading
from dataclasses import replace

import numpy as np
import pytest

from app.vision.people import PeopleRegistry
from app.vision.tracking import BodyParts, TargetLock
from tests.vision.test_tracking import BLACK, BLUE, GREEN, RED, WHITE, YELLOW, Walker, parts_of, render

MOM = Walker(0.5, pants=BLUE, shirt=RED)
DAD = Walker(0.5, pants=BLACK, shirt=GREEN)
KID = Walker(0.5, pants=WHITE, shirt=YELLOW)


def look(walker: Walker, index: int = 0, **changes) -> BodyParts:
    parts = parts_of(replace(walker, **changes) if changes else walker, index=index)
    assert parts is not None
    return parts


@pytest.fixture
def registry(tmp_path) -> PeopleRegistry:
    reg = PeopleRegistry(tmp_path / "people.json")
    reg.save("Mom", look(MOM))
    reg.save("Dad", look(DAD))
    return reg


def test_match_finds_the_right_person_in_a_new_frame(registry):
    # A different frame (new noise), standing elsewhere and a bit closer.
    name, d = registry.match(look(MOM, index=9, cx=0.3, w=0.3))
    assert name == "Mom" and d < 0.2
    name, _ = registry.match(look(DAD, index=4, cx=0.7))
    assert name == "Dad"


def test_a_stranger_matches_nobody(registry):
    assert registry.match(look(KID, index=3)) is None


def test_match_restricted_to_one_name(registry):
    mom_now = look(MOM, index=5)
    assert registry.match(mom_now, name="mom")[0] == "Mom"  # case-insensitive
    assert registry.match(mom_now, name="Dad") is None  # Dad doesn't look like that
    assert registry.match(mom_now, name="Grandpa") is None  # unknown name


def test_threshold_is_adjustable(registry):
    kid = look(KID)
    assert registry.match(kid) is None
    assert registry.match(kid, max_dist=1.0) is not None  # anything goes


def test_same_shirt_different_trousers_is_not_a_match(tmp_path):
    reg = PeopleRegistry(tmp_path / "p.json")
    reg.save("Mom", look(MOM))
    assert reg.match(look(MOM, pants=BLACK)) is None  # the per-part veto


def test_names_get_and_forget(registry):
    assert registry.names() == ["Mom", "Dad"]
    assert "mom" in registry and "Grandpa" not in registry
    assert registry.get("MOM") is not None and registry.get("nobody") is None
    assert registry.forget("dad") is True
    assert registry.forget("dad") is False
    assert registry.names() == ["Mom"]
    assert registry.match(look(DAD)) is None


def test_saving_again_replaces_the_look(registry):
    registry.save("mom", look(KID))  # Mom changed clothes
    assert registry.names() == ["mom", "Dad"]
    assert registry.match(look(KID, index=2))[0] == "mom"
    assert registry.match(look(MOM, index=2)) is None


def test_persists_across_a_restart(tmp_path, registry):
    path = tmp_path / "people.json"
    data = json.loads(path.read_text())
    assert [p["name"] for p in data["people"]] == ["Mom", "Dad"]
    assert isinstance(data["people"][0]["torso"], list)

    reloaded = PeopleRegistry(path)
    assert reloaded.names() == ["Mom", "Dad"]
    saved, loaded = registry.get("Mom"), reloaded.get("Mom")
    assert loaded.torso.dtype == np.float32
    assert np.allclose(saved.torso, loaded.torso) and np.allclose(saved.legs, loaded.legs)
    assert loaded.torso_px == saved.torso_px
    assert reloaded.match(look(MOM, index=11))[0] == "Mom"

    registry.forget("Mom")
    assert PeopleRegistry(path).names() == ["Dad"]


def test_save_from_lock_uses_the_followed_persons_look(tmp_path):
    lock = TargetLock()
    reg = PeopleRegistry(tmp_path / "p.json")
    with pytest.raises(ValueError):
        reg.save_from_lock("Mom", lock)  # not following anyone yet

    dets, image = render(0, [MOM, Walker(0.85, pants=BLACK, shirt=GREEN, w=0.2)])
    lock.engage(dets, image)
    reg.save_from_lock("Mom", lock)
    assert reg.match(look(MOM, index=7))[0] == "Mom"
    assert reg.match(look(DAD, index=7)) is None


def test_match_person_histograms_a_detection(registry):
    dets, image = render(3, [Walker(0.3, pants=BLACK, shirt=GREEN), Walker(0.75, pants=BLUE, shirt=RED)])
    left, right = dets.people
    assert registry.match_person(image, left, dets.people)[0] == "Dad"
    assert registry.match_person(image, right, dets.people, name="Mom")[0] == "Mom"
    assert registry.match_person(image, right, dets.people, name="Dad") is None


def test_bad_inputs(tmp_path):
    reg = PeopleRegistry(tmp_path / "p.json")
    with pytest.raises(ValueError):
        reg.save("  ", look(MOM))
    with pytest.raises(ValueError):
        reg.save("Mom", BodyParts())
    assert reg.match(BodyParts()) is None


def test_corrupt_file_starts_empty(tmp_path):
    path = tmp_path / "people.json"
    path.write_text("{not json")
    reg = PeopleRegistry(path)
    assert reg.names() == []
    reg.save("Mom", look(MOM))  # and overwrites it with a good file
    assert PeopleRegistry(path).names() == ["Mom"]


def test_in_memory_registry_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    reg = PeopleRegistry(None)
    reg.save("Mom", look(MOM))
    assert reg.names() == ["Mom"]
    assert list(tmp_path.iterdir()) == []


def test_concurrent_saves_and_matches(tmp_path):
    reg = PeopleRegistry(tmp_path / "p.json")
    mom, dad = look(MOM), look(DAD)
    errors: list[BaseException] = []

    def writer(i: int) -> None:
        try:
            for j in range(20):
                reg.save(f"p{i}-{j % 3}", mom if j % 2 else dad)
        except BaseException as e:  # pragma: no cover - surfaced below
            errors.append(e)

    def reader() -> None:
        try:
            for _ in range(50):
                reg.match(mom)
                reg.names()
        except BaseException as e:  # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(3)] + [
        threading.Thread(target=reader) for _ in range(2)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert len(PeopleRegistry(tmp_path / "p.json").names()) == 9
