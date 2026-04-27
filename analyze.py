#!/usr/bin/env python3
"""
ledger.db から戦略別の指標を集計する。
publish.py / weekly_report.py から import される土台。

提供する関数:
- summary_by_strategy(): 全戦略のKPI（横断比較表用）
- daily_pnl(pj, strategy): 日次PnLとequity曲線
- per_pj_summary(): PJ単位のロールアップ
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from etl.base import connect

# 1ベットで1000万円超 = 複利暴走 or データ異常（S8で実発覚）
ANOMALY_STAKE = 1.0e7
NORMAL_FILTER = "stake > 0 AND stake < {}".format(ANOMALY_STAKE)


def anomalies() -> list[dict]:
    """異常stake検出（複利発散/データバグ）。レポートで警告表示するため。"""
    with connect() as con:
        rows = con.execute(
            f"""
            SELECT pj, strategy, COUNT(*) AS n, MAX(stake) AS max_stake,
                   MIN(bet_date) AS first_date, MAX(bet_date) AS last_date
              FROM bets
             WHERE stake >= {ANOMALY_STAKE}
             GROUP BY pj, strategy
             ORDER BY max_stake DESC
            """
        ).fetchall()
    return [
        {"pj": r[0], "strategy": r[1], "anomaly_bets": r[2],
         "max_stake": r[3], "first_date": r[4], "last_date": r[5]}
        for r in rows
    ]


def summary_by_strategy(min_bets: int = 10) -> list[dict]:
    """戦略単位の集計（正常範囲stakeのみ）。"""
    with connect() as con:
        rows = con.execute(
            f"""
            SELECT
                pj,
                strategy,
                COUNT(*)                                  AS bets_n,
                SUM(stake)                                AS stake_total,
                SUM(payout)                               AS payout_total,
                SUM(pnl)                                  AS pnl_total,
                SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END)  AS wins,
                MIN(bet_date)                             AS first_date,
                MAX(bet_date)                             AS last_date
              FROM bets
             WHERE {NORMAL_FILTER}
             GROUP BY pj, strategy
            HAVING bets_n >= ?
             ORDER BY pnl_total DESC
            """,
            (min_bets,),
        ).fetchall()

    out = []
    for r in rows:
        pj, strat, n, stake, payout, pnl, wins, fd, ld = r
        roi = (pnl / stake * 100.0) if stake else 0.0
        win_rate = (wins / n * 100.0) if n else 0.0
        recovery = (payout / stake * 100.0) if stake else 0.0
        out.append({
            "pj": pj,
            "strategy": strat,
            "bets_n": n,
            "stake_total": round(stake or 0, 2),
            "payout_total": round(payout or 0, 2),
            "pnl_total": round(pnl or 0, 2),
            "roi_pct": round(roi, 2),
            "win_rate_pct": round(win_rate, 2),
            "recovery_pct": round(recovery, 2),
            "first_date": fd,
            "last_date": ld,
        })
    return out


def per_pj_summary() -> list[dict]:
    """PJ単位ロールアップ（正常範囲のみ）。"""
    with connect() as con:
        rows = con.execute(
            f"""
            SELECT pj,
                   COUNT(*)        AS bets_n,
                   SUM(stake)      AS stake,
                   SUM(payout)     AS payout,
                   SUM(pnl)        AS pnl,
                   COUNT(DISTINCT strategy) AS strategies,
                   MIN(bet_date)   AS first_date,
                   MAX(bet_date)   AS last_date
              FROM bets
             WHERE {NORMAL_FILTER}
             GROUP BY pj
             ORDER BY pnl DESC
            """
        ).fetchall()
    out = []
    for r in rows:
        pj, n, stake, payout, pnl, strategies, fd, ld = r
        out.append({
            "pj": pj,
            "bets_n": n,
            "stake_total": round(stake or 0, 2),
            "payout_total": round(payout or 0, 2),
            "pnl_total": round(pnl or 0, 2),
            "roi_pct": round((pnl / stake * 100.0) if stake else 0, 2),
            "strategies": strategies,
            "first_date": fd,
            "last_date": ld,
        })
    return out


def daily_equity(pj: str, strategy: str) -> list[dict]:
    """日次PnLと累積equity（初期残高=0からのデルタ、正常範囲のみ）"""
    with connect() as con:
        rows = con.execute(
            f"""
            SELECT bet_date, SUM(stake) AS stake, SUM(payout) AS payout, SUM(pnl) AS pnl
              FROM bets
             WHERE pj = ? AND strategy = ? AND {NORMAL_FILTER}
             GROUP BY bet_date
             ORDER BY bet_date
            """,
            (pj, strategy),
        ).fetchall()
    eq = 0.0
    out = []
    for d, stake, payout, pnl in rows:
        eq += pnl or 0
        out.append({
            "date": d,
            "stake": round(stake or 0, 2),
            "pnl": round(pnl or 0, 2),
            "equity": round(eq, 2),
        })
    return out


def overall_kpi() -> dict:
    with connect() as con:
        n, stake, payout, pnl, days = con.execute(
            f"""
            SELECT COUNT(*), SUM(stake), SUM(payout), SUM(pnl),
                   COUNT(DISTINCT bet_date)
              FROM bets WHERE {NORMAL_FILTER}
            """
        ).fetchone()
    return {
        "bets_total": n or 0,
        "stake_total": round(stake or 0, 2),
        "payout_total": round(payout or 0, 2),
        "pnl_total": round(pnl or 0, 2),
        "roi_pct": round((pnl / stake * 100.0) if stake else 0, 2),
        "active_days": days or 0,
    }


def to_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    print("=== KPI ===")
    print(to_json(overall_kpi()))
    print("\n=== PJ別 ===")
    print(to_json(per_pj_summary()))
    print("\n=== 戦略別 (top 12) ===")
    print(to_json(summary_by_strategy()[:12]))
