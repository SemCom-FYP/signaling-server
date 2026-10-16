# coding: utf-8
"""
Standalone room signaling server for WebRTC conferencing, over a websocket.

The server is a pure relay: it never sees media, only SDP and ICE. Rooms form
a full mesh, and the join order settles who offers — a newcomer receives the
list of peers already present and offers to each of them, so both sides of
every pair agree on their role without any glare handling.

Wire protocol (JSON text frames over /ws):
  client -> server
    {"type": "join", "room": "<name>", "peer_id": "<optional>", "name": "<display name>"}
    {"type": "signal", "to": "<peer_id>", "data": <sdp/ice payload>}
    {"type": "bye"}
  server -> client
    {"type": "joined", "peer_id": "<id>", "room": "<name>", "peers": [{"id", "name"}, ...]}
    {"type": "peer-joined", "peer": {"id", "name"}}
    {"type": "peer-left", "peer_id": "<id>"}
    {"type": "signal", "from": "<peer_id>", "data": <sdp/ice payload>}

Run directly with `python server.py`, or import `build_app()` / `SignalingServer`
to embed it in another aiohttp application.
"""

import argparse
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Optional

from aiohttp import WSMsgType, web

log = logging.getLogger("signaling")

DEFAULT_PORT = 8765


@dataclass
class _Member:
    peer_id: str
    name: str
    ws: web.WebSocketResponse


@dataclass
class _Room:
    name: str
    members: dict[str, _Member] = field(default_factory=dict)


class SignalingServer:
    def __init__(self):
        self.rooms: dict[str, _Room] = {}

    def build_app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/ws", self.ws_handler)
        app.router.add_get("/rooms", self.rooms_handler)
        app.router.add_get("/", self.index_handler)
        return app

    async def index_handler(self, request):
        return web.Response(
            text="WebRTC conference signaling server. Connect to /ws\n")

    async def rooms_handler(self, request):
        return web.json_response({
            name: [{"id": m.peer_id, "name": m.name} for m in room.members.values()]
            for name, room in self.rooms.items()
        })

    async def ws_handler(self, request):
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=4 * 1024 * 1024)
        await ws.prepare(request)

        member: Optional[_Member] = None
        room: Optional[_Room] = None

        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    data = json.loads(msg.data)
                except json.JSONDecodeError:
                    continue
                kind = data.get("type")

                if kind == "join" and member is None:
                    room_name = str(data.get("room", "lobby"))
                    peer_id = str(data.get("peer_id") or uuid.uuid4().hex[:8])
                    name = str(data.get("name") or peer_id)
                    room = self.rooms.setdefault(room_name, _Room(room_name))

                    existing = [{"id": m.peer_id, "name": m.name}
                                for m in room.members.values()]
                    member = _Member(peer_id, name, ws)
                    room.members[peer_id] = member
                    log.info("%s (%s) joined %s (%d present)",
                             name, peer_id, room_name, len(room.members))

                    await _send(ws, {"type": "joined", "peer_id": peer_id,
                                     "room": room_name, "peers": existing})
                    await self._broadcast(room, {
                        "type": "peer-joined",
                        "peer": {"id": peer_id, "name": name},
                    }, exclude=peer_id)

                elif kind == "signal" and member is not None and room is not None:
                    target = room.members.get(str(data.get("to")))
                    if target is not None:
                        await _send(target.ws, {"type": "signal",
                                                "from": member.peer_id,
                                                "data": data.get("data")})

                elif kind == "bye":
                    break
        finally:
            if member is not None and room is not None:
                room.members.pop(member.peer_id, None)
                log.info("%s left %s (%d remain)", member.name, room.name,
                         len(room.members))
                await self._broadcast(room, {"type": "peer-left",
                                             "peer_id": member.peer_id})
                if not room.members:
                    self.rooms.pop(room.name, None)
        return ws

    async def _broadcast(self, room: _Room, payload: dict, exclude: str = ""):
        for m in list(room.members.values()):
            if m.peer_id != exclude:
                await _send(m.ws, payload)


async def _send(ws, payload: dict):
    try:
        await ws.send_str(json.dumps(payload))
    except Exception:
        pass


def build_app() -> web.Application:
    return SignalingServer().build_app()


def main():
    parser = argparse.ArgumentParser(
        description="Standalone signaling server for WebRTC conferencing")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(name)-12s %(message)s", datefmt="%H:%M:%S")

    server = SignalingServer()
    print(f"Signaling on ws://{args.host}:{args.port}/ws")
    web.run_app(server.build_app(), host=args.host, port=args.port,
                access_log=None)


if __name__ == "__main__":
    main()
