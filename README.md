# signaling-server

Standalone WebRTC signaling server. It relays SDP offers/answers and ICE
candidates between peers in a room — it never touches media. Rooms form a
full mesh: a newcomer gets the list of peers already present and is
responsible for offering to each of them, so both sides of every pair agree
on their role without extra negotiation.

## Run

```
pip install -r requirements.txt
python server.py --host 0.0.0.0 --port 8765
```

## Endpoints

- `GET /ws` — websocket endpoint clients connect to for signaling.
- `GET /rooms` — JSON snapshot of current rooms and their members.
- `GET /` — plain-text health check.

## Protocol

JSON text frames over `/ws`.

Client -> server:

```
{"type": "join", "room": "<name>", "peer_id": "<optional>", "name": "<display name>"}
{"type": "signal", "to": "<peer_id>", "data": <sdp/ice payload>}
{"type": "bye"}
```

Server -> client:

```
{"type": "joined", "peer_id": "<id>", "room": "<name>", "peers": [{"id", "name"}, ...]}
{"type": "peer-joined", "peer": {"id", "name"}}
{"type": "peer-left", "peer_id": "<id>"}
{"type": "signal", "from": "<peer_id>", "data": <sdp/ice payload>}
```

This is the same protocol used by `LivePortrait/webrtc_conference`'s client,
so this server can be pointed to by that app's `--signaling` flag, or reused
by any other WebRTC app that speaks the same join/signal/bye messages.
