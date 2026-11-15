"""Cartesia STT client against a fake /stt/turns/websocket on 127.0.0.1 (no network, no real key).

The fake speaks the message shapes in docs.cartesia.ai/api-reference/stt/turns/websocket.md:
binary audio and {"type": "close"} in; connected / turn.* / error events (JSON) out.
"""

from __future__ import annotations

import asyncio
import json
import logging

from aiohttp import WSMsgType, web
from aiohttp.test_utils import TestServer

from app.brain.types import Utterance
from app.speech.stt import CartesiaSTT

KEY = "sk_car_SECRET_stt_key_456"
RATE = 16000
FRAME = b"\x01\x02" * 640          # 40 ms at 16 kHz, s16le
CHUNK = RATE * 2 // 10             # the client sends 100 ms chunks


class FakeCartesia:
    """Records every connection; replies with turn events according to `mode`."""

    def __init__(self, mode: str = "turn_after_audio", transcript: str = "Hey Miguel, come here.") -> None:
        self.mode = mode
        self.transcript = transcript
        self.conns: list[dict] = []

    async def handle(self, request: web.Request) -> web.StreamResponse:
        if self.mode == "reject":
            return web.Response(status=401, text=f"bad key {request.headers.get('X-API-Key')}")
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        conn = {
            "query": list(request.query.items()),
            "headers": dict(request.headers),
            "chunks": [],
            "texts": [],
        }
        self.conns.append(conn)
        n = len(self.conns)
        rid = f"req-{n}"
        await ws.send_json({"type": "connected", "request_id": rid})
        turn_sent = False
        async for msg in ws:
            if msg.type == WSMsgType.BINARY:
                conn["chunks"].append(msg.data)
                if self.mode == "drop_first" and n == 1:
                    await ws.close(code=1011, message=b"internal error")
                    break
                if self.mode == "error_event" and len(conn["chunks"]) == 1:
                    await ws.send_json({"type": "error", "request_id": rid, "status_code": 400,
                                        "title": "Bad request", "message": f"oops {KEY}"})
                if self.mode in ("turn_after_audio", "drop_first") and not turn_sent and len(conn["chunks"]) >= 2:
                    turn_sent = True
                    words = self.transcript.split()
                    await ws.send_json({"type": "turn.start", "request_id": rid})
                    await ws.send_json({"type": "turn.update", "request_id": rid, "transcript": words[0]})
                    await ws.send_json({"type": "turn.eager_end", "request_id": rid, "transcript": words[0]})
                    await ws.send_json({"type": "turn.resume", "request_id": rid})
                    await ws.send_json({"type": "turn.end", "request_id": rid, "transcript": self.transcript})
                    await ws.send_json({"type": "turn.end", "request_id": rid, "transcript": "   "})
            elif msg.type == WSMsgType.TEXT:
                conn["texts"].append(json.loads(msg.data))
                if json.loads(msg.data).get("type") == "close":
                    if self.mode == "turn_on_close":
                        await ws.send_json({"type": "turn.end", "request_id": rid, "transcript": "last words"})
                    await ws.close()
                    break
        return ws


def run(fake: FakeCartesia, scenario, **kw):
    async def main():
        app = web.Application()
        app.router.add_get("/stt/turns/websocket", fake.handle)
        server = TestServer(app, host="127.0.0.1")
        await server.start_server()
        base = str(server.make_url("")).rstrip("/").replace("http://", "ws://")
        kw.setdefault("backoff_s", (0.05,))
        stt = CartesiaSTT(KEY, base_url=base, **kw)
        try:
            return await asyncio.wait_for(scenario(stt), 10)
        finally:
            await server.close()

    return asyncio.run(main())


async def feed(session, frames: int, delay: float = 0.005) -> None:
    for _ in range(frames):
        session.send_audio(FRAME)
        await asyncio.sleep(delay)


def test_audio_forwarded_in_100ms_chunks_and_turn_end_becomes_utterance():
    fake = FakeCartesia()

    async def scenario(stt):
        s = await stt.session()
        await feed(s, 10)                      # 400 ms
        u = await asyncio.wait_for(s.utterances.get(), 3)
        await s.close()
        return s, u

    s, u = run(fake, scenario)
    assert isinstance(u, Utterance)
    assert u.source == "senior"
    assert u.text == "Hey Miguel, come here."
    assert u.meta["channel"] == "mic"
    assert "confidence" in u.meta and u.meta["confidence"] is None   # Cartesia sends no score
    assert u.meta["request_id"] == "req-1"
    assert s.utterances.empty()               # updates, eager ends and empty turns are not utterances
    conn = fake.conns[0]
    q = dict(conn["query"])
    assert q["model"] == "ink-2"
    assert q["encoding"] == "pcm_s16le"
    assert q["sample_rate"] == "16000"
    assert q["cartesia_version"] == "2026-08-14"
    assert ("keyterm", "Miguel") in conn["query"]
    assert conn["headers"]["X-API-Key"] == KEY
    assert KEY not in json.dumps(conn["query"])            # the key is never in the URL
    assert all(len(c) == CHUNK for c in conn["chunks"])    # whole 100 ms chunks (400 ms -> 4)
    assert b"".join(conn["chunks"]) == FRAME * 10
    assert conn["texts"] == [{"type": "close"}]


def test_close_flushes_and_delivers_the_last_turn_to_the_callback():
    fake = FakeCartesia(mode="turn_on_close")
    got: list[Utterance] = []

    async def on_utt(u):
        got.append(u)

    async def scenario(stt):
        s = await stt.session(on_utt)
        await feed(s, 4)                      # 160 ms: one whole chunk + 60 ms left over
        await s.close()

    run(fake, scenario)
    assert [u.text for u in got] == ["last words"]
    conn = fake.conns[0]
    assert len(b"".join(conn["chunks"])) == len(FRAME) * 4   # the partial chunk was flushed too
    assert conn["texts"] == [{"type": "close"}]


def test_keyterms_and_turn_params_go_in_the_query():
    fake = FakeCartesia()

    async def scenario(stt):
        s = await stt.session(sample_rate=24000)
        s.send_audio(b"\x00\x00" * 2400 * 2)
        await asyncio.sleep(0.3)
        await s.close()

    run(fake, scenario, keyterms=["Miguel", "Miguel", " ", "pill box"],
        turn_params={"turn_end_timeout_ms": 2000})
    q = fake.conns[0]["query"]
    assert [v for k, v in q if k == "keyterm"] == ["Miguel", "pill box"]
    assert ("sample_rate", "24000") in q
    assert ("turn_end_timeout_ms", "2000") in q


def test_reconnects_after_the_socket_drops():
    fake = FakeCartesia(mode="drop_first")

    async def scenario(stt):
        s = await stt.session()
        for _ in range(60):
            s.send_audio(FRAME)
            await asyncio.sleep(0.01)
            if not s.utterances.empty():
                break
        u = await asyncio.wait_for(s.utterances.get(), 3)
        await s.close()
        return s, u

    s, u = run(fake, scenario)
    assert len(fake.conns) >= 2
    assert s.connects >= 2
    assert u.text == "Hey Miguel, come here."
    assert u.meta["request_id"] == f"req-{len(fake.conns)}"


def test_key_never_logged_on_rejection_or_error_event(caplog):
    caplog.set_level(logging.DEBUG)
    reject = FakeCartesia(mode="reject")

    async def scenario(stt):
        s = await stt.session()
        await feed(s, 6, 0.02)
        await asyncio.sleep(0.2)
        assert s.connects == 0
        await s.close(drain_timeout_s=0.5)
        return stt

    stt = run(reject, scenario)
    assert "connection failed" in caplog.text
    assert KEY not in repr(stt)

    errors = FakeCartesia(mode="error_event")

    async def scenario2(stt):
        s = await stt.session()
        await feed(s, 6)
        await asyncio.sleep(0.2)
        await s.close()

    run(errors, scenario2)
    assert "Cartesia error 400" in caplog.text
    assert KEY not in caplog.text


def test_buffer_drops_oldest_audio_when_cartesia_lags():
    fake = FakeCartesia(mode="reject")      # never connects, so audio piles up

    async def scenario(stt):
        s = await stt.session()
        for _ in range(100):                   # 4 s of audio, buffer holds 0.5 s
            s.send_audio(FRAME)
        await asyncio.sleep(0)
        n = len(s._buf)
        dropped = s.dropped_chunks
        await s.close(drain_timeout_s=0.2)
        return n, dropped

    n, dropped = run(fake, scenario, max_buffer_ms=500, backoff_s=(5.0,))
    assert n <= 5
    assert dropped >= 30


def test_from_env():
    assert CartesiaSTT.from_env({}) is None
    assert CartesiaSTT.from_env({"CARTESIA_API_KEY": "  "}) is None
    stt = CartesiaSTT.from_env({"CARTESIA_API_KEY": KEY})
    assert stt is not None and stt.model == "ink-2" and stt.keyterms == ("Miguel",)
    assert KEY not in repr(stt)
    stt = CartesiaSTT.from_env({"CARTESIA_API_KEY": KEY, "CARTESIA_STT_MODEL": "ink-preview",
                                "CARTESIA_STT_KEYTERMS": "Miguel, Grandma Rosa,"})
    assert stt.model == "ink-preview" and stt.keyterms == ("Miguel", "Grandma Rosa")
    assert CartesiaSTT.from_env({"CARTESIA_API_KEY": KEY, "CARTESIA_STT_KEYTERMS": ""}).keyterms == ()


def test_stt_close_closes_open_sessions():
    fake = FakeCartesia()

    async def scenario(stt):
        a = await stt.session()
        b = await stt.session()
        await feed(a, 4)
        await stt.close()
        return a, b

    a, b = run(fake, scenario)
    assert a._closed.is_set() and b._closed.is_set()
    assert fake.conns[0]["texts"] == [{"type": "close"}]
