"""Run the iMessage bridge: `uv run --env-file .env python -m bridge` (setup: docs/photon.md).

Needs PHOTON_PROJECT_ID and PHOTON_API_KEY (Photon 2.0 Beta, app.beta.photon.codes) and the Miguel
server running (live robot or mock). MIGUEL_FAMILY_WS overrides where it is
(default ws://127.0.0.1:8080/family/ws); FAMILY_TOKEN is sent if set; PHOTON_FAMILY is a fallback list
of phones (`+12155550123:m2,...`).
"""

from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import logging
import os
import sys
import uuid
from typing import Any

import aiohttp
import socketio

from app.family import MEMBERS
from bridge import THREADS_PATH, Bridge, parse_family

log = logging.getLogger("bridge")


class Photon:
    """Photon 2.0's Beta HTTP API (https://api.photon.codes/openapi.json), just the four calls we need."""

    def __init__(self, session: aiohttp.ClientSession, origin: str, project: str, key: str):
        self.session, self.origin, self.project = session, origin.rstrip("/"), project
        self.auth = {"Authorization": f"Bearer {key}"}

    def _url(self, path: str) -> str:
        return f"{self.origin}/v1/projects/{self.project}{path}"

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        async with self.session.post(self._url(path), json=body,
                                     headers={**self.auth, "Idempotency-Key": str(uuid.uuid4())}) as r:
            data = await r.json(content_type=None) if r.content_length != 0 else {}
            if r.status >= 400:
                raise RuntimeError(f"photon {path}: {r.status} {(data or {}).get('code', '')} "
                                   f"{(data or {}).get('detail', '')}".strip())
            return data or {}

    async def send_text(self, thread: dict[str, str], text: str) -> None:
        await self._post("/messages", {"spaceId": thread["space"], "senderId": thread["agent"],
                                       "content": {"type": "text", "format": "plain", "text": text}})

    async def send_photo(self, thread: dict[str, str], jpeg: bytes) -> None:
        aid = await self.upload(jpeg)
        await self._post("/messages", {"spaceId": thread["space"], "senderId": thread["agent"],
                                       "content": {"type": "attachment", "attachmentId": aid}})

    async def upload(self, data: bytes, content_type: str = "image/jpeg") -> str:
        """multipart/related: a JSON part (contentType, sizeBytes, filename), then the bytes."""
        boundary = uuid.uuid4().hex
        meta = json.dumps({"contentType": content_type, "sizeBytes": len(data), "filename": "miguel.jpg"}).encode()
        body = (f"--{boundary}\r\nContent-Type: application/json\r\n\r\n".encode() + meta
                + f"\r\n--{boundary}\r\nContent-Type: {content_type}\r\n\r\n".encode() + data
                + f"\r\n--{boundary}--\r\n".encode())
        headers = {**self.auth, "Idempotency-Key": str(uuid.uuid4()),
                   "Content-Type": f'multipart/related; boundary={boundary}; type="application/json"'}
        async with self.session.post(self._url("/attachments"), data=body, headers=headers) as r:
            out = await r.json(content_type=None)
            if r.status >= 400:
                raise RuntimeError(f"photon upload: {r.status} {(out or {}).get('code', '')}")
            return out["id"]

    async def typing(self, thread: dict[str, str]) -> None:
        await self._post(f"/spaces/{thread['space']}/typing", {"senderId": thread["agent"], "typing": True})


class Family:
    """One `/family/ws` socket per family member (so requests come from them by name). The first one
    also passes the server's broadcasts to the bridge."""

    def __init__(self, session: aiohttp.ClientSession, url: str, token: str | None):
        self.session, self.url, self.token = session, url, token
        self.socks: dict[str, aiohttp.ClientWebSocketResponse] = {}
        self.waiting: dict[str, asyncio.Future] = {}
        self.refs = itertools.count(1)
        self.on_server = None

    def media_url(self, path: str) -> str:
        base = self.url.split("/family/ws")[0].replace("wss://", "https://").replace("ws://", "http://")
        return base + path

    async def fetch(self, path: str) -> bytes | None:
        try:
            async with self.session.get(self.media_url(path), ssl=False) as r:
                return await r.read() if r.status == 200 else None
        except aiohttp.ClientError:
            return None

    async def request(self, member: str, msg: dict[str, Any]) -> dict[str, Any]:
        ws = self.socks.get(member)
        if ws is None or ws.closed:
            return {"t": "error", "message": "Miguel's server isn't reachable right now."}
        ref = f"b{next(self.refs)}"
        fut = asyncio.get_running_loop().create_future()
        self.waiting[ref] = fut
        await ws.send_json({**msg, "ref": ref})
        try:
            return await asyncio.wait_for(fut, 10)
        except asyncio.TimeoutError:
            return {"t": "error", "message": "Miguel didn't answer in time."}
        finally:
            self.waiting.pop(ref, None)

    async def keep(self, member: str, primary: bool) -> None:
        """Connect as this member, read forever, reconnect with backoff."""
        delay = 1.0
        while True:
            try:
                async with self.session.ws_connect(self.url, heartbeat=20, ssl=False) as ws:
                    hello: dict[str, Any] = {"t": "hello", "v": 1, "viewer": member}
                    if self.token:
                        hello["token"] = self.token
                    await ws.send_json(hello)
                    self.socks[member] = ws
                    async for msg in ws:
                        if msg.type != aiohttp.WSMsgType.TEXT:
                            continue
                        m = json.loads(msg.data)
                        if m.get("t") == "welcome":
                            log.info("miguel: connected as %s", MEMBERS.get(member, member))
                            delay = 1.0
                        if m.get("t") in ("ack", "error") and m.get("ref") in self.waiting:
                            self.waiting[m["ref"]].set_result(m)
                            continue
                        if m.get("t") == "error" and m.get("code") == "unauthorized":
                            log.error("miguel: refused the sign-in (FAMILY_TOKEN differs from the server's)")
                        if primary and self.on_server is not None:
                            try:
                                await self.on_server(m)
                            except Exception:  # noqa: BLE001
                                log.exception("bridge: handling %s failed", m.get("t"))
            except (aiohttp.ClientError, OSError) as e:
                log.warning("miguel: can't connect to %s (%s)", self.url, e)
            self.socks.pop(member, None)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 15.0)


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--miguel", default=os.environ.get("MIGUEL_FAMILY_WS", "ws://127.0.0.1:8080/family/ws"))
    args = ap.parse_args()
    project, key = os.environ.get("PHOTON_PROJECT_ID"), os.environ.get("PHOTON_API_KEY")
    if not project or not key:
        sys.exit("Set PHOTON_PROJECT_ID and PHOTON_API_KEY in server/.env (docs/photon.md), then run with "
                 "`uv run --env-file .env python -m bridge`.")
    origin = os.environ.get("PHOTON_API_ORIGIN", "https://api.photon.codes")
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        photon = Photon(session, origin, project, key)
        family = Family(session, args.miguel, os.environ.get("FAMILY_TOKEN") or None)
        bridge = Bridge(send_text=photon.send_text, send_photo=photon.send_photo, typing=photon.typing,
                        request=family.request, fetch=family.fetch,
                        fallback_phones=parse_family(os.environ.get("PHOTON_FAMILY")),
                        tz=os.environ.get("FAMILY_TZ", "America/New_York"), threads_path=THREADS_PATH)
        family.on_server = bridge.on_server
        texts: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)

        sio = socketio.AsyncClient(reconnection=True)

        @sio.event
        async def connect() -> None:
            r = await sio.call("subscribe", {"startSeq": 0}, timeout=10)   # live only: nothing old on restart
            if not (r or {}).get("ok"):
                log.error("photon: subscribe failed: %s", (r or {}).get("error"))
            else:
                log.info("photon: connected")

        @sio.on("delivery")
        async def delivery(event: dict[str, Any], meta: dict[str, Any] | None = None) -> None:
            if isinstance(event, dict) and event.get("type") == "message.received":
                obj = (event.get("data") or {}).get("object")
                if isinstance(obj, dict):
                    texts.put_nowait(obj)

        @sio.on("delivery_error")
        async def delivery_error(error: Any) -> None:
            log.warning("photon: delivery error %s", error)

        @sio.event
        async def connect_error(data: Any) -> None:
            log.warning("photon: can't connect (%s): check PHOTON_PROJECT_ID and PHOTON_API_KEY", data)

        async def worker() -> None:   # one text at a time, in order
            while True:
                obj = await texts.get()
                try:
                    await bridge.on_text(obj)
                except Exception:  # noqa: BLE001
                    log.exception("bridge: a text failed")

        tasks = [asyncio.create_task(family.keep(m, i == 0)) for i, m in enumerate(MEMBERS)]
        tasks.append(asyncio.create_task(worker()))
        await sio.connect(origin, socketio_path=f"/v1/projects/{project}/events/ws", transports=["websocket"],
                          headers=photon.auth, wait_timeout=15)
        await sio.wait()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("engineio").setLevel(logging.WARNING)
    logging.getLogger("socketio").setLevel(logging.WARNING)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
