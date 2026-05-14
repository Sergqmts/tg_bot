import os
from starlette.applications import Starlette
from starlette.routing import WebSocketRoute, Mount
from starlette.middleware.wsgi import WSGIMiddleware

from app import app as flask_app
from signaling import handle_call_ws

app = Starlette(routes=[
    Mount('/', WSGIMiddleware(flask_app)),
    WebSocketRoute('/ws/call', handle_call_ws),
])
