#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""根据 diagnose.py 的输出生成自包含 HTML 骨架（内联 SVG，无外部依赖）。

用法：
    python render_quickstart.py <数据文件> --diagnosis <输出目录>/diagnosis.json --out quickstart.html

说明：
    输出是版式起点，不是成品。KPI 与图表需按实际问题重选。
"""

from __future__ import annotations

import argparse
import html
import json
import os
import sys


# ---------------------------------------------------------------- 格式化

def esc(s) -> str:
    return html.escape(str(s), quote=True)


def fmt_num(v, digits=0) -> str:
    if v is None:
        return "—"
    try:
        if digits:
            return f"{v:,.{digits}f}"
        return f"{round(v):,}"
    except (TypeError, ValueError):
        return esc(v)


def fmt_compact(v) -> str:
    if v is None:
        return "0"
    if abs(v) >= 100000000:
        return f"{v / 100000000:.1f}亿"
    if abs(v) >= 10000:
        return f"{v / 10000:.1f}万"
    if abs(v) >= 1000:
        return f"{v / 1000:.1f}k"
    if abs(v) >= 10:
        return f"{v:.0f}"
    return f"{v:.2f}".rstrip("0").rstrip(".")


def short_date(d: str, monthly: bool) -> str:
    if monthly:
        return d[:7]
    return d[5:]


# ---------------------------------------------------------------- SVG

W = 1080
H = 360
PAD_L, PAD_R, PAD_T, PAD_B = 76, 28, 28, 40


def line_chart(points, monthly: bool) -> str:
    """points: [[label, value], ...]，label 为 ISO 日期或 yyyy-MM。"""
    if not points:
        return '<p class="empty">没有可绘制的时间序列</p>'

    values = [p[1] for p in points]
    vmax = max(values)
    vmin = min(values)
    top = vmax if vmax > 0 else 1
    plot_w = W - PAD_L - PAD_R
    plot_h = H - PAD_T - PAD_B
    n = len(points)
    step = plot_w / max(1, n - 1)

    def x(i):
        return PAD_L + i * step

    def y(v):
        return PAD_T + plot_h - (v / top) * plot_h if top else PAD_T + plot_h

    parts = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="时间趋势">']
    parts.append(f'<rect x="0" y="0" width="{W}" height="{H}" fill="#ffffff"/>')

    # 横向网格 + y 轴刻度
    for i in range(5):
        gy = PAD_T + plot_h * i / 4
        gv = top * (4 - i) / 4
        parts.append(f'<line x1="{PAD_L}" y1="{gy:.1f}" x2="{W - PAD_R}" y2="{gy:.1f}" stroke="#eef2f7" stroke-width="1"/>')
        parts.append(f'<text x="{PAD_L - 10}" y="{gy + 4:.1f}" text-anchor="end" class="axis">{fmt_compact(gv)}</text>')

    # 面积 + 折线
    line_pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, (_, v) in enumerate(points))
    area = f"{PAD_L},{PAD_T + plot_h} " + line_pts + f" {x(n - 1):.1f},{PAD_T + plot_h}"
    parts.append(f'<polygon points="{area}" fill="#2f87c9" opacity="0.08"/>')
    parts.append(f'<polyline points="{line_pts}" fill="none" stroke="#2f87c9" stroke-width="2.2" stroke-linejoin="round"/>')

    # 峰值标注
    pi = max(range(n), key=lambda i: points[i][1])
    px, py = x(pi), y(points[pi][1])
    parts.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="4" fill="#c0392b" stroke="#fff" stroke-width="2"/>')
    anchor = "end" if px > W * 0.72 else "start"
    dx = -8 if anchor == "end" else 8
    parts.append(
        f'<text x="{px + dx:.1f}" y="{py - 10:.1f}" text-anchor="{anchor}" class="anno">'
        f'峰值 {esc(short_date(points[pi][0], monthly))} · {fmt_num(points[pi][1])}</text>'
    )

    # x 轴标签（首、中、尾 + 1/3、2/3）
    idxs = sorted({0, n // 3, (2 * n) // 3, n - 1})
    for i in idxs:
        parts.append(
            f'<text x="{x(i):.1f}" y="{H - 14}" text-anchor="middle" class="axis">'
            f'{esc(short_date(points[i][0], monthly))}</text>'
        )

    # 基线
    parts.append(f'<line x1="{PAD_L}" y1="{PAD_T + plot_h}" x2="{W - PAD_R}" y2="{PAD_T + plot_h}" stroke="#d0d7e2" stroke-width="1"/>')
    parts.append("</svg>")
    return "".join(parts)


def bar_chart(rows) -> str:
    """rows: [[label, value, share], ...]，已排序。"""
    if not rows:
        return '<p class="empty">没有可分组的分类维度</p>'

    rows = rows[:10]
    row_h = 30
    height = max(200, row_h * len(rows) + 40)
    label_w = 170
    value_w = 96
    bar_max = W - label_w - value_w - 24
    vmax = max(r[1] for r in rows) or 1

    parts = [f'<svg viewBox="0 0 {W} {height}" role="img" aria-label="分类排行">']
    parts.append(f'<rect x="0" y="0" width="{W}" height="{height}" fill="#ffffff"/>')
    for i, (label, value, share) in enumerate(rows):
        cy = 16 + i * row_h
        bw = max(2.0, bar_max * (value / vmax))
        parts.append(f'<text x="{label_w - 12}" y="{cy + 15}" text-anchor="end" class="bar-label">{esc(label)}</text>')
        parts.append(f'<rect x="{label_w}" y="{cy + 2}" width="{bw:.1f}" height="18" rx="3" fill="#5470C6" opacity="{1 - i * 0.055:.2f}"/>')
        parts.append(
            f'<text x="{label_w + bw + 10:.1f}" y="{cy + 15}" class="bar-value">'
            f'{fmt_num(value)} · {share:.1%}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


# ---------------------------------------------------------------- HTML

CSS = """
:root{
  --bg:#f2f5fa; --card:#fff; --ink:#12325e; --text:#1d2939;
  --sub:#667085; --muted:#98a2b3; --line:#eef2f7; --axis:#d0d7e2;
  --primary:#2f87c9; --alert:#c0392b;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
  font-family:-apple-system,"Segoe UI","Microsoft YaHei","PingFang SC",sans-serif;
  font-size:13px;line-height:1.6}
.wrap{max-width:1440px;margin:0 auto;padding:24px}
header{padding:4px 4px 18px}
h1{margin:0 0 6px;font-size:24px;font-weight:700;color:var(--ink)}
.sub{color:var(--sub);font-size:13px}
.note{margin:0 0 18px;padding:10px 14px;border-left:3px solid var(--primary);
  background:#eaf4fc;color:#1b4b73;border-radius:0 8px 8px 0;font-size:12px}
.kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:14px;margin-bottom:18px}
.kpi{background:var(--card);border-radius:12px;padding:16px 18px;
  box-shadow:0 1px 2px rgba(16,24,40,.04)}
.kpi .k{font-size:12px;color:var(--sub);margin-bottom:6px}
.kpi .v{font-size:24px;font-weight:700;color:var(--ink);font-variant-numeric:tabular-nums}
.kpi .u{font-size:12px;color:var(--muted);margin-left:4px;font-weight:400}
.card{background:var(--card);border-radius:12px;padding:18px 20px;margin-bottom:16px;
  box-shadow:0 1px 2px rgba(16,24,40,.04)}
.card h2{margin:0 0 2px;font-size:15px;font-weight:600;color:var(--ink)}
.card .cap{margin:0 0 12px;font-size:12px;color:var(--sub)}
svg{width:100%;height:auto;display:block}
.axis{font-size:11px;fill:var(--muted)}
.anno{font-size:11px;fill:var(--alert)}
.bar-label{font-size:12px;fill:var(--text)}
.bar-value{font-size:11px;fill:var(--sub)}
.empty{color:var(--muted);padding:20px 0}
.flags{list-style:none;margin:0;padding:0}
.flags li{padding:9px 12px;border-left:3px solid var(--axis);background:#fafbfd;
  border-radius:0 6px 6px 0;margin-bottom:8px;font-size:12.5px}
.flags li.high{border-left-color:var(--alert)}
.flags li.mid{border-left-color:#e8a33d}
.flags li.low{border-left-color:var(--primary)}
.tag{display:inline-block;font-size:11px;color:#fff;border-radius:3px;
  padding:0 6px;margin-right:8px;vertical-align:1px}
.tag.high{background:var(--alert)} .tag.mid{background:#e8a33d} .tag.low{background:var(--primary)}
footer{color:var(--muted);font-size:11.5px;padding:8px 4px 24px}
@media (max-width:1100px){.kpis{grid-template-columns:repeat(3,1fr)}}
@media (max-width:680px){.kpis{grid-template-columns:repeat(2,1fr)}}
"""


def render(rep, source_name: str) -> str:
    k = rep["kpis"]
    t = rep["time"] or {}
    cats = rep["categorical"] or []
    breakdown = rep["breakdown_col"]
    rows = []
    if breakdown:
        for c in cats:
            if c["name"] == breakdown:
                rows = c["top"]
                break

    daily = rep["series"]["daily"]
    monthly_mode = len(daily) > 400
    points = rep["series"]["monthly"] if monthly_mode else daily
    gran = "月" if monthly_mode else "日"

    total = sum(v for _, v in daily) if daily else (rep["numeric"] or {}).get("mean", 0)
    day_count = max(1, t.get("distinct_days") or len(daily) or 1)
    avg = total / day_count
    peak = max(daily, key=lambda x: x[1]) if daily else ("—", 0)

    kpi_cards = [
        ("合计", fmt_num(total), "累计值" if not rep["numeric"] else f"列 {rep['meta']['value_col']}"),
        ("日均", fmt_num(avg), "按有数据天数"),
        ("峰值日", esc(peak[0] if daily else "—"), fmt_num(peak[1])),
        ("记录数", fmt_num(k["rows"]), f"{k['columns']} 列"),
        ("有数据天数", fmt_num(day_count), f"缺失 {t.get('missing_days', 0)} 天"),
    ]
    kpi_html = "".join(
        f'<div class="kpi"><div class="k">{esc(a)}</div>'
        f'<div class="v">{b}<span class="u">{esc(c)}</span></div></div>'
        for a, b, c in kpi_cards
    )

    flags = rep["flags"]
    level_cn = {"high": "高", "mid": "中", "low": "低"}
    if flags:
        flags_html = "".join(
            f'<li class="{f["level"]}"><span class="tag {f["level"]}">{level_cn.get(f["level"], "")}</span>'
            f'{esc(f["message"])}</li>'
            for f in flags
        )
    else:
        flags_html = '<li class="low"><span class="tag low">提示</span>未发现明显异常，仍需核对口径与能力边界。</li>'

    title = os.path.splitext(source_name)[0]
    range_text = f"{t.get('start', '—')} ~ {t.get('end', '—')}" if t else "未识别时间列"
    missing_note = f"，缺失 {t.get('missing_days', 0)} 天按 0 绘制" if t.get("missing_days") else ""

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc('快速诊断 · ' + title)}</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>{esc(title)} · 快速诊断视图</h1>
    <div class="sub">{esc(range_text)} · {fmt_num(k['rows'])} 行 · 按{gran}汇总 · 生成于本地脚本</div>
  </header>

  <div class="note">这是骨架页，不是成品。图表类型与模块顺序请按「问题类型 → 数据形态」重新选择；结论必须自己写。</div>

  <div class="kpis">{kpi_html}</div>

  <section class="card">
    <h2>{esc(gran + '度趋势')}</h2>
    <p class="cap">按{gran}汇总{esc(missing_note)}；峰值已标注。若为量级很小的长尾，考虑改看 TopN 或分布。</p>
    {line_chart(points, monthly_mode)}
  </section>

  <section class="card">
    <h2>{esc(breakdown or '无可用分类维度')} · Top 10</h2>
    <p class="cap">按该维度总量降序。类别超过 20 个应截断并归入「其他」；条形图不要用于表达份额迁移。</p>
    {bar_chart(rows)}
  </section>

  <section class="card">
    <h2>诊断提示</h2>
    <p class="cap">以下为脚本按默认阈值筛出的客观信号，需逐条确认原因后才能写进结论。</p>
    <ul class="flags">{flags_html}</ul>
  </section>

  <footer>由 scripts/render_quickstart.py 生成 · 数据截止 {esc(t.get('end', '—') if t else '—')} · 口径与能力边界需人工补充</footer>
</div>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser(description="根据诊断 JSON 生成自包含 HTML 骨架")
    ap.add_argument("input", nargs="?", help="原始数据文件（仅用于标题与核对）")
    ap.add_argument("--diagnosis", required=True, help="diagnose.py 生成的 diagnosis.json")
    ap.add_argument("--out", default="quickstart.html", help="输出 HTML 路径")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    if not os.path.exists(args.diagnosis):
        raise SystemExit(f"找不到诊断文件：{args.diagnosis}（先运行 diagnose.py）")

    with open(args.diagnosis, "r", encoding="utf-8") as f:
        rep = json.load(f)

    source_name = os.path.basename(args.input) if args.input else "数据集"
    html_text = render(rep, source_name)

    out_dir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html_text)

    size = os.path.getsize(args.out)
    print(f"已生成 {os.path.abspath(args.out)}（{size / 1024:.1f} KB）")
    print(f"图表 {granitor(rep)}")


def granitor(rep):
    n = len(rep["series"]["daily"])
    return "月度趋势 + Top10 条形" if n > 400 else "日度趋势 + Top10 条形"


if __name__ == "__main__":
    main()
