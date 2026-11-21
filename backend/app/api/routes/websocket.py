from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.services.websocket import manager, price_stream_manager
from app.core.redis import get_position_state
from app.core.database import AsyncSessionLocal
from app.api.deps import user_from_access_token
import asyncio
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

AUTH_TIMEOUT_SEC = 10
UNAUTHORIZED = 4401  # клиент: обновить access-токен и переподключиться


async def authenticate(websocket: WebSocket):
    """Первое сообщение — {"type": "auth", "token": <access>}. Токен не в URL: URL пишется в логи nginx."""
    try:
        first = await asyncio.wait_for(websocket.receive_json(), timeout=AUTH_TIMEOUT_SEC)
    except Exception:
        return None
    if not isinstance(first, dict) or first.get("type") != "auth":
        return None
    async with AsyncSessionLocal() as db:
        return await user_from_access_token(first.get("token"), db)


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Main WebSocket endpoint for real-time updates"""
    await websocket.accept()
    user = await authenticate(websocket)
    if not user:
        await websocket.close(code=UNAUTHORIZED)
        return
    await manager.connect(websocket, user.id)
    await manager.send_personal_message({"type": "authenticated"}, websocket)

    try:
        while True:
            # Receive messages from client
            data = await websocket.receive_json()

            message_type = data.get("type")

            if message_type == "subscribe_price":
                # Subscribe to price updates for a symbol
                symbol = data.get("symbol")
                if symbol:
                    manager.subscribe_to_price(symbol, websocket)
                    await price_stream_manager.start_price_stream(symbol)

                    await manager.send_personal_message(
                        {"type": "subscribed", "symbol": symbol},
                        websocket
                    )

            elif message_type == "subscribe_bot":
                # Subscribe to bot updates
                bot_id = data.get("bot_id")
                if bot_id and await manager.owner_of(bot_id) == user.id:
                    # Get current state from Redis
                    state = await get_position_state(str(bot_id))

                    if state:
                        await manager.send_personal_message(
                            {"type": "bot_state", "bot_id": bot_id, "state": state},
                            websocket
                        )

            elif message_type == "ping":
                # Heartbeat
                await manager.send_personal_message(
                    {"type": "pong"},
                    websocket
                )

    except WebSocketDisconnect:
        manager.disconnect(websocket)
        logger.info("Client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(websocket)
