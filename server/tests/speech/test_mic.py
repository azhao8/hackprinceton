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
    def __init__(self, on_utterance, sample_rate, on_event=None):
        self.on_utterance = on_utterance
        self.on_event = on_event
        self.sample_rate = sample_rate
        self.audio = bytearray()
        self.closed = False

    def send_audio(self, pcm: bytes) -> None:
        self.audio += pcm

    async def close(self) -> None:
        self.closed = True

    async def hear(self, text: str, partials=()) -> None:
        """One turn, like Cartesia: start, running transcripts, end, then the utterance."""
        if self.on_event is not None:
            self.on_event("start", "")
            for p in partials:
                self.on_event("update", p)
            self.on_event("end", text)
        await self.on_utterance(Utterance(source="senior", text=text, meta={"channel": "mic", "confidence": None}))


class FakeSTT:
    def __init__(self):
        self.sessions: list[FakeSession] = []

    async def session(self, on_utterance=None, *, sample_rate=16000, on_event=None):
        s = FakeSession(on_utterance, sample_rate, on_event)
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
    hub = MicHub(None, asyncio.Queue(), "Miguel", clock=clock)
    assert hub.filter("what time is it") is None                       # not addressed, not listening
    assert hub.filter("Hey Miguel, come here.") == ("come here.", {"addressed": True, "via": "wake"})
    assert hub.filter("talking to someone else") is None              # no follow-on window any more
    assert hub.filter("Come here, Miguel.")[0] == "Come here."
    assert hub.filter("Can you, Miguel, get my keys?")[0] == "Can you get my keys?"
    assert hub.filter("okay MIGUEL stop")[0] == "stop"
    assert hub.filter("Miguelito is my cat") is None                   # whole words only
    assert hub.ignored == 3


def test_wake_word_alone_opens_listening_for_one_request_instead_of_asking_claude():
    clock = Clock()
    hub = MicHub(None, asyncio.Queue(), "Miguel", tap_window_s=8.0, clock=clock)
    assert hub.filter("Miguel?") is None                               # nothing for Claude...
    assert hub.listening() and hub.listen_reason() == "wake"           # ...but the ring and ping
    clock.t += 3
    assert hub.filter("bring me my glasses") == ("bring me my glasses", {"addressed": True, "via": "wake"})
    assert not hub.listening()                                         # one utterance only
    assert hub.filter("and my book") is None
    assert hub.filter("Hey Miguel, um") is None and hub.listen_reason() == "wake"
    clock.t += 8.1
    assert not hub.listening()


def test_question_window_only_after_a_question_and_only_for_a_few_seconds():
    clock = Clock()
    hub = MicHub(None, asyncio.Queue(), "Miguel", answer_window_s=4.0, clock=clock)
    hub._control('{"type": "voice", "busy": true, "text": "Hello there!"}')
    hub._control('{"type": "voice", "busy": false}')
    assert not hub.listening()                                         # not a question: no window
    assert hub.filter("how are you") is None

    hub._control('{"type": "voice", "busy": true, "text": "Would you like some water?"}')
    clock.t += 30                                                      # a long line: never while he talks
    assert not hub.listening() and hub.filter("yes") is None
    hub._control('{"type": "voice", "busy": false}')
    assert hub.listening() and hub.listen_reason() == "question"
    clock.t += 3.9
    assert hub.filter("yes") == ("yes", {"addressed": False, "via": "question"})   # short answers count
    assert hub.filter("yes please") is None                            # the window is spent

    hub._control('{"type": "voice", "busy": true, "text": "Are you sure?"}')
    hub._control('{"type": "voice", "busy": false}')
    clock.t += 4.1
    assert hub.filter("yes") is None                                   # too late
    hub._control("not json")                                           # ignored


def test_queued_line_is_the_fallback_when_the_page_sends_no_text():
    clock = Clock()
    hub = MicHub(None, asyncio.Queue(), "Miguel", clock=clock)
    hub.note_miguel_spoke("Shall I go to the kitchen?")
    hub._control('{"type": "voice", "busy": true}')
    hub._control('{"type": "voice", "busy": false}')
    assert hub.listen_reason() == "question"


def test_a_turn_that_starts_inside_the_window_counts_even_if_it_ends_after():
    clock = Clock()
    hub = MicHub(None, asyncio.Queue(), "Miguel", answer_window_s=4.0, clock=clock)
    hub._control('{"type": "voice", "busy": true, "text": "Do you want tea or coffee?"}')
    hub._control('{"type": "voice", "busy": false}')
    clock.t += 3.5
    hub.on_stt_event("start", "")
    clock.t += 3.0                                                     # window closed at +4
    hub.on_stt_event("update", "Coffee with a")
    hub.on_stt_event("end", "Coffee with a little milk")
    asyncio.run(hub.on_heard(Utterance("senior", "Coffee with a little milk", meta={"channel": "mic"})))
    u = hub.inbox.get_nowait()
    assert u.text == "Coffee with a little milk" and u.meta["via"] == "question"


def test_waiting_for_a_reply_listens_until_the_agent_stops_waiting():
    clock = Clock()
    hub = MicHub(None, asyncio.Queue(), "Miguel", clock=clock)
    hub._control('{"type": "voice", "busy": true, "text": "Is now a good time for a call?"}')
    hub.set_awaiting(True)
    assert not hub.listening()                                         # still talking
    hub._control('{"type": "voice", "busy": false}')
    clock.t += 30                                                      # long past the answer window
    assert hub.listen_reason() == "reply"
    assert hub.filter("no") == ("no", {"addressed": False, "via": "reply"})
    assert hub.filter("not now") is not None                           # still waiting: still listening
    hub.set_awaiting(False)
    assert not hub.listening() and hub.filter("not now") is None


def test_filler_and_short_fragments():
    clock = Clock()
    open_hub = MicHub(None, asyncio.Queue(), None, clock=clock)        # no wake word: everything is heard
    assert open_hub.filter("uh") is None and open_hub.filter("Hmm, um.") is None
    assert open_hub.filter("okay") is None and open_hub.filter("yeah right") is None
    assert open_hub.filter("come here please") == ("come here please", {"addressed": False, "via": "open"})
    assert open_hub.filter("stop") == ("stop", {"addressed": False, "via": "open"})   # stop is never too short

    hub = MicHub(None, asyncio.Queue(), "Miguel", clock=clock)
    hub.set_awaiting(True)
    assert hub.filter("um") is None                                    # filler, even while waiting
    assert hub.filter("okay") == ("okay", {"addressed": False, "via": "reply"})
    assert hub.filter("Miguel, yes") == ("yes", {"addressed": True, "via": "wake"})


def test_stop_needs_no_wake_word_unless_switched_off():
    hub = MicHub(None, asyncio.Queue(), "Miguel", clock=Clock())
    assert hub.filter("Stop!") == ("Stop!", {"addressed": False, "via": "stop"})
    assert hub.filter("wait wait") == ("wait wait", {"addressed": False, "via": "stop"})
    assert hub.filter("you have to stop doing that every single day") is None
    strict = MicHub(None, asyncio.Queue(), "Miguel", stop_without_wake=False, clock=Clock())
    assert strict.filter("stop") is None


def test_tap_to_talk_listens_for_one_utterance():
    clock = Clock()
    hub = MicHub(None, asyncio.Queue(), "Miguel", tap_window_s=8.0, clock=clock)
    hub._control('{"type": "listen"}')
    assert hub.listen_reason() == "tap"
    clock.t += 5
    assert hub.filter("what's the weather") == ("what's the weather", {"addressed": True, "via": "tap"})
    assert hub.filter("and tomorrow") is None
    hub._control('{"type": "listen"}')
    clock.t += 8.1
    assert not hub.listening() and hub.filter("hello there you") is None
    hub._control('{"type": "listen"}')
    hub._control('{"type": "voice", "busy": true, "text": "Hi!"}')    # he starts talking: the tap is over
    hub._control('{"type": "voice", "busy": false}')
    assert not hub.listening()


def test_second_tap_stops_listening_and_drops_the_half_heard_turn():
    clock = Clock()
    inbox: asyncio.Queue = asyncio.Queue()
    hub = MicHub(None, inbox, "Miguel", tap_window_s=8.0, clock=clock)
    hub._control('{"type": "listen"}')                       # tap: listening
    hub.on_stt_event("start", "")
    hub.on_stt_event("update", "what's the")
    hub._control('{"type": "listen_off"}')                   # tapped again mid-sentence
    assert not hub.listening()
    hub.on_stt_event("update", "what's the weather Miguel")   # even the name doesn't bring the ring back
    assert not hub.listening()
    hub.on_stt_event("end", "what's the weather Miguel")
    asyncio.run(hub.on_heard(Utterance(source="senior", text="what's the weather Miguel")))
    assert inbox.empty() and hub.ignored == 1
    # the next turn is judged normally again
    hub.on_stt_event("start", "")
    hub.on_stt_event("end", "Miguel, come here")
    asyncio.run(hub.on_heard(Utterance(source="senior", text="Miguel, come here")))
    assert inbox.get_nowait().text == "come here"


def test_tap_off_after_the_turn_ended_but_before_its_transcript_arrived():
    inbox: asyncio.Queue = asyncio.Queue()
    hub = MicHub(None, inbox, "Miguel", clock=Clock())
    hub._control('{"type": "listen"}')
    hub.on_stt_event("start", "")
    hub.on_stt_event("end", "turn on the lights")             # ended; the final text is on its way
    hub._control('{"type": "listen_off"}')
    asyncio.run(hub.on_heard(Utterance(source="senior", text="turn on the lights")))
    assert inbox.empty()


def test_tap_off_closes_every_window_and_the_wait_for_a_reply():
    clock = Clock()
    hub = MicHub(None, asyncio.Queue(), "Miguel", answer_window_s=4.0, clock=clock)
    hub._control('{"type": "voice", "busy": true, "text": "Want some water?"}')
    hub._control('{"type": "voice", "busy": false}')
    hub.set_awaiting(True)
    assert hub.listening()
    hub._control('{"type": "listen_off"}')
    assert not hub.listening() and hub.filter("yes please") is None
    assert hub.filter("Miguel, yes please") == ("yes please", {"addressed": True, "via": "wake"})


def test_tap_off_is_pushed_to_the_phone():
    stt = FakeSTT()
    handler = make_mic_handler(stt, asyncio.Queue(), wake_word="Miguel", env={})

    async def scenario(http, server):
        async with http.ws_connect(server.make_url("/mic?rate=16000")) as ws:
            await ws.send_str('{"type": "listen"}')
            on = await ws.receive_json(timeout=2)
            await ws.send_str('{"type": "listen_off"}')
            off = await ws.receive_json(timeout=2)
            return on, off

    on, off = serve(handler, scenario)
    assert on == {"type": "listen", "on": True, "why": "tap"}
    assert off == {"type": "listen", "on": False, "why": None}


def test_wake_word_in_the_partial_transcript_turns_listening_on_while_they_talk():
    hub = MicHub(None, asyncio.Queue(), "Miguel", clock=Clock())
    hub.on_stt_event("start", "")
    hub.on_stt_event("update", "Hey Mig")
    assert not hub.listening()
    hub.on_stt_event("update", "Hey Miguel can you")
    assert hub.listening() and hub.listen_reason() == "wake"
    assert hub.status()["listening"] is True and hub.in_window() is True   # family.py's old name
    hub.on_stt_event("end", "Hey Miguel can you come here")
    assert not hub.listening()


def test_listening_and_say_lines_are_pushed_to_the_phone():
    clock = Clock()
    stt, inbox = FakeSTT(), asyncio.Queue()
    handler = make_mic_handler(stt, inbox, "Miguel", clock=clock)
    voices = []
    handler.hub.on_voice = lambda busy, text, sid: voices.append((busy, text, sid))

    async def scenario(http, server):
        async with http.ws_connect(server.make_url("/mic")) as ws:
            await until(lambda: stt.sessions)
            s = stt.sessions[0]
            await ws.send_str('{"type": "listen"}')                            # tap-to-talk
            first = await asyncio.wait_for(ws.receive_json(), 2)
            await s.hear("what time is it")
            u = await asyncio.wait_for(inbox.get(), 2)
            second = await asyncio.wait_for(ws.receive_json(), 2)
            handler.hub.push_say(7, "It's three o'clock.")
            say = await asyncio.wait_for(ws.receive_json(), 2)
            await ws.send_json({"type": "voice", "busy": True, "text": "It's three o'clock.", "id": 7})
            await until(lambda: voices)
            await ws.send_json({"type": "voice", "busy": False})
            await until(lambda: len(voices) == 2)
            await s.hear("Hey Miguel, thanks", partials=["Hey", "Hey Miguel"])
            third = await asyncio.wait_for(ws.receive_json(), 2)
        return first, u, second, say, third

    first, u, second, say, third = serve(handler, scenario)
    assert first == {"type": "listen", "on": True, "why": "tap"}
    assert u.text == "what time is it" and u.meta["via"] == "tap"
    assert second == {"type": "listen", "on": False, "why": None}
    assert say == {"type": "say", "id": 7, "text": "It's three o'clock."}
    assert voices == [(True, "It's three o'clock.", 7), (False, "It's three o'clock.", None)]
    assert third == {"type": "listen", "on": True, "why": "wake"}


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
            await ws.send_str('{"type": "voice", "busy": true, "text": "Which glasses?"}')
            await ws.send_str('{"type": "voice", "busy": false}')
            await until(lambda: not handler.hub.voice_busy and handler.hub.listening())
            await s.hear("the reading ones")                   # answering Miguel, no wake word
            second = await asyncio.wait_for(inbox.get(), 2)
        return first, second

    first, second = serve(handler, scenario)
    assert first.text == "bring my glasses" and first.meta["raw"] == "Miguel, bring my glasses"
    assert first.meta["addressed"] is True and first.meta["channel"] == "mic"
    assert second.text == "the reading ones" and second.meta["via"] == "question"
    assert handler.hub.ignored == 1


def test_env_sets_the_windows():
    h = make_mic_handler(None, asyncio.Queue(), "Miguel",
                         env={"MIGUEL_ANSWER_WINDOW_S": "6", "MIGUEL_TAP_LISTEN_S": "oops"})
    assert h.hub.answer_window_s == 6.0 and h.hub.tap_window_s == 8.0


def test_push_to_talk():
    clock = Clock()
    inbox: asyncio.Queue = asyncio.Queue()
    hub = MicHub(None, inbox, "Miguel", clock=clock)
    assert hub.push_to_talk("   ") is None
    u = hub.push_to_talk("  bring  the   water ")
    assert u.text == "bring the water" and u.source == "operator" and u.meta == {"channel": "ptt"}
    assert inbox.get_nowait() is u
    assert hub.filter("and a cup") is None                # typed lines don't open the mic
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


def test_no_ring_while_his_line_is_on_its_way():
    """Sat night: the ring lit ~2 s before his voice, while Cartesia made the audio."""
    clock = Clock()
    hub = MicHub(None, asyncio.Queue(), "Miguel", clock=clock)
    hub._ws = object()                      # a phone is connected
    hub.note_line("Sarah would like to check in. Is now a good time?")
    hub.set_awaiting(True)                  # Claude waits for the answer at once
    assert not hub.listening()              # ...but the line hasn't played yet
    hub._voice(True, "Sarah would like to check in. Is now a good time?")
    assert not hub.listening()              # talking: mic muted
    hub._voice(False)
    assert hub.listening() and hub.listen_reason() == "reply"
    hub.note_line("Okay?")
    assert not hub.listening()
    clock.t += 9                            # the phone never played it: listen anyway after 8 s
    assert hub.listen_reason() == "reply"


def test_a_line_queued_as_asking_opens_the_answer_window_without_a_question_mark():
    """#120: the introduction ends with 'Just say "Miguel" first.', but it asks what to show."""
    clock = Clock()
    hub = MicHub(None, asyncio.Queue(), "Miguel", answer_window_s=4.0, clock=clock)
    intro_end = 'Just say "Miguel" first.'
    hub.note_line(intro_end, asks=True)
    hub._voice(True, intro_end)
    hub._voice(False)
    assert hub.listen_reason() == "question"
    clock.t += 4.1
    assert hub.listen_reason() is None
    hub.note_line("Here is your water.")                 # an ordinary line: no window
    hub._voice(True, "Here is your water.")
    hub._voice(False)
    assert hub.listen_reason() is None
    hub.note_line(intro_end, asks=True)
    hub.note_line("Okay, stopping.")                     # another line came after it: that one decides
    hub._voice(True, intro_end)
    hub._voice(True, "Okay, stopping.")
    hub._voice(False)
    assert hub.listen_reason() is None
