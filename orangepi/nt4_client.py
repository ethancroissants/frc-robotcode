"""Minimal pure-Python NetworkTables 4 client.

Why this exists
---------------
WPILib publishes `pyntcore` wheels only for `linux_roborio` (the rio's
ARMv7 CPU) and desktop sim platforms. The Orange Pi / Raspberry Pi 5 is
`linux_aarch64`, with no PyPI wheel. The Pi also lives on the FRC robot
network with no internet, so we can't build pyntcore from source there.

This module implements just enough of the NT4 protocol for the Pi's
needs (publish a few topics, subscribe to a few topics) using the
pure-Python `websockets` + `msgpack` libraries (both have aarch64 wheels).

Protocol (NetworkTables 4):
  - WebSocket on TCP port 5810, path `/nt/<client-name>`
  - Subprotocol: ``networktables.first.wpi.edu`` (4.0)
  - Text frames carry JSON arrays of {method, params} control messages:
      publish / unpublish / subscribe / unsubscribe / setproperties
      announce / unannounce / properties
  - Binary frames carry MessagePack-encoded ``[topic_id, ts_us, type_id, value]``

Type IDs we handle: 0=bool, 1=double, 2=int, 4=string.

Public surface
--------------
The API is intentionally small and shaped like the slice of pyntcore that
NTBridge in server.py uses:

    client = nt4_client.Client("OrangePi-Sight")
    client.set_server_team(1279)         # OR client.set_server("10.12.79.2")
    client.start()                       # spawns background asyncio thread

    pub = client.publish("/Sight/x", "double")
    pub.set(3.14)

    sub = client.subscribe("/Sight/y", "double", default=0.0)
    sub.get()

    client.is_connected()
    client.stop()

Reconnection is automatic (1 s backoff). All public methods are thread-safe.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import msgpack
import websockets

log = logging.getLogger("nt4")

NT4_PORT = 5810
NT4_SUBPROTOCOL = "networktables.first.wpi.edu"

# NT4 type-id ↔ type-string mapping. We keep it minimal; arrays / raw / json
# can be added later if a topic needs them.
_TYPE_STR_TO_ID = {"boolean": 0, "double": 1, "int": 2, "string": 4}
_TYPE_ID_TO_STR = {v: k for k, v in _TYPE_STR_TO_ID.items()}


# ----- public-facing handles -----

@dataclass
class _PubState:
    path: str
    type_str: str
    pubuid: int
    topic_id: int | None = None  # filled when server sends `announce`
    last_value: Any = None


@dataclass
class _SubState:
    path: str
    type_str: str
    subuid: int
    default: Any
    value: Any = None
    last_update_us: int = 0


class Publisher:
    """Handle returned by Client.publish(). Call .set() to push a value."""

    def __init__(self, client: "Client", state: _PubState) -> None:
        self._client = client
        self._state = state

    def set(self, value: Any) -> None:
        self._client._send_value(self._state, value)


class Subscriber:
    """Handle returned by Client.subscribe(). Call .get() for the latest value."""

    def __init__(self, client: "Client", state: _SubState) -> None:
        self._client = client
        self._state = state

    def get(self) -> Any:
        v = self._state.value
        return v if v is not None else self._state.default


# ----- main client -----

class Client:
    """NT4 client running an asyncio loop in a background thread."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._server_host: str | None = None
        self._server_port: int = NT4_PORT

        # State protected by _lock — read/written from both the main thread
        # (publish/subscribe/set/get) and the asyncio thread (announce
        # routing, value updates).
        self._lock = threading.Lock()
        self._next_pubuid = 1
        self._next_subuid = 1
        self._pubs: dict[int, _PubState] = {}            # pubuid -> state
        self._subs: dict[int, _SubState] = {}            # subuid -> state
        self._topic_id_to_subs: dict[int, list[_SubState]] = {}
        self._topic_id_to_pub: dict[int, _PubState] = {}
        # Outgoing send queue for binary value frames. The asyncio loop
        # drains it; main-thread setters append to it. Stored as raw msgpack
        # bytes ready to send (avoids re-serializing on the loop side).
        self._out_q: list[bytes] = []
        # Pending control messages queued before the loop has spun up. Drained
        # into _loop_control_q on first iteration of the loop.
        self._control_pending: list[str] = []

        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._stop = False
        self._connected = False

    # ---- configuration ----

    def set_server(self, host: str, port: int = NT4_PORT) -> None:
        self._server_host = host
        self._server_port = port

    def set_server_team(self, team: int) -> None:
        # FRC convention: rio is at 10.TE.AM.2 on the robot network.
        self._server_host = f"10.{team // 100}.{team % 100}.2"
        self._server_port = NT4_PORT

    def is_connected(self) -> bool:
        return self._connected

    def server_host(self) -> str | None:
        """Address the client is currently dialing (or None if unset). Used
        by the dashboard to show *which* rio address it's trying so an
        operator can tell "wrong host" from "rio offline" at a glance."""
        return self._server_host

    # ---- lifecycle ----

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop = False
        self._thread = threading.Thread(
            target=self._run_loop, name="nt4-client", daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop = True
        if self._loop and self._loop.is_running():
            # _loop_wake lives on the asyncio thread, so cross-thread wake
            # has to go through call_soon_threadsafe.
            self._loop.call_soon_threadsafe(self._loop_wake.set)
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

    # ---- topic API ----

    def publish(self, path: str, type_str: str) -> Publisher:
        if type_str not in _TYPE_STR_TO_ID:
            raise ValueError(f"Unsupported NT4 type: {type_str}")
        with self._lock:
            pubuid = self._next_pubuid
            self._next_pubuid += 1
            state = _PubState(path=path, type_str=type_str, pubuid=pubuid)
            self._pubs[pubuid] = state
        # Schedule the control message; idempotent if not yet connected
        # (we'll re-send on reconnect).
        self._post_control({
            "method": "publish",
            "params": {
                "name": path, "pubuid": pubuid,
                "type": type_str, "properties": {},
            },
        })
        return Publisher(self, state)

    def subscribe(self, path: str, type_str: str, default: Any) -> Subscriber:
        if type_str not in _TYPE_STR_TO_ID:
            raise ValueError(f"Unsupported NT4 type: {type_str}")
        with self._lock:
            subuid = self._next_subuid
            self._next_subuid += 1
            state = _SubState(
                path=path, type_str=type_str, subuid=subuid, default=default,
            )
            self._subs[subuid] = state
        self._post_control({
            "method": "subscribe",
            "params": {
                "topics": [path], "subuid": subuid,
                "options": {"all": False, "topicsonly": False, "prefix": False},
            },
        })
        return Subscriber(self, state)

    # ---- internals: outgoing ----

    def _post_control(self, msg: dict) -> None:
        # Control messages are wrapped in a JSON array. We append to the
        # outgoing-text queue via a thread-safe call into the loop.
        text = json.dumps([msg])
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._control_q_append, text)
        else:
            # Loop not running yet — buffer for later send. Stash in the
            # control_pending list (read once the loop comes up).
            self._control_pending.append(text)  # type: ignore[attr-defined]

    def _control_q_append(self, text: str) -> None:
        # Called inside the loop. Just append to the loop-side buffer.
        self._loop_control_q.append(text)
        self._loop_wake.set()

    def _send_value(self, pub: _PubState, value: Any) -> None:
        """Encode a value frame and queue it for the loop to send.

        Called from the main thread (e.g. NTBridge.publish_target). Drops the
        send if we don't yet have a topic_id (publish hasn't been ack'd by
        the server) — last_value is still recorded so we can flush on
        announce.
        """
        with self._lock:
            pub.last_value = value
            if pub.topic_id is None:
                return
            type_id = _TYPE_STR_TO_ID[pub.type_str]
            ts_us = int(time.time() * 1_000_000)
            frame = msgpack.packb([pub.topic_id, ts_us, type_id, value])
            self._out_q.append(frame)
        # Wake the asyncio writer task so it drains _out_q immediately
        # instead of waiting up to 100ms on its idle tick. Cross-thread
        # access to an asyncio.Event has to go via call_soon_threadsafe.
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop_wake.set)

    # ---- internals: asyncio loop ----

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        # On Python 3.9 (Bullseye Pis), `asyncio.Event()` looks up the
        # thread's *current* event loop via `get_event_loop()`. `new_event_loop()`
        # creates a loop but does NOT install it on the thread, so the
        # lookup raises "There is no current event loop in thread …" and
        # this whole thread dies before opening a websocket — which is
        # exactly the failure mode operators saw as "rio never connects"
        # despite a working ping. Bind the loop here.
        asyncio.set_event_loop(self._loop)
        # Loop-side state, only touched on the asyncio thread.
        self._loop_control_q: list[str] = list(self._control_pending)
        self._control_pending.clear()
        self._loop_wake = asyncio.Event()
        try:
            self._loop.run_until_complete(self._loop_main())
        except Exception as e:
            log.exception("NT4 loop crashed: %s", e)
        finally:
            self._loop.close()

    async def _loop_main(self) -> None:
        # Reconnect forever. Each iteration is one connection lifetime.
        backoff = 1.0
        while not self._stop:
            host = self._server_host
            if not host:
                await asyncio.sleep(0.5)
                continue
            url = f"ws://{host}:{self._server_port}/nt/{self.name}"
            try:
                log.info("NT4: connecting %s", url)
                async with websockets.connect(
                    url,
                    subprotocols=[NT4_SUBPROTOCOL],
                    open_timeout=5,
                    ping_interval=10,
                    ping_timeout=10,
                    max_size=2**20,
                ) as ws:
                    self._connected = True
                    backoff = 1.0
                    log.info("NT4: connected")
                    await self._on_connected(ws)
                    await self._serve(ws)
            except Exception as e:
                log.warning("NT4: connection lost (%s) — retrying in %.1fs", e, backoff)
            finally:
                self._connected = False
            await asyncio.sleep(backoff)
            backoff = min(backoff * 1.5, 5.0)

    async def _on_connected(self, ws) -> None:
        """On every (re)connect, replay our publish/subscribe state so the
        server has a current picture of what we own + listen to."""
        with self._lock:
            pubs = list(self._pubs.values())
            subs = list(self._subs.values())
            for p in pubs:
                p.topic_id = None  # cleared until server re-announces
            self._topic_id_to_pub.clear()
            self._topic_id_to_subs.clear()

        msgs: list[dict] = []
        for p in pubs:
            msgs.append({
                "method": "publish",
                "params": {
                    "name": p.path, "pubuid": p.pubuid,
                    "type": p.type_str, "properties": {},
                },
            })
        for s in subs:
            msgs.append({
                "method": "subscribe",
                "params": {
                    "topics": [s.path], "subuid": s.subuid,
                    "options": {"all": False, "topicsonly": False, "prefix": False},
                },
            })
        if msgs:
            await ws.send(json.dumps(msgs))

    async def _serve(self, ws) -> None:
        # Multiplex: read incoming, send pending control text, send pending
        # binary frames. We pump everything from one task by polling the
        # wake event; for higher throughput we'd split into reader/writer.
        async def reader():
            async for raw in ws:
                if isinstance(raw, str):
                    self._handle_control(raw)
                else:
                    self._handle_binary(raw)

        async def writer():
            while not self._stop:
                # Drain any pending text control messages.
                while self._loop_control_q:
                    text = self._loop_control_q.pop(0)
                    await ws.send(text)
                # Drain any pending binary value frames.
                with self._lock:
                    out, self._out_q = self._out_q, []
                for frame in out:
                    await ws.send(frame)
                # Wait for new work or a small idle tick.
                self._loop_wake.clear()
                try:
                    await asyncio.wait_for(self._loop_wake.wait(), timeout=0.1)
                except asyncio.TimeoutError:
                    pass

        # Run both tasks; the connection ends when reader returns (server
        # closed) or writer raises.
        reader_task = asyncio.create_task(reader())
        writer_task = asyncio.create_task(writer())
        done, pending = await asyncio.wait(
            [reader_task, writer_task], return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()

    def _handle_control(self, text: str) -> None:
        try:
            msgs = json.loads(text)
        except Exception:
            log.warning("NT4: bad text frame")
            return
        for msg in msgs:
            method = msg.get("method")
            params = msg.get("params") or {}
            if method == "announce":
                self._on_announce(params)
            elif method == "unannounce":
                self._on_unannounce(params)
            # `properties` updates ignored — we don't track properties.

    def _on_announce(self, params: dict) -> None:
        path = params.get("name")
        topic_id = params.get("id")
        pubuid = params.get("pubuid")
        if topic_id is None or path is None:
            return
        with self._lock:
            # Match this announce to a publisher we own (pubuid will match)
            # OR to subscribers watching this path.
            if pubuid is not None and pubuid in self._pubs:
                p = self._pubs[pubuid]
                p.topic_id = topic_id
                self._topic_id_to_pub[topic_id] = p
                # Flush a value if we have one buffered from before the
                # announce arrived.
                pending = p.last_value
                pending_type = p.type_str
            else:
                pending = None
                pending_type = None
            for s in self._subs.values():
                if s.path == path:
                    self._topic_id_to_subs.setdefault(topic_id, []).append(s)
        if pending is not None and pending_type is not None and pubuid is not None:
            type_id = _TYPE_STR_TO_ID[pending_type]
            ts_us = int(time.time() * 1_000_000)
            frame = msgpack.packb([topic_id, ts_us, type_id, pending])
            with self._lock:
                self._out_q.append(frame)
            self._loop_wake.set()

    def _on_unannounce(self, params: dict) -> None:
        topic_id = params.get("id")
        if topic_id is None:
            return
        with self._lock:
            self._topic_id_to_pub.pop(topic_id, None)
            self._topic_id_to_subs.pop(topic_id, None)
            for p in self._pubs.values():
                if p.topic_id == topic_id:
                    p.topic_id = None

    def _handle_binary(self, data: bytes) -> None:
        # NT4 packs values as concatenated msgpack arrays (one per update,
        # multiple per frame). Unpacker iterates each top-level array.
        unpacker = msgpack.Unpacker(use_list=True, raw=False)
        unpacker.feed(data)
        for arr in unpacker:
            self._dispatch_value(arr)

    def _dispatch_value(self, arr: Any) -> None:
        if not isinstance(arr, list) or len(arr) < 4:
            return
        topic_id, ts_us, type_id, value = arr[0], arr[1], arr[2], arr[3]
        with self._lock:
            subs = self._topic_id_to_subs.get(topic_id, [])
            for s in subs:
                if s.last_update_us <= ts_us:
                    s.value = value
                    s.last_update_us = ts_us


# Convenience alias for callers that prefer `nt4_client.connect(...)`.
def connect(name: str, host: str | None = None, team: int | None = None) -> Client:
    c = Client(name)
    if host is not None:
        c.set_server(host)
    elif team is not None:
        c.set_server_team(team)
    c.start()
    return c
