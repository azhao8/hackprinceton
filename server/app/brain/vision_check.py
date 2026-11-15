"""Claude vision checks on camera frames (owner: Grant).

- `matches_description(jpeg, description)`: does this person crop match "the man in the red
  shirt"? Returns (match, short reason). The search skills use it to pick the right person.
- `describe_scene(jpeg)`: one or two sentences about the frame, for the agent's planner. It also
  takes a short clip: a list of 1 to 3 JPEGs, oldest first (what is happening, motion, a fall).

Both take JPEG bytes and an optional client (default: the shared lazy `AsyncAnthropic`). They
run at low effort with refusal fallbacks (see prompt.py). Network and API failures raise the
SDK's typed exceptions (`anthropic.APIError` and subclasses); a refusal or an unreadable answer
is not an exception: `matches_description` returns (False, reason), `describe_scene` raises
`VisionCheckError`.

With MIGUEL_LLM=local the shared client is the Ollama one (local_llm.py, #81): the images go to the
local model as base64, the same way.
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

from app.brain.prompt import MATCH_PROMPT, MODEL, QUESTION_PROMPT, SCENE_PROMPT, create_message, get_client

log = logging.getLogger(__name__)

MATCH_SCHEMA = {
    "type": "object",
    "properties": {
        "match": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["match", "reason"],
    "additionalProperties": False,
}


class VisionCheckError(Exception):
    """Claude declined or gave no usable answer about the image."""


def image_block(jpeg: bytes) -> dict[str, Any]:
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.standard_b64encode(jpeg).decode("ascii")},
    }


MAX_FRAMES = 3


def as_frames(jpegs: bytes | list[bytes] | tuple[bytes, ...]) -> list[bytes]:
    """One JPEG or a clip -> a list of 1 to MAX_FRAMES frames (the newest ones)."""
    frames = [jpegs] if isinstance(jpegs, (bytes, bytearray)) else [f for f in jpegs if f]
    if not frames:
        raise ValueError("no camera frame")
    return [bytes(f) for f in frames[-MAX_FRAMES:]]


def clip_note(n: int) -> str:
    return (f"These are {n} camera frames from a short clip, about 0.3 s apart, oldest first. "
            "Use them together: they show what is happening and what moves.\n" if n > 1 else "")


def _text_of(resp: Any) -> str:
    return "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", None) == "text").strip()


async def matches_description(
    jpeg: bytes,
    description: str,
    client: Any = None,
    *,
    model: str = MODEL,
    fallbacks: bool | None = None,
) -> tuple[bool, str]:
    """Ask Claude whether the person in `jpeg` (a crop) matches `description`."""
    resp = await create_message(
        client or get_client(),
        fallbacks=fallbacks,
        model=model,
        max_tokens=2048,
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": MATCH_SCHEMA}},
        messages=[{
            "role": "user",
            "content": [image_block(jpeg), {"type": "text", "text": MATCH_PROMPT.format(description=description)}],
        }],
    )
    if resp.stop_reason == "refusal":
        log.warning("vision match declined: %s", getattr(resp, "stop_details", None))
        return False, "the vision check was declined"
    if resp.stop_reason == "max_tokens":
        return False, "the vision check ran out of tokens"
    try:
        data = json.loads(_text_of(resp))
        return bool(data["match"]), str(data.get("reason", ""))
    except (ValueError, KeyError, TypeError):
        log.warning("vision match: unreadable answer %r", _text_of(resp)[:200])
        return False, "could not read the vision check's answer"


async def describe_scene(
    jpeg: bytes | list[bytes],
    client: Any = None,
    *,
    model: str = MODEL,
    fallbacks: bool | None = None,
    question: str | None = None,
) -> str:
    """One or two sentences describing the frame, for the agent; or the answer to `question` about it.
    `jpeg` is one frame or a short clip (a list of 1 to 3 frames, oldest first)."""
    frames = as_frames(jpeg)
    prompt = QUESTION_PROMPT.format(question=question.strip()) if question and question.strip() else SCENE_PROMPT
    prompt = clip_note(len(frames)) + prompt
    resp = await create_message(
        client or get_client(),
        fallbacks=fallbacks,
        model=model,
        max_tokens=2048,
        output_config={"effort": "low"},
        messages=[{"role": "user", "content": [*(image_block(f) for f in frames), {"type": "text", "text": prompt}]}],
    )
    if resp.stop_reason == "refusal":
        raise VisionCheckError("the scene description was declined")
    text = _text_of(resp)
    if not text:
        raise VisionCheckError(f"no description (stop_reason={resp.stop_reason})")
    return text
