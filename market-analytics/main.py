"""
Market Analytics FastAPI Application
Provides cryptocurrency market data, sentiment, and analysis
"""

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from datetime import datetime
import os
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Application metadata
VERSION = "1.0.0"
TITLE = "Market Analytics API"
DESCRIPTION = """
Cryptocurrency Market Analytics and Sentiment Analysis API

## Features

* **Fear & Greed Index** - Market sentiment indicator
* **Altseason Index** - Alt vs BTC performance
* **BTC Dominance** - Bitcoin market cap dominance
* **Market Narrative** - Aggregated market analysis (Risk-on/off, etc.)
* **Macro Indicators** - DXY, SPX, US10Y, GOLD, etc.

## Status

🟡 In Development - Basic endpoints available
"""

# Lifespan events
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    # Startup
    logger.info("=" * 60)
    logger.info(f"Starting {TITLE} v{VERSION}")
    logger.info("=" * 60)

    # TODO: Initialize database connection
    # TODO: Initialize Redis cache
    # TODO: Start scheduler for automatic updates

    logger.info("✓ Application started successfully")

    yield

    # Shutdown
    logger.info("Shutting down application...")
    # TODO: Close database connections
    # TODO: Stop scheduler

# Create FastAPI app
app = FastAPI(
    title=TITLE,
    description=DESCRIPTION,
    version=VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # В продакшене указать конкретные домены
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# Health Check Endpoints
# ============================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "market-analytics",
        "version": VERSION,
        "timestamp": datetime.utcnow().isoformat(),
        "components": {
            "api": "operational",
            "database": "not_implemented",  # TODO
            "redis": "not_implemented",  # TODO
            "scheduler": "not_implemented"  # TODO
        }
    }

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": TITLE,
        "version": VERSION,
        "status": "running",
        "documentation": "/docs",
        "endpoints": {
            "health": "/health",
            "fear_greed": "/api/v1/fear-greed",
            "altseason": "/api/v1/altseason",
            "btc_dominance": "/api/v1/btc-dominance",
            "narrative": "/api/v1/narrative",
            "macro": "/api/v1/macro",
            "dashboard": "/api/v1/dashboard"
        }
    }

# ============================================================================
# API v1 Endpoints
# ============================================================================

@app.get("/api/v1/fear-greed")
async def get_fear_greed(latest: bool = True):
    """
    Get Fear & Greed Index

    Source: Alternative.me
    - Returns: Current value (0-100), classification, timestamp
    """
    try:
        from services.fear_greed import fear_greed_service
        data = await fear_greed_service.fetch()
        return data
    except Exception as e:
        logger.error(f"Error fetching fear & greed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/altseason")
async def get_altseason():
    """
    Get Altseason Index

    Calculated based on top altcoins vs BTC performance
    - Returns: Index (0-100), phase (BTC Season/Neutral/Altseason)
    """
    try:
        from services.altseason import altseason_service
        data = await altseason_service.fetch()
        return data
    except Exception as e:
        logger.error(f"Error fetching altseason: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/btc-dominance")
async def get_btc_dominance():
    """
    Get Bitcoin Dominance

    Source: CoinGecko
    - Returns: BTC market cap dominance %, 24h change
    """
    try:
        from services.btc_dominance import btc_dominance_service
        data = await btc_dominance_service.fetch()
        return data
    except Exception as e:
        logger.error(f"Error fetching BTC dominance: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/narrative")
async def get_market_narrative():
    """
    Get Market Narrative

    Aggregates multiple signals to determine overall market state
    - Returns: Narrative (Risk-on/Risk-off/Distribution/Accumulation/Uncertain)
    - Components: Price action, funding, OI, sentiment, BTC.D
    - Confidence: 0.0 - 1.0
    """
    try:
        from services.narrative import narrative_analyzer
        data = await narrative_analyzer.analyze()
        return data
    except Exception as e:
        logger.error(f"Error analyzing narrative: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/macro")
async def get_macro_indicators():
    """
    Get Macro Indicators

    Global financial market indicators
    - DXY (Dollar Index)
    - SPX (S&P 500)
    - NASDAQ
    - US10Y (10-Year Treasury)
    - GOLD
    """
    try:
        from services.macro import macro_service
        data = await macro_service.fetch()
        return data
    except Exception as e:
        logger.error(f"Error fetching macro: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/dashboard")
async def get_dashboard():
    """
    Get Complete Dashboard

    Aggregated view of all market metrics
    """
    try:
        fear_greed = await get_fear_greed()
        altseason = await get_altseason()
        btc_dom = await get_btc_dominance()
        narrative = await get_market_narrative()
        macro = await get_macro_indicators()

        return {
            "fear_greed": fear_greed,
            "altseason": altseason,
            "btc_dominance": btc_dom,
            "narrative": narrative,
            "macro": macro,
            "timestamp": datetime.utcnow().isoformat(),
            "status": "live_data"
        }
    except Exception as e:
        logger.error(f"Error fetching dashboard: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# Admin Endpoints (for debugging)
# ============================================================================

@app.get("/api/v1/update/all")
async def trigger_update_all():
    """
    Manually trigger update of all metrics

    TODO: Add authentication
    """
    return {
        "status": "not_implemented",
        "message": "Manual update trigger is under development"
    }

# ============================================================================
# Error Handlers
# ============================================================================

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """Handle HTTP exceptions"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "status_code": exc.status_code,
            "timestamp": datetime.utcnow().isoformat()
        }
    )

@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """Handle general exceptions"""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "message": str(exc) if os.getenv("DEBUG") else "An error occurred",
            "timestamp": datetime.utcnow().isoformat()
        }
    )

# ============================================================================
# Entry point
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8001,
        reload=True,
        log_level="info"
    )
