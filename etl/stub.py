"""
ペーパー未着手PJ用のスタブ adapter。
- 044 高知競馬 (kochi)
- 046 ばんえい競馬 (banei)
- 047 兵庫競馬 (sonoda)
- 031 小倉ミッドナイト競輪 (kokura)

ペーパーベットの ledger ファイルが出来たらここに実装する。
今は run() を呼ばれても 0,0 を返すだけ（ETLパイプライン全体が落ちないように）。
"""
from __future__ import annotations


def run_kochi():  return (0, 0)
def run_banei():  return (0, 0)
def run_sonoda(): return (0, 0)
def run_kokura(): return (0, 0)
