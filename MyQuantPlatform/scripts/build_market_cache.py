#!/usr/bin/env python3
"""Build API-key-free static market-data snapshots for MyQuantPlatform.

The browser never calls a paid market API.  This script runs in GitHub Actions,
collects public Nasdaq.com page data once, normalizes it, and commits JSON files
that GitHub Pages can serve repeatedly.  Cached files are never deleted when a
temporary upstream failure occurs.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
MARKET_DIR = DATA_DIR / "market"
CATALOG_PATH = DATA_DIR / "catalog.json"
MANIFEST_PATH = DATA_DIR / "manifest.json"
DEFAULT_TICKERS_PATH = DATA_DIR / "default-tickers.json"
UNIVERSE_PATH = DATA_DIR / "universe.json"
SCHEMA_VERSION = 2
NASDAQ_BASE = "https://api.nasdaq.com/api"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "Chrome/126.0 Safari/537.36 MyQuantPlatform/2.0"
)
KNOWN_FUND_METADATA: dict[str, dict[str, Any]] = {
    "VIG": {
        "provider": "Vanguard",
        "exchange": "NYSE Arca",
        "inceptionDate": "2006-04-21",
        "benchmarkIndex": "S&P U.S. Dividend Growers Index",
        "assetClass": "미국 대형주",
        "strategy": "배당금을 꾸준히 늘려 온 미국 기업에 투자하는 패시브 ETF",
        "distributionFrequency": "분기",
        "officialUrl": "https://investor.vanguard.com/investment-products/etfs/profile/vig",
    },
    "IQQ": {
        "provider": "iShares by BlackRock",
        "exchange": "NASDAQ",
        "inceptionDate": "2026-07-08",
        "benchmarkIndex": "Nasdaq 100 Index",
        "assetClass": "미국 대형 성장주",
        "strategy": "Nasdaq에 상장된 시가총액 상위 비금융 기업을 추종하는 패시브 ETF",
        "distributionFrequency": "분기",
        "officialUrl": "https://www.ishares.com/us/products/351653/ishares-nasdaq-100-etf",
        "expenseRatio": 0.0012,
        "netExpenseRatio": 0.0010,
        "spread": 0.0004,
        "holdingsCount": 103,
        "holdingsUrl": "https://www.ishares.com/us/products/351653/ishares-nasdaq-100-etf/latest-holdings.csv",
    },
}


class DataUnavailable(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def parse_number(value: Any, *, thousands: bool = False) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = finite(value)
        return number * 1000 if number is not None and thousands else number
    text = str(value).strip()
    if not text or text.upper() in {"N/A", "NA", "--", "NONE", "NULL"}:
        return None
    negative = text.startswith("-") or (text.startswith("(") and text.endswith(")"))
    percent = "%" in text
    cleaned = re.sub(r"[^0-9.]+", "", text)
    if not cleaned:
        return None
    number = finite(cleaned)
    if number is None:
        return None
    if negative:
        number = -number
    if thousands:
        number *= 1000
    if percent:
        number /= 100
    return number


def pick_value(payload: dict[str, Any] | None, key: str) -> Any:
    item = (payload or {}).get(key)
    return item.get("value") if isinstance(item, dict) else item


class NasdaqClient:
    def __init__(self) -> None:
        self.headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": "https://www.nasdaq.com",
            "Referer": "https://www.nasdaq.com/",
        }

    def get(self, path: str, params: dict[str, Any] | None = None, *, attempts: int = 4) -> Any:
        url = f"{NASDAQ_BASE}/{path.lstrip('/')}"
        if params:
            url = f"{url}?{urlencode(params)}"
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                request = Request(url, headers=self.headers)
                with urlopen(request, timeout=35) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                status = payload.get("status") if isinstance(payload, dict) else None
                if isinstance(status, dict) and status.get("rCode") not in (None, 200):
                    raise DataUnavailable(f"Nasdaq data unavailable: {path}")
                if isinstance(payload, dict) and payload.get("data") is None:
                    raise DataUnavailable(f"No data: {path}")
                return payload.get("data") if isinstance(payload, dict) else payload
            except HTTPError as exc:
                if exc.code == 404:
                    raise DataUnavailable(f"404: {path}") from exc
                last_error = exc
                if attempt + 1 < attempts:
                    time.sleep(1.5 * (attempt + 1))
            except (URLError, TimeoutError, ValueError, DataUnavailable) as exc:
                last_error = exc
                if attempt + 1 < attempts:
                    time.sleep(1.5 * (attempt + 1))
        raise DataUnavailable(str(last_error or f"Failed: {path}"))


def safe_get(client: NasdaqClient, path: str, params: dict[str, Any] | None = None) -> Any:
    try:
        return client.get(path, params)
    except DataUnavailable:
        return None


def load_official_fund_holdings(symbol: str) -> list[dict[str, Any]]:
    metadata = KNOWN_FUND_METADATA.get(symbol, {})
    url = metadata.get("holdingsUrl")
    if not url:
        return []
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/csv,*/*"})
    try:
        with urlopen(request, timeout=35) as response:
            text = response.read().decode("utf-8-sig")
    except (HTTPError, URLError, TimeoutError, UnicodeDecodeError):
        return []
    lines = text.splitlines()
    header_index = next(
        (index for index, line in enumerate(lines) if line.startswith("Ticker,Name,")),
        None,
    )
    if header_index is None:
        return []
    holdings: list[dict[str, Any]] = []
    for row in csv.DictReader(io.StringIO("\n".join(lines[header_index:]))):
        if str(row.get("Asset Class") or "").strip().casefold() != "equity":
            continue
        symbol_value = str(row.get("Ticker") or "").strip().upper()
        weight = parse_number(row.get("Weight (%)"))
        if not symbol_value or weight is None or weight <= 0:
            continue
        holdings.append(
            {
                "symbol": symbol_value,
                "name": row.get("Name") or symbol_value,
                "weight": weight,
                "sector": row.get("Sector") or None,
                "country": row.get("Location") or None,
            }
        )
    return holdings


def normalize_symbol(value: str) -> str:
    symbol = value.strip().upper().replace("/", "-")
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9.\-^]{0,19}", symbol):
        raise ValueError(f"Unsupported ticker: {value}")
    return symbol


def table_rows(table: dict[str, Any] | None) -> list[dict[str, Any]]:
    rows = ((table or {}).get("rows") if isinstance(table, dict) else None) or []
    return rows if isinstance(rows, list) else []


def table_periods(table: dict[str, Any] | None) -> list[tuple[str, str]]:
    headers = ((table or {}).get("headers") if isinstance(table, dict) else None) or {}
    return [(key, str(value)) for key, value in headers.items() if key != "value1" and value]


def row_by_label(table: dict[str, Any] | None, labels: tuple[str, ...]) -> dict[str, Any] | None:
    wanted = {label.casefold() for label in labels}
    for row in table_rows(table):
        if str(row.get("value1", "")).strip().casefold() in wanted:
            return row
    return None


def build_financial_years(financials: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not financials:
        return []
    income = financials.get("incomeStatementTable") or {}
    balance = financials.get("balanceSheetTable") or {}
    cashflow = financials.get("cashFlowTable") or {}
    ratios = financials.get("financialRatiosTable") or {}
    periods = table_periods(income) or table_periods(balance)

    fields: dict[str, tuple[dict[str, Any], tuple[str, ...], bool]] = {
        "revenue": (income, ("Total Revenue",), True),
        "grossProfit": (income, ("Gross Profit",), True),
        "operatingIncome": (income, ("Operating Income",), True),
        "netIncome": (income, ("Net Income", "Net Income-Cont. Operations"), True),
        "cash": (balance, ("Cash and Cash Equivalents",), True),
        "shortTermInvestments": (balance, ("Short-Term Investments",), True),
        "totalAssets": (balance, ("Total Assets",), True),
        "totalLiabilities": (balance, ("Total Liabilities",), True),
        "equity": (balance, ("Total Equity",), True),
        "shortTermDebt": (balance, ("Short-Term Debt / Current Portion of Long-Term Debt",), True),
        "longTermDebt": (balance, ("Long-Term Debt",), True),
        "operatingCashFlow": (cashflow, ("Net Cash Flow-Operating",), True),
        "capex": (cashflow, ("Capital Expenditures",), True),
        "grossMargin": (ratios, ("Gross Margin",), False),
        "operatingMargin": (ratios, ("Operating Margin",), False),
        "netMargin": (ratios, ("Profit Margin",), False),
        "roe": (ratios, ("After Tax ROE",), False),
        "currentRatio": (ratios, ("Current Ratio",), False),
    }

    result: list[dict[str, Any]] = []
    for column, period in periods:
        item: dict[str, Any] = {"date": period}
        for field, (table, labels, thousands) in fields.items():
            row = row_by_label(table, labels)
            item[field] = parse_number(row.get(column), thousands=thousands) if row else None
        item["totalCash"] = sum(
            value for value in (item.get("cash"), item.get("shortTermInvestments")) if value is not None
        ) or None
        item["totalDebt"] = sum(
            value for value in (item.get("shortTermDebt"), item.get("longTermDebt")) if value is not None
        ) or None
        if item.get("operatingCashFlow") is not None:
            capex = abs(item.get("capex") or 0)
            item["freeCashFlow"] = item["operatingCashFlow"] - capex
        result.append(item)
    return result


def parse_history(payload: dict[str, Any] | None) -> dict[str, list[Any]]:
    rows = table_rows(((payload or {}).get("tradesTable") or {}))
    parsed: list[tuple[str, float, float | None, float | None, float | None]] = []
    for row in rows:
        raw_date = str(row.get("date", ""))
        try:
            day = datetime.strptime(raw_date, "%m/%d/%Y").date().isoformat()
        except ValueError:
            continue
        close = parse_number(row.get("close"))
        if close is None or close <= 0:
            continue
        parsed.append(
            (
                day,
                close,
                parse_number(row.get("high")),
                parse_number(row.get("low")),
                parse_number(row.get("volume")),
            )
        )
    parsed.sort(key=lambda row: row[0])
    return {
        "dates": [row[0] for row in parsed],
        "close": [row[1] for row in parsed],
        "high": [row[2] for row in parsed],
        "low": [row[3] for row in parsed],
        "volume": [row[4] for row in parsed],
    }


def period_stats(history: dict[str, list[Any]], days: int) -> dict[str, Any] | None:
    dates = history.get("dates") or []
    close = history.get("close") or []
    if len(dates) < 2 or len(close) != len(dates):
        return None
    available_days = (date.fromisoformat(dates[-1]) - date.fromisoformat(dates[0])).days
    if available_days < days * 0.8:
        return None
    cutoff = (date.fromisoformat(dates[-1]) - timedelta(days=days)).isoformat()
    indices = [index for index, value in enumerate(dates) if value >= cutoff]
    if len(indices) < 2:
        return None
    first, last = indices[0], indices[-1]
    highs = [history["high"][i] for i in indices if history["high"][i] is not None]
    lows = [history["low"][i] for i in indices if history["low"][i] is not None]
    return {
        "start": dates[first],
        "end": dates[last],
        "return": close[last] / close[first] - 1 if close[first] else None,
        "high": max(highs) if highs else max(close[i] for i in indices),
        "low": min(lows) if lows else min(close[i] for i in indices),
    }


def stock_research(client: NasdaqClient, symbol: str) -> dict[str, Any]:
    info = client.get(f"quote/{quote(symbol)}/info", {"assetclass": "stocks"})
    summary_payload = client.get(f"quote/{quote(symbol)}/summary", {"assetclass": "stocks"})
    summary = summary_payload.get("summaryData") or {}
    profile = safe_get(client, f"company/{quote(symbol)}/company-profile") or {}
    financials = safe_get(client, f"company/{quote(symbol)}/financials") or {}
    eps_payload = safe_get(client, f"quote/{quote(symbol)}/eps", {"assetclass": "stocks"}) or {}
    analyst_payload = safe_get(client, f"analyst/{quote(symbol)}/targetprice") or {}
    return build_research_payload(
        client, symbol, "STOCK", info, summary, profile, financials, eps_payload, analyst_payload, None
    )


def etf_research(client: NasdaqClient, symbol: str) -> dict[str, Any]:
    info = client.get(f"quote/{quote(symbol)}/info", {"assetclass": "etf"})
    summary_payload = client.get(f"quote/{quote(symbol)}/summary", {"assetclass": "etf"})
    summary = summary_payload.get("summaryData") or {}
    holdings_payload = safe_get(client, f"company/{quote(symbol)}/holdings", {"assetclass": "etf"}) or {}
    return build_research_payload(
        client, symbol, "ETF", info, summary, {}, {}, {}, {}, holdings_payload
    )


def build_research_payload(
    client: NasdaqClient,
    symbol: str,
    instrument_type: str,
    info: dict[str, Any],
    summary: dict[str, Any],
    profile: dict[str, Any],
    financials: dict[str, Any],
    eps_payload: dict[str, Any],
    analyst_payload: dict[str, Any],
    holdings_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    today = date.today()
    asset_class = "etf" if instrument_type == "ETF" else "stocks"
    history_payload = client.get(
        f"quote/{quote(symbol)}/historical",
        {
            "assetclass": asset_class,
            "fromdate": (today - timedelta(days=3653)).isoformat(),
            "todate": today.isoformat(),
            "limit": 5000,
        },
    )
    history = parse_history(history_payload)
    if len(history["dates"]) < 2:
        raise DataUnavailable(f"Not enough history for {symbol}")

    primary = info.get("primaryData") or {}
    company_name = info.get("companyName") or pick_value(profile, "CompanyName") or symbol
    price = parse_number(primary.get("lastSalePrice")) or history["close"][-1]
    financial_years = build_financial_years(financials)
    latest = financial_years[0] if financial_years else {}
    market_cap = parse_number(pick_value(summary, "MarketCap"))

    previous_eps = [
        item
        for item in (eps_payload.get("earningsPerShare") or [])
        if item.get("type") == "PreviousQuarter" and finite(item.get("earnings")) is not None
    ]
    trailing_eps = sum(float(item["earnings"]) for item in previous_eps[-4:]) if previous_eps else None
    pe = price / trailing_eps if price and trailing_eps and trailing_eps > 0 else None
    pbr = market_cap / latest["equity"] if market_cap and latest.get("equity") and latest["equity"] > 0 else None
    psr = market_cap / latest["revenue"] if market_cap and latest.get("revenue") and latest["revenue"] > 0 else None

    consensus = analyst_payload.get("consensusOverview") or {}
    analyst = {
        "targetMean": finite(consensus.get("priceTarget")) or parse_number(pick_value(summary, "OneYrTarget")),
        "targetHigh": finite(consensus.get("highPriceTarget")),
        "targetLow": finite(consensus.get("lowPriceTarget")),
        "buy": finite(consensus.get("buy")),
        "hold": finite(consensus.get("hold")),
        "sell": finite(consensus.get("sell")),
    }
    analyst["count"] = sum(value or 0 for key, value in analyst.items() if key in {"buy", "hold", "sell"})

    top_holdings: list[dict[str, Any]] = []
    if instrument_type == "ETF":
        holding_table = ((holdings_payload or {}).get("holdings") or {})
        for row in table_rows(holding_table):
            holding_symbol = str(row.get("symbol") or "").strip().upper()
            raw_weight = row.get("weighting")
            weight = parse_number(raw_weight)
            if weight is not None and "%" in str(raw_weight):
                weight *= 100
            if not holding_symbol or weight is None or weight <= 0:
                continue
            sector = None
            holding_summary = safe_get(
                client, f"quote/{quote(holding_symbol)}/summary", {"assetclass": "stocks"}
            )
            if holding_summary:
                sector = pick_value(holding_summary.get("summaryData") or {}, "Sector")
            top_holdings.append(
                {
                    "symbol": holding_symbol,
                    "name": row.get("companyname") or holding_symbol,
                    "weight": weight,
                    "sector": sector,
                }
            )
            time.sleep(0.12)
        official_holdings = load_official_fund_holdings(symbol)
        if official_holdings:
            top_holdings = official_holdings

    sector_weights: dict[str, float] = {}
    country_weights: dict[str, float] = {}
    for holding in top_holdings:
        sector = holding.get("sector") or "기타/미분류"
        sector_weights[sector] = sector_weights.get(sector, 0) + float(holding["weight"])
        country = holding.get("country") or "기타/미분류"
        country_weights[country] = country_weights.get(country, 0) + float(holding["weight"])

    high_low = str(pick_value(summary, "FiftTwoWeekHighLow") or "")
    high_low_numbers = [parse_number(value) for value in high_low.split("/")]
    high_low_numbers = [value for value in high_low_numbers if value is not None]
    recent_volumes = [
        value for value in history.get("volume", []) if value is not None and value >= 0
    ]
    average_20_day_volume = (
        sum(recent_volumes[-20:]) / 20 if len(recent_volumes) >= 20 else None
    )
    average_30_day_volume = (
        sum(recent_volumes[-30:]) / 30 if len(recent_volumes) >= 30 else None
    )
    latest_normal_volume = recent_volumes[-1] if recent_volumes else None
    upstream_average_volume = parse_number(
        pick_value(summary, "AverageVolume") or pick_value(summary, "FiftyDayAvgDailyVol")
    )
    liquidity_value = (
        average_20_day_volume
        if average_20_day_volume is not None
        else average_30_day_volume
        if average_30_day_volume is not None
        else upstream_average_volume
        if upstream_average_volume is not None
        else latest_normal_volume
    )
    liquidity_basis = (
        "최근 20거래일 평균 거래량"
        if average_20_day_volume is not None
        else "최근 30거래일 평균 거래량"
        if average_30_day_volume is not None
        else "공급처 평균 거래량"
        if upstream_average_volume is not None
        else "최근 정상 거래일 거래량"
    )
    fund_metadata = KNOWN_FUND_METADATA.get(symbol, {}) if instrument_type == "ETF" else {}
    quote_data = {
        "price": price,
        "previousClose": parse_number(pick_value(summary, "PreviousClose")),
        "marketCap": market_cap,
        "volume": parse_number(pick_value(summary, "ShareVolume")),
        "averageVolume": liquidity_value,
        "high52": high_low_numbers[0] if len(high_low_numbers) >= 2 else None,
        "low52": high_low_numbers[1] if len(high_low_numbers) >= 2 else None,
        "dividend": parse_number(pick_value(summary, "AnnualizedDividend")),
        "dividendYield": parse_number(pick_value(summary, "Yield")),
        "beta": parse_number(pick_value(summary, "Beta")),
        "aum": parse_number(pick_value(summary, "AUM"), thousands=True),
        "expenseRatio": parse_number(pick_value(summary, "ExpenseRatio"))
        or fund_metadata.get("expenseRatio"),
    }

    updated_at = utc_now()
    result = {
        "schemaVersion": SCHEMA_VERSION,
        "symbol": symbol,
        "name": company_name,
        "type": instrument_type,
        "exchange": fund_metadata.get("exchange")
        or info.get("exchange")
        or pick_value(summary, "Exchange"),
        "currency": "USD",
        "sector": pick_value(profile, "Sector") or pick_value(summary, "Sector"),
        "industry": pick_value(profile, "Industry") or pick_value(summary, "Industry"),
        "region": pick_value(profile, "Region"),
        "description": pick_value(profile, "CompanyDescription")
        or (f"{company_name}는 {symbol} 티커로 거래되는 상장지수펀드(ETF)입니다." if instrument_type == "ETF" else ""),
        "website": pick_value(profile, "CompanyUrl"),
        "updatedAt": updated_at,
        "dataDate": history["dates"][-1],
        "cache": {
            "updatedAt": updated_at,
            "source": "Nasdaq.com market pages",
            "status": "success",
            "version": str(SCHEMA_VERSION),
        },
        "dataStatus": {
            "status": "success",
            "history": "short" if len(history["dates"]) < 20 else "available",
            "historyPoints": len(history["dates"]),
            "message": "상장 이력이 짧아 일부 기간 계산 불가"
            if len(history["dates"]) < 20
            else "정상",
        },
        "liquidity": {
            "threshold": 1_000_000,
            "value": liquidity_value,
            "basis": liquidity_basis,
            "qualifies": liquidity_value is not None and liquidity_value >= 1_000_000,
            "average20Day": average_20_day_volume,
            "average30Day": average_30_day_volume,
            "latestNormalDay": latest_normal_volume,
        },
        "quote": quote_data,
        "valuation": {"pe": pe, "pbr": pbr, "psr": psr},
        "profitability": {
            "roe": latest.get("roe"),
            "grossMargin": latest.get("grossMargin"),
            "operatingMargin": latest.get("operatingMargin"),
            "netMargin": latest.get("netMargin"),
        },
        "financialHealth": {
            "totalDebt": latest.get("totalDebt"),
            "totalCash": latest.get("totalCash"),
            "totalAssets": latest.get("totalAssets"),
            "totalLiabilities": latest.get("totalLiabilities"),
            "equity": latest.get("equity"),
            "currentRatio": latest.get("currentRatio"),
            "freeCashFlow": latest.get("freeCashFlow"),
        },
        "earnings": {"trailingEps": trailing_eps, "quarters": previous_eps[-4:]},
        "analyst": analyst,
        "periods": {
            "1m": period_stats(history, 31),
            "3m": period_stats(history, 93),
            "6m": period_stats(history, 186),
            "1y": period_stats(history, 366),
        },
        "financials": {"unit": "USD", "years": financial_years},
        "etf": {
            "aum": quote_data["aum"],
            "expenseRatio": quote_data["expenseRatio"],
            "netExpenseRatio": fund_metadata.get("netExpenseRatio"),
            "yield": quote_data["dividendYield"],
            "provider": fund_metadata.get("provider"),
            "inceptionDate": fund_metadata.get("inceptionDate"),
            "benchmarkIndex": fund_metadata.get("benchmarkIndex"),
            "assetClass": fund_metadata.get("assetClass"),
            "strategy": fund_metadata.get("strategy"),
            "distributionFrequency": fund_metadata.get("distributionFrequency"),
            "spread": fund_metadata.get("spread"),
            "holdingsCount": fund_metadata.get("holdingsCount"),
            "currency": "USD",
            "leveraged": False,
            "coveredCall": False,
            "active": False,
            "currencyHedged": False,
            "topHoldings": top_holdings,
            "sectorWeights": [
                {"name": name, "weight": weight}
                for name, weight in sorted(sector_weights.items(), key=lambda item: item[1], reverse=True)
            ],
            "countryWeights": [
                {"name": name, "weight": weight}
                for name, weight in sorted(country_weights.items(), key=lambda item: item[1], reverse=True)
            ],
            "holdingsCoverage": sum(float(item["weight"]) for item in top_holdings),
        }
        if instrument_type == "ETF"
        else None,
        "history": history,
        "sources": [
            {
                "name": "Nasdaq.com market pages",
                "url": f"https://www.nasdaq.com/market-activity/{'etf' if instrument_type == 'ETF' else 'stocks'}/{symbol.lower()}",
                "retrievedAt": utc_now(),
                "note": "Delayed/public website data; annual financial figures are normalized from Nasdaq tables.",
            }
        ]
        + (
            [
                {
                    "name": f"{fund_metadata.get('provider')} official fund page",
                    "url": fund_metadata.get("officialUrl"),
                    "retrievedAt": updated_at,
                    "note": "Fund identity, exchange, inception, benchmark and product facts.",
                }
            ]
            if fund_metadata.get("officialUrl")
            else []
        ),
    }
    return result


def build_one(client: NasdaqClient, symbol: str) -> dict[str, Any]:
    symbol = normalize_symbol(symbol)
    errors: list[str] = []
    for builder in (stock_research, etf_research):
        try:
            return builder(client, symbol)
        except DataUnavailable as exc:
            errors.append(str(exc))
    raise DataUnavailable(f"{symbol}: " + " / ".join(errors))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temporary.replace(path)


def load_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return fallback


def update_manifest() -> None:
    entries = []
    for path in sorted(MARKET_DIR.glob("*.json")):
        payload = load_json(path, {})
        if payload.get("symbol"):
            entries.append(
                {
                    "symbol": payload["symbol"],
                    "name": payload.get("name"),
                    "type": payload.get("type"),
                    "dataDate": payload.get("dataDate"),
                    "updatedAt": payload.get("updatedAt"),
                }
            )
    write_json(
        MANIFEST_PATH,
        {"schemaVersion": SCHEMA_VERSION, "updatedAt": utc_now(), "count": len(entries), "symbols": entries},
    )


def build_liquidity_universe() -> None:
    catalog = load_json(CATALOG_PATH, {})
    defaults = set(load_json(DEFAULT_TICKERS_PATH, []))
    eligible: list[dict[str, Any]] = []
    for item in catalog.get("items") or []:
        volume = finite(item.get("volume"))
        cached_eligibility = item.get("liquidityEligible")
        qualifies = (
            bool(cached_eligibility)
            if cached_eligibility is not None
            else volume is not None and volume >= 1_000_000
        )
        if not qualifies and item.get("symbol") not in defaults:
            continue
        eligible.append(
            {
                "symbol": item.get("symbol"),
                "name": item.get("name"),
                "type": item.get("type"),
                "exchange": item.get("exchange"),
                "currency": item.get("currency"),
                "volume": volume,
                "volumeBasis": item.get("liquidityBasis")
                or "최근 정상 거래일 거래량(카탈로그 공급처 값)",
                "meetsMillionVolume": qualifies,
                "manualException": item.get("symbol") in defaults and not qualifies,
            }
        )
    updated_at = utc_now()
    write_json(
        UNIVERSE_PATH,
        {
            "schemaVersion": SCHEMA_VERSION,
            "updatedAt": updated_at,
            "threshold": 1_000_000,
            "methodPriority": [
                "최근 20거래일 평균 거래량",
                "최근 30거래일 평균 거래량",
                "평균 거래량 데이터가 없으면 최근 정상 거래일 거래량",
            ],
            "cache": {
                "updatedAt": updated_at,
                "source": "data/catalog.json + detailed snapshots + manual defaults",
                "status": "success",
                "version": str(SCHEMA_VERSION),
            },
            "count": len(eligible),
            "items": eligible,
        },
    )


def build_catalog(client: NasdaqClient) -> None:
    stocks_payload = client.get("screener/stocks", {"download": "true"})
    etfs_payload = client.get("screener/etf", {"download": "true"})
    stock_rows = stocks_payload.get("rows") or []
    etf_rows = (((etfs_payload.get("data") or {}).get("rows")) if isinstance(etfs_payload, dict) else None) or []
    rows: dict[str, dict[str, Any]] = {}
    for item in stock_rows:
        try:
            symbol = normalize_symbol(str(item.get("symbol") or ""))
        except ValueError:
            continue
        rows[symbol] = {
            "symbol": symbol,
            "name": item.get("name") or symbol,
            "type": "STOCK",
            "exchange": None,
            "currency": "USD",
            "country": item.get("country"),
            "sector": item.get("sector"),
            "industry": item.get("industry"),
            "marketCap": parse_number(item.get("marketCap")),
            "price": parse_number(item.get("lastsale")),
            "volume": parse_number(item.get("volume")),
        }
    for item in etf_rows:
        try:
            symbol = normalize_symbol(str(item.get("symbol") or ""))
        except ValueError:
            continue
        rows[symbol] = {
            "symbol": symbol,
            "name": item.get("companyName") or symbol,
            "type": "ETF",
            "exchange": None,
            "currency": "USD",
            "country": None,
            "sector": None,
            "industry": None,
            "marketCap": None,
            "price": parse_number(item.get("lastSalePrice")),
            "volume": parse_number(item.get("volume")),
        }
    for path in MARKET_DIR.glob("*.json"):
        snapshot = load_json(path, {})
        symbol = snapshot.get("symbol")
        if not symbol:
            continue
        quote_data = snapshot.get("quote") or {}
        liquidity = snapshot.get("liquidity") or {}
        existing = rows.get(symbol, {})
        rows[symbol] = {
            **existing,
            "symbol": symbol,
            "name": snapshot.get("name") or existing.get("name") or symbol,
            "type": snapshot.get("type") or existing.get("type"),
            "exchange": snapshot.get("exchange") or existing.get("exchange"),
            "currency": snapshot.get("currency") or existing.get("currency"),
            "country": snapshot.get("region") or existing.get("country"),
            "sector": snapshot.get("sector") or existing.get("sector"),
            "industry": snapshot.get("industry") or existing.get("industry"),
            "marketCap": quote_data.get("marketCap") or existing.get("marketCap"),
            "price": quote_data.get("price") or existing.get("price"),
            "volume": liquidity.get("value") or quote_data.get("averageVolume") or existing.get("volume"),
            "liquidityEligible": liquidity.get("qualifies"),
            "liquidityBasis": liquidity.get("basis"),
        }
    catalog = sorted(rows.values(), key=lambda item: (item["symbol"], item["name"]))
    write_json(
        CATALOG_PATH,
        {"schemaVersion": SCHEMA_VERSION, "updatedAt": utc_now(), "count": len(catalog), "items": catalog},
    )
    print(f"catalog: {len(catalog)} symbols")


def cached_symbols() -> list[str]:
    return sorted(path.stem.upper() for path in MARKET_DIR.glob("*.json")) if MARKET_DIR.exists() else []


def parse_requested_tickers(args: argparse.Namespace) -> list[str]:
    values: list[str] = []
    for raw in args.ticker or []:
        values.extend(re.split(r"[,\s]+", raw))
    if args.issue_title:
        match = re.search(r"\[DATA\]\s*([A-Z0-9.\-^, ]+)", args.issue_title.upper())
        if match:
            values.extend(re.split(r"[,\s]+", match.group(1)))
    if args.defaults:
        values.extend(load_json(DEFAULT_TICKERS_PATH, []))
    if args.refresh_cached:
        values.extend(cached_symbols())
    normalized: list[str] = []
    for value in values:
        if not value:
            continue
        try:
            symbol = normalize_symbol(value)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            continue
        if symbol not in normalized:
            normalized.append(symbol)
    return normalized[:200]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", action="append", help="Ticker or comma-separated tickers")
    parser.add_argument("--issue-title", help="Parse '[data] TICKER' from a GitHub issue title")
    parser.add_argument("--defaults", action="store_true", help="Build data/default-tickers.json")
    parser.add_argument("--refresh-cached", action="store_true", help="Refresh every existing data/market JSON")
    parser.add_argument("--catalog", action="store_true", help="Refresh the searchable symbol catalog")
    args = parser.parse_args()

    MARKET_DIR.mkdir(parents=True, exist_ok=True)
    client = NasdaqClient()
    failures: list[str] = []

    if args.catalog:
        try:
            build_catalog(client)
        except Exception as exc:  # keep an existing catalog on temporary failures
            failures.append(f"catalog: {exc}")

    for symbol in parse_requested_tickers(args):
        try:
            payload = build_one(client, symbol)
            write_json(MARKET_DIR / f"{symbol}.json", payload)
            print(f"{symbol}: {payload['type']} / {len(payload['history']['dates'])} days / OK")
        except Exception as exc:
            failures.append(f"{symbol}: {exc}")
            print(f"{symbol}: FAILED ({exc})", file=sys.stderr)
        time.sleep(0.35)

    update_manifest()
    build_liquidity_universe()
    if failures:
        print("\nFailures (existing cache files were preserved):", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
    if failures and not cached_symbols():
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
