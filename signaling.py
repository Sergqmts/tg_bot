import json
import logging
from datetime import datetime
from starlette.websockets import WebSocket, WebSocketState

logger = logging.getLogger(__name__)

connections: dict[int, list[WebSocket]] = {}
call_rooms: dict[int, set[int]] = {}


async def send_to_user(user_id: int, data: dict):
    socks = connections.get(user_id)
    if not socks:
        return
    dead = []
    for ws in socks:
        try:
            await ws.send_json(data)
        except:
            dead.append(ws)
    for ws in dead:
        socks.remove(ws)


async def handle_call_ws(websocket: WebSocket):
    await websocket.accept()
    user_id = None

    try:
        while True:
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            msg_type = msg.get('type')

            if msg_type == 'auth':
                user_id = msg.get('user_id')
                if user_id:
                    connections.setdefault(user_id, []).append(websocket)
                    await websocket.send_json({'type': 'auth:ok', 'user_id': user_id})
                continue

            if msg_type == 'ping':
                await websocket.send_json({'type': 'pong'})
                continue

            if user_id is None:
                await websocket.send_json({'type': 'error', 'message': 'not authenticated'})
                continue

            data = msg.get('data', {})

            if msg_type == 'call:initiate':
                callee_id = data.get('callee_id')
                call_id = data.get('call_id')
                call_type = data.get('call_type', 'audio')

                if callee_id not in connections or not connections[callee_id]:
                    await websocket.send_json({'type': 'error', 'message': 'user offline'})
                    continue

                call_rooms.setdefault(call_id, set()).add(user_id)

                await send_to_user(callee_id, {
                    'type': 'call:incoming',
                    'data': {
                        'call_id': call_id,
                        'caller_id': user_id,
                        'caller_username': data.get('caller_username'),
                        'call_type': call_type,
                    }
                })
                await websocket.send_json({'type': 'call:initiated', 'data': {'call_id': call_id}})

            elif msg_type == 'call:answer':
                call_id = data.get('call_id')
                call_rooms.setdefault(call_id, set()).add(user_id)
                for uid in call_rooms.get(call_id, set()):
                    if uid != user_id:
                        await send_to_user(uid, {
                            'type': 'call:answered',
                            'data': {'call_id': call_id, 'user_id': user_id}
                        })

            elif msg_type == 'call:rejoin':
                call_id = data.get('call_id')
                if call_id:
                    call_rooms.setdefault(call_id, set()).add(user_id)
                    await websocket.send_json({'type': 'call:rejoined', 'data': {'call_id': call_id}})

            elif msg_type == 'call:decline':
                call_id = data.get('call_id')
                for uid in call_rooms.get(call_id, set()):
                    if uid != user_id:
                        await send_to_user(uid, {
                            'type': 'call:declined',
                            'data': {'call_id': call_id, 'user_id': user_id}
                        })
                if call_id in call_rooms:
                    del call_rooms[call_id]

            elif msg_type == 'call:end':
                call_id = data.get('call_id')
                for uid in call_rooms.get(call_id, set()):
                    if uid != user_id:
                        await send_to_user(uid, {
                            'type': 'call:ended',
                            'data': {'call_id': call_id, 'user_id': user_id}
                        })
                if call_id in call_rooms:
                    del call_rooms[call_id]

            elif msg_type == 'sdp:offer':
                call_id = data.get('call_id')
                sdp = data.get('sdp')
                for uid in call_rooms.get(call_id, set()):
                    if uid != user_id:
                        await send_to_user(uid, {
                            'type': 'sdp:offer',
                            'data': {'call_id': call_id, 'sdp': sdp}
                        })

            elif msg_type == 'sdp:answer':
                call_id = data.get('call_id')
                sdp = data.get('sdp')
                for uid in call_rooms.get(call_id, set()):
                    if uid != user_id:
                        await send_to_user(uid, {
                            'type': 'sdp:answer',
                            'data': {'call_id': call_id, 'sdp': sdp}
                        })

            elif msg_type == 'ice:candidate':
                call_id = data.get('call_id')
                candidate = data.get('candidate')
                for uid in call_rooms.get(call_id, set()):
                    if uid != user_id:
                        await send_to_user(uid, {
                            'type': 'ice:candidate',
                            'data': {'call_id': call_id, 'candidate': candidate}
                        })

            elif msg_type == 'call:toggle_mute':
                call_id = data.get('call_id')
                muted = data.get('muted')
                for uid in call_rooms.get(call_id, set()):
                    if uid != user_id:
                        await send_to_user(uid, {
                            'type': 'call:peer_mute',
                            'data': {'call_id': call_id, 'user_id': user_id, 'muted': muted}
                        })

            elif msg_type == 'call:toggle_camera':
                call_id = data.get('call_id')
                camera_on = data.get('camera_on')
                for uid in call_rooms.get(call_id, set()):
                    if uid != user_id:
                        await send_to_user(uid, {
                            'type': 'call:peer_camera',
                            'data': {'call_id': call_id, 'user_id': user_id, 'camera_on': camera_on}
                        })

    except Exception as e:
        logger.error(f"WebSocket error for user {user_id}: {e}")
    finally:
        if user_id:
            socks = connections.get(user_id)
            if socks and websocket in socks:
                socks.remove(websocket)
                if not socks:
                    del connections[user_id]
            for call_id in list(call_rooms.keys()):
                if user_id in call_rooms[call_id]:
                    call_rooms[call_id].discard(user_id)
                    for uid in call_rooms[call_id]:
                        await send_to_user(uid, {
                            'type': 'call:ended',
                            'data': {'call_id': call_id, 'user_id': user_id}
                        })
                    if not call_rooms[call_id]:
                        del call_rooms[call_id]
