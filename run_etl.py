#!/usr/bin/env python3
"""
全PJ ETL を順番に走らせて統合 ledger.db を更新。
Usage:
    python run_etl.py
"""
from __future__ import annotations
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from etl import ooi, fx, s4, crypto, stub

ADAPTERS = [
    ("ooi",    ooi.run),
    ("fx",     fx.run),
    ("s4",     s4.run),
    ("crypto", crypto.run),
    ("kochi",  stub.run_kochi),
    ("banei",  stub.run_banei),
    ("sonoda", stub.run_sonoda),
    ("kokura", stub.run_kokura),
]


def main() -> int:
    fails = 0
    print("=" * 56)
    print("ペーパー横断 ETL 開始")
    print("=" * 56)
    for name, fn in ADAPTERS:
        try:
            seen, added = fn()
            mark = "✅" if seen >= 0 else "⚠️"
            print(f"{mark} {name:8s} seen={seen:>6}  added={added:>6}")
        except Exception as e:
            fails += 1
            print(f"❌ {name:8s} ERROR: {e}")
            traceback.print_exc()
    print("=" * 56)
    print(f"完了 (失敗 {fails} 件)")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
