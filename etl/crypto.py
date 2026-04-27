"""
006_仮想通貨ボット ETL adapter
ソース: paper.db / trades
"""
from __future__ import annotations
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .base import upsert_bets

SRC = Path(r"c:/Users/atsus/000_ClaudeCode/006_仮想通貨ボット/paper.db")
PJ = "crypto"


def run() -> tuple[int, int]:
    if not SRC.exists():
        return 0, 0
    rows = []
    con = sqlite3.connect(str(SRC))
    try:
        for r in con.execute(
            """
            SELECT id, strategy_id, ts, symbol, side, price, amount, fee, pnl, equity_after
              FROM trades
            """
        ).fetchall():
            tid, strat, ts, symbol, side, price, amount, fee, pnl, eq = r
            try:
                # tsはunix秒 or ms
                ts_int = int(ts)
                if ts_int > 10**12:
                    ts_int = ts_int // 1000
                bet_date = datetime.fromtimestamp(ts_int, tz=timezone.utc).strftime("%Y-%m-%d")
            except Exception:
                bet_date = "1970-01-01"
            rows.append({
                "bet_date": bet_date,
                "strategy": strat,
                "race_id": f"{symbol}_{ts}_{tid}",
                "bet_type": side,
                "combo": symbol,
                "stake": float(price or 0) * float(amount or 0),
                "payout": (float(price or 0) * float(amount or 0)) + float(pnl or 0)
                          if pnl is not None else 0,
                "pnl": float(pnl or 0),
                "meta": f'{{"fee":{fee or 0},"equity_after":{eq or 0}}}',
            })
    finally:
        con.close()
    return upsert_bets(PJ, rows)


if __name__ == "__main__":
    seen, added = run()
    print(f"[crypto] seen={seen} added={added}")
