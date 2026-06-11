"""
Internal HTTP API for managing subscriptions.
Execution service calls POST /subscribe when a bot starts
and DELETE /subscribe when a bot stops.
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from app.config import settings
import logging

logger = logging.getLogger(__name__)

app = FastAPI(title="Price Tracker", version="1.0.0")

_tracker = None  # injected at startup


def set_tracker(tracker):
    global _tracker
    _tracker = tracker


class SubscribeRequest(BaseModel):
    exchange: str
    symbol: str


@app.post("/subscribe", status_code=200)
async def subscribe(req: SubscribeRequest):
    try:
        await _tracker.subscribe(req.exchange, req.symbol)
        return {"status": "ok", "exchange": req.exchange, "symbol": req.symbol}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/subscribe", status_code=200)
async def unsubscribe(req: SubscribeRequest):
    await _tracker.unsubscribe(req.exchange, req.symbol)
    return {"status": "ok"}


@app.get("/subscriptions")
async def list_subscriptions():
    return {
        exchange: list(symbols)
        for exchange, symbols in _tracker._subscriptions.items()
    }


@app.get("/health")
async def health():
    return {"status": "healthy"}
