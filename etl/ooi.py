"""
045_大井競馬自動予想 ETL adapter
ソース: results/paper_trade/bets.csv
"""
from __future__ import annotations
import csv
import json
from pathlib import Path

from .base import upsert_bets

SRC = Path(r"c:/Users/atsus/000_ClaudeCode/045_大井競馬自動予想/results/paper_trade/bets.csv")
PJ = "ooi"


def run() -> tuple[int, int]:
    if not SRC.exists():
        return 0, 0
    rows = []
    with SRC.open(encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            rows.append({
                "bet_date": r["race_date"],
                "strategy": r["strategy"],
                "race_id": r["race_id"],
                "bet_type": r.get("bet_type"),
                "combo": r.get("combo"),
                "stake": r.get("stake") or 0,
                "payout": r.get("payout") or 0,
                "pnl": r.get("pnl") or 0,
                "meta": None,
            })
    return upsert_bets(PJ, rows)


if __name__ == "__main__":
    seen, added = run()
    print(f"[ooi] seen={seen} added={added}")
