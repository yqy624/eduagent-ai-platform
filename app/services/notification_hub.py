"""In-memory WebSocket fan-out for user notifications."""
from collections import defaultdict
from typing import DefaultDict, Set

from fastapi import WebSocket


class NotificationHub:
    def __init__(self) -> None:
        self._connections: DefaultDict[str, Set[WebSocket]] = defaultdict(set)

    async def connect(self, username: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[username].add(websocket)

    def disconnect(self, username: str, websocket: WebSocket) -> None:
        connections = self._connections.get(username)
        if not connections:
            return
        connections.discard(websocket)
        if not connections:
            self._connections.pop(username, None)

    async def publish(self, username: str, payload: dict) -> None:
        stale = []
        for websocket in tuple(self._connections.get(username, ())):
            try:
                await websocket.send_json(payload)
            except Exception:
                stale.append(websocket)
        for websocket in stale:
            self.disconnect(username, websocket)


notification_hub = NotificationHub()
