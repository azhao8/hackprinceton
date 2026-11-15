"""The family app's server side (contract/web/family.md, v1): one WebSocket `/family/ws` per app.

A thin translator, not a second brain (Alex's design, Sat night): the app's requests become agent
messages (the agent picks the tools, as always), and the app's `state` is worked out from what the
server already knows: the robot link, the bring behavior's stages, the agent's events, vision.

- Sign-in: the first frame is `hello` with FAMILY_TOKEN (server/.env). Without FAMILY_TOKEN only
  this laptop may connect (no one else can drive Miguel's tasks).
- send:     one delivery at a time -> agent ("bring <item> to <resident>") -> stages from bring's
            on_step -> on `delivered` the family's note is read out WORD FOR WORD (not by Claude) and
            a photo is taken -> event in Mom's day. Honest failures show as stage `failed`.
- check_in: the agent asks her first and calls check_in_result. Only on yes does the call start
            (consent enforced here): a two-way WebRTC video call (#118) between the robot's phone page
            and whoever asked. The server only relays the setup (`rtc`): the phone's offer and
            candidates come over its mic socket (app/speech/mic.py) and go to the caller; the app's
            answer and candidates go back the same way. Miguel doesn't hear or talk during the call
            (MicHub.set_call). Either side ends it: the app's `end`, or the phone's End button
            ({"type": "hangup"}). Camera frames (`frame`, JPEG relay, ~5 fps) still go to the caller
            as the fallback until the video plays. The phone switches to the front camera for the
            call and back after.
- ask:      free text to the agent ("Ask Miguel"); his replies arrive as `event` kind `message`.
- alert:    raise_alert() (the control page's test button, or vision later) -> the agent asks if she's
            okay and tells the family; `alert` handled by any family member clears it for everyone.
- phone:    links a phone number to a family member (`phones` to every app; saved in FAMILY_PHONES,
            default server/family-phones.json), so the iMessage bridge (server/bridge/) knows who texts.
            The control page links them too (/family/phones, this laptop only).
- routine / invite / talk: acknowledged; routines and the circle stay the app's demo data (cut for
            Sunday); talk (voice clips to her) isn't supported yet.
"""

from __future__ import annotations

import asyncio
import base64
import hmac
import itertools
import json
import logging
import os
import re
import secrets
import time
from collections import OrderedDict
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from aiohttp import WSMsgType, web

log = logging.getLogger("app.family")

ITEMS = ("water", "medication", "note", "other")
FRAME_HZ = 5
CALL_MAX_S = 600
ASK_TIMEOUT_S = 60.0            # Miguel asks and listens ~15 s; past this the check-in counts as declined
SETTLE_DELAY_S = 0.3            # after a task ends, let a queued request start before deciding he's done
STALE_ANSWER_S = 30.0           # after calling off a check-in, a new one waits this long while he's still working
DID_KEEP = 8                    # alert.did: the latest lines only
SAME_ITEM = {"medication": {"medication", "medicine", "meds", "pill", "pills", "tablets"},
             "water": {"water", "drink", "glass", "bottle"}}
STATE_MIN_GAP_S = 0.2           # at most 5 state messages a second
MEDIA_KEEP = 40
MEDIA_TTL_S = 24 * 3600
LINK_DOWN_S = 3.0
MEMBERS = {"m1": "Sarah", "m2": "David", "m3": "Lin"}   # the app's demo circle (seed.ts); names for messages
PHONES_PATH = Path(__file__).resolve().parents[1] / "family-phones.json"   # personal data: git-ignored
RTC_MAX = 64_000                # characters in one sdp or candidate (a real one is a few kB)
EVENT_KIND = {"water": "water", "medication": "medication", "note": "message", "other": "delivery"}


def iso(t: float | None = None) -> str:
    return datetime.fromtimestamp(time.time() if t is None else t).astimezone().isoformat(timespec="seconds")


_YES = re.compile(r"\b(yes|yeah|yep|yup|sure|ok|okay|alright|all right|go ahead|of course|absolutely|"
                  r"please|sounds good|why not|let's|that's fine|fine)\b", re.IGNORECASE)
_NO = re.compile(r"\b(no|nope|not|don't|do not|later|busy|stop|wait)\b", re.IGNORECASE)


def said_yes(text: str) -> bool:
    """Her words sound like agreeing (and not like refusing): the code's half of check-in consent."""
    return bool(text and _YES.search(text) and not _NO.search(text))


def rtc_payload(m: dict[str, Any]) -> dict[str, Any] | None:
    """The WebRTC part of an `rtc` message, checked: {"sdp": {type, sdp}} or {"candidate": {...}}."""
    sdp, cand = m.get("sdp"), m.get("candidate")
    if isinstance(sdp, dict):
        if sdp.get("type") in ("offer", "answer") and isinstance(sdp.get("sdp"), str) \
                and 0 < len(sdp["sdp"]) <= RTC_MAX:
            return {"sdp": {"type": sdp["type"], "sdp": sdp["sdp"]}}
        return None
    if isinstance(cand, dict) and len(json.dumps(cand)) <= RTC_MAX:
        return {"candidate": cand}
    return None


def normalize_phone(raw: Any) -> str | None:
    """A phone number in E.164 (+12155550123), or None. Ten digits are a US number; anything else needs
    its country code (a leading + and 8 to 15 digits)."""
    if not isinstance(raw, str):
        return None
    s = re.sub(r"[\s\-().]", "", raw.strip())
    if re.fullmatch(r"\d{10}", s):
        return "+1" + s
    if re.fullmatch(r"1\d{10}", s):
        return "+" + s
    return s if re.fullmatch(r"\+\d{8,15}", s) else None


def wire_copy(d: dict[str, Any], drop: tuple[str, ...] = ()) -> dict[str, Any]:
    """A copy for the wire: no None values (the app's parser rejects null for optional fields, and one
    bad field drops the whole message) and fresh lists, so later in-place changes to the hub's own
    dicts still show up as changes in push_state."""
    return {k: list(v) if isinstance(v, list) else v for k, v in d.items() if v is not None and k not in drop}


class FamilyHub:
    def __init__(self, state: Any, memory: Any = None, *, snapshot: Callable[[], bytes | None] | None = None,
                 token: str | None = None, resident: str | None = None, short: str | None = None,
                 tz: str | None = None):
        self.state = state
        self.memory = memory
        self.snapshot = snapshot
        self.token = token if token is not None else (os.environ.get("FAMILY_TOKEN") or None)
        self.resident = resident or os.environ.get("FAMILY_RESIDENT_NAME", "Margaret")
        self.short = short or os.environ.get("FAMILY_RESIDENT_SHORT", "Mom")
        self.tz = tz or os.environ.get("FAMILY_TZ", "America/New_York")
        self.clients: dict[web.WebSocketResponse, str] = {}   # socket -> viewer id
        self.delivery: dict[str, Any] | None = None
        self.check_in: dict[str, Any] = {"phase": "idle"}
        self.alert: dict[str, Any] | None = None
        self.media: OrderedDict[str, tuple[float, str, bytes]] = OrderedDict()   # id -> (time, type, bytes)
        self._ids = itertools.count(1)
        self._mode = ("idle", "")
        self._since = time.time()
        self._last_state: dict[str, Any] | None = None
        self._last_sent = 0.0
        self._call_task: asyncio.Task | None = None
        self._camera_before: str | None = None
        self._follow_before = False
        self._pump: asyncio.Task | None = None
        self._settle: asyncio.TimerHandle | None = None
        self._last_words = ""            # Miguel's last reply to the family: why a delivery failed
        self._caller: web.WebSocketResponse | None = None   # who asked for the check-in: only they see it
        self._called_off_at: float | None = None             # a check-in was called off while he asked
        self._to_caller_q: list[dict[str, Any]] = []         # the phone's call setup, in order, to the caller
        self._to_caller_task: asyncio.Task | None = None
        self.phones_path = Path(os.environ.get("FAMILY_PHONES") or PHONES_PATH)
        self.phones: dict[str, str] = self._load_phones()     # E.164 phone -> member id

    # --- linked phones (texting Miguel through the iMessage bridge) ------------------------------

    def _load_phones(self) -> dict[str, str]:
        try:
            raw = json.loads(self.phones_path.read_text())
        except (OSError, ValueError):
            return {}
        if not isinstance(raw, dict):
            return {}
        return {p: m for p, m in raw.items() if normalize_phone(p) == p and m in MEMBERS}

    def phones_msg(self) -> dict[str, Any]:
        return {"t": "phones", "items": [{"member": m, "phone": p} for p, m in self.phones.items()]}

    def link_phone(self, member: str, raw: Any) -> str | None:
        """Link a phone to a member ("" unlinks that member's phones). Returns an error for people, or None.
        A phone belongs to one member: linking it again moves it. One phone per member."""
        if member not in MEMBERS:
            return "Pick someone in the family."
        unlink = isinstance(raw, str) and not raw.strip()
        phone = None if unlink else normalize_phone(raw)
        if phone is None and not unlink:
            return "That doesn't look like a phone number. Try +1 215 555 0123."
        self.phones = {p: m for p, m in self.phones.items() if m != member and p != phone}
        if phone is not None:
            self.phones[phone] = member
        try:
            self.phones_path.write_text(json.dumps(self.phones, indent=1))
        except OSError:
            log.exception("family: couldn't save the linked phones")
        log.info("family: %s %s", MEMBERS[member], f"linked a phone ending {phone[-4:]}" if phone else "unlinked")
        try:
            asyncio.get_running_loop().create_task(self._broadcast(self.phones_msg()))
        except RuntimeError:
            pass
        return None

    # --- state ----------------------------------------------------------------------------------

    def _link_up(self) -> bool:
        try:
            ok = bool(self.state.link.health().ok)
        except Exception:  # noqa: BLE001
            ok = False
        frames = getattr(self.state, "phone_frames", None)
        if frames is not None:
            age = frames.age()
            ok = ok and age is not None and age < LINK_DOWN_S
        return ok

    def _work_out_mode(self) -> tuple[str, str]:
        her = "her"
        if not self._link_up():
            return "offline", "Miguel isn't connected right now"
        if self.delivery is not None and self.delivery["stage"] not in ("delivered", "failed"):
            return "delivering", f"Bringing {self.delivery['label'].lower()} to {her}"
        if self.check_in.get("phase") == "live":
            return "with_mom", f"On a call with {self.check_in.get('by', 'you')}"
        if self.alert is not None and self.alert.get("status") == "active":
            return "with_mom", f"Staying beside {her}"
        # the same source of truth as the phone's ring and /ws status.listening (MicHub.listening)
        hub = getattr(getattr(self.state, "mic", None), "hub", None)
        try:
            listening = hub is not None and bool((getattr(hub, "listening", None) or hub.in_window)())
        except Exception:  # noqa: BLE001
            listening = False
        if listening or self.check_in.get("phase") == "asking":
            return "listening", f"Talking with {her}"
        running = getattr(self.state, "follow_running", None)
        if callable(running) and running():
            return "with_mom", f"Walking with {her}"
        return "idle", f"Nearby, waiting for {her}"

    def snapshot_state(self) -> dict[str, Any]:
        mode = self._work_out_mode()
        if mode[0] != self._mode[0]:
            self._since = time.time()
        self._mode = mode
        check_in = wire_copy({k: v for k, v in self.check_in.items() if k in ("phase", "id", "started_at")})
        return {"t": "state", "mode": mode[0], "mode_note": mode[1], "since": iso(self._since),
                "link": "up" if self._link_up() else "down",
                "delivery": None if self.delivery is None else wire_copy(self.delivery, drop=("by",)),
                "check_in": check_in, "alert": None if self.alert is None else wire_copy(self.alert)}

    async def push_state(self, force: bool = False) -> None:
        st = self.snapshot_state()
        if not force and st == self._last_state:
            return
        gap = time.monotonic() - self._last_sent
        if not force and gap < STATE_MIN_GAP_S:
            await asyncio.sleep(STATE_MIN_GAP_S - gap)
            st = self.snapshot_state()
        self._last_state, self._last_sent = st, time.monotonic()
        for ws in list(self.clients):
            try:
                await ws.send_json(self._state_for(ws, st))
            except Exception:  # noqa: BLE001 - a closed socket is cleaned up by its handler
                pass

    def _state_for(self, ws: web.WebSocketResponse, st: dict[str, Any]) -> dict[str, Any]:
        """The check-in (and its frames) belong to the person who asked for it. Everyone else sees no
        check-in (the mode note still says Mom is on a call); asking for another one gets `busy`."""
        if ws is not self._caller and st["check_in"].get("phase", "idle") != "idle":
            return {**st, "check_in": {"phase": "idle"}}
        return st

    def changed(self) -> None:
        """Something in the state changed (from sync code): send it soon."""
        try:
            asyncio.get_running_loop().create_task(self.push_state())
        except RuntimeError:
            pass

    def timeline_cleared(self) -> None:
        """The control page erased the memory (#79): every open app gets today's (now empty) timeline."""
        today = self.memory.today() if self.memory is not None else []
        msg = {"t": "events", "day": datetime.now().astimezone().date().isoformat(),
               "items": [self._wire_event(e) for e in today]}
        try:
            asyncio.get_running_loop().create_task(self._broadcast(msg))
        except RuntimeError:
            pass

    async def _broadcast(self, msg: dict[str, Any]) -> None:
        for ws in list(self.clients):
            try:
                await ws.send_json(msg)
            except Exception:  # noqa: BLE001 - a closed socket is cleaned up by its handler
                pass

    async def _state_pump(self) -> None:
        """Link and mode change without any request: check twice a second."""
        while True:
            await asyncio.sleep(0.5)
            if self.clients:
                await self.push_state()

    # --- events (Mom's day) ---------------------------------------------------------------------

    def _wire_event(self, e: dict[str, Any]) -> dict[str, Any]:
        out = {"id": f"e{e['id']}", "at": iso(e["at"]), "kind": e["kind"], "title": e["title"]}
        if e.get("note"):
            out["note"] = e["note"]
        for k in ("quote", "quote_by", "photo"):
            if e.get("data", {}).get(k):
                out[k] = e["data"][k]
        return out

    def add_event(self, kind: str, title: str, note: str = "", **data: Any) -> None:
        if self.memory is None:
            e = {"id": next(self._ids), "at": time.time(), "kind": kind, "title": title, "note": note, "data": data}
        else:
            e = self.memory.add_event(kind, title, note, {k: v for k, v in data.items() if v})
        try:
            asyncio.get_running_loop().create_task(self._broadcast({"t": "event", **self._wire_event(e)}))
        except RuntimeError:
            pass

    # --- media ----------------------------------------------------------------------------------

    def store_media(self, data: bytes, content_type: str = "image/jpeg") -> str:
        mid = secrets.token_hex(16)
        self.media[mid] = (time.time(), content_type, data)
        while len(self.media) > MEDIA_KEEP:
            self.media.popitem(last=False)
        return f"/family/media/{mid}"

    def photo(self) -> str | None:
        if self.snapshot is None:
            return None
        try:
            jpeg = self.snapshot()
        except Exception:  # noqa: BLE001
            return None
        return self.store_media(jpeg) if jpeg else None

    # --- hooks from the rest of the server ------------------------------------------------------

    @staticmethod
    def _same_item(item: str, d: dict[str, Any]) -> bool:
        """Is this bring the family's? The family's message names the item; Mom may ask for something else."""
        said = set(re.findall(r"[a-z]+", item.lower()))
        ours = SAME_ITEM.get(d["item"], {d["item"]}) | set(re.findall(r"[a-z]+", d["label"].lower()))
        return bool(said & ours)

    def on_bring_step(self, stage: str, text: str, item: str | None = None) -> None:
        """The bring behavior's progress. `item` is what that bring carries: a bring Mom asked for by voice
        (pills while the family's water waits) doesn't move the family's delivery or read their note."""
        d = self.delivery
        if d is None or d["stage"] in ("delivered", "failed"):
            return
        if item is not None and not self._same_item(item, d):
            log.info("family: a bring of %r isn't the family's %s", item, d["label"])
            return
        d["stage"] = stage
        if stage == "failed":
            d["detail"] = text[:1].upper() + text[1:] if text else "Something went wrong"
            self.add_event("delivery", f"{d['label']} didn't arrive", d["detail"])
        elif stage == "delivered":
            if d.get("message"):
                self.state.add_say(d["message"])   # word for word, in Miguel's voice; never through Claude
            d["photo"] = self.photo()
            by = d.get("by") or "the family"
            self.add_event(EVENT_KIND.get(d["item"], "delivery"), f"{d['label']}, from {by}",
                           quote=d.get("message"), quote_by=by if d.get("message") else None, photo=d["photo"])
        self.changed()

    def on_agent_event(self, ev: dict[str, Any]) -> None:
        kind, text, data = ev.get("kind"), str(ev.get("text", "")), ev.get("data") or {}
        if data.get("ack"):
            return   # the instant "Got it, I'm on it." / "On it!": not an answer, not something he did
        if kind == "reply":
            photo = None
            m = re.fullmatch(r"/agent/photo/(\d+)\.jpg", str(data.get("photo_url") or ""))
            if m is not None:   # the agent's proof photo (ApiState.save_photo), re-served under a random id
                jpeg = getattr(self.state, "agent_photos", {}).get(int(m.group(1)))
                photo = self.store_media(jpeg) if jpeg else None
            self.add_event("message", "Miguel", text, photo=photo)
            self._last_words = text
            if self.alert is not None and self.alert.get("status") == "active":
                self._did("Told the family")
        elif kind == "check_in":
            self._check_in_answer(str(data.get("answer", text)))
        elif kind == "say":
            if self.alert is not None and self.alert.get("status") == "active":
                self._did(f"Said: {text}"[:120])
            if self.check_in.get("phase") == "asking" and "asked_at" not in self.check_in:
                self.check_in["asked_at"] = time.monotonic()   # he asked her: her answer must come after
        elif kind == "heard" and ev.get("data", {}).get("source", "senior") == "senior":
            asked = self.check_in.get("asked_at")
            if self.check_in.get("phase") == "asking" and asked is not None and said_yes(text):
                self.check_in["heard_yes"] = True              # #5: a spoken yes from her, after the question
            if self.alert is not None and self.alert.get("status") == "active" and text:
                self.alert["heard"] = text[:200]
            if self.check_in.get("phase") == "live" and text:
                from app.brain.agent import stop_requested

                if stop_requested(text):   # "stop" / "wait" from her ends the call, like hanging up
                    self._end_call("she stopped it")
        if kind in ("task", "reply", "error") and data.get("status") != "started":
            self._settle_soon()
        self.changed()

    def _did(self, line: str) -> None:
        did = self.alert["did"]
        if line not in did:
            did.append(line)
            del did[:-DID_KEEP]

    # --- requests the agent dropped -----------------------------------------------------------

    def _settle_soon(self) -> None:
        """A task ended (or he answered, or hit an error): a moment later, once a queued request has had
        the chance to start, check whether he has stopped working with a family request still open."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._settle is not None:
            self._settle.cancel()
        self._settle = loop.call_later(SETTLE_DELAY_S, self._settle_if_idle)

    def _agent_idle(self) -> bool:
        """True only when the agent says it has nothing running or waiting (ApiState.agent_working)."""
        working = getattr(self.state, "agent_working", None)
        if not callable(working):
            return False   # can't tell: leave it to bring's stages and the check-in timeout
        try:
            return not working()
        except Exception:  # noqa: BLE001
            return False

    def _settle_if_idle(self) -> None:
        """He finished everything he was asked without finishing the family's request: say so. Another
        task ending (Mom chatting with him) no longer fails a delivery that's still queued behind it."""
        self._settle = None
        if not self._agent_idle():
            return
        d = self.delivery
        if d is not None and d["stage"] in ("sent", "loading", "on_the_way") \
                and getattr(self.state.skills, "running", None) != "bring":
            d["stage"] = "failed"
            d["detail"] = (self._last_words or "Miguel stopped before he got to her.")[:200]
            self.add_event("delivery", f"{d['label']} didn't arrive", d["detail"])
        if self.check_in.get("phase") == "asking":
            self._decline("No answer.")
        self.changed()

    def raise_alert(self, saw: str, place: str | None = None, *, tell_agent: bool = True) -> dict[str, Any]:
        aid = f"a{next(self._ids)}"
        self.alert = {"id": aid, "kind": "possible_fall", "at": iso(), "saw": saw, "did": [], "status": "active"}
        photo = self.photo()   # None before the camera's first frame: then the alert has no photo field
        if photo:
            self.alert["photo"] = photo
        if place:
            self.alert["place"] = place
        self.add_event("alert", "Possible fall", saw, photo=photo)
        if tell_agent:
            self.state.agent_message(
                f"[fall alert] The camera thinks {self.short} may have fallen: {saw} Tell the family now with a "
                f"photo, then ask if she is okay, wait for her answer, and tell them what she said.",
                "operator", "fall detector")   # this channel name skips the "On it!" ack (brain.prompt.FALL_CHANNEL)
        self.changed()
        return self.alert

    # --- requests -------------------------------------------------------------------------------

    async def _request(self, ws: web.WebSocketResponse, viewer: str, m: dict[str, Any]) -> None:
        t, ref = m.get("t"), m.get("ref")

        about = {"ref": ref} if isinstance(ref, str) else {}   # never "ref": null (the app drops it)

        async def ok(**extra: Any) -> None:
            await ws.send_json({"t": "ack", **about, "ok": True, **extra})

        async def err(code: str, message: str) -> None:
            await ws.send_json({"t": "error", **about, "code": code, "message": message})

        name = MEMBERS.get(viewer, "your family")
        if t == "send":
            item, label = m.get("item"), str(m.get("label") or "").strip()[:60]
            message = str(m.get("message") or "").strip()[:300] or None
            if item not in ITEMS or not label:
                return await err("bad_request", "Pick something to send.")
            if self.delivery is not None and self.delivery["stage"] not in ("delivered", "failed"):
                return await err("busy", f"Miguel is already bringing {self.delivery['label'].lower()}. "
                                         "Try again when he's back.")
            did = f"d{next(self._ids)}"
            self.delivery = {"id": did, "item": item, "label": label, "message": message, "stage": "sent",
                             "detail": None, "photo": None, "by": name}
            self._last_words = ""
            note = (" They wrote a note; don't read it or make one up: it is read to her word for word when you "
                    "deliver." if message else "")
            status, why = self.state.agent_message(
                f"[family app, from {name}] Please bring {self.short} {label.lower()} (item: {item}). Use "
                f"bring(item={item!r}, person={self.short!r}).{note}", "guardian", "family app")
            if status != 200:
                self.delivery["stage"], self.delivery["detail"] = "failed", f"Miguel's brain is off ({why})"
            await ok(id=did)
        elif t == "check_in":
            action = m.get("action")
            if action == "request":
                if self.check_in.get("phase") in ("asking", "live"):
                    return await err("busy", "A check-in is already going.")
                if self._called_off_at is not None and time.monotonic() - self._called_off_at < STALE_ANSWER_S \
                        and not self._agent_idle():
                    # He may still answer the one that was called off; that answer mustn't open this one.
                    return await err("busy", "Miguel is still finishing the last check-in. Try again in a moment.")
                cid = f"c{next(self._ids)}"
                self.check_in = {"phase": "asking", "id": cid, "by": name}
                self._caller, self._called_off_at = ws, None
                status, why = self.state.agent_message(
                    f"[check-in request, family app] {name} would like to check in on {self.short} by video. Ask "
                    f"her by name if now is a good time, wait_for_reply(15), then call check_in_result. If she "
                    f"says yes, the video call opens on your screen and you stay quiet until it ends.",
                    "guardian", "family app")
                if status != 200:
                    self.check_in = {"phase": "declined", "id": cid}
                else:
                    asyncio.get_running_loop().call_later(ASK_TIMEOUT_S, self._ask_timed_out, cid)
                await ok(id=cid)
            elif action == "end":
                if self.check_in.get("phase") == "asking":   # Miguel is still asking her: call it off
                    self._call_off(f"{name} cancelled the video check-in.")
                self._end_call("ended")
                await ok()
            else:
                await err("bad_request", "Unknown check-in action.")
        elif t == "ask":
            text = str(m.get("text") or "").strip()
            if not 1 <= len(text) <= 500:
                return await err("bad_request", "Type a message for Miguel.")
            status, why = self.state.agent_message(f"[family app, from {name}] {text}", "guardian", "family app")
            if status != 200:
                return await err("unavailable", f"Miguel can't answer right now ({why}).")
            await ok()
        elif t == "alert":
            if self.alert is None or self.alert.get("id") != m.get("id"):
                return await err("not_found", "That alert is already closed.")
            self.alert.update(status="handled", handled_by=name)
            self.add_event("alert", "Alert handled", f"{name} is on it.")
            await ok()
        elif t == "phone":
            problem = self.link_phone(str(m.get("member") or viewer), m.get("phone"))
            if problem:
                return await err("bad_request", problem)
            await ok()
        elif t in ("routine", "invite"):
            await ok()   # routines and the circle stay the app's demo data for Sunday
        elif t == "talk":
            await err("unsupported", "Voice clips to her aren't ready yet. Use Ask Miguel instead.")
        elif t == "rtc":
            c = self.check_in
            if c.get("phase") != "live" or ws is not self._caller or m.get("call") != c.get("id"):
                return await err("no_consent", "There's no video call to connect.")
            payload = rtc_payload(m)
            if payload is None:
                return await err("bad_request", "That isn't a WebRTC offer, answer or candidate.")
            hub = self._mic_hub()
            if hub is None or not hub.send({"type": "rtc", "call": c["id"], **payload}):
                return await err("unavailable", "Miguel's phone isn't connected.")
            return   # relayed; no ack (call setup has no ref) and nothing in `state` changed
        else:
            await err("bad_request", f"Unknown message {t!r}.")
        await self.push_state()

    # --- check-in -------------------------------------------------------------------------------

    def _check_in_answer(self, answer: str) -> None:
        if self.check_in.get("phase") == "live" and answer in ("no", "no_answer"):
            self._end_call("she ended it")   # the agent's end-call path (see the request message)
            return
        if self.check_in.get("phase") != "asking":
            return
        if answer == "yes" and not self.check_in.get("heard_yes"):
            # #69 review #5: consent in code, not only the LLM's judgment. No spoken yes from her after
            # the question (background talk, or someone telling the agent to say yes): declined.
            log.warning("family: check-in 'yes' refused: no spoken yes from her after the question")
            self._decline("She didn't say yes.")
            return
        if answer == "yes":
            self.check_in.update(phase="live", started_at=iso(), t0=time.time())
            settings = getattr(self.state, "settings", None) or {}
            self._camera_before = settings.get("camera")
            self._follow_before = self._following()
            busy = getattr(getattr(self.state, "skills", None), "running", None)
            try:
                if hasattr(self.state, "set_follow"):
                    self.state.set_follow(False)
                if busy in (None, "follow"):   # not mid-delivery: switching cameras would turn him around
                    self.state.set_settings({"camera": "front"})   # look at her while they talk
            except Exception:  # noqa: BLE001
                log.exception("family: switching to the front camera failed")
            self._call_task = asyncio.get_running_loop().create_task(self._relay(self.check_in["id"]))
            hub = self._mic_hub()
            if hub is not None and hasattr(hub, "set_call"):   # the phone shows the call; Miguel stops hearing
                hub.on_call_message = self.on_phone_call
                hub.set_call({"type": "call", "call": self.check_in["id"], "on": True,
                              "by": self.check_in.get("by", "Family")})
        else:
            self._decline("Not a good time." if answer == "no" else "No answer.")

    def _call_off(self, why: str) -> None:
        """Tell the agent to stop asking her, and hold new check-ins until he's done with this one."""
        self._called_off_at = time.monotonic()
        self.state.agent_message(f"[check-in cancelled, family app] {why} Stop asking {self.short} about it; "
                                 f"don't call check_in_result.", "guardian", "family app")

    def _decline(self, note: str) -> None:
        self.check_in.update(phase="declined")
        self.add_event("check_in", "Check-in declined", note)

    def _ask_timed_out(self, cid: str) -> None:
        """Nobody answered in time (the agent never called check_in_result): decline, and tell him to drop
        it in case the request is still waiting behind something else."""
        if self.check_in.get("phase") != "asking" or self.check_in.get("id") != cid:
            return
        busy = not self._agent_idle() and callable(getattr(self.state, "agent_working", None))
        if busy:   # the request may still be waiting behind something else: don't let him ask her later
            self._call_off("Nobody answered the video check-in in time.")
        self._decline("Miguel was busy and couldn't ask her." if busy else "No answer.")
        self.changed()

    def _end_call(self, why: str) -> None:
        c = self.check_in
        if c.get("phase") == "live":
            minutes = max(1, round((time.time() - c.get("t0", time.time())) / 60))
            self.add_event("check_in", f"{c.get('by', 'You')} checked in", f"{minutes} minute{'s' if minutes > 1 else ''}.")
            if self._camera_before is not None:
                try:
                    self.state.set_settings({"camera": self._camera_before})
                except Exception:  # noqa: BLE001
                    pass
            if self._follow_before and hasattr(self.state, "set_follow"):   # back to walking with her
                try:
                    self.state.set_follow(True)
                except Exception:  # noqa: BLE001
                    log.exception("family: turning follow back on failed")
            self._follow_before = False
        if self._call_task is not None:
            self._call_task.cancel()
            self._call_task = None
        hub = self._mic_hub()
        if hub is not None and getattr(hub, "call", None) is not None:   # the phone's call ends too
            hub.set_call(None)
        self.check_in = {"phase": "idle"}
        self._caller = None
        self._to_caller_q.clear()
        log.info("family: check-in %s", why)
        self.changed()

    # --- the video call (#118) --------------------------------------------------------------------

    def _mic_hub(self) -> Any:
        """The phone's mic socket (app/speech/mic.py MicHub): the phone page's channel for the call."""
        return getattr(getattr(self.state, "mic", None), "hub", None)

    def on_phone_call(self, msg: dict[str, Any]) -> None:
        """A call message from the robot's phone page (over its mic socket): its WebRTC setup goes to
        the caller, only while that call is live; `hangup` (her End button) ends it for both."""
        c = self.check_in
        if c.get("phase") != "live" or msg.get("call") != c.get("id"):
            return
        if msg.get("type") == "hangup":
            self._end_call("she hung up on Miguel's screen")
            return
        payload = rtc_payload(msg)
        if payload is not None and self._caller is not None:
            self._to_caller({"t": "rtc", "call": c["id"], **payload})

    def _to_caller(self, msg: dict[str, Any]) -> None:
        """Send to the caller in order (an offer before its candidates), from sync code."""
        self._to_caller_q.append(msg)
        if self._to_caller_task is None or self._to_caller_task.done():
            self._to_caller_task = asyncio.get_running_loop().create_task(self._drain_to_caller())

    async def _drain_to_caller(self) -> None:
        while self._to_caller_q:
            msg, caller = self._to_caller_q.pop(0), self._caller
            live = self.check_in.get("phase") == "live" and self.check_in.get("id") == msg.get("call")
            if caller is None or not live:
                continue
            try:
                await caller.send_json(msg)
            except Exception:  # noqa: BLE001 - their socket closing ends the call (handle)
                pass

    def _following(self) -> bool:
        f = getattr(self.state, "following", None) or getattr(self.state, "follow_running", None)
        try:
            return bool(f()) if callable(f) else False
        except Exception:  # noqa: BLE001
            return False

    async def _relay(self, call: str) -> None:
        """Camera frames to the apps, only while the call is live (consent is checked every frame).
        The JPEG is made off the event loop, so a call doesn't hold up driving or speech."""
        t0 = time.monotonic()
        try:
            while self.check_in.get("phase") == "live" and self.check_in.get("id") == call:
                if time.monotonic() - t0 > CALL_MAX_S:
                    self._end_call("timed out")
                    return
                try:
                    jpeg = await asyncio.to_thread(self.snapshot) if self.snapshot is not None else None
                except Exception:  # noqa: BLE001 - one bad frame mustn't end the call's video
                    log.exception("family: camera snapshot failed")
                    jpeg = None
                live = self.check_in.get("phase") == "live" and self.check_in.get("id") == call
                caller = self._caller
                if jpeg and live and caller is not None:   # consent again, and only to whoever asked
                    try:
                        await caller.send_json({"t": "frame", "call": call, "jpeg": base64.b64encode(jpeg).decode()})
                    except Exception:  # noqa: BLE001 - their socket closing ends the call (handle)
                        pass
                await asyncio.sleep(1 / FRAME_HZ)
        except asyncio.CancelledError:
            pass

    # --- sockets --------------------------------------------------------------------------------

    def _token_ok(self, given: Any, request: web.Request) -> bool:
        if self.token:
            return isinstance(given, str) and hmac.compare_digest(given.encode(), self.token.encode())
        from app.api import _direct_local   # no token: this laptop only, never through a tunnel on it

        return _direct_local(request)

    async def handle(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        if self._pump is None or self._pump.done():
            self._pump = asyncio.get_running_loop().create_task(self._state_pump())
        try:
            first = await ws.receive(timeout=10)
        except asyncio.TimeoutError:
            await ws.close()
            return ws
        try:
            hello = first.json() if first.type == WSMsgType.TEXT else {}
        except ValueError:
            hello = {}
        if not isinstance(hello, dict):
            hello = {}
        if hello.get("t") != "hello" or not self._token_ok(hello.get("token"), request):
            await ws.send_json({"t": "error", "code": "unauthorized", "message": "Sign in again."})
            await ws.close()
            log.warning("family: refused a sign-in from %s", request.remote)
            return ws
        viewer = str(hello.get("viewer") or "m1")
        self.clients[ws] = viewer
        log.info("family app connected (%s, %s)", MEMBERS.get(viewer, viewer), request.remote)
        try:
            await ws.send_json({"t": "welcome", "v": 1, "resident": {"name": self.resident, "short": self.short},
                                "viewer": {"id": viewer, "name": MEMBERS.get(viewer, "You")}, "tz": self.tz,
                                "now": iso()})
            await ws.send_json(self._state_for(ws, self.snapshot_state()))
            today = self.memory.today() if self.memory is not None else []
            await ws.send_json({"t": "events", "day": datetime.now().astimezone().date().isoformat(),
                                "items": [self._wire_event(e) for e in today]})
            await ws.send_json(self.phones_msg())
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    m = msg.json()
                except ValueError:
                    continue
                if isinstance(m, dict):
                    await self._request(ws, viewer, m)
        finally:
            self.clients.pop(ws, None)
            if ws is self._caller and self.check_in.get("phase") in ("asking", "live", "declined"):
                # The person who asked left (closed the app, lost the connection): the call ends with them.
                if self.check_in.get("phase") == "asking":
                    self._call_off(f"{MEMBERS.get(viewer, 'The family')} left before she answered.")
                self._end_call("the caller left")
        return ws

    async def get_media(self, request: web.Request) -> web.StreamResponse:
        item = self.media.get(request.match_info["mid"])
        if item is None or time.time() - item[0] > MEDIA_TTL_S:
            raise web.HTTPNotFound()
        return web.Response(body=item[2], content_type=item[1], headers={"Cache-Control": "private, max-age=86400"})

    async def control_phones(self, request: web.Request) -> web.Response:
        """The control page's Family phones (this laptop only): GET the list, POST {member, phone}."""
        from app.api import _local

        if not _local(request):
            raise web.HTTPForbidden()
        if request.method == "POST":
            try:
                body = await request.json()
            except ValueError:
                body = {}
            problem = self.link_phone(str(body.get("member") or ""), body.get("phone")) if isinstance(body, dict) \
                else "Bad request."
            if problem:
                return web.json_response({"ok": False, "error": problem}, status=400)
        return web.json_response({"ok": True, "members": MEMBERS, **self.phones_msg()})

    def routes(self) -> list[web.RouteDef]:
        return [web.get("/family/ws", self.handle), web.get("/family/media/{mid}", self.get_media),
                web.get("/family/phones", self.control_phones), web.post("/family/phones", self.control_phones)]
