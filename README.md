# Market Sentiment Auto-Trading Engine

## Executive Summary
This project implements the proposal for an automated cryptocurrency signal generator. It ingests live market data and relevant news, computes a sentiment score using an LLM (or a deterministic fallback), applies a decision-tree strategy with risk constraints, and outputs BUY/SELL/HOLD signals. A local web dashboard visualizes signals, and an optional paper-trading layer simulates execution for safe testing. n8n workflows are provided to automate the pipeline and notifications.

## Objectives (Aligned to Proposal)
- Automate ingestion of market data and news.
- Use LLM-based sentiment analysis to quantify bullish/bearish bias.
- Apply a search-based decision tree to generate actionable spot signals.
- Provide automated delivery, visualization, and safe paper execution.

## System Architecture (High Level)
Data Sources
- Binance API (market snapshots, order book, klines)
- Google News RSS (symbol-aware headline search)

Processing Pipeline
1. Fetch market data and news headlines
2. LLM sentiment scoring (OpenAI or compatible provider)
3. Decision-tree evaluation + risk controls
4. Signal output to JSONL
5. Optional paper execution and notifications
6. Dashboard visualization and controls

## Technology Stack
- Python 3.x
- FastAPI + Uvicorn (local API and dashboard backend)
- OpenAI SDK (LLM sentiment)
- Requests (HTTP client)
- feedparser (RSS parsing)
- python-dotenv (.env configuration)
- pytest (unit tests)
- HTML/CSS/JavaScript (dashboard UI)
- n8n workflow templates (automation and notifications)

Note: The original proposal mentioned Pandas/NumPy. The current implementation does not require them.

## AI Approach and Methodology
### LLM Sentiment Analysis
- The system prompts the LLM with headlines and market context.
- Output is strict JSON with score in [-1.0, +1.0] and confidence in [0.0, 1.0].
- If the API key is missing or invalid, a lexicon-based fallback assigns sentiment.

### Decision Tree Strategy
- Combines sentiment score and recent price momentum into a composite score.
- Applies bullish/bearish thresholds with an adaptive confidence shift.
- Includes a neutral band to avoid noisy trades.

### Risk Management Rules
- Minimum sentiment and trade confidence gates.
- Maximum 24h volatility gate.
- Daily loss gate and position-size scaling.
- Automatic stop-loss and take-profit calculation.

### Search Optimization (Beam Search)
- A local beam search optimizer tunes decision thresholds using historical signal data.
- Evaluates candidate strategies by reward and directional accuracy.
- Produces ready-to-copy .env overrides for thresholds.

## Core Features Implemented
- Live market data ingestion (Binance API)
- Live headline ingestion (Google News RSS)
- LLM sentiment scoring (OpenAI or compatible provider)
- Decision-tree signal generation with risk constraints
- Signal export to signals/signals.jsonl
- Web dashboard with charts, order book, signal history
- Light/dark theme toggle in the UI
- Paper trading simulation and daily guardrails
- n8n workflow templates for automation and notifications

## Project Structure
market_sentiment_engine/
  config.py
  models.py
  data_sources.py
  sentiment.py
  decision.py
  search_optimizer.py
  alerts.py
  engine.py
  main.py
  paper_trading.py
  web_app.py
run_engine.py
run_search.py
run_web.py
web/
  index.html
  styles.css
  app.js
n8n/
  market_sentiment_workflow.json
  market_sentiment_workflow_notifications.json
requirements.txt
.env.example

## Configuration (.env)
Required or common fields:
- OPENAI_API_KEY
- OPENAI_BASE_URL (optional for OpenAI-compatible providers)
- OPENAI_MODEL
- TRADING_SYMBOL or TRADING_SYMBOLS
- NEWS_QUERY
- ACCOUNT_EQUITY_USDT

Risk tuning fields:
- RISK_PER_TRADE_PCT
- BASE_POSITION_SIZE_PCT
- MIN_POSITION_SIZE_PCT
- MAX_POSITION_SIZE_PCT
- STOP_LOSS_MIN_PCT
- STOP_LOSS_MAX_PCT
- TAKE_PROFIT_RR
- MAX_VOLATILITY_24H_PCT
- MAX_DAILY_LOSS_PCT
- DAILY_LOSS_USED_PCT
- MIN_SENTIMENT_CONFIDENCE
- MOMENTUM_OVERRIDE_PCT
- MIN_TRADE_CONFIDENCE

Paper trading fields:
- PAPER_STARTING_CASH_USDT
- PAPER_FEE_BPS
- PAPER_SLIPPAGE_BPS
- PAPER_MIN_NOTIONAL_USDT
- PAPER_MAX_TRADES_PER_DAY
- PAPER_MAX_DAILY_DRAWDOWN_PCT
- PAPER_STATE_PATH
- PAPER_TRADES_PATH

n8n fields:
- N8N_WEBHOOK_SECRET
- N8N_SIGNATURE_TTL_SECONDS

## How to Run
### 1) Setup
cd "/Users/mac/Desktop/AI PROJECT"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

### 2) Run Engine (CLI)
python run_engine.py --once
python run_engine.py --once --all-symbols
python run_engine.py

### 3) Run Web Dashboard
python run_web.py --reload
Open: http://127.0.0.1:8000

### 4) Run Search Optimizer
python run_search.py --signals-path signals/signals.jsonl --beam-width 8 --depth 10

## Dashboard Features
- Watchlist and market snapshot
- Candlestick rendering with price markers
- Order book view (bids/asks)
- Signal and risk breakdown
- Headlines and rationale
- Paper account state and trade log
- Manual and auto refresh/run controls
- Light/dark mode toggle

## Paper Trading (Safety Layer)
- Applies BUY/SELL actions to a simulated account.
- Enforces min notional, fees, slippage, and daily guardrails.
- Stores state in signals/paper_state.json and trades in signals/paper_trades.jsonl.

## API Endpoints (FastAPI)
- GET /api/config
- GET /api/terminal/snapshots
- GET /api/terminal/order-book
- GET /api/terminal/klines
- GET /api/latest-signal
- GET /api/signals
- GET /api/summary
- GET /api/paper/state
- GET /api/paper/trades
- POST /api/paper/apply-latest
- POST /api/paper/reset
- POST /api/run-once
- POST /api/run-all

## n8n Integration
Templates:
- n8n/market_sentiment_workflow.json
- n8n/market_sentiment_workflow_notifications.json

n8n API endpoints:
- POST /api/n8n/run-once
- POST /api/n8n/run-once-paper
- POST /api/n8n/run-all
- GET /api/n8n/latest-signal

If N8N_WEBHOOK_SECRET is set, all n8n routes require signed headers.

## Output Data
- signals/signals.jsonl contains market snapshot, sentiment, decision, risk plan, and headlines.
- Paper state and trades are stored in signals/paper_state.json and signals/paper_trades.jsonl.

## Testing
pytest -q

## Limitations and Ethics
- Educational/research use only, not financial advice.
- This system does not execute real trades.
- LLM outputs can be noisy; risk gates reduce but do not remove risk.

## Future Work
- Add portfolio-level risk controls and correlation limits.
- Add backtesting with real historical price and news data.
- Improve sentiment with source weighting and entity recognition.
- Expand UI with alerts, export, and analytics dashboards.

## Presentation Slide Outline (Suggested)
1. Title and Team
  - Project name, team members, course/date
2. Problem and Motivation
  - Information overload, need for fast sentiment-driven signals
3. Proposed Solution
  - End-to-end pipeline: data -> LLM -> decision tree -> signals
4. Architecture and Data Flow
  - Market data + news ingestion, processing stages, outputs
5. AI Methodology
  - LLM sentiment scoring and fallback
  - Decision tree thresholds and risk gates
6. Implementation Highlights
  - FastAPI backend, dashboard UI, paper trading layer
7. Results and Demo
  - Sample signals, dashboard screenshots, paper account state
8. Limitations and Future Work
  - No live trading, model noise, next improvements

## References
- OpenAI Platform Documentation
- Binance API Documentation
- Google News RSS Documentation
- n8n Workflow Automation Documentation
