"""The iMessage bridge (server/bridge): texts in -> family requests; the server's broadcasts -> texts."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.family import normalize_phone
from bridge import Bridge, parse_bring, parse_family

DAVID, SARAH, STRANGER = "+12155550123", "+16095550188", "+19175550100"


@pytest.mark.parametrize("text, want", [
    ('bring her water, say "love you, Mom"', {"item": "water", "label": "Water", "message": "love you, Mom"}),
    ("bring mom some water", {"item": "water", "label": "Water", "message": None}),
    ("Please bring her pills", {"item": "medication", "label": "Her medication", "message": None}),
    ("take her a banana", {"item": "other", "label": "Banana", "message": None}),
    ("bring her water and tell her I love her", None),     # unquoted note: Miguel's agent words it
    ("how's mom?", None),
    ("bring her the big blue box from the attic upstairs now", None),
    ("bring her to the kitchen", None),
    ('bring her a blanket with a note "stay warm"', {"item": "other", "label": "Blanket", "message": "stay warm"}),
])
def test_parse_bring(text: str, want: dict | None) -> None:
    assert parse_bring(text) == want


def test_parse_family_and_phones() -> None:
    assert parse_family("+1 (215) 555-0123:m2, 6095550188:m1, junk, +15550000000:m9") == {DAVID: "m2", SARAH: "m1"}
    assert normalize_phone("215-555-0123") == DAVID
    assert normalize_phone("12") is None


class Fakes:
    def __init__(self) -> None:
        self.texts: list[tuple[str, str]] = []      # (space, text)
        self.photos: list[str] = []
        self.requests: list[tuple[str, dict]] = []
        self.reply: dict[str, Any] = {"t": "ack", "ok": True}

    async def send_text(self, thread: dict, text: str) -> None:
        self.texts.append((thread["space"], text))

    async def send_photo(self, thread: dict, jpeg: bytes) -> None:
        self.photos.append(thread["space"])

    async def typing(self, thread: dict) -> None:
        pass

    async def request(self, member: str, msg: dict) -> dict:
        self.requests.append((member, msg))
        return self.reply

    async def fetch(self, path: str) -> bytes | None:
        return b"jpeg"


def make(fakes: Fakes) -> Bridge:
    return Bridge(send_text=fakes.send_text, send_photo=fakes.send_photo, typing=fakes.typing,
                  request=fakes.request, fetch=fakes.fetch, fallback_phones={DAVID: "m2"})


def text(phone: str, body: str, mid: str) -> dict:
    return {"id": mid, "sentBy": {"kind": "human", "handle": phone}, "receivedBy": {"id": "pho_usr_agent"},
            "space": {"id": f"spc-{phone[-4:]}"}, "content": {"type": "text", "format": "plain", "text": body}}


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_stranger_is_turned_away() -> None:
    f = Fakes()
    run(make(f).on_text(text(STRANGER, "bring her water", "m1")))
    assert f.requests == []
    assert "only talk with" in f.texts[0][1]


def test_ask_round_trip_and_dedupe() -> None:
    f = Fakes()
    b = make(f)

    async def go() -> None:
        await b.on_text(text(DAVID, "how's mom?", "x1"))
        await b.on_text(text(DAVID, "how's mom?", "x1"))   # Photon redelivered it
        await b.on_server({"t": "event", "kind": "message", "title": "Miguel", "note": "She's resting."})

    run(go())
    assert f.requests == [("m2", {"t": "ask", "text": "how's mom?"})]
    assert f.texts == [("spc-0123", "She's resting.")]


def test_server_linked_phone_and_delivery_with_photo() -> None:
    f = Fakes()
    b = make(f)
    f.reply = {"t": "ack", "ok": True, "id": "d7"}

    async def go() -> None:
        await b.on_server({"t": "phones", "items": [{"member": "m1", "phone": SARAH}]})
        await b.on_text(text(SARAH, 'bring her water, say "love you"', "x2"))
        await b.on_server({"t": "state", "delivery": {"id": "d7", "stage": "on_the_way"}, "alert": None})
        await b.on_server({"t": "state", "delivery": {"id": "d7", "stage": "on_the_way"}, "alert": None})
        await b.on_server({"t": "state", "delivery": {"id": "d7", "stage": "delivered", "photo": "/family/media/p"},
                           "alert": None})

    run(go())
    assert f.requests[0] == ("m1", {"t": "send", "item": "water", "label": "Water", "message": "love you"})
    said = [t for _, t in f.texts]
    assert said[0].startswith("On it.") and said[1].startswith("On my way") and said[2].startswith("Delivered")
    assert len(said) == 3 and f.photos == ["spc-0188"]


def test_alert_goes_to_everyone_who_texted_and_got_it_tells_the_others() -> None:
    f = Fakes()
    b = make(f)
    b.fallback[SARAH] = "m1"
    alert = {"id": "a1", "kind": "possible_fall", "saw": "She's on the floor.", "status": "active",
             "photo": "/family/media/q"}

    async def go() -> None:
        await b.on_text(text(DAVID, "hi", "y1"))
        await b.on_text(text(SARAH, "hi", "y2"))
        f.texts.clear()
        await b.on_server({"t": "state", "delivery": None, "alert": alert})
        await b.on_text(text(SARAH, "got it", "y3"))
        await b.on_server({"t": "state", "delivery": None, "alert": {**alert, "status": "handled",
                                                                    "handled_by": "Sarah"}})

    run(go())
    alerts = [s for s, t in f.texts if "may have fallen" in t]
    assert sorted(alerts) == ["spc-0123", "spc-0188"] and sorted(f.photos) == ["spc-0123", "spc-0188"]
    assert ("m1", {"t": "alert", "id": "a1", "action": "handled"}) in f.requests
    assert ("spc-0123", "Sarah is on it.") in f.texts
    assert ("spc-0188", "Sarah is on it.") not in f.texts
