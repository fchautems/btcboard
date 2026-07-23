from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data.json"
SATS = 100_000_000

# Points officiels publiés par Strategy. Les actions sont ajustées du split 10:1.
DISCLOSURES = [
    {"date": "2020-12-31", "btc": 70469, "shares": 124_510_000},
    {"date": "2021-12-31", "btc": 124391, "shares": 149_234_000},
    {"date": "2022-12-31", "btc": 132500, "shares": 156_113_000},
    {"date": "2023-12-31", "btc": 189150, "shares": 207_636_000},
    {"date": "2024-12-31", "btc": 447470, "shares": 281_735_000},
    {"date": "2025-12-31", "btc": 672500, "shares": 344_897_000},
    {"date": "2026-03-31", "btc": 762099, "shares": 378_834_000},
    {"date": "2026-05-25", "btc": 843738, "bps": 220900},
    {"date": "2026-06-14", "btc": 846842, "shares": 386_052_000},
]

HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (compatible; Strategy-BTC-Dashboard/1.0)",
    "Origin": "https://www.strategy.com",
    "Referer": "https://www.strategy.com/",
}


def to_number(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "").replace("$", "").strip())
    except ValueError:
        return None


def disclosure_rows():
    rows = []
    for item in DISCLOSURES:
        row = dict(item)
        if not row.get("bps"):
            row["bps"] = row["btc"] / row["shares"] * SATS
        rows.append(row)
    return rows


def fetch_live_bps():
    response = requests.get(
        "https://api.strategy.com/btc/bitcoinKpis",
        headers=HEADERS,
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    results = payload.get("results", {})
    bps = to_number(results.get("satsPerShare"))
    holdings = to_number(results.get("btcHoldings"))
    if not bps:
        raise RuntimeError("Strategy API did not return satsPerShare")
    timestamp = payload.get("timestamp") or datetime.now(timezone.utc).isoformat()
    return {
        "date": pd.Timestamp(timestamp).date().isoformat(),
        "bps": bps,
        "btc": round(holdings) if holdings else None,
        "live": True,
    }


def close_series(symbol: str):
    frame = yf.Ticker(symbol).history(
        start="2020-08-10",
        interval="1d",
        auto_adjust=True,
        actions=False,
    )
    if frame.empty or "Close" not in frame:
        raise RuntimeError(f"No market history returned for {symbol}")
    series = pd.to_numeric(frame["Close"], errors="coerce").dropna()
    series.index = pd.to_datetime(series.index).tz_localize(None).normalize()
    series.name = symbol
    return series


def main():
    disclosures = disclosure_rows()
    live_error = None
    try:
        live = fetch_live_bps()
        disclosures = [x for x in disclosures if x["date"] != live["date"]]
        disclosures.append(live)
    except Exception as exc:
        live_error = str(exc)

    disclosures.sort(key=lambda x: x["date"])

    mstr = close_series("MSTR")
    btc = close_series("BTC-USD")
    prices = pd.concat([mstr, btc], axis=1).sort_index()
    prices["BTC-USD"] = prices["BTC-USD"].ffill()
    prices = prices.dropna(subset=["MSTR", "BTC-USD"]).reset_index()
    prices.columns = ["date", "mstr", "btc"]

    ddf = pd.DataFrame(disclosures)
    ddf["date"] = pd.to_datetime(ddf["date"])
    merged = pd.merge_asof(
        prices.sort_values("date"),
        ddf[["date", "bps"]].sort_values("date"),
        on="date",
        direction="backward",
    ).dropna(subset=["bps"])

    merged["marketShares"] = merged["btc"] / merged["mstr"]
    merged["backingShares"] = SATS / merged["bps"]
    merged["multiple"] = merged["backingShares"] / merged["marketShares"]

    history = []
    for row in merged.itertuples(index=False):
        history.append({
            "date": row.date.date().isoformat(),
            "mstr": round(float(row.mstr), 4),
            "btc": round(float(row.btc), 2),
            "bps": round(float(row.bps), 2),
            "marketShares": round(float(row.marketShares), 4),
            "backingShares": round(float(row.backingShares), 4),
            "multiple": round(float(row.multiple), 5),
        })

    latest = history[-1]
    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "latest": latest,
        "disclosures": [
            {
                "date": x["date"],
                "bps": round(float(x["bps"]), 2),
                "btc": x.get("btc"),
                "shares": x.get("shares"),
                "live": bool(x.get("live")),
            }
            for x in disclosures
        ],
        "history": history,
        "warnings": [live_error] if live_error else [],
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {OUT}: {len(history)} market sessions, {len(disclosures)} BPS points")


if __name__ == "__main__":
    main()
