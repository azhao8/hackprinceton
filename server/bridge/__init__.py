"""Miguel on iMessage: family members text Miguel through Photon 2.0 (Beta), and he texts back.

A separate process, one more client of the family app's `/family/ws` (contract/web/family.md). It
never talks to the robot and never changes the server: it turns texts into the same requests the
family app sends, and the server's broadcasts into texts. Setup for people: docs/photon.md.

    text "how's mom?"                -> `ask`             -> Miguel's reply (an `event`) -> a text
    text 'bring her water, say "hi"' -> `send`            -> delivery stages             -> texts (+ photo)
    text "got it" during an alert    -> `alert` handled   -> the others are told who's on it
    (a fall alert on the server)                          -> a text + photo to everyone linked

Who's who: the phones linked in the family app or on the control page (`phones`), plus
PHOTON_FAMILY in .env as a fallback (`+12155550123:m2,...`). Anyone else gets a polite no.
Photon's shared iMessage line only sends to someone who has texted it since their number was
assigned, so every family member texts Miguel once first.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.family import MEMBERS, normalize_phone

log = logging.getLogger("bridge")

ASKER_WINDOW_S = 180.0     # Miguel's reply to an `ask` goes to whoever asked within this long
THREADS_PATH = Path(__file__).resolve().parents[1] / "photon-threads.json"   # phone -> its thread (git-ignored)

GOT_IT = re.compile(r"^\s*(i'?ve |i |ive )?(got it|got this|on it|i'?m on it|handled|handling it|coming|on my way)\b",
                    re.I)
QUOTED = re.compile(r"[\"“”]([^\"“”]{1,300})[\"“”]")
BRING = re.compile(r"^\s*(?:please\s+|can you\s+|could you\s+|miguel,?\s+)*(?:bring|take|get)\s+(?P<rest>.+)$", re.I | re.S)
WATER = {"water", "drink", "glass", "bottle"}
MEDS = {"medication", "medicine", "meds", "pill", "pills", "tablets"}
FILLER = {"her", "him", "mom", "mum", "my", "a", "an", "some", "the", "of", "to", "please", "glass", "bottle",
          "cup", "for", "me", "now", "fresh", "cold"}


def last4(phone: str) -> str:
    return "…" + phone[-4:]


def parse_bring(text: str) -> dict[str, Any] | None:
    """'bring her water, say "love you"' -> {item: water, label: Water, message: love you}. None when it isn't a
    plain bring, or when the note isn't in quotes (then Miguel's agent handles it in his own words)."""
    m = BRING.match(text)
    if m is None:
        return None
    note_m = QUOTED.search(text)
    rest = QUOTED.sub("", m.group("rest"))
    if note_m is None and re.search(r"\b(tell|say|ask|remind)\b", rest, re.I):
        return None   # an unquoted note: let the agent say it his way
    if re.match(r"\s*(?:her|him|mom|them)?\s*(?:to|into|over)\b", rest, re.I):
        return None   # "bring her to the kitchen": walking with her, not an item
    parts = re.split(r"(,|\.|!|\band\b|\bsay\b|\btell\b|\bwith\b|\bfrom\b)", rest, maxsplit=1, flags=re.I)
    what, tail = parts[0], "".join(parts[1:])
    if re.sub(r"[\s,.!]|\b(and|say|with|a|the|note|it|please)\b", "", tail, flags=re.I):
        return None   # more than an item and a quoted note ("from the attic", "after lunch"): the agent decides
    words = [w for w in re.findall(r"[a-z]+", what.lower()) if w not in FILLER]
    if not words or len(words) > 4:
        return None
    if set(words) & WATER or "water" in what.lower():
        item, label = "water", "Water"
    elif set(words) & MEDS:
        item, label = "medication", "Her medication"
    else:
        item, label = "other", " ".join(words).capitalize()[:60]
    message = note_m.group(1).strip() if note_m else None
    return {"item": item, "label": label, "message": message}


class Bridge:
    """The logic, with Photon and the server behind small callables so tests can fake both.

    - `send_text(thread, text)`, `send_photo(thread, jpeg)`, `typing(thread)`: Photon, by thread
      (`{"space": ..., "agent": ...}`, taken from the person's last text).
    - `request(member, msg) -> reply`: one request on that member's `/family/ws` socket; the reply is the
      server's `ack` or `error`.
    - `fetch(path) -> bytes | None`: a `/family/media/...` photo from the server.
    """

    def __init__(self, *, send_text: Callable[[dict, str], Awaitable[None]],
                 send_photo: Callable[[dict, bytes], Awaitable[None]],
                 typing: Callable[[dict], Awaitable[None]],
                 request: Callable[[str, dict], Awaitable[dict]],
                 fetch: Callable[[str], Awaitable[bytes | None]],
                 fallback_phones: dict[str, str] | None = None, resident: str = "Margaret", short: str = "Mom",
                 tz: str = "America/New_York", threads_path: Path | None = None):
        self.send_text, self.send_photo, self.typing = send_text, send_photo, typing
        self.request, self.fetch = request, fetch
        self.fallback = dict(fallback_phones or {})
        self.server_phones: dict[str, str] = {}
        self.resident, self.short, self.tz = resident, short, tz
        self.threads_path = threads_path
        self.threads: dict[str, dict[str, str]] = self._load_threads()
        self.seen: set[str] = set()
        self.asker: tuple[str, float] | None = None          # (member, when) of the last texted `ask`
        self.deliveries: dict[str, dict[str, Any]] = {}       # our delivery id -> {member, stage}
        self.alert: dict[str, Any] | None = None              # the last alert we texted about
        self.names = dict(MEMBERS)

    # --- who's who ---------------------------------------------------------------------------------

    @property
    def phones(self) -> dict[str, str]:
        return {**self.fallback, **self.server_phones}

    def member_of(self, handle: str) -> str | None:
        return self.phones.get(normalize_phone(handle) or handle.strip().lower())

    def phones_of(self, member: str) -> list[str]:
        return [p for p, m in self.phones.items() if m == member]

    def _load_threads(self) -> dict[str, dict[str, str]]:
        if self.threads_path is None:
            return {}
        try:
            raw = json.loads(self.threads_path.read_text())
        except (OSError, ValueError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def _save_threads(self) -> None:
        if self.threads_path is not None:
            try:
                self.threads_path.write_text(json.dumps(self.threads))
            except OSError:
                log.exception("couldn't save the threads")

    async def text_member(self, member: str, text: str, photo: str | None = None) -> bool:
        """Text everyone linked as this member who has a thread with Miguel. False if nobody could be reached."""
        sent = False
        for phone in self.phones_of(member):
            thread = self.threads.get(phone)
            if thread is None:
                log.info("%s (%s) hasn't texted Miguel yet: can't text them", self.names.get(member, member), last4(phone))
                continue
            await self._send(thread, text, photo)
            sent = True
        return sent

    async def text_family(self, text: str, photo: str | None = None, *, skip: str | None = None) -> None:
        for member in {m for m in self.phones.values() if m != skip}:
            await self.text_member(member, text, photo)

    async def _send(self, thread: dict[str, str], text: str, photo: str | None = None) -> None:
        try:
            await self.send_text(thread, text)
            if photo:
                jpeg = await self.fetch(photo)
                if jpeg:
                    await self.send_photo(thread, jpeg)
        except Exception:  # noqa: BLE001 - one failed text mustn't stop the others
            log.exception("photon: send failed")

    # --- texts in ----------------------------------------------------------------------------------

    async def on_text(self, msg: dict[str, Any]) -> None:
        """A `message.received` object from Photon."""
        mid = str(msg.get("id") or "")
        if not mid or mid in self.seen:
            return   # Photon may redeliver after a reconnect
        self.seen.add(mid)
        sent_by, space = msg.get("sentBy") or {}, msg.get("space") or {}
        if sent_by.get("kind", "human") != "human":
            return
        handle = str(sent_by.get("handle") or "")
        thread = {"space": str(space.get("id") or ""), "agent": str((msg.get("receivedBy") or {}).get("id") or "")}
        content = msg.get("content") or {}
        text = str(content.get("text") or "").strip() if content.get("type") == "text" else ""
        if not thread["space"] or not thread["agent"]:
            return
        member = self.member_of(handle)
        key = normalize_phone(handle) or handle.strip().lower()
        self.threads[key] = thread
        self._save_threads()
        if member is None:
            log.info("text from an unlinked number (%s): turned away", last4(key))
            await self._send(thread, f"Hi! I'm Miguel. I only talk with {self.resident}'s family. Ask them to link "
                                     f"your number in the family app.")
            return
        name = self.names.get(member, "family")
        if not text:
            await self._send(thread, "I can only read text for now.")
            return
        log.info("text from %s: %r", name, text[:80])
        try:
            await self.typing(thread)
        except Exception:  # noqa: BLE001 - typing dots are a nicety
            pass
        if self.alert is not None and self.alert.get("status") == "active" and GOT_IT.match(text):
            r = await self.request(member, {"t": "alert", "id": self.alert["id"], "action": "handled"})
            await self._send(thread, "Thanks. I've told everyone you're on it." if r.get("t") == "ack"
                             else r.get("message", "That alert is already closed."))
            return
        if text.lower() in ("hi", "hello", "hey", "hi miguel", "hello miguel", "hey miguel"):
            await self._send(thread, f"Hi {name}! It's Miguel. Ask me how {self.short} is, or say "
                                     f"'bring her water, say \"love you\"'. I'll text you if anything happens.")
            return
        bring = parse_bring(text)
        if bring is not None:
            r = await self.request(member, {"t": "send", **{k: v for k, v in bring.items() if v is not None}})
            if r.get("t") == "ack" and r.get("id"):
                self.deliveries[str(r["id"])] = {"member": member, "stage": "sent", "label": bring["label"]}
                await self._send(thread, f"On it. {bring['label']} for {self.short}"
                                         + (", with your note." if bring.get("message") else "."))
            else:
                await self._send(thread, r.get("message") or "I couldn't start that.")
            return
        self.asker = (member, time.monotonic())
        r = await self.request(member, {"t": "ask", "text": text[:500]})
        if r.get("t") != "ack":
            await self._send(thread, r.get("message") or "I can't answer right now.")

    # --- the server's broadcasts ---------------------------------------------------------------------

    def _clock(self) -> str:
        try:
            now = datetime.now(ZoneInfo(self.tz))
        except Exception:  # noqa: BLE001
            now = datetime.now()
        return now.strftime("%-I:%M")

    async def on_server(self, m: dict[str, Any]) -> None:
        t = m.get("t")
        if t == "welcome":
            self.resident = (m.get("resident") or {}).get("name") or self.resident
            self.short = (m.get("resident") or {}).get("short") or self.short
            self.tz = m.get("tz") or self.tz
        elif t == "phones":
            self.server_phones = {str(i.get("phone")): str(i.get("member")) for i in m.get("items") or []
                                  if isinstance(i, dict) and i.get("phone") and i.get("member")}
            log.info("linked phones: %s", ", ".join(f"{self.names.get(mb, mb)} {last4(p)}"
                                                    for p, mb in self.phones.items()) or "none")
        elif t == "state":
            await self._on_delivery(m.get("delivery"))
            await self._on_alert(m.get("alert"))
        elif t == "event" and m.get("kind") == "message" and str(m.get("title", "")).startswith("Miguel"):
            await self._on_reply(str(m.get("note") or "").strip(), m.get("photo"))

    async def _on_reply(self, text: str, photo: str | None) -> None:
        if not text:
            return
        if self.alert is not None and self.alert.get("status") == "active":
            await self.text_family(text, photo)   # during an alert, what Miguel tells the family goes to everyone
            return
        if self.asker is not None and time.monotonic() - self.asker[1] < ASKER_WINDOW_S:
            await self.text_member(self.asker[0], text, photo)

    async def _on_delivery(self, d: dict[str, Any] | None) -> None:
        if not isinstance(d, dict):
            return
        ours = self.deliveries.get(str(d.get("id")))
        stage = d.get("stage")
        if ours is None or stage == ours["stage"]:
            return
        ours["stage"] = stage
        label = ours["label"]
        if stage == "loading":
            text = f"At the station, waiting for someone to put the {label.lower()} on my tray."
        elif stage == "on_the_way":
            text = f"On my way to {self.short} with the {label.lower()}."
        elif stage == "delivered":
            text = f"Delivered {self._clock()}. {self.short} has the {label.lower()}."
        elif stage == "failed":
            text = f"I couldn't deliver the {label.lower()}: {d.get('detail') or 'something went wrong'}."
        else:
            return
        await self.text_member(ours["member"], text, d.get("photo") if stage == "delivered" else None)

    async def _on_alert(self, a: dict[str, Any] | None) -> None:
        if not isinstance(a, dict):
            return
        before = self.alert if self.alert is not None and self.alert.get("id") == a.get("id") else None
        self.alert = dict(a)
        if before is None and a.get("status") == "active":
            where = f" in the {a['place']}" if a.get("place") else ""
            heard = f' She said: "{a["heard"]}"' if a.get("heard") else ""
            await self.text_family(f"⚠️ {self.resident} may have fallen{where}. {a.get('saw', '')}{heard} "
                                   f"Miguel is with her. Reply \"got it\" if you're handling it.", a.get("photo"))
            return
        if before is None:
            return
        if a.get("heard") and a.get("heard") != before.get("heard") and a.get("status") == "active":
            await self.text_family(f'{self.short} said: "{a["heard"]}"')
        if a.get("status") == "handled" and before.get("status") != "handled":
            by = a.get("handled_by") or "Someone"
            skip = next((mid for mid, n in self.names.items() if n == by), None)
            await self.text_family(f"{by} is on it.", skip=skip)


def parse_family(raw: str | None) -> dict[str, str]:
    """PHOTON_FAMILY: '+12155550123:m2, +16095550188:m1' -> {phone: member}."""
    out: dict[str, str] = {}
    for part in (raw or "").split(","):
        phone, _, member = part.strip().rpartition(":")
        p = normalize_phone(phone)
        if p and member.strip() in MEMBERS:
            out[p] = member.strip()
    return out
