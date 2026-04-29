from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Import your existing logic
from .config import Settings
from .main import build_engine

app = FastAPI()

# Crucial: Allow the frontend's dev tunnel URL to talk to this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Change to the frontend dev tunnel URL later for security
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize your engine once when the server starts
settings = Settings.from_env()
engine = build_engine(settings)

@app.get("/api/config")
async def get_engine_config():
    return {
        "status": "success",
        "active_symbols": settings.trading_symbols or ["AAPL", "XRPUSDT"],
        "strategy": {
            "bullish_threshold": settings.bullish_threshold,
            "bearish_threshold": settings.bearish_threshold
        }
    }

@app.get("/api/sentiment/{symbol}")
async def get_sentiment_signal(symbol: str):
    """
    The frontend can hit this endpoint (e.g., /api/sentiment/XRPUSDT) 
    to trigger an AI analysis and get the trading signal.
    """
    try:
        # Override the symbol for this specific request
        settings.trading_symbol = symbol.upper()
        
        # Run one cycle of the engine to get the latest data & decision
        # You may need to adjust this depending on what run_cycle() returns!
        signal = engine.run_cycle() 
        
        return {"status": "success", "symbol": symbol, "signal": signal}
    
    except Exception as e:
        return {"status": "error", "message": str(e)}

# To run this, you will type: uvicorn api:app --port 8000 --reload