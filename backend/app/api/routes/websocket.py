from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from app.services.websocket import manager, price_stream_manager
from app.core.redis import get_position_state
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Main WebSocket endpoint for real-time updates"""
    await manager.connect(websocket)

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
                if bot_id:
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
