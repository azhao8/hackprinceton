"""The per-turn timing log (app/speech/timing.py)."""

import logging

from app.speech.timing import TurnTimer


class Clock:
    def __init__(self):
        self.t = 10.0

    def __call__(self):
        return self.t


def test_a_turn_without_playback_is_logged_when_the_next_starts(caplog):
    caplog.set_level(logging.INFO, logger="app.speech.timing")
    clock = Clock()
    timer = TurnTimer(clock=clock)
    timer.start({"heard": 10.0, "llm_start": 10.0, "first_text": 10.8, "say": 10.8}, "Hi there!")
    timer.said(4, "Hi there!")
    clock.t = 10.9
    timer.mark("tts_request", "Another line")   # not the turn's first line: ignored
    timer.mark("tts_request", "Hi  there!")
    timer.playback(5, None)                      # another line playing: ignored
    assert timer.last is None
    timer.start({"heard": 20.0}, "Next.")        # the phone never said it played (Safari's voice)
    assert timer.last == {"text": "Hi there!", "ms": {"Claude asked": 0, "first text": 800, "say": 800,
                                                      "audio asked": 900}}
    assert "turn timing (ms after the message)" in caplog.text
    clock.t = 20.5
    timer.playback(None, "Next.")                # matched by text when the page sends no id
    assert timer.last["ms"] == {"playback": 500}
