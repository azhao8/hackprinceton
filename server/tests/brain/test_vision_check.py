"""vision_check tests with a fake Anthropic client (no network)."""

import asyncio
import base64
from types import SimpleNamespace

import pytest

from app.brain.prompt import MODEL
from app.brain.vision_check import VisionCheckError, describe_scene, matches_description


class FakeClient:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    async def _create(self, **kw):
        self.calls.append(kw)
        return self.responses.pop(0)


def resp(text=None, stop="end_turn"):
    content = [SimpleNamespace(type="text", text=text)] if text is not None else []
    return SimpleNamespace(content=content, stop_reason=stop, stop_details=None)


def test_match_parses_yes_and_sends_the_image():
    client = FakeClient(resp('{"match": true, "reason": "red shirt, gray hair"}'))
    ok, reason = asyncio.run(matches_description(b"\xff\xd8jpeg", "man in a red shirt", client))
    assert (ok, reason) == (True, "red shirt, gray hair")
    kw = client.calls[0]
    image, prompt = kw["messages"][0]["content"]
    assert image["source"] == {"type": "base64", "media_type": "image/jpeg",
                               "data": base64.standard_b64encode(b"\xff\xd8jpeg").decode()}
    assert "man in a red shirt" in prompt["text"]
    assert kw["output_config"]["effort"] == "low"
    assert kw["output_config"]["format"]["type"] == "json_schema"
    assert kw["model"] == MODEL


def test_match_parses_no():
    client = FakeClient(resp('{"match": false, "reason": "blue jacket"}'))
    assert asyncio.run(matches_description(b"j", "red shirt", client)) == (False, "blue jacket")


def test_match_handles_garbage_and_refusal():
    client = FakeClient(resp("not json"), resp(stop="refusal"))
    ok, reason = asyncio.run(matches_description(b"j", "red shirt", client))
    assert not ok and "could not read" in reason
    ok, reason = asyncio.run(matches_description(b"j", "red shirt", client))
    assert not ok and "declined" in reason


def test_describe_scene():
    client = FakeClient(resp("An older woman sits on a sofa. A glass is on the table."), resp(stop="refusal"))
    assert asyncio.run(describe_scene(b"j", client, fallbacks=False)).startswith("An older woman")
    assert "betas" not in client.calls[0]
    with pytest.raises(VisionCheckError):
        asyncio.run(describe_scene(b"j", client))
