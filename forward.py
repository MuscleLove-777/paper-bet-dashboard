#!/usr/bin/env python3
"""
forward.py - フォワード検証ベット記録 CLI
================================================
108 ペーパー横断分析 PJ 向け。「これから走るレース」に対して
ペーパー賭けを ledger.db (forward_bets) に時系列で記録する。

bets テーブルが過去レースの後方検証(=back-test)であるのに対し、
forward_bets は live予想機能(045_predict_live.py 等)で出した予想を
未来発走に対して賭けて、数日後に結果が確定する前向き検証。

サブコマンド:
  record   : 賭け記録（発走前 or 直後）
  settle   : 結果照合（発走後、actual_top3 と payout を埋めて確定）
  list     : 記録済み一覧表示（--unsettled で未確定のみ）

使用例:
  python forward.py record --pj ooi --race-id 202604292011 \\
    --strategy S5_TRIO_BOX3 --model-version 045_v1 \\
    --bet-type 三連複 --combo 2-3-13 --stake 100 \\
    --note "羽田盃JpnⅠ、live予想初戦"

  python forward.py settle --race-id 202604292011 \\
    --actual-top3 11-13-6 --payout 0

  python forward.py list --unsettled
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from etl.base import connect  # noqa: E402  forward_bets DDL も含む

# ===== PJ → 各PJ DB（results / payouts 自動引き当て用）=====
# パスは absolute、日本語パス可。新PJ追加時はここに足す。
PJ_DB_MAP: dict[str, Path] = {
    "ooi": Path(r"C:/Users/atsus/000_ClaudeCode/045_大井競馬自動予想/data/ooi.db"),
    # 他PJは results/payouts スキーマが揃ったら順次追加（forward 自動引き当ては
    # 競馬系のみで十分。FX/Cryptoは payout を手動指定でも実害なし）
}


# ----------------- helpers -----------------

def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _normalize_combo(combo: str) -> str:
    """三連複の '2-3-13' を昇順 '2-3-13' に統一。
    payouts.combination とのマッチで順序差を吸収するため。
    単勝など 1要素はそのまま返す。"""
    if not combo:
        return combo
    parts = combo.split("-")
    try:
        nums = sorted(int(p) for p in parts)
        return "-".join(str(n) for n in nums)
    except ValueError:
        return combo


def _resolve_actual_top3(pj: str, race_id: str) -> str | None:
    """各PJ DB の results テーブルから 1-2-3着 を引く。"""
    db_path = PJ_DB_MAP.get(pj)
    if not db_path or not db_path.exists():
        return None
    con = sqlite3.connect(str(db_path))
    try:
        rows = con.execute(
            """
            SELECT horse_no FROM results
             WHERE race_id = ? AND finish_pos IN (1,2,3)
             ORDER BY finish_pos
            """,
            (race_id,),
        ).fetchall()
    finally:
        con.close()
    if len(rows) < 3:
        return None
    return "-".join(str(r[0]) for r in rows)


def _resolve_payout(pj: str, race_id: str, bet_type: str, combo: str) -> int | None:
    """各PJ DB の payouts から bet_type+combo 完全一致で payout 取得。
    マッチしなければ None（=結果はあったが当該combo外れ→payout=0扱いするのは
    呼び出し側の責任）。"""
    db_path = PJ_DB_MAP.get(pj)
    if not db_path or not db_path.exists():
        return None
    norm = _normalize_combo(combo)
    con = sqlite3.connect(str(db_path))
    try:
        rows = con.execute(
            "SELECT combination, payout FROM payouts WHERE race_id = ? AND bet_type = ?",
            (race_id, bet_type),
        ).fetchall()
    finally:
        con.close()
    for combination, payout in rows:
        if _normalize_combo(combination) == norm:
            return int(payout or 0)
    return None


# ----------------- subcommands -----------------

def cmd_record(args: argparse.Namespace) -> int:
    bet_date = args.bet_date or _today()
    combo = _normalize_combo(args.combo)
    placed_at = _now_iso()
    with connect() as con:
        try:
            con.execute(
                """
                INSERT INTO forward_bets
                  (pj, bet_date, race_id, strategy, model_version,
                   bet_type, combo, stake, placed_at, settled, note)
                VALUES (?,?,?,?,?,?,?,?,?,0,?)
                """,
                (
                    args.pj, bet_date, args.race_id, args.strategy,
                    args.model_version, args.bet_type, combo,
                    int(args.stake), placed_at, args.note,
                ),
            )
        except sqlite3.IntegrityError:
            print(f"[skip] already recorded: pj={args.pj} race={args.race_id} "
                  f"strategy={args.strategy} combo={combo}")
            return 0
    print(f"[ok] recorded forward bet: pj={args.pj} race={args.race_id} "
          f"strategy={args.strategy} type={args.bet_type} combo={combo} "
          f"stake={args.stake} placed_at={placed_at}")
    return 0


def cmd_settle(args: argparse.Namespace) -> int:
    settled_at = _now_iso()
    with connect() as con:
        rows = con.execute(
            """
            SELECT id, pj, race_id, strategy, bet_type, combo, stake, settled
              FROM forward_bets
             WHERE race_id = ?
            """,
            (args.race_id,),
        ).fetchall()

        if not rows:
            print(f"[err] no forward bet found for race_id={args.race_id}")
            return 2

        for fid, pj, race_id, strategy, bet_type, combo, stake, already in rows:
            if already and not args.force:
                print(f"[skip] id={fid} already settled (use --force to overwrite)")
                continue

            actual = args.actual_top3
            if actual is None:
                actual = _resolve_actual_top3(pj, race_id)
                if actual is None:
                    print(f"[err] id={fid} could not auto-resolve actual_top3 "
                          f"(pj={pj}, no results in pj DB). "
                          "Pass --actual-top3 explicitly.")
                    return 3
                print(f"[auto] id={fid} actual_top3={actual} from pj DB")

            if args.payout is not None:
                payout = int(args.payout)
            else:
                p = _resolve_payout(pj, race_id, bet_type, combo)
                if p is None:
                    print(f"[err] id={fid} could not auto-resolve payout "
                          f"(pj={pj} bet_type={bet_type} combo={combo} not in payouts table). "
                          "If the combo simply lost, pass --payout 0 explicitly.")
                    return 4
                payout = p
                print(f"[auto] id={fid} payout={payout} from pj DB")

            pnl = payout - int(stake)
            con.execute(
                """
                UPDATE forward_bets
                   SET settled=1, actual_top3=?, payout=?, pnl=?, settled_at=?
                 WHERE id=?
                """,
                (actual, payout, pnl, settled_at, fid),
            )
            print(f"[ok] settled id={fid} {pj}/{race_id}/{strategy}/{combo} "
                  f"actual={actual} payout={payout} pnl={pnl:+d}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    where = "WHERE settled = 0" if args.unsettled else ""
    with connect() as con:
        rows = con.execute(
            f"""
            SELECT id, pj, bet_date, race_id, strategy, bet_type, combo,
                   stake, settled, actual_top3, payout, pnl, placed_at
              FROM forward_bets {where}
             ORDER BY placed_at DESC
             LIMIT ?
            """,
            (args.limit,),
        ).fetchall()
    if not rows:
        print("(no forward bets)")
        return 0
    print(f"{'id':>4}  {'pj':<8} {'bet_date':<10} {'race_id':<14} "
          f"{'strategy':<18} {'type':<6} {'combo':<10} "
          f"{'stake':>6} {'sett':<4} {'actual':<10} {'payout':>7} {'pnl':>7}")
    for r in rows:
        (fid, pj, d, rid, strat, bt, combo, stake, settled,
         actual, payout, pnl, placed_at) = r
        print(f"{fid:>4}  {pj:<8} {d:<10} {rid:<14} "
              f"{strat:<18} {bt:<6} {combo:<10} "
              f"{stake:>6} {('yes' if settled else 'no'):<4} "
              f"{(actual or '-'):<10} "
              f"{(str(payout) if payout is not None else '-'):>7} "
              f"{(f'{pnl:+d}' if pnl is not None else '-'):>7}")
    return 0


# ----------------- entry -----------------

def main() -> int:
    ap = argparse.ArgumentParser(description="forward bet ledger CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("record", help="forward bet を記録（発走前 or 直後）")
    pr.add_argument("--pj", required=True)
    pr.add_argument("--race-id", required=True)
    pr.add_argument("--bet-date", default=None,
                    help="YYYY-MM-DD（省略時は今日）")
    pr.add_argument("--strategy", required=True)
    pr.add_argument("--model-version", default=None)
    pr.add_argument("--bet-type", required=True)
    pr.add_argument("--combo", required=True)
    pr.add_argument("--stake", type=int, required=True)
    pr.add_argument("--note", default=None)
    pr.set_defaults(func=cmd_record)

    ps = sub.add_parser("settle", help="forward bet の結果を埋める")
    ps.add_argument("--race-id", required=True)
    ps.add_argument("--actual-top3", default=None,
                    help="例 11-13-6（省略時は各PJ DB から自動引き当て）")
    ps.add_argument("--payout", type=int, default=None,
                    help="円。省略時は payouts テーブルから自動引き当て。"
                         "外れの場合は 0 を明示")
    ps.add_argument("--force", action="store_true",
                    help="既に settled でも上書きする")
    ps.set_defaults(func=cmd_settle)

    pl = sub.add_parser("list", help="forward bet 一覧表示")
    pl.add_argument("--unsettled", action="store_true",
                    help="未確定のみ表示")
    pl.add_argument("--limit", type=int, default=50)
    pl.set_defaults(func=cmd_list)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
