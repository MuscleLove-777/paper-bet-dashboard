#!/usr/bin/env python3
"""auto_settle.py

毎朝 07:00 に forward_bets で settled=0 の全件を、対応PJ DB の results/payouts から
自動引き当てて settle する。

処理:
  1. forward_bets WHERE settled=0 を全件抽出
  2. 各 race_id ごとに、対応する PJ DB(現状 ooi のみ)を見て:
     - results に1-3着が揃っていれば actual_top3 を引ける
     - payouts に bet_type+combo の combination が載っていれば payout 取得
       無ければ「外れ→payout=0」扱い（forward.py の _resolve_payout の意味的に）
  3. 両方揃っていれば forward.py settle で確定
  4. データ未確定(=06:00 fetch 未到達 or レース後すぐ等)はスキップ

使い方:
    python scripts/auto_settle.py
    python scripts/auto_settle.py --dry-run

注: Ooi_Keiba_Daily_Fetch (06:00) が完了した後の 07:00 に走る前提。
"""
from __future__ import annotations

import argparse
import sys
import sqlite3
import subprocess
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from forward import PJ_DB_MAP, _normalize_combo  # noqa: E402

LEDGER_DB = ROOT / "ledger.db"
FORWARD_PY = ROOT / "forward.py"
PYTHON_EXE = r"C:\Users\atsus\AppData\Local\Python\pythoncore-3.14-64\python.exe"


def _backup(p: Path, tag: str) -> None:
    if not p.exists():
        return
    bak = p.with_suffix(p.suffix + f".bak_{tag}")
    try:
        bak.write_bytes(p.read_bytes())
        print(f"[backup] {p.name} → {bak.name}")
    except Exception as e:
        print(f"[warn] backup failed: {e}")


def _list_unsettled() -> list[dict]:
    if not LEDGER_DB.exists():
        return []
    with sqlite3.connect(str(LEDGER_DB)) as con:
        rows = con.execute(
            """
            SELECT id, pj, race_id, strategy, bet_type, combo
              FROM forward_bets
             WHERE settled = 0
             ORDER BY race_id, id
            """
        ).fetchall()
    return [
        {"id": r[0], "pj": r[1], "race_id": r[2], "strategy": r[3],
         "bet_type": r[4], "combo": r[5]}
        for r in rows
    ]


def _race_is_finalized(pj: str, race_id: str, bet_type: str) -> tuple[bool, str | None]:
    """対応PJ DB が当該race_id について results(1〜3着)とpayouts(bet_type)を持つか。
    Returns: (is_ready, reason_if_not)"""
    db = PJ_DB_MAP.get(pj)
    if db is None or not db.exists():
        return False, f"PJ DB未対応 or 未作成: pj={pj}"
    con = sqlite3.connect(str(db))
    try:
        n_top3 = con.execute(
            "SELECT COUNT(*) FROM results WHERE race_id=? AND finish_pos IN (1,2,3)",
            (race_id,),
        ).fetchone()[0]
        if n_top3 < 3:
            return False, f"results未確定 (top3 rows={n_top3})"
        n_payouts = con.execute(
            "SELECT COUNT(*) FROM payouts WHERE race_id=? AND bet_type=?",
            (race_id, bet_type),
        ).fetchone()[0]
        # 注: bet_type に該当 combination が無ければ「外れ」確定なので OK 判定
        # results 揃ってる時点で ready とみなす
        return True, None
    finally:
        con.close()


def _settle(race_id: str, dry_run: bool) -> int:
    cmd = [PYTHON_EXE, str(FORWARD_PY), "settle", "--race-id", race_id]
    if dry_run:
        print(f"[dry-run] would run: {' '.join(cmd)}")
        return 0
    # forward.settle の cmd_settle は payout 自動引きで「外れ combo→未マッチ」を
    # 検出するとエラー code 4 を返してしまう。--payout 0 を fallback で渡す手も
    # あるが、まずは自動引きで試す → 失敗したら --payout 0 で再試行する。
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if res.stdout:
        print(res.stdout.rstrip())
    if res.stderr:
        print(res.stderr.rstrip(), file=sys.stderr)
    if res.returncode == 4:
        # 外れ combo パターン: payout=0 を明示
        print(f"  [retry] race={race_id} 外れ可能性 → --payout 0 で再試行")
        cmd2 = cmd + ["--payout", "0"]
        res2 = subprocess.run(cmd2, capture_output=True, text=True, encoding="utf-8")
        if res2.stdout:
            print(res2.stdout.rstrip())
        if res2.stderr:
            print(res2.stderr.rstrip(), file=sys.stderr)
        return res2.returncode
    return res.returncode


def main() -> int:
    ap = argparse.ArgumentParser(description="auto settle forward_bets from PJ DB")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    print("=== auto_settle ===")
    if not LEDGER_DB.exists():
        print(f"[err] ledger.db 未作成: {LEDGER_DB}")
        return 1

    unsettled = _list_unsettled()
    if not unsettled:
        print("[info] 未確定 forward_bets なし。終了。")
        return 0

    # race_id 単位に集約（同一race_idで複数戦略が来ても settle は race_id 単位で動く）
    by_race: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in unsettled:
        by_race[(r["pj"], r["race_id"])].append(r)
    print(f"[info] 未確定: {len(unsettled)}件 / {len(by_race)}レース")

    # バックアップ
    if not args.dry_run:
        _backup(LEDGER_DB, tag="auto_settle")

    n_ok = 0
    n_skip = 0
    n_err = 0
    handled_race_ids: set[str] = set()
    for (pj, race_id), bets in by_race.items():
        if race_id in handled_race_ids:
            continue
        handled_race_ids.add(race_id)
        # bet_type は先頭のもので確定確認 (実用上 race_id+bet_type=三連複で十分)
        bet_type = bets[0]["bet_type"]
        ready, reason = _race_is_finalized(pj, race_id, bet_type)
        if not ready:
            print(f"[skip] race={race_id} pj={pj}: {reason}")
            n_skip += 1
            continue
        rc = _settle(race_id, dry_run=args.dry_run)
        if rc == 0:
            n_ok += 1
        else:
            print(f"[err] settle failed race={race_id} rc={rc}")
            n_err += 1

    print()
    print(f"=== 完了: settled={n_ok}, skipped={n_skip}, error={n_err} ===")
    return 0 if n_err == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
