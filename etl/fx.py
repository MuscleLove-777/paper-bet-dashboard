"""
042_FXトレードボット ETL adapter
ソース: paper_trade.db (runs と trades)
- trades: 確定したクローズ済みポジション(まだゼロかも)
- runs:   日次状態(holdでも記録、サンプルとして残す)
"""
from __future__ import annotations
import sqlite3
from pathlib import Path

from .base import upsert_bets

SRC = Path(r"c:/Users/atsus/000_ClaudeCode/042_FXトレードボット/paper_trade.db")
PJ = "fx"
STRATEGY = "Breakout_20"  # 現在の唯一戦略


def run() -> tuple[int, int]:
    if not SRC.exists():
        return 0, 0
    rows = []
    con = sqlite3.connect(str(SRC))
    try:
        # trades: 確定エントリ。pnl はクローズ時のみ
        for t in con.execute(
            "SELECT entry_date, exit_date, direction, entry_price, exit_price, units, pnl FROM trades"
        ).fetchall():
            ent_date, exi_date, direction, ent, exi, units, pnl = t
            rows.append({
                "bet_date": (exi_date or ent_date)[:10],
                "strategy": STRATEGY,
                "race_id": f"{ent_date}_{direction}",
                "bet_type": "long" if (direction or 0) > 0 else "short",
                "combo": "AUDJPY",
                "stake": float(abs(units or 0)) * float(ent or 0),
                "payout": float(abs(units or 0)) * float(exi or 0) if exi else 0,
                "pnl": float(pnl or 0),
                "meta": None,
            })
        # runs: holdでもログを残す（実トレード無くても日次記録）
        for r in con.execute(
            "SELECT run_date, signal, position, equity, note FROM runs"
        ).fetchall():
            run_date, sig, pos, eq, note = r
            if sig == 0 and pos == 0:
                # holdは bet=0 のサンプル行として残す（pnl=0）
                rows.append({
                    "bet_date": run_date,
                    "strategy": STRATEGY,
                    "race_id": f"daily_{run_date}",
                    "bet_type": "hold",
                    "combo": "AUDJPY",
                    "stake": 0,
                    "payout": 0,
                    "pnl": 0,
                    "meta": f'{{"equity":{eq},"note":"{note or ""}"}}',
                })
    finally:
        con.close()
    return upsert_bets(PJ, rows)


if __name__ == "__main__":
    seen, added = run()
    print(f"[fx] seen={seen} added={added}")
