#!/usr/bin/env python3
"""
ledger.db を読んで docs/index.html （横断ダッシュボード）を生成。
オプション: --weekly で claude -p に方針提案レポMD/HTMLも生成して docs/reports/ に追加。

Usage:
    python publish.py                # ダッシュボードのみ更新
    python publish.py --weekly       # 週次レポも生成
"""
from __future__ import annotations
import argparse
import html
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
DOCS = ROOT / "docs"
REPORTS = DOCS / "reports"

sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import analyze


def fmt_yen(v) -> str:
    if v is None:
        return "-"
    return f"¥{int(round(v)):,}"


def fmt_pct(v) -> str:
    if v is None:
        return "-"
    color = "+" if v >= 0 else ""
    return f"{color}{v:.2f}%"


def equity_svg(daily: list[dict], width: int = 320, height: int = 90) -> str:
    """累積equityの簡易折れ線SVG。"""
    if not daily:
        return '<svg width="320" height="90"></svg>'
    eqs = [d["equity"] for d in daily]
    lo, hi = min(eqs + [0]), max(eqs + [0])
    span = (hi - lo) or 1
    n = len(daily)
    pts = []
    for i, d in enumerate(daily):
        x = (i / max(n - 1, 1)) * (width - 4) + 2
        y = height - 4 - ((d["equity"] - lo) / span) * (height - 8)
        pts.append(f"{x:.1f},{y:.1f}")
    color = "#22a06b" if eqs[-1] >= 0 else "#d9534f"
    zero_y = height - 4 - ((0 - lo) / span) * (height - 8)
    return (
        f'<svg viewBox="0 0 {width} {height}" preserveAspectRatio="none" '
        f'style="width:100%; height:{height}px; background:#f7f3ed; border-radius:6px;">'
        f'<line x1="0" y1="{zero_y:.1f}" x2="{width}" y2="{zero_y:.1f}" '
        f'stroke="#bbb" stroke-dasharray="3,3" stroke-width="1"/>'
        f'<polyline fill="none" stroke="{color}" stroke-width="2" points="{" ".join(pts)}"/>'
        f'</svg>'
    )


def render_forward_section() -> str:
    """フォワード検証累積成績セクション。
    収入額(絶対金額)は画面表示しない方針 → 比率と件数のみ。
    """
    fkpi = analyze.forward_overall_kpi()
    fstrats = analyze.forward_by_strategy()
    fpjs = analyze.forward_by_pj()
    recent = analyze.forward_recent(limit=20)

    # データなし
    if fkpi["bets_total"] == 0 and fkpi["unsettled_n"] == 0:
        return f'''
        <section class="card forward">
          <h2>🚀 フォワード検証累積成績</h2>
          <p class="hint">live予想機能で打った forward bet はまだ記録されていません。
          <code>python forward.py record ...</code> で記録開始。</p>
        </section>
        '''

    # KPIブロック（金額は非表示、ROI/件数/的中率/未確定数のみ）
    overall_cls = "pos" if fkpi["roi_pct"] >= 0 else "neg"
    kpi_block = f'''
    <div class="kpi-grid">
      <div class="kpi-cell">
        <div class="label">累積件数(確定)</div>
        <div class="big">{fkpi["bets_total"]:,}</div>
      </div>
      <div class="kpi-cell">
        <div class="label">未確定</div>
        <div class="big">{fkpi["unsettled_n"]:,}</div>
      </div>
      <div class="kpi-cell">
        <div class="label">forward ROI</div>
        <div class="big {overall_cls}">{fmt_pct(fkpi["roi_pct"])}</div>
      </div>
      <div class="kpi-cell">
        <div class="label">的中率</div>
        <div class="big">{fkpi["win_rate_pct"]:.1f}%</div>
      </div>
      <div class="kpi-cell">
        <div class="label">アクティブ日数</div>
        <div class="num">{fkpi["active_days"]}</div>
      </div>
    </div>
    '''

    # 戦略別小計＋backtest 比較
    strat_rows = ""
    for s in fstrats:
        roi_cls = "pos" if s["roi_pct"] >= 0 else "neg"
        bt_pct = s["backtest_roi_pct"]
        if bt_pct is None:
            delta_html = '<span class="dim">backtest n/a</span>'
        else:
            diff = s["roi_pct"] - bt_pct
            diff_cls = "pos" if diff >= 0 else "neg"
            delta_html = (
                f'<span class="dim">backtest {fmt_pct(bt_pct)} '
                f'(n={s["backtest_n"]:,})</span> '
                f'<strong class="{diff_cls}">Δ{fmt_pct(diff)}</strong>'
            )
        strat_rows += f'''
        <tr>
          <td><span class="pj-tag">{html.escape(s["pj"])}</span></td>
          <td><strong>{html.escape(s["strategy"])}</strong></td>
          <td class="num">{s["bets_n"]:,}</td>
          <td class="num">{s["win_rate_pct"]:.1f}%</td>
          <td class="num {roi_cls}">{fmt_pct(s["roi_pct"])}</td>
          <td>{delta_html}</td>
        </tr>
        '''
    strat_table = ""
    if strat_rows:
        strat_table = f'''
        <h3 class="sub">戦略別（forward 確定分）</h3>
        <table>
          <thead><tr>
            <th>PJ</th><th>戦略</th><th>件数</th><th>的中率</th>
            <th>forward ROI</th><th>backtest との差分</th>
          </tr></thead>
          <tbody>{strat_rows}</tbody>
        </table>
        '''

    # PJ別小計
    pj_rows = ""
    for p in fpjs:
        roi_cls = "pos" if p["roi_pct"] >= 0 else "neg"
        pj_rows += f'''
        <tr>
          <td><span class="pj-tag">{html.escape(p["pj"])}</span></td>
          <td class="num">{p["bets_n"]:,}</td>
          <td class="num">{p["strategies"]}</td>
          <td class="num {roi_cls}">{fmt_pct(p["roi_pct"])}</td>
          <td><span class="dim">{p["first_date"]} 〜 {p["last_date"]}</span></td>
        </tr>
        '''
    pj_table = ""
    if pj_rows:
        pj_table = f'''
        <h3 class="sub">PJ別（forward 確定分）</h3>
        <table>
          <thead><tr>
            <th>PJ</th><th>件数</th><th>戦略数</th><th>forward ROI</th><th>期間</th>
          </tr></thead>
          <tbody>{pj_rows}</tbody>
        </table>
        '''

    # 直近20件明細
    rec_rows = ""
    for r in recent:
        if not r["settled"]:
            cls = "unsettled"
            payout_disp = '<span class="badge">未確定</span>'
            pnl_disp = "-"
            actual_disp = r["actual_top3"] or "-"
        else:
            cls = ""
            pnl = r["pnl"] or 0
            cls_pnl = "pos" if pnl >= 0 else "neg"
            payout_disp = f'{int(r["payout"] or 0):,}'
            pnl_disp = f'<span class="{cls_pnl}">{pnl:+,}</span>'
            actual_disp = r["actual_top3"] or "-"
        rec_rows += f'''
        <tr class="{cls}">
          <td>{html.escape(r["bet_date"] or "-")}</td>
          <td><span class="pj-tag">{html.escape(r["pj"])}</span></td>
          <td>{html.escape(r["strategy"])}</td>
          <td>{html.escape(r["bet_type"] or "-")}</td>
          <td>{html.escape(r["combo"] or "-")}</td>
          <td class="num">{int(r["stake"] or 0):,}</td>
          <td>{html.escape(actual_disp)}</td>
          <td class="num">{payout_disp}</td>
          <td class="num">{pnl_disp}</td>
        </tr>
        '''
    recent_table = f'''
    <h3 class="sub">直近 {len(recent)} 件</h3>
    <table>
      <thead><tr>
        <th>発走日</th><th>PJ</th><th>戦略</th><th>券種</th><th>combo</th>
        <th>stake</th><th>actual top3</th><th>payout</th><th>PnL</th>
      </tr></thead>
      <tbody>{rec_rows}</tbody>
    </table>
    <p class="hint">未確定行は <code>forward.py settle</code> で結果確定後に集計対象。
    backtest ROI とのΔが「過学習度合い」の目安。3ヶ月で N=30〜50 溜まったら実弾GO/NOGO判断。</p>
    '''

    return f'''
    <section class="card forward">
      <h2>🚀 フォワード検証累積成績</h2>
      <p class="hint">live予想で打った（=未来発走の）ペーパーベットの累積成績。
      bets テーブル（=後方検証）とは独立集計。確定分(<code>settled=1</code>)のみが ROI/件数に反映されます。
      金額の絶対値は内部DBにのみ保持し、画面では比率/件数のみ表示。</p>
      {kpi_block}
      {strat_table}
      {pj_table}
      {recent_table}
    </section>
    '''


def render_dashboard(weekly_reports: list[Path]) -> str:
    kpi = analyze.overall_kpi()
    pjs = analyze.per_pj_summary()
    strats = analyze.summary_by_strategy()
    anoms = analyze.anomalies()
    forward_html = render_forward_section()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # PJ別カード
    pj_cards = ""
    for p in pjs:
        roi_cls = "pos" if p["roi_pct"] >= 0 else "neg"
        pj_cards += f'''
        <div class="pj-card">
          <h3>{html.escape(p["pj"])}</h3>
          <div class="pj-pnl {roi_cls}">{fmt_yen(p["pnl_total"])}</div>
          <div class="pj-roi {roi_cls}">ROI {fmt_pct(p["roi_pct"])}</div>
          <div class="pj-meta">
            {p["bets_n"]:,} bets / {p["strategies"]} strats<br>
            stake {fmt_yen(p["stake_total"])}<br>
            <span class="dim">{p["first_date"]} 〜 {p["last_date"]}</span>
          </div>
        </div>
        '''

    # 戦略別ランキング行 + equity曲線
    rows = ""
    for s in strats:
        eq = analyze.daily_equity(s["pj"], s["strategy"])
        roi_cls = "pos" if s["roi_pct"] >= 0 else "neg"
        rows += f'''
        <tr>
          <td><span class="pj-tag">{html.escape(s["pj"])}</span></td>
          <td><strong>{html.escape(s["strategy"])}</strong></td>
          <td class="num">{s["bets_n"]:,}</td>
          <td class="num">{s["win_rate_pct"]:.1f}%</td>
          <td class="num {roi_cls}">{fmt_pct(s["roi_pct"])}</td>
          <td class="num {roi_cls}">{fmt_yen(s["pnl_total"])}</td>
          <td class="chart">{equity_svg(eq)}</td>
        </tr>
        '''

    # 異常検出
    anom_html = ""
    if anoms:
        anom_rows = "".join(
            f'<tr><td>{html.escape(a["pj"])}</td><td>{html.escape(a["strategy"])}</td>'
            f'<td class="num">{a["anomaly_bets"]}</td>'
            f'<td class="num">{a["max_stake"]:.2e}</td>'
            f'<td>{a["first_date"]}〜{a["last_date"]}</td></tr>'
            for a in anoms
        )
        anom_html = f'''
        <section class="card warn">
          <h2>⚠️ 異常検出 ({len(anoms)})</h2>
          <p class="hint">stake≥1000万のベットを検出。複利発散・データ品質バグの可能性。
          実弾運用の前に該当戦略のロジック見直し必須。</p>
          <table>
            <thead><tr><th>PJ</th><th>戦略</th><th>件数</th><th>最大stake</th><th>期間</th></tr></thead>
            <tbody>{anom_rows}</tbody>
          </table>
        </section>
        '''

    # 週次レポ一覧
    weekly_html = ""
    if weekly_reports:
        items = "".join(
            f'<li><a href="reports/{r.name}">{r.stem}</a></li>'
            for r in sorted(weekly_reports, reverse=True)[:12]
        )
        weekly_html = f'''
        <section class="card">
          <h2>📝 週次方針レポ</h2>
          <ul class="reports">{items}</ul>
        </section>
        '''

    overall_cls = "pos" if kpi["pnl_total"] >= 0 else "neg"

    return f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>ペーパーベット 横断ダッシュボード</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<link rel="stylesheet" href="style.css">
</head>
<body>
<div class="wrap">
  <header>
    <h1>📊 ペーパーベット 横断ダッシュボード</h1>
    <div class="updated">最終更新: {now}</div>
  </header>

  <section class="kpi card">
    <div class="kpi-grid">
      <div class="kpi-cell">
        <div class="label">総PnL</div>
        <div class="big {overall_cls}">{fmt_yen(kpi["pnl_total"])}</div>
      </div>
      <div class="kpi-cell">
        <div class="label">総ROI</div>
        <div class="big {overall_cls}">{fmt_pct(kpi["roi_pct"])}</div>
      </div>
      <div class="kpi-cell">
        <div class="label">ベット数</div>
        <div class="big">{kpi["bets_total"]:,}</div>
      </div>
      <div class="kpi-cell">
        <div class="label">アクティブ日数</div>
        <div class="big">{kpi["active_days"]}</div>
      </div>
      <div class="kpi-cell">
        <div class="label">ステーク総額</div>
        <div class="num">{fmt_yen(kpi["stake_total"])}</div>
      </div>
      <div class="kpi-cell">
        <div class="label">払戻総額</div>
        <div class="num">{fmt_yen(kpi["payout_total"])}</div>
      </div>
    </div>
  </section>

  {anom_html}

  <section class="card">
    <h2>🎯 PJ別サマリ ({len(pjs)})</h2>
    <div class="pj-grid">{pj_cards}</div>
  </section>

  <section class="card">
    <h2>🏆 戦略別ランキング ({len(strats)})</h2>
    <table>
      <thead><tr>
        <th>PJ</th><th>戦略</th><th>件数</th><th>勝率</th>
        <th>ROI</th><th>PnL</th><th>累積equity</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>
    <p class="hint">※ 1ベット1000万超のstakeは異常として除外集計</p>
  </section>

  {forward_html}

  {weekly_html}

  <footer>
    <p>Generated by 108_ペーパー横断分析 / Powered by Claude Code</p>
  </footer>
</div>
</body>
</html>
"""


CSS = """
* { box-sizing: border-box; }
body {
  margin: 0; font-family: 'Noto Sans JP', -apple-system, sans-serif;
  background: #f5efe6; color: #2a2018;
}
.wrap { max-width: 1100px; margin: 0 auto; padding: 18px 14px 60px; }
header {
  background: linear-gradient(135deg, #2a3a55, #44607f);
  color: #fff; border-radius: 12px;
  padding: 18px 22px; margin-bottom: 14px;
  box-shadow: 0 2px 6px rgba(0,0,0,0.15);
}
header h1 { margin: 0; font-size: 22px; }
header .updated { font-size: 12px; opacity: 0.8; margin-top: 4px; }
.card {
  background: #fff; border-radius: 12px;
  padding: 18px 20px; margin-bottom: 14px;
  box-shadow: 0 2px 6px rgba(0,0,0,0.06);
}
.card h2 { margin: 0 0 12px; font-size: 16px; color: #2a3a55; }
.card.warn { background: #fff7e6; border-left: 4px solid #d97a1a; }
.kpi-grid {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 12px;
}
.kpi-cell { padding: 8px 4px; }
.kpi-cell .label { font-size: 11px; color: #6b5b48; }
.kpi-cell .big { font-size: 26px; font-weight: 800; margin-top: 2px; }
.kpi-cell .num { font-size: 17px; font-weight: 700; margin-top: 2px; }
.pos { color: #1f8a5b; }
.neg { color: #c8423b; }
.pj-grid {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 12px;
}
.pj-card {
  background: #faf6ee; border-radius: 8px; padding: 12px 14px;
  border: 1px solid #e8dfca;
}
.pj-card h3 { margin: 0 0 6px; font-size: 14px; color: #2a3a55; }
.pj-pnl { font-size: 22px; font-weight: 800; }
.pj-roi { font-size: 13px; font-weight: 700; }
.pj-meta { font-size: 11px; color: #6b5b48; margin-top: 6px; line-height: 1.5; }
.dim { color: #8a7a64; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { padding: 8px 6px; border-bottom: 1px solid #ece4d2; vertical-align: middle; }
th { text-align: left; background: #f7f3ed; font-size: 12px; color: #6b5b48; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
td.chart { width: 320px; }
.pj-tag {
  display: inline-block; background: #2a3a55; color: #fff;
  padding: 2px 7px; border-radius: 99px; font-size: 11px; font-weight: 700;
}
.hint { font-size: 11px; color: #8a7a64; margin: 8px 0 0; }
.reports { margin: 0; padding: 0 0 0 18px; }
.reports li { margin-bottom: 6px; font-size: 14px; }
.reports a { color: #2a3a55; text-decoration: none; font-weight: 600; }
.reports a:hover { text-decoration: underline; }
footer { text-align: center; font-size: 11px; color: #8a7a64; margin-top: 24px; }
.card.forward {
  border-left: 4px solid #2a3a55;
  background: linear-gradient(180deg, #fff 0%, #f3f6fb 100%);
}
.card.forward h2 { color: #2a3a55; }
.card.forward h3.sub {
  font-size: 13px; color: #44607f; margin: 18px 0 6px;
  padding-bottom: 4px; border-bottom: 1px dashed #c8d1e0;
}
.card.forward .kpi-grid { margin-bottom: 8px; }
tr.unsettled td { background: #fff8d6; }
.badge {
  display: inline-block; background: #d97a1a; color: #fff;
  padding: 1px 7px; border-radius: 99px; font-size: 11px; font-weight: 700;
}
@media (max-width: 700px) {
  td.chart { display: none; }
}
"""


# ===== claude -p で週次レポ生成 =====
WEEKLY_PROMPT = """あなたは公営ギャンブル＆FX/Crypto系のペーパー戦略を冷静に評価する分析家。
以下の集計JSONから「今週のハイライト」「方針提案」を3〜6セクションでまとめろ。

# 制約
- 結論ファースト。「Aを止めろ／Bは増やせ／Cは寝かせろ」のような断定推奨をする
- ROIだけでなく win_rate / 件数 / 期間も判断材料に入れる
- 件数が極端に少ない戦略は「サンプル不足」と明示して結論を保留してもよい
- 異常検出があれば必ず冒頭で警告
- 出力は Markdown 本文のみ。表を1〜2個入れてOK。前後の挨拶不要

# 集計データ
```json
{data}
```
"""


def gen_weekly_report() -> Path:
    REPORTS.mkdir(parents=True, exist_ok=True)
    payload = {
        "kpi": analyze.overall_kpi(),
        "by_pj": analyze.per_pj_summary(),
        "by_strategy": analyze.summary_by_strategy(),
        "anomalies": analyze.anomalies(),
    }
    prompt = WEEKLY_PROMPT.format(data=json.dumps(payload, ensure_ascii=False, indent=2))
    print("[claude] generating weekly report...", flush=True)
    proc = subprocess.run(
        ["claude", "-p", prompt],
        capture_output=True, text=True, timeout=240,
        encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude failed: {proc.stderr[:400]}")
    md = proc.stdout.strip()

    today = datetime.now().strftime("%Y-%m-%d")
    out = REPORTS / f"{today}.html"
    body = _md_to_html(md)
    page = f"""<!doctype html>
<html lang="ja"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>週次方針レポ {today}</title>
<link rel="stylesheet" href="../style.css">
<style>
.report {{ background:#fff; padding:24px; border-radius:12px;
  box-shadow:0 2px 6px rgba(0,0,0,0.06); }}
.report h1, .report h2, .report h3 {{ color: #2a3a55; }}
.report h1 {{ font-size: 22px; }}
.report h2 {{ font-size: 17px; margin-top: 22px; padding-bottom: 6px; border-bottom: 2px solid #ece4d2;}}
.report h3 {{ font-size: 14px; margin-top: 16px; }}
.report table {{ font-size: 13px; }}
.report code {{ background: #f7f3ed; padding: 1px 5px; border-radius: 3px; }}
</style>
</head>
<body><div class="wrap">
<p><a href="../">← ダッシュボードに戻る</a></p>
<div class="report">
<h1>📝 週次方針レポ {today}</h1>
{body}
</div>
</div></body></html>
"""
    out.write_text(page, encoding="utf-8")
    print(f"[ok] {out}")
    return out


def _md_to_html(md: str) -> str:
    """軽量Markdown→HTML変換（h1-3, リスト, テーブル, 段落）"""
    lines = md.split("\n")
    out = []
    in_table = False
    in_list = False
    for ln in lines:
        s = ln.rstrip()
        # table
        if "|" in s and s.lstrip().startswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            is_sep = all(set(c) <= set("-:") for c in cells if c)
            if is_sep:
                continue
            tag = "th" if not in_table else "td"
            if not in_table:
                out.append("<table>")
                in_table = True
            row = "".join(f"<{tag}>{html.escape(c)}</{tag}>" for c in cells)
            out.append(f"<tr>{row}</tr>")
            continue
        else:
            if in_table:
                out.append("</table>")
                in_table = False

        if s.startswith("### "):
            if in_list: out.append("</ul>"); in_list=False
            out.append(f"<h3>{html.escape(s[4:])}</h3>")
        elif s.startswith("## "):
            if in_list: out.append("</ul>"); in_list=False
            out.append(f"<h2>{html.escape(s[3:])}</h2>")
        elif s.startswith("# "):
            if in_list: out.append("</ul>"); in_list=False
            out.append(f"<h1>{html.escape(s[2:])}</h1>")
        elif s.lstrip().startswith(("- ", "* ")):
            if not in_list: out.append("<ul>"); in_list=True
            out.append(f"<li>{html.escape(s.lstrip()[2:])}</li>")
        elif s.strip() == "":
            if in_list: out.append("</ul>"); in_list=False
            out.append("")
        else:
            if in_list: out.append("</ul>"); in_list=False
            out.append(f"<p>{html.escape(s)}</p>")
    if in_list: out.append("</ul>")
    if in_table: out.append("</table>")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weekly", action="store_true", help="claude -p で週次方針レポも生成")
    args = ap.parse_args()

    DOCS.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    (DOCS / "style.css").write_text(CSS, encoding="utf-8")
    (DOCS / ".nojekyll").write_text("", encoding="utf-8")

    if args.weekly:
        gen_weekly_report()

    reports = list(REPORTS.glob("*.html"))
    (DOCS / "index.html").write_text(render_dashboard(reports), encoding="utf-8")
    print(f"[ok] dashboard: {DOCS / 'index.html'}")


if __name__ == "__main__":
    main()
