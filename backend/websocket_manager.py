"""
AI Disaster Response Coordinator — WebSocket Manager
Manages real-time WebSocket connections for live updates.
"""

import json
import logging
from typing import Dict, List, Set
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WebSocketManager:
    """Manages WebSocket connections with room-based broadcasting."""

    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.rooms: Dict[str, Set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, room: str = "global"):
        await websocket.accept()
        self.active_connections.append(websocket)
        if room not in self.rooms:
            self.rooms[room] = set()
        self.rooms[room].add(websocket)
        logger.info(f"WebSocket connected (room={room}). Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        for room_conns in self.rooms.values():
            room_conns.discard(websocket)
        logger.info(f"WebSocket disconnected. Total: {len(self.active_connections)}")

    async def broadcast(self, event_type: str, data: dict, room: str = "global"):
        """Broadcast an event to all connections in a room."""
        message = json.dumps({"type": event_type, "data": data}, default=str)
        targets = self.rooms.get(room, set()) | self.rooms.get("global", set())
        dead = []
        for conn in targets:
            try:
                await conn.send_text(message)
            except Exception:
                dead.append(conn)
        for conn in dead:
            self.disconnect(conn)

    async def broadcast_all(self, event_type: str, data: dict):
        """Broadcast to ALL connected clients regardless of room."""
        message = json.dumps({"type": event_type, "data": data}, default=str)
        dead = []
        for conn in self.active_connections:
            try:
                await conn.send_text(message)
            except Exception:
                dead.append(conn)
        for conn in dead:
            self.disconnect(conn)


# Singleton
ws_manager = WebSocketManager()
