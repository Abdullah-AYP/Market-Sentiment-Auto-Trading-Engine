const statusText = document.getElementById("statusText");
const refreshBtn = document.getElementById("refreshBtn");
const runSelectedBtn = document.getElementById("runSelectedBtn");
const runAllBtn = document.getElementById("runAllBtn");
const autoRefreshCheckbox = document.getElementById("autoRefresh");
const autoRunCycleCheckbox = document.getElementById("autoRunCycle");
const symbolSelect = document.getElementById("symbolSelect");
const intervalSelect = document.getElementById("intervalSelect");
const resetPaperBtn = document.getElementById("resetPaperBtn");
const applyPaperBtn = document.getElementById("applyPaperBtn");
const autoPaperCheckbox = document.getElementById("autoPaper");
const themeToggleBtn = document.getElementById("themeToggleBtn");
const themeToggleText = document.getElementById("themeToggleText");
const navLinks = Array.from(document.querySelectorAll(".nav-link"));

const providerModel = document.getElementById("providerModel");
const activeSymbol = document.getElementById("activeSymbol");
const latestAction = document.getElementById("latestAction");
const latestConfidence = document.getElementById("latestConfidence");
const latestTimestamp = document.getElementById("latestTimestamp");

const summaryTotal = document.getElementById("summaryTotal");
const summaryBuy = document.getElementById("summaryBuy");
const summarySell = document.getElementById("summarySell");
const summaryHold = document.getElementById("summaryHold");
const summaryAvgConfidence = document.getElementById("summaryAvgConfidence");

const marketSymbol = document.getElementById("marketSymbol");
const marketPrice = document.getElementById("marketPrice");
const marketChange = document.getElementById("marketChange");
const marketVolume = document.getElementById("marketVolume");
const lastPrice = document.getElementById("lastPrice");
const lastChange = document.getElementById("lastChange");

const sentimentSource = document.getElementById("sentimentSource");
const sentimentScore = document.getElementById("sentimentScore");
const sentimentConfidence = document.getElementById("sentimentConfidence");
const sentimentRationale = document.getElementById("sentimentRationale");

const riskTradeAllowed = document.getElementById("riskTradeAllowed");
const riskPositionPct = document.getElementById("riskPositionPct");
const riskStopLoss = document.getElementById("riskStopLoss");
const riskTakeProfit = document.getElementById("riskTakeProfit");
const riskMaxRisk = document.getElementById("riskMaxRisk");
const riskEstimatedRisk = document.getElementById("riskEstimatedRisk");

const headlineList = document.getElementById("headlineList");
const reasonList = document.getElementById("reasonList");
const historyBody = document.getElementById("historyBody");
const watchlistBody = document.getElementById("watchlistBody");
const asksBody = document.getElementById("asksBody");
const bidsBody = document.getElementById("bidsBody");
const spreadValue = document.getElementById("spreadValue");
const candleCanvas = document.getElementById("candleCanvas");

const paperEquity = document.getElementById("paperEquity");
const paperCash = document.getElementById("paperCash");
const paperTotalPnl = document.getElementById("paperTotalPnl");
const paperRealizedPnl = document.getElementById("paperRealizedPnl");
const paperUnrealizedPnl = document.getElementById("paperUnrealizedPnl");
const paperFees = document.getElementById("paperFees");
const paperPositionsCount = document.getElementById("paperPositionsCount");
const paperTradesToday = document.getElementById("paperTradesToday");
const paperDrawdown = document.getElementById("paperDrawdown");
const paperHardStop = document.getElementById("paperHardStop");
const paperPositionsBody = document.getElementById("paperPositionsBody");
const paperTradesBody = document.getElementById("paperTradesBody");

const REFRESH_MS = 15000;
let refreshTimer = null;
const THEME_KEY = "mse_theme";
let activeTheme = "dark";

const state = {
  symbols: [],
  selectedSymbol: null,
  interval: "15m",
  refreshInFlight: false,
  runInFlight: false,
};

function setTheme(nextTheme) {
  activeTheme = nextTheme === "light" ? "light" : "dark";
  document.body.dataset.theme = activeTheme;
  if (themeToggleBtn) {
    const label = activeTheme === "light" ? "Light" : "Dark";
    if (themeToggleText) {
      themeToggleText.textContent = label;
    } else {
      themeToggleBtn.textContent = `Theme: ${label}`;
    }
    themeToggleBtn.setAttribute("aria-pressed", activeTheme === "light" ? "true" : "false");
  }
}

function getInitialTheme() {
  const stored = localStorage.getItem(THEME_KEY);
  if (stored === "light" || stored === "dark") {
    return stored;
  }
  if (window.matchMedia) {
    return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  }
  return "dark";
}

function setActiveNav(targetId) {
  if (!targetId) {
    return;
  }
  navLinks.forEach((link) => {
    const href = link.getAttribute("href") || "";
    link.classList.toggle("active", href === `#${targetId}`);
  });
}

function setupNavObserver() {
  if (!navLinks.length || !("IntersectionObserver" in window)) {
    return;
  }

  const targets = navLinks
    .map((link) => {
      const href = link.getAttribute("href");
      return href ? document.querySelector(href) : null;
    })
    .filter(Boolean);

  if (!targets.length) {
    return;
  }

  const observer = new IntersectionObserver(
    (entries) => {
      const visible = entries
        .filter((entry) => entry.isIntersecting)
        .sort((a, b) => b.intersectionRatio - a.intersectionRatio);
      if (visible.length) {
        setActiveNav(visible[0].target.id);
      }
    },
    { rootMargin: "-35% 0px -55% 0px", threshold: [0.2, 0.6] }
  );

  targets.forEach((target) => observer.observe(target));
  const initial = window.location.hash.replace("#", "") || targets[0].id;
  setActiveNav(initial);
}

function setStatus(message, isError = false) {
  statusText.textContent = message;
  statusText.style.color = isError ? "#f6465d" : "#848e9c";
}

function buildQuery(params) {
  const entries = Object.entries(params).filter(([, value]) => value !== null && value !== undefined && value !== "");
  if (!entries.length) {
    return "";
  }
  return `?${new URLSearchParams(entries).toString()}`;
}

function actionClass(action) {
  const normalized = String(action || "HOLD").toLowerCase();
  if (normalized === "buy") return "buy";
  if (normalized === "sell") return "sell";
  return "hold";
}

function formatNumber(value, digits = 4) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "-";
  }
  return Number(value).toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  });
}

function formatPrice(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "-";
  }
  const n = Number(value);
  if (n >= 1000) return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
  if (n >= 1) return n.toLocaleString(undefined, { maximumFractionDigits: 4 });
  return n.toLocaleString(undefined, { maximumFractionDigits: 6 });
}

function formatUsd(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "-";
  }
  return `$${Number(value).toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  })}`;
}

function formatPct(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "-";
  }
  return `${Number(value).toFixed(digits)}%`;
}

function populateSymbols(symbols, defaultSymbol) {
  const nextSymbols = symbols.length ? symbols : [defaultSymbol];
  state.symbols = nextSymbols;

  const current = state.selectedSymbol || defaultSymbol || nextSymbols[0];
  symbolSelect.innerHTML = "";
  for (const symbol of nextSymbols) {
    const option = document.createElement("option");
    option.value = symbol;
    option.textContent = symbol;
    option.selected = symbol === current;
    symbolSelect.appendChild(option);
  }

  state.selectedSymbol = symbolSelect.value || nextSymbols[0] || null;
  activeSymbol.textContent = state.selectedSymbol || "-";
}

function renderWatchlist(items) {
  watchlistBody.innerHTML = "";

  if (!items.length) {
    const row = document.createElement("li");
    row.textContent = "No symbols available.";
    watchlistBody.appendChild(row);
    return;
  }

  for (const item of items) {
    const change = Number(item.change_percent_24h || 0);
    const row = document.createElement("li");
    row.className = `watch-row${item.symbol === state.selectedSymbol ? " active" : ""}`;
    row.innerHTML = `
      <div class="watch-top">
        <strong>${item.symbol}</strong>
        <span class="watch-change ${change >= 0 ? "pos" : "neg"}">${formatPct(change, 2)}</span>
      </div>
      <div class="watch-price">${formatPrice(item.price)}</div>
    `;

    row.addEventListener("click", async () => {
      state.selectedSymbol = item.symbol;
      symbolSelect.value = item.symbol;
      activeSymbol.textContent = item.symbol;
      await refreshDashboard({ silent: true });
    });

    watchlistBody.appendChild(row);
  }
}

function renderLatest(payload) {
  const signal = payload.signal || {};
  const sentiment = payload.sentiment || {};
  const market = payload.market || {};
  const risk = signal.risk_management || {};

  marketSymbol.textContent = market.symbol || "-";
  marketPrice.textContent = market.price ? `$${formatPrice(market.price)}` : "-";
  marketChange.textContent = formatPct(market.change_percent_24h, 3);
  marketVolume.textContent = formatNumber(market.volume_24h, 2);

  lastPrice.textContent = market.price ? `$${formatPrice(market.price)}` : "-";
  lastChange.textContent = formatPct(market.change_percent_24h, 3);
  lastChange.classList.remove("price-up", "price-down");
  if (Number(market.change_percent_24h || 0) >= 0) {
    lastChange.classList.add("price-up");
  } else {
    lastChange.classList.add("price-down");
  }

  latestAction.textContent = signal.action || "HOLD";
  latestAction.className = `signal-badge ${actionClass(signal.action)}`;
  latestConfidence.textContent = formatPct((signal.confidence || 0) * 100, 1);
  latestTimestamp.textContent = signal.timestamp || "-";

  sentimentSource.textContent = sentiment.model_source || "-";
  sentimentScore.textContent = formatNumber(sentiment.score, 3);
  sentimentConfidence.textContent = formatPct((sentiment.confidence || 0) * 100, 1);
  sentimentRationale.textContent = sentiment.rationale || "-";

  riskTradeAllowed.textContent = risk.trade_allowed ? "YES" : "NO";
  riskPositionPct.textContent = formatPct(risk.position_size_pct, 3);
  riskStopLoss.textContent = formatPct(risk.stop_loss_pct, 3);
  riskTakeProfit.textContent = formatPct(risk.take_profit_pct, 3);
  riskMaxRisk.textContent = formatNumber(risk.max_risk_usdt, 3);
  riskEstimatedRisk.textContent = formatNumber(risk.estimated_risk_usdt, 3);

  reasonList.innerHTML = "";
  for (const reason of signal.reasons || []) {
    const item = document.createElement("li");
    item.textContent = reason;
    reasonList.appendChild(item);
  }

  headlineList.innerHTML = "";
  for (const headline of (payload.headlines || []).slice(0, 8)) {
    const item = document.createElement("li");
    item.textContent = headline;
    headlineList.appendChild(item);
  }
}

function renderSummary(summary) {
  const counts = summary.counts || { BUY: 0, SELL: 0, HOLD: 0 };
  summaryTotal.textContent = String(summary.total || 0);
  summaryBuy.textContent = String(counts.BUY || 0);
  summarySell.textContent = String(counts.SELL || 0);
  summaryHold.textContent = String(counts.HOLD || 0);
  summaryAvgConfidence.textContent = formatPct((summary.avg_confidence || 0) * 100, 1);
}

function renderHistory(items) {
  historyBody.innerHTML = "";
  if (!items.length) {
    const row = document.createElement("tr");
    row.innerHTML = `<td colspan="7">No signal rows yet.</td>`;
    historyBody.appendChild(row);
    return;
  }

  for (const item of [...items].reverse()) {
    const signal = item.signal || {};
    const sentiment = item.sentiment || {};
    const market = item.market || {};
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${signal.symbol || market.symbol || "-"}</td>
      <td>${signal.timestamp || "-"}</td>
      <td><span class="action-pill ${actionClass(signal.action)}">${signal.action || "HOLD"}</span></td>
      <td>${formatPct((signal.confidence || 0) * 100, 1)}</td>
      <td>${market.price ? formatPrice(market.price) : "-"}</td>
      <td>${formatNumber(sentiment.score, 3)}</td>
      <td>${sentiment.model_source || "-"}</td>
    `;
    historyBody.appendChild(row);
  }
}

function renderOrderBook(payload) {
  const asks = payload.asks || [];
  const bids = payload.bids || [];

  asksBody.innerHTML = "";
  bidsBody.innerHTML = "";

  for (const level of asks.slice(0, 12).reverse()) {
    const row = document.createElement("tr");
    row.className = "ask-row";
    row.innerHTML = `
      <td>${formatPrice(level.price)}</td>
      <td>${formatNumber(level.quantity, 5)}</td>
      <td>${formatNumber(level.total, 5)}</td>
    `;
    asksBody.appendChild(row);
  }

  for (const level of bids.slice(0, 12)) {
    const row = document.createElement("tr");
    row.className = "bid-row";
    row.innerHTML = `
      <td>${formatPrice(level.price)}</td>
      <td>${formatNumber(level.quantity, 5)}</td>
      <td>${formatNumber(level.total, 5)}</td>
    `;
    bidsBody.appendChild(row);
  }

  if (asks.length && bids.length) {
    const spread = Number(asks[0].price) - Number(bids[0].price);
    spreadValue.textContent = `Spread: ${formatPrice(spread)}`;
  } else {
    spreadValue.textContent = "Spread: -";
  }
}

function renderPaperAccount(account, tradesResponse) {
  const daily = account.daily_guardrails || {};
  const trades = (tradesResponse && tradesResponse.items) || [];

  paperEquity.textContent = formatUsd(account.equity_usdt, 2);
  paperCash.textContent = formatUsd(account.cash_usdt, 2);
  paperTotalPnl.textContent = formatUsd(account.total_pnl_usdt, 2);
  paperRealizedPnl.textContent = formatUsd(account.realized_pnl_usdt, 2);
  paperUnrealizedPnl.textContent = formatUsd(account.unrealized_pnl_usdt, 2);
  paperFees.textContent = formatUsd(account.fees_paid_usdt, 2);
  paperPositionsCount.textContent = String(account.positions_count || 0);
  paperTradesToday.textContent = `${daily.trades_executed || 0} / ${daily.max_trades_per_day || "-"}`;
  paperDrawdown.textContent = `${formatPct(daily.drawdown_pct, 2)} / ${formatPct(daily.max_daily_drawdown_pct, 2)}`;

  const hardStopActive = Boolean(daily.hard_stop_active);
  paperHardStop.textContent = hardStopActive
    ? `ON${daily.hard_stop_reason ? ` - ${daily.hard_stop_reason}` : ""}`
    : "OFF";
  paperHardStop.classList.remove("hard-stop-on", "hard-stop-off");
  paperHardStop.classList.add(hardStopActive ? "hard-stop-on" : "hard-stop-off");

  for (const node of [paperTotalPnl, paperRealizedPnl, paperUnrealizedPnl]) {
    const value = Number(node.textContent.replace(/[^0-9.-]/g, "") || 0);
    node.classList.remove("pnl-pos", "pnl-neg");
    if (value > 0) node.classList.add("pnl-pos");
    if (value < 0) node.classList.add("pnl-neg");
  }

  paperPositionsBody.innerHTML = "";
  const positions = account.positions || [];
  if (!positions.length) {
    const row = document.createElement("tr");
    row.innerHTML = '<td colspan="5">No open paper positions.</td>';
    paperPositionsBody.appendChild(row);
  } else {
    for (const pos of positions) {
      const upnl = Number(pos.unrealized_pnl_usdt || 0);
      const row = document.createElement("tr");
      row.innerHTML = `
        <td>${pos.symbol || "-"}</td>
        <td>${formatNumber(pos.quantity, 6)}</td>
        <td>${formatPrice(pos.avg_price)}</td>
        <td>${formatPrice(pos.mark_price)}</td>
        <td class="${upnl >= 0 ? "pnl-pos" : "pnl-neg"}">${formatUsd(upnl, 3)}</td>
      `;
      paperPositionsBody.appendChild(row);
    }
  }

  paperTradesBody.innerHTML = "";
  if (!trades.length) {
    const row = document.createElement("tr");
    row.innerHTML = '<td colspan="6">No paper trades recorded.</td>';
    paperTradesBody.appendChild(row);
  } else {
    for (const trade of [...trades].reverse().slice(0, 10)) {
      const pnl = Number(trade.realized_pnl_usdt || 0);
      const row = document.createElement("tr");
      row.innerHTML = `
        <td>${trade.timestamp || "-"}</td>
        <td><span class="action-pill ${actionClass(trade.side)}">${trade.side || "-"}</span></td>
        <td>${trade.symbol || "-"}</td>
        <td>${formatNumber(trade.quantity, 6)}</td>
        <td>${formatPrice(trade.execution_price)}</td>
        <td class="${pnl >= 0 ? "pnl-pos" : "pnl-neg"}">${formatUsd(pnl, 3)}</td>
      `;
      paperTradesBody.appendChild(row);
    }
  }
}

function renderCandles(candles) {
  if (!candles.length) {
    return;
  }

  const ctx = candleCanvas.getContext("2d");
  const ratio = window.devicePixelRatio || 1;
  const width = candleCanvas.clientWidth;
  const height = candleCanvas.clientHeight;

  candleCanvas.width = Math.floor(width * ratio);
  candleCanvas.height = Math.floor(height * ratio);
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);

  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "rgba(255,255,255,0.02)";
  ctx.fillRect(0, 0, width, height);

  const highs = candles.map((c) => Number(c.high));
  const lows = candles.map((c) => Number(c.low));
  const minPrice = Math.min(...lows);
  const maxPrice = Math.max(...highs);
  const range = Math.max(maxPrice - minPrice, 1e-7);

  ctx.strokeStyle = "rgba(255,255,255,0.08)";
  ctx.lineWidth = 1;
  for (let i = 1; i <= 4; i += 1) {
    const y = (height / 5) * i;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(width, y);
    ctx.stroke();
  }

  const toY = (price) => {
    const normalized = (Number(price) - minPrice) / range;
    return height - normalized * (height - 20) - 10;
  };

  const step = width / candles.length;
  const bodyWidth = Math.max(2, step * 0.58);

  for (let i = 0; i < candles.length; i += 1) {
    const candle = candles[i];
    const x = i * step + step / 2;

    const open = Number(candle.open);
    const close = Number(candle.close);
    const high = Number(candle.high);
    const low = Number(candle.low);

    const yOpen = toY(open);
    const yClose = toY(close);
    const yHigh = toY(high);
    const yLow = toY(low);
    const color = close >= open ? "#0ecb81" : "#f6465d";

    ctx.strokeStyle = color;
    ctx.beginPath();
    ctx.moveTo(x, yHigh);
    ctx.lineTo(x, yLow);
    ctx.stroke();

    const bodyTop = Math.min(yOpen, yClose);
    const bodyHeight = Math.max(1, Math.abs(yClose - yOpen));
    ctx.fillStyle = color;
    ctx.fillRect(x - bodyWidth / 2, bodyTop, bodyWidth, bodyHeight);
  }

  const lastClose = Number(candles[candles.length - 1].close);
  const y = toY(lastClose);
  ctx.strokeStyle = "rgba(240, 185, 11, 0.9)";
  ctx.beginPath();
  ctx.moveTo(0, y);
  ctx.lineTo(width, y);
  ctx.stroke();

  ctx.fillStyle = "#f0b90b";
  ctx.font = "12px JetBrains Mono";
  ctx.fillText(`${formatPrice(lastClose)}`, 8, Math.max(14, y - 5));
}

async function fetchJson(path) {
  const response = await fetch(path);
  if (!response.ok) {
    let message = `Request failed: ${response.status}`;
    try {
      const body = await response.json();
      message = body.detail || message;
    } catch {
      // ignore JSON parse errors
    }
    throw new Error(message);
  }
  return response.json();
}

async function postJson(path) {
  const response = await fetch(path, { method: "POST" });
  if (!response.ok) {
    let message = `Request failed: ${response.status}`;
    try {
      const body = await response.json();
      message = body.detail || message;
    } catch {
      // ignore JSON parse errors
    }
    throw new Error(message);
  }
  return response.json();
}

async function applyPaperLatest(symbol) {
  return postJson(`/api/paper/apply-latest${buildQuery({ symbol })}`);
}

async function fetchConfig() {
  const config = await fetchJson("/api/config");
  providerModel.textContent = config.openai_model || "-";
  populateSymbols(config.trading_symbols || [], config.trading_symbol);
}

async function refreshDashboard({ silent = false } = {}) {
  if (state.refreshInFlight) {
    return;
  }

  state.refreshInFlight = true;
  try {
    if (!silent) {
      setStatus("Refreshing terminal...");
    }

    await fetchConfig();

    const symbol = state.selectedSymbol;
    const interval = state.interval;
    const [snapshots, latestSignal, summary, history, orderBook, klines, paperAccount, paperTrades] = await Promise.all([
      fetchJson("/api/terminal/snapshots"),
      fetchJson(`/api/latest-signal${buildQuery({ symbol })}`),
      fetchJson(`/api/summary${buildQuery({ symbol, limit: 160 })}`),
      fetchJson(`/api/signals${buildQuery({ symbol, limit: 28 })}`),
      fetchJson(`/api/terminal/order-book${buildQuery({ symbol, limit: 20 })}`),
      fetchJson(`/api/terminal/klines${buildQuery({ symbol, interval, limit: 120 })}`),
      fetchJson("/api/paper/state").catch(() => null),
      fetchJson("/api/paper/trades?limit=24").catch(() => ({ items: [] })),
    ]);

    renderWatchlist(snapshots.items || []);
    renderLatest(latestSignal);
    renderSummary(summary);
    renderHistory(history.items || []);
    renderOrderBook(orderBook);
    renderCandles(klines.items || []);
    if (paperAccount) {
      renderPaperAccount(paperAccount, paperTrades);
    }

    if (!silent) {
      setStatus("Terminal data updated.");
    }
  } catch (error) {
    setStatus(String(error.message || error), true);
  } finally {
    state.refreshInFlight = false;
  }
}

async function executeRun(kind) {
  if (state.runInFlight) {
    return;
  }

  state.runInFlight = true;
  runSelectedBtn.disabled = true;
  runAllBtn.disabled = true;

  try {
    if (kind === "all") {
      setStatus("Running all symbols...");
      const response = await fetch("/api/run-all", { method: "POST" });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || "Run-all failed.");
      }
    } else {
      setStatus(`Running ${state.selectedSymbol}...`);
      const response = await fetch(`/api/run-once${buildQuery({ symbol: state.selectedSymbol })}`, {
        method: "POST",
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || "Run-selected failed.");
      }
    }

    if (autoPaperCheckbox && autoPaperCheckbox.checked) {
      const symbols = kind === "all" ? state.symbols : [state.selectedSymbol];
      for (const symbol of symbols) {
        if (!symbol) {
          continue;
        }
        try {
          const result = await applyPaperLatest(symbol);
          const reason = result.reason ? ` ${result.reason}` : "";
          if (result.status === "executed") {
            setStatus(`Paper trade executed for ${symbol}.`);
          } else {
            setStatus(`Paper trade skipped for ${symbol}.${reason}`);
          }
        } catch (error) {
          setStatus(String(error.message || error), true);
        }
      }
    }

    await refreshDashboard({ silent: true });
    setStatus("Run finished and terminal refreshed.");
  } catch (error) {
    setStatus(String(error.message || error), true);
  } finally {
    runSelectedBtn.disabled = false;
    runAllBtn.disabled = false;
    state.runInFlight = false;
  }
}

function restartAutoLoop() {
  if (refreshTimer) {
    clearInterval(refreshTimer);
    refreshTimer = null;
  }

  if (!autoRefreshCheckbox.checked) {
    return;
  }

  refreshTimer = setInterval(async () => {
    if (state.refreshInFlight || state.runInFlight) {
      return;
    }

    if (autoRunCycleCheckbox.checked) {
      await executeRun("selected");
    } else {
      await refreshDashboard({ silent: true });
    }
  }, REFRESH_MS);
}

symbolSelect.addEventListener("change", async () => {
  state.selectedSymbol = symbolSelect.value || null;
  activeSymbol.textContent = state.selectedSymbol || "-";
  await refreshDashboard({ silent: true });
});

intervalSelect.addEventListener("change", async () => {
  state.interval = intervalSelect.value || "15m";
  await refreshDashboard({ silent: true });
});

runSelectedBtn.addEventListener("click", async () => {
  await executeRun("selected");
});

runAllBtn.addEventListener("click", async () => {
  await executeRun("all");
});

refreshBtn.addEventListener("click", async () => {
  await refreshDashboard();
});

autoRefreshCheckbox.addEventListener("change", restartAutoLoop);
autoRunCycleCheckbox.addEventListener("change", restartAutoLoop);

if (themeToggleBtn) {
  themeToggleBtn.addEventListener("click", () => {
    const nextTheme = activeTheme === "dark" ? "light" : "dark";
    setTheme(nextTheme);
    localStorage.setItem(THEME_KEY, nextTheme);
  });
}

navLinks.forEach((link) => {
  link.addEventListener("click", () => {
    const href = link.getAttribute("href") || "";
    setActiveNav(href.replace("#", ""));
  });
});

if (applyPaperBtn) {
  applyPaperBtn.addEventListener("click", async () => {
    if (!state.selectedSymbol) {
      setStatus("Select a symbol first.", true);
      return;
    }

    try {
      setStatus(`Applying latest ${state.selectedSymbol} signal to paper...`);
      const result = await applyPaperLatest(state.selectedSymbol);
      const reason = result.reason ? ` ${result.reason}` : "";
      if (result.status === "executed") {
        setStatus(`Paper trade executed for ${state.selectedSymbol}.`);
      } else {
        setStatus(`Paper trade skipped for ${state.selectedSymbol}.${reason}`);
      }
      await refreshDashboard({ silent: true });
    } catch (error) {
      setStatus(String(error.message || error), true);
    }
  });
}

if (resetPaperBtn) {
  resetPaperBtn.addEventListener("click", async () => {
    const confirmed = window.confirm("Reset paper account and clear paper trade history?");
    if (!confirmed) {
      return;
    }

    try {
      setStatus("Resetting paper account...");
      const response = await fetch("/api/paper/reset?clear_trades=true", { method: "POST" });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || "Paper reset failed.");
      }
      await refreshDashboard({ silent: true });
      setStatus("Paper account reset.");
    } catch (error) {
      setStatus(String(error.message || error), true);
    }
  });
}

window.addEventListener("resize", async () => {
  await refreshDashboard({ silent: true });
});

setTheme(getInitialTheme());
setupNavObserver();
refreshDashboard();
restartAutoLoop();
