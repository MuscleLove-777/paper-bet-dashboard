# 108 ペーパーベット横断分析

6PJ（大井競馬・FX・オートレースS4・Crypto・高知/ばんえい/園田/小倉）のペーパーベット結果を統合 sqlite に集約し、ダッシュボード＆週次方針レポを自動生成。

## アーキテクチャ

```
[各PJ] ─pull─→ [ledger.db]  ─→ [analyze.py] ─→ [publish.py] ─→ docs/index.html
                                                                  docs/reports/<date>.html
                                                                  ↓
                                                              GitHub Pages
```

- **ETL** (`run_etl.py`)：6PJのDB/CSVを読んで統合スキーマに upsert
- **集計** (`analyze.py`)：PJ別 / 戦略別 / 異常検出
- **公開** (`publish.py`)：横断ダッシュボード + 週次レポ（`--weekly` 時に `claude -p` で方針提案）

## 共通スキーマ

```sql
bets(pj, bet_date, strategy, race_id, bet_type, combo, stake, payout, pnl, meta)
UNIQUE(pj, bet_date, strategy, race_id, bet_type, combo)
```

## 使い方

```bash
# 日次（ETL→ダッシュボード再生成）
python run_etl.py
python publish.py

# 週次（ETL→ダッシュボード→claude -p で方針レポ）
python run_etl.py
python publish.py --weekly
```

## 公開URL
https://musclelove-777.github.io/paper-bet-dashboard/

## PJ別 adapter 状態

| PJ | adapter | 実データ | 件数 |
|---|---|---|---|
| 045 大井競馬 | etl/ooi.py | ✅ | 17,538 |
| 042 FX | etl/fx.py | ✅ | 2 |
| 032 オートレース S4 | etl/s4.py | ✅ | 358 |
| 006 仮想通貨 | etl/crypto.py | ✅ | 8 |
| 044 高知競馬 | etl/stub.py | 🕓 待機 | - |
| 046 ばんえい | etl/stub.py | 🕓 待機 | - |
| 047 園田 | etl/stub.py | 🕓 待機 | - |
| 031 小倉競輪 | etl/stub.py | 🕓 待機 | - |

ペーパー開始したPJはスタブを差し替えるだけで自動的にダッシュボードに乗る。

## 異常検出

`stake >= 1000万` のベットは「複利暴走 or データバグ」として正規集計から除外し、「⚠️ 異常検出」セクションに警告表示。実弾運用前のロジックチェック対象。

## 自動化

scheduled task:
- `Paper_Cross_Daily` — 毎日 06:00 / `run_etl.py` + `publish.py`（push まで自動）
- `Paper_Cross_Weekly` — 月曜 07:00 / `run_etl.py` + `publish.py --weekly`（claude で方針レポ生成）
- `Forward_Settle_Daily` — 毎日 07:00 / `scripts/auto_settle.py` で `forward_bets` の未確定を自動 settle

## フォワード検証自動化フロー

forward.py + ledger.db の `forward_bets` テーブルを使った日次フォワード検証パイプライン。

```
[17:30] 045/scripts/auto_live_predict.py        … 大井 R1〜R12 を S5_TRIO_BOX3 で予想 → forward_bets に record
                ↓
[06:00] Ooi_Keiba_Daily_Fetch                   … 結果 fetch (NAR公式) → 045/data/ooi.db
                ↓
[07:00] 108/scripts/auto_settle.py              … forward_bets 未確定を ooi.db results/payouts から自動 settle
                ↓
[06:00] Paper_Cross_Daily（翌日）               … 横断ダッシュボード再生成 → push
```

サンプル：1日12レース×月20開催 ≒ 月240件積み上がる。`stake=100` 円固定（絶対金額は画面非表示、PnL率のみ表示）。

```bash
# 手動デバッグ
python "C:\Users\atsus\000_ClaudeCode\045_大井競馬自動予想\scripts\auto_live_predict.py" --date 2026-04-29 --dry-run
python scripts/auto_settle.py --dry-run
python forward.py list --unsettled
```
