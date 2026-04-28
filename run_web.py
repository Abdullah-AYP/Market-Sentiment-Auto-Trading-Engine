from __future__ import annotations

import argparse

import uvicorn


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run web dashboard for market sentiment engine")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind, e.g. 127.0.0.1")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind, e.g. 8000")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    uvicorn.run(
        "market_sentiment_engine.web_app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
