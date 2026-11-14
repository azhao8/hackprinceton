"""The phone's /mic WebSocket: relay to STT, wake word, conversation window, no-STT path (no network)."""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
from pathlib import Path

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from app.brain.types import Utterance
from app.speech.mic import MicHub, make_mic_handler, push_to_talk
from app.speech.stt import CartesiaSTT

from .test_stt import FakeCartesia

FRAME = b"\x01\x02" * 640


class FakeSession:
    def __init__(self, on_utterance, sample_rate):
        self.on_utterance = on_utterance
        self.sample_rate = sample_rate
        self.audio = bytearray()
        self.closed = False

    def send_audio(self, pcm: bytes) -> None:
        self.audio += pcm

    async def close(self) -> None:
        self.closed = True

    async def hear(self, text: str) -> None:
        await self.on_utterance(Utterance(source="senior", text=text, meta={"channel": "mic", "confidence": None}))


class FakeSTT:
    def __init__(self):
        self.sessions: list[FakeSession] = []

    async def session(self, on_utterance=None, *, sample_rate=16000):
        s = FakeSession(on_utterance, sample_rate)
        self.sessions.append(s)
        return s


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def serve(handler, scenario):
    async def main():
        app = web.Application()
        app.router.add_get("/mic", handler)
        server = TestServer(app, host="127.0.0.1")
        await server.start_server()
        try:
            async with aiohttp.ClientSession() as http:
                return await asyncio.wait_for(scenario(http, server), 10)
        finally:
            await server.close()

    return asyncio.run(main())


async def until(cond, timeout=2.0):
    for _ in range(int(timeout / 0.01)):
        if cond():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("timed out")


def test_frames_relayed_to_stt_and_utterances_reach_the_inbox():
    stt, inbox = FakeSTT(), asyncio.Queue()
    handler = make_mic_handler(stt, inbox)

    async def scenario(http, server):
        async with http.ws_connect(server.make_url("/mic?rate=16000")) as ws:
            await ws.send_bytes(FRAME)
            await ws.send_bytes(b"\x05")            # an odd byte is carried to the next frame
            await ws.send_bytes(b"\x06" + FRAME[:-2])
            await until(lambda: stt.sessions and len(stt.sessions[0].audio) >= 2 * len(FRAME) - 2)
            await stt.sessions[0].hear("what time is it")
            u = await asyncio.wait_for(inbox.get(), 2)
        await until(lambda: stt.sessions[0].closed)
        return u

    u = serve(handler, scenario)
    s = stt.sessions[0]
    assert s.sample_rate == 16000
    assert bytes(s.audio) == FRAME + b"\x05\x06" + FRAME[:-2]
    assert u.source == "senior" and u.text == "what time is it"
    assert u.meta["channel"] == "mic" and u.meta["raw"] == "what time is it"
    assert handler.hub.frames == 3


def test_bad_rate_is_refused():
    handler = make_mic_handler(FakeSTT(), asyncio.Queue())

    async def scenario(http, server):
        async with http.ws_connect(server.make_url("/mic?rate=banana")) as ws:
            msg = await ws.receive()
            return msg.type, ws.close_code

    kind, code = serve(handler, scenario)
    assert kind in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED)
    assert code == 1003


def test_new_phone_connection_replaces_the_old_one():
    stt = FakeSTT()
    handler = make_mic_handler(stt, asyncio.Queue())

    async def scenario(http, server):
        old = await http.ws_connect(server.make_url("/mic"))
        await until(lambda: len(stt.sessions) == 1)
        async with http.ws_connect(server.make_url("/mic")) as new:
            msg = await asyncio.wait_for(old.receive(), 2)
            await until(lambda: stt.sessions[0].closed)
            assert not stt.sessions[1].closed
            await new.close()
        await old.close()
        return msg.type

    assert serve(handler, scenario) in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED)


def test_no_stt_accepts_and_drops_audio_with_one_log_line(caplog):
    caplog.set_level(logging.INFO, logger="app.speech.mic")
    inbox: asyncio.Queue = asyncio.Queue()
    handler = make_mic_handler(None, inbox, wake_word="Miguel")

    async def scenario(http, server):
        for _ in range(2):
            async with http.ws_connect(server.make_url("/mic")) as ws:
                for _ in range(5):
                    await ws.send_bytes(FRAME)
                await ws.send_str('{"type": "voice", "busy": true}')
                await until(lambda: handler.hub.frames >= 5)
            await asyncio.sleep(0.05)

    serve(handler, scenario)
    assert handler.hub.frames == 10
    assert inbox.empty()
    assert caplog.text.count("speech to text is off") == 1
    assert handler.hub.status()["stt"] is False


def test_wake_word_filter_and_stripping():
    clock = Clock()
    hub = MicHub(None, asyncio.Queue(), "Miguel", window_s=8.0, clock=clock)
    assert hub.filter("what time is it") is None                       # not addressed, no window
    assert hub.filter("Hey Miguel, come here.") == ("come here.", {"addressed": True, "in_window": False})
    clock.t += 100
    assert hub.filter("Come here, Miguel.")[0] == "Come here."
    clock.t += 100
    assert hub.filter("Can you, Miguel, get my keys?")[0] == "Can you get my keys?"
    clock.t += 100
    assert hub.filter("okay MIGUEL stop")[0] == "stop"
    clock.t += 100
    assert hub.filter("Miguelito is my cat") is None                   # whole words only
    text, meta = hub.filter("Miguel?")
    assert text == "Miguel" and meta["wake_only"] is True


def test_conversation_window_after_being_addressed_or_speaking():
    clock = Clock()
    hub = MicHub(None, asyncio.Queue(), "Miguel", window_s=8.0, clock=clock)
    hub.filter("Miguel, hello")                     # addressed at t=100: window to 108
    clock.t = 105
    assert hub.filter("how are you") == ("how are you", {"addressed": False, "in_window": True})  # extends to 113
    clock.t = 112.9
    assert hub.filter("fine thanks") is not None    # extends to 120.9
    clock.t = 121.0
    assert hub.filter("talking to someone else") is None

    clock.t = 200
    hub.note_miguel_spoke()                         # Miguel asked a question
    clock.t = 207
    assert hub.filter("yes please") is not None
    clock.t = 300
    hub._control('{"type": "voice", "busy": true}')
    clock.t = 330                                   # long line: still in the window while he talks
    assert hub.in_window()
    hub._control('{"type": "voice", "busy": false}')
    clock.t = 337
    assert hub.filter("sure") is not None
    clock.t = 400
    assert hub.filter("sure") is None
    hub._control("not json")                         # ignored


def test_wake_word_through_the_websocket_and_voice_messages():
    clock = Clock()
    stt, inbox = FakeSTT(), asyncio.Queue()
    handler = make_mic_handler(stt, inbox, "Miguel", clock=clock)

    async def scenario(http, server):
        async with http.ws_connect(server.make_url("/mic")) as ws:
            await until(lambda: stt.sessions)
            s = stt.sessions[0]
            await s.hear("it's cold today")                    # ignored
            await s.hear("Miguel, bring my glasses")
            first = await asyncio.wait_for(inbox.get(), 2)
            clock.t += 30
            await ws.send_str('{"type": "voice", "busy": true}')
            await ws.send_str('{"type": "voice", "busy": false}')
            await until(lambda: not handler.hub.voice_busy and handler.hub.in_window())
            await s.hear("thank you")                          # answering Miguel, no wake word
            second = await asyncio.wait_for(inbox.get(), 2)
        return first, second

    first, second = serve(handler, scenario)
    assert first.text == "bring my glasses" and first.meta["raw"] == "Miguel, bring my glasses"
    assert first.meta["addressed"] is True and first.meta["channel"] == "mic"
    assert second.text == "thank you" and second.meta["in_window"] is True
    assert handler.hub.ignored == 1


def test_push_to_talk():
    clock = Clock()
    inbox: asyncio.Queue = asyncio.Queue()
    hub = MicHub(None, inbox, "Miguel", clock=clock)
    assert hub.push_to_talk("   ") is None
    u = hub.push_to_talk("  bring  the   water ")
    assert u.text == "bring the water" and u.source == "operator" and u.meta == {"channel": "ptt"}
    assert inbox.get_nowait() is u
    assert hub.filter("and a cup") is not None            # push-to-talk opens the window too
    u2 = push_to_talk(inbox, "hello", source="senior")
    assert inbox.get_nowait() is u2 and u2.source == "senior"


def test_end_to_end_with_real_stt_client_and_fake_cartesia():
    fake = FakeCartesia()
    inbox: asyncio.Queue = asyncio.Queue()

    async def main():
        capp = web.Application()
        capp.router.add_get("/stt/turns/websocket", fake.handle)
        cserver = TestServer(capp, host="127.0.0.1")
        await cserver.start_server()
        stt = CartesiaSTT("sk_test", base_url=str(cserver.make_url("")).rstrip("/").replace("http", "ws"))
        handler = make_mic_handler(stt, inbox, wake_word="Miguel")

        async def scenario(http, server):
            async with http.ws_connect(server.make_url("/mic?rate=16000")) as ws:
                for _ in range(10):
                    await ws.send_bytes(FRAME)
                    await asyncio.sleep(0.005)
                return await asyncio.wait_for(inbox.get(), 3)

        try:
            app = web.Application()
            app.router.add_get("/mic", handler)
            server = TestServer(app, host="127.0.0.1")
            await server.start_server()
            try:
                async with aiohttp.ClientSession() as http:
                    return await asyncio.wait_for(scenario(http, server), 10)
            finally:
                await server.close()
        finally:
            await cserver.close()

    u = asyncio.run(main())
    assert u.text == "come here." and u.source == "senior" and u.meta["channel"] == "mic"
    assert b"".join(fake.conns[0]["chunks"]).startswith(FRAME * 5)


# ---------- the phone side (firmware/balance/phone/mic.js), with Node if it's installed ----------

MIC_JS = Path(__file__).resolve().parents[3] / "firmware" / "balance" / "phone" / "mic.js"
NODE = shutil.which("node")

DOWNSAMPLER_TEST = r"""
const m = require(process.argv[1]);
const assert = require('assert');
// 1 s of a 440 Hz tone at 48 kHz in 128-sample blocks (an AudioWorklet's block size) -> 16000 samples
const ds = m.makeDownsampler(48000, 16000), blocks = [];
const tone = i => 0.5 * Math.sin(2 * Math.PI * 440 * i / 48000);
for (let s = 0; s < 48000; s += 128) {
  const b = new Float32Array(128); for (let i = 0; i < 128; i++) b[i] = tone(s + i); blocks.push(ds(b));
}
const out = Int16Array.from(blocks.flatMap(b => Array.from(b)));
assert.strictEqual(out.length, 16000);
for (const k of [100, 5000, 12345]) {           // each output = average of 3 inputs around it
  const want = (tone(3 * k) + tone(3 * k + 1) + tone(3 * k + 2)) / 3 * 0x7fff;
  assert.ok(Math.abs(out[k] - want) < 2, `sample ${k}: ${out[k]} vs ${want}`);
}
// 44.1 kHz in odd block sizes -> 16000 per second too (fractional ratio, state kept across calls)
const d2 = m.makeDownsampler(44100, 16000); let n = 0;
for (let s = 0; s < 44100;) { const len = Math.min(1000 + (s % 7), 44100 - s); n += d2(new Float32Array(len)).length; s += len; }
assert.ok(Math.abs(n - 16000) <= 1, 'got ' + n);
// clipping and s16le bytes
assert.strictEqual(m.floatTo16(2), 32767); assert.strictEqual(m.floatTo16(-2), -32768); assert.strictEqual(m.floatTo16(0), 0);
assert.strictEqual(m.FRAME_SAMPLES, 640);
const bytes = Buffer.from(new Int16Array([1, -2]).buffer);
assert.deepStrictEqual([...bytes], [1, 0, 0xfe, 0xff]);   // little-endian, like pcm_s16le
assert.throws(() => m.makeDownsampler(8000, 16000));
console.log('ok');
"""


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_mic_js_parses():
    r = subprocess.run([NODE, "--check", str(MIC_JS)], check=False, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_mic_js_downsampler_48k_float_to_16k_s16le():
    r = subprocess.run([NODE, "-e", DOWNSAMPLER_TEST, str(MIC_JS)], check=False, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0 and r.stdout.strip() == "ok", r.stderr or r.stdout
