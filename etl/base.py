"""
統合ledger基盤。
6PJ共通スキーマで全ペーパーベット結果を集約する sqlite。
各PJのETL adapter は upsert_bets() を呼ぶだけでいい。
"""
from __future__ import annotations
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "ledger.db"


SCHEMA = """
CREATE TABLE IF NOT EXISTS bets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    pj          TEXT    NOT NULL,         -- 'ooi' | 'fx' | 's4' | 'crypto' | ...
    bet_date    TEXT    NOT NULL,         -- YYYY-MM-DD
    strategy    TEXT    NOT NULL,         -- 'S1','Breakout_20','strategy_a' ...
    race_id     TEXT    NOT NULL,         -- レース識別子 or 取引ID（FX等は date+strat）
    bet_type    TEXT,                     -- 単勝/place/long/short/...
    combo       TEXT,                     -- 馬番/車番/サイド
    stake       REAL    NOT NULL DEFAULT 0,
    payout      REAL    NOT NULL DEFAULT 0,
    pnl         REAL    NOT NULL DEFAULT 0,
    meta        TEXT,                     -- JSON 文字列
    ingested_at TEXT    NOT NULL,
    UNIQUE(pj, bet_date, strategy, race_id, bet_type, combo)
);
CREATE INDEX IF NOT EXISTS idx_bets_pj_date  ON bets(pj, bet_date);
CREATE INDEX IF NOT EXISTS idx_bets_strategy ON bets(strategy);

CREATE TABLE IF NOT EXISTS etl_runs (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    pj        TEXT NOT NULL,
    ran_at    TEXT NOT NULL,
    rows_seen INTEGER NOT NULL,
    rows_added INTEGER NOT NULL,
    note      TEXT
);
"""


@contextmanager
def connect():
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(LEDGER))
    con.executescript(SCHEMA)
    try:
        yield con
        con.commit()
    finally:
        con.close()


def upsert_bets(pj: str, rows: list[dict]) -> tuple[int, int]:
    """
    rows: dict with keys: bet_date, strategy, race_id, bet_type, combo, stake, payout, pnl, meta(optional)
    Returns: (seen, added)
    """
    if not rows:
        return 0, 0
    now = datetime.now().isoformat(timespec="seconds")
    added = 0
    with connect() as con:
        cur = con.cursor()
        for r in rows:
            try:
                cur.execute(
                    """
                    INSERT INTO bets
                      (pj, bet_date, strategy, race_id, bet_type, combo,
                       stake, payout, pnl, meta, ingested_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        pj,
                        r["bet_date"],
                        r["strategy"],
                        str(r["race_id"]),
                        r.get("bet_type") or "",
                        str(r.get("combo") or ""),
                        float(r.get("stake") or 0),
                        float(r.get("payout") or 0),
                        float(r.get("pnl") or 0),
                        r.get("meta"),
                        now,
                    ),
                )
                added += 1
            except sqlite3.IntegrityError:
                pass  # 重複スキップ
        cur.execute(
            "INSERT INTO etl_runs (pj, ran_at, rows_seen, rows_added, note) VALUES (?,?,?,?,?)",
            (pj, now, len(rows), added, None),
        )
    return len(rows), added


def latest_runs() -> list[dict]:
    with connect() as con:
        rows = con.execute(
            """
            SELECT pj, ran_at, rows_seen, rows_added
              FROM etl_runs
             ORDER BY ran_at DESC LIMIT 50
            """
        ).fetchall()
    return [
        dict(zip(("pj", "ran_at", "rows_seen", "rows_added"), r)) for r in rows
    ]
