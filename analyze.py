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


# ===== forward_bets（前向き検証） =====
# bets テーブルとは独立。settled=1 のみ集計（未確定はカウントから除外）。

def forward_overall_kpi() -> dict:
    """forward_bets の累積 KPI（確定分のみ）。"""
    with connect() as con:
        n, stake, payout, pnl, wins, days = con.execute(
            """
            SELECT COUNT(*), SUM(stake), SUM(payout), SUM(pnl),
                   SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END),
                   COUNT(DISTINCT bet_date)
              FROM forward_bets WHERE settled = 1
            """
        ).fetchone()
        unsettled_n = con.execute(
            "SELECT COUNT(*) FROM forward_bets WHERE settled = 0"
        ).fetchone()[0]
    n = n or 0
    stake = stake or 0
    return {
        "bets_total": n,
        "unsettled_n": unsettled_n,
        "stake_total": stake,
        "payout_total": payout or 0,
        "pnl_total": pnl or 0,
        "roi_pct": round(((pnl or 0) / stake * 100.0) if stake else 0, 2),
        "win_rate_pct": round((wins / n * 100.0) if n else 0, 2),
        "active_days": days or 0,
    }


def forward_by_strategy() -> list[dict]:
    """戦略単位の forward 集計（確定分のみ）。bets 側の同戦略 ROI も並べて返す。"""
    with connect() as con:
        rows = con.execute(
            """
            SELECT pj, strategy,
                   COUNT(*)                                  AS n,
                   SUM(stake)                                AS stake,
                   SUM(payout)                               AS payout,
                   SUM(pnl)                                  AS pnl,
                   SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END)  AS wins,
                   MIN(bet_date)                             AS first_date,
                   MAX(bet_date)                             AS last_date
              FROM forward_bets
             WHERE settled = 1
             GROUP BY pj, strategy
             ORDER BY pj, strategy
            """
        ).fetchall()

        # bets 側の各 (pj, strategy) ROI を引いて backtest 比較に使う
        bt_rows = con.execute(
            f"""
            SELECT pj, strategy, SUM(stake), SUM(pnl), COUNT(*)
              FROM bets WHERE {NORMAL_FILTER}
             GROUP BY pj, strategy
            """
        ).fetchall()
    bt_map = {}
    for pj, st, s, p, n in bt_rows:
        bt_map[(pj, st)] = {
            "backtest_roi_pct": round(((p or 0) / s * 100.0) if s else 0, 2),
            "backtest_n": n,
        }

    out = []
    for r in rows:
        pj, strat, n, stake, payout, pnl, wins, fd, ld = r
        roi = (pnl / stake * 100.0) if stake else 0.0
        bt = bt_map.get((pj, strat), {"backtest_roi_pct": None, "backtest_n": 0})
        out.append({
            "pj": pj,
            "strategy": strat,
            "bets_n": n,
            "stake_total": stake or 0,
            "payout_total": payout or 0,
            "pnl_total": pnl or 0,
            "roi_pct": round(roi, 2),
            "win_rate_pct": round((wins / n * 100.0) if n else 0, 2),
            "first_date": fd,
            "last_date": ld,
            "backtest_roi_pct": bt["backtest_roi_pct"],
            "backtest_n": bt["backtest_n"],
        })
    return out


def forward_by_pj() -> list[dict]:
    """PJ単位の forward 集計（確定分のみ）。"""
    with connect() as con:
        rows = con.execute(
            """
            SELECT pj,
                   COUNT(*)        AS n,
                   SUM(stake)      AS stake,
                   SUM(payout)     AS payout,
                   SUM(pnl)        AS pnl,
                   COUNT(DISTINCT strategy) AS strategies,
                   MIN(bet_date)   AS first_date,
                   MAX(bet_date)   AS last_date
              FROM forward_bets
             WHERE settled = 1
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
            "stake_total": stake or 0,
            "payout_total": payout or 0,
            "pnl_total": pnl or 0,
            "roi_pct": round(((pnl or 0) / stake * 100.0) if stake else 0, 2),
            "strategies": strategies,
            "first_date": fd,
            "last_date": ld,
        })
    return out


def forward_recent(limit: int = 20) -> list[dict]:
    """直近 N 件（未確定含む、新しい順）。"""
    with connect() as con:
        rows = con.execute(
            """
            SELECT bet_date, pj, strategy, bet_type, combo, stake,
                   settled, actual_top3, payout, pnl, placed_at, model_version, note
              FROM forward_bets
             ORDER BY placed_at DESC
             LIMIT ?
            """,
            (limit,),
        ).fetchall()
    keys = ("bet_date", "pj", "strategy", "bet_type", "combo", "stake",
            "settled", "actual_top3", "payout", "pnl", "placed_at",
            "model_version", "note")
    return [dict(zip(keys, r)) for r in rows]


def to_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    print("=== KPI ===")
    print(to_json(overall_kpi()))
    print("\n=== PJ別 ===")
    print(to_json(per_pj_summary()))
    print("\n=== 戦略別 (top 12) ===")
    print(to_json(summary_by_strategy()[:12]))
