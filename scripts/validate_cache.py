#!/usr/bin/env python3
"""Offline integrity checks for committed market snapshots."""

from __future__ import annotations

import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MARKET = ROOT / "data" / "market"


def fail(message: str) -> None:
    raise AssertionError(message)


def main() -> None:
    paths = sorted(MARKET.glob("*.json"))
    if not paths:
        fail("no market snapshots")
    symbols: list[str] = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        symbol = payload.get("symbol")
        symbols.append(symbol)
        if payload.get("schemaVersion") != 2:
            fail(f"{symbol}: wrong schema")
        if symbol != path.stem:
            fail(f"{path.name}: symbol mismatch")
        history = payload.get("history") or {}
        dates, closes = history.get("dates") or [], history.get("close") or []
        if len(dates) != len(closes) or len(dates) < 200:
            fail(f"{symbol}: invalid history length")
        if dates != sorted(dates) or len(dates) != len(set(dates)):
            fail(f"{symbol}: dates are not unique ascending values")
        if any(not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0 for value in closes):
            fail(f"{symbol}: invalid close")
        if payload.get("type") == "STOCK":
            if not (payload.get("financials") or {}).get("years"):
                fail(f"{symbol}: missing annual financials")
            if not (payload.get("quote") or {}).get("marketCap"):
                fail(f"{symbol}: missing market cap")
        if payload.get("type") == "ETF":
            etf = payload.get("etf") or {}
            weights = [item.get("weight") for item in etf.get("topHoldings") or []]
            if any(not isinstance(value, (int, float)) or value <= 0 or value > 100 for value in weights):
                fail(f"{symbol}: invalid ETF holding weight")
            if weights and abs(sum(weights) - (etf.get("holdingsCoverage") or 0)) > 1e-6:
                fail(f"{symbol}: ETF coverage mismatch")

    manifest = json.loads((ROOT / "data" / "manifest.json").read_text(encoding="utf-8"))
    manifest_symbols = sorted(item["symbol"] for item in manifest.get("symbols") or [])
    if manifest.get("count") != len(paths) or manifest_symbols != sorted(symbols):
        fail("manifest does not match market files")
    catalog = json.loads((ROOT / "data" / "catalog.json").read_text(encoding="utf-8"))
    if catalog.get("count") != len(catalog.get("items") or []) or catalog.get("count", 0) < 1000:
        fail("catalog is missing or truncated")
    print(f"cache integrity OK: {len(paths)} detailed tickers / {catalog['count']} searchable tickers")


if __name__ == "__main__":
    main()
