"""
032_オートレースボット ETL adapter
ソース: db/autorace.sqlite3 / paper_trade_log
"""
from __future__ import annotations
import sqlite3
from pathlib import Path

from .base import upsert_bets

SRC = Path(r"c:/Users/atsus/000_ClaudeCode/032_オートレースボット/db/autorace.sqlite3")
PJ = "s4_autorace"


def run() -> tuple[int, int]:
    if not SRC.exists():
        return 0, 0
    rows = []
    con = sqlite3.connect(str(SRC))
    try:
        for r in con.execute(
            """
            SELECT race_id, car_no, bet_type, flag, bet, payout, pl,
                   model_version, decided_at
              FROM paper_trade_log
            """
        ).fetchall():
            race_id, car_no, bet_type, flag, bet, payout, pl, model_ver, decided_at = r
            bet_date = (decided_at or "")[:10] or "1970-01-01"
            rows.append({
                "bet_date": bet_date,
                "strategy": f"S4_{flag}",
                "race_id": race_id,
                "bet_type": bet_type or "place",
                "combo": str(car_no),
                "stake": float(bet or 0),
                "payout": float(payout or 0),
                "pnl": float(pl or 0),
                "meta": f'{{"model":"{model_ver}"}}',
            })
    finally:
        con.close()
    return upsert_bets(PJ, rows)


if __name__ == "__main__":
    seen, added = run()
    print(f"[s4] seen={seen} added={added}")
