#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据诊断脚本：读 CSV / TSV / XLSX，输出客观统计与可疑点。

用法：
    python diagnose.py <数据文件> --out <输出目录> [--date-col 列名] [--value-col 列名]

输出：
    <输出目录>/diagnosis.md    人读报告
    <输出目录>/diagnosis.json  聚合结果，供 render_quickstart.py 使用

依赖：Python 3.9+ 标准库；读取 .xlsx 需要 openpyxl（可选）。
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import statistics
import sys
from collections import Counter
from datetime import date, datetime, timedelta

NULL_TOKENS = {"", "-", "--", "null", "none", "n/a", "na", "nan", "\\n", "暂无", "无"}
DATE_RE = re.compile(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})")
NUM_CLEAN_RE = re.compile(r"[,\s¥$￥]")
VALUE_HINTS = (
    "amount", "revenue", "sales", "gmv", "price", "qty", "quantity", "count",
    "num", "total", "value", "金额", "销售额", "收入", "数量", "销量", "单量",
    "件数", "台数", "次数", "时长", "费用", "成本", "利润", "激活",
)
DATE_HINTS = ("date", "day", "time", "日期", "时间", "daytime")


# ---------------------------------------------------------------- 读入

def load_table(path: str) -> tuple[list[str], list[list[str]]]:
    ext = os.path.splitext(path)[1].lower()
    if ext in (".csv", ".tsv", ".txt"):
        return _load_delimited(path, ext)
    if ext in (".xlsx", ".xlsm"):
        return _load_xlsx(path)
    raise SystemExit(f"不支持的文件类型：{ext}（支持 .csv / .tsv / .xlsx / .xlsm）")


def _load_delimited(path: str, ext: str) -> tuple[list[str], list[list[str]]]:
    raw = None
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            with open(path, "r", encoding=enc, newline="") as f:
                raw = f.read()
            break
        except UnicodeDecodeError:
            continue
    if raw is None:
        raise SystemExit("无法解码文件，请另存为 UTF-8 后重试")

    sample = raw[:8192]
    delimiter = "\t" if ext == ".tsv" else ","
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
        delimiter = dialect.delimiter
    except csv.Error:
        pass

    reader = list(csv.reader(raw.splitlines(), delimiter=delimiter))
    reader = [r for r in reader if any(cell.strip() for cell in r)]
    if not reader:
        raise SystemExit("文件为空")
    header = [h.strip() or f"col_{i + 1}" for i, h in enumerate(reader[0])]
    rows = [r for r in reader[1:]]
    return header, rows


def _load_xlsx(path: str) -> tuple[list[str], list[list[str]]]:
    try:
        import openpyxl  # type: ignore
    except ImportError:
        raise SystemExit("读取 .xlsx 需要 openpyxl：python -m pip install openpyxl\n"
                         "或先在 Excel 中另存为 CSV 再运行。")
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    data = []
    for row in ws.iter_rows(values_only=True):
        if row is None:
            continue
        data.append(["" if v is None else str(v) for v in row])
    wb.close()
    data = [r for r in data if any(c.strip() for c in r)]
    if not data:
        raise SystemExit("工作表为空")
    header = [h.strip() or f"col_{i + 1}" for i, h in enumerate(data[0])]
    return header, data[1:]


# ---------------------------------------------------------------- 类型

def is_null(v: str) -> bool:
    return v is None or v.strip().lower() in NULL_TOKENS


def to_number(v: str):
    s = NUM_CLEAN_RE.sub("", str(v).strip())
    if s.endswith("%"):
        try:
            return float(s[:-1]) / 100.0
        except ValueError:
            return None
    try:
        return float(s)
    except ValueError:
        return None


def to_date(v: str):
    s = str(v).strip()
    m = DATE_RE.match(s)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def infer_types(header, rows):
    n = len(rows)
    info = []
    for i, name in enumerate(header):
        col = [r[i] if i < len(r) else "" for r in rows]
        present = [c for c in col if not is_null(c)]
        total_present = len(present)
        numeric = [to_number(c) for c in present]
        date_vals = [to_date(c) for c in present]
        num_ratio = sum(1 for x in numeric if x is not None) / total_present if total_present else 0
        date_ratio = sum(1 for x in date_vals if x is not None) / total_present if total_present else 0
        if date_ratio >= 0.9:
            ctype = "date"
        elif num_ratio >= 0.9:
            ctype = "number"
        elif num_ratio > 0.1 or date_ratio > 0.1:
            ctype = "mixed"
        else:
            ctype = "text"
        uniques = len({c.strip() for c in present})
        info.append({
            "name": name,
            "index": i,
            "type": ctype,
            "null_ratio": round(1 - (total_present / n), 4) if n else 0,
            "unique": uniques,
            "numeric_ratio": round(num_ratio, 4),
            "date_ratio": round(date_ratio, 4),
        })
    return info


# ---------------------------------------------------------------- 统计

def percentile(sorted_vals, p):
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * p
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return sorted_vals[int(k)]
    return sorted_vals[lo] * (hi - k) + sorted_vals[hi] * (k - lo)


def numeric_stats(values):
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    s = sorted(vals)
    n = len(s)
    mean = sum(s) / n
    std = statistics.pstdev(s) if n > 1 else 0.0
    pos_total = sum(v for v in s if v > 0)
    top_n = max(1, math.ceil(n * 0.01))
    top_sum = sum(sorted((v for v in s if v > 0), reverse=True)[:top_n])
    return {
        "count": n,
        "min": round(s[0], 4),
        "p25": round(percentile(s, 0.25), 4),
        "median": round(percentile(s, 0.50), 4),
        "p75": round(percentile(s, 0.75), 4),
        "p90": round(percentile(s, 0.90), 4),
        "p99": round(percentile(s, 0.99), 4),
        "max": round(s[-1], 4),
        "mean": round(mean, 4),
        "std": round(std, 4),
        "cv": round(std / mean, 4) if mean else None,
        "zero_ratio": round(sum(1 for v in s if v == 0) / n, 4),
        "negative": sum(1 for v in s if v < 0),
        "top1pct_share": round(top_sum / pos_total, 4) if pos_total > 0 else None,
    }


def pick_date_col(columns):
    best, best_score = None, -1
    for c in columns:
        score = 0
        if c["type"] == "date":
            score += 100
        elif c["type"] == "mixed" and c["date_ratio"] > 0.5:
            score += 40
        if any(h in c["name"].lower() for h in DATE_HINTS):
            score += 10
        if score > best_score:
            best, best_score = c, score
    return best if best_score > 0 else None


def pick_value_col(columns):
    nums = [c for c in columns if c["type"] == "number"]
    if not nums:
        return None

    def score(c):
        s = 0
        if any(h in c["name"].lower() for h in VALUE_HINTS):
            s += 20
        if c["unique"] > 1:
            s += 5
        return s

    # 名称命中相同时，取取值更丰富的那一列（通常是金额，而不是件数）
    return max(nums, key=lambda c: (score(c), c["unique"]))


def key_candidates(header, rows, columns, date_col):
    n = len(rows)
    results = []
    for c in columns:
        if c["unique"] <= 1:
            continue
        idx = c["index"]
        vals = [r[idx] if idx < len(r) else "" for r in rows]
        dup = 1 - (len(set(vals)) / n) if n else 0
        results.append({
            "columns": [c["name"]],
            "unique": len(set(vals)),
            "duplicate_rate": round(dup, 4),
        })

    if date_col:
        d_idx = date_col["index"]
        cats = [c for c in columns if c["type"] == "text" and 1 < c["unique"] <= 2000]
        cats = sorted(cats, key=lambda c: c["unique"])[:6]
        for c in cats:
            idx = c["index"]
            keys = [(r[d_idx] if d_idx < len(r) else "", r[idx] if idx < len(r) else "") for r in rows]
            dup = 1 - (len(set(keys)) / n) if n else 0
            results.append({
                "columns": [date_col["name"], c["name"]],
                "unique": len(set(keys)),
                "duplicate_rate": round(dup, 4),
            })

    # 只保留重复率较低的前几个候选，按列数少优先、重复率低优先
    results.sort(key=lambda x: (x["duplicate_rate"], len(x["columns"])))
    return results[:6]


def time_stats(dates):
    ds = sorted(set(d for d in dates if d))
    if not ds:
        return None
    start, end = ds[0], ds[-1]
    calendar_days = (end - start).days + 1
    present = set(ds)
    missing = []
    cur = start
    while cur <= end:
        if cur not in present:
            missing.append(cur.isoformat())
        cur += timedelta(days=1)
    gaps = [(ds[i] - ds[i - 1]).days - 1 for i in range(1, len(ds))] or [0]
    last = end
    days_in_month = (date(last.year + (last.month == 12), (last.month % 12) + 1, 1) - timedelta(days=1)).day
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "distinct_days": len(ds),
        "calendar_days": calendar_days,
        "missing_days": missing,
        "missing_ratio": round(len(missing) / calendar_days, 4) if calendar_days else 0,
        "max_gap_days": max(gaps),
        "partial_last_month": last.day < days_in_month,
    }


def daily_series(dates, values):
    acc = {}
    for d, v in zip(dates, values):
        if d is None or v is None:
            continue
        acc[d] = acc.get(d, 0.0) + v
    if not acc:
        return []
    start, end = min(acc), max(acc)
    out, cur = [], start
    while cur <= end:
        out.append([cur.isoformat(), round(acc.get(cur, 0.0), 4)])
        cur += timedelta(days=1)
    return out


def monthly_series(series):
    acc = {}
    for d, v in series:
        acc[d[:7]] = acc.get(d[:7], 0.0) + v
    return [[k, round(acc[k], 4)] for k in sorted(acc)]


# ---------------------------------------------------------------- 主流程

def build_report(header, rows, columns, date_col, value_col, source_name="dataset"):
    n = len(rows)

    # 日期
    tstats, dseries, mseries = None, [], []
    if date_col:
        d_idx = date_col["index"]
        dates = [to_date(r[d_idx] if d_idx < len(r) else "") for r in rows]
        tstats = time_stats(dates)
        if value_col:
            v_idx = value_col["index"]
            vals = [to_number(r[v_idx] if v_idx < len(r) else "") for r in rows]
            dseries = daily_series(dates, vals)
            mseries = monthly_series(dseries)

    # 数值
    vstats = None
    if value_col:
        v_idx = value_col["index"]
        vstats = numeric_stats([to_number(r[v_idx] if v_idx < len(r) else "") for r in rows])

    # 分类
    cats = []
    for c in columns:
        if c["type"] not in ("text", "mixed") or c["unique"] > 60:
            continue
        idx = c["index"]
        counter = Counter(((r[idx] if idx < len(r) else "").strip() or "（空）") for r in rows)
        total = sum(counter.values()) or 1
        top = counter.most_common(12)
        cats.append({
            "name": c["name"],
            "unique": c["unique"],
            "top": [[k, v, round(v / total, 4)] for k, v in top],
            "top1_share": round(top[0][1] / total, 4) if top else 0,
            "top5_share": round(sum(v for _, v in top[:5]) / total, 4),
        })

    keys = key_candidates(header, rows, columns, date_col)

    # 标记
    flags = []
    best = keys[0] if keys else None
    if best and best["duplicate_rate"] > 0.005:
        flags.append({"level": "high", "code": "duplicate_key",
                      "message": f"候选主键 {best['columns']} 重复率 {best['duplicate_rate']:.1%}，需先确认粒度"})
    if tstats:
        if tstats["missing_ratio"] > 0.05:
            flags.append({"level": "high", "code": "missing_days",
                          "message": f"缺失 {len(tstats['missing_days'])} 天（{tstats['missing_ratio']:.1%}），先问原因，不要默认补 0"})
        if tstats["max_gap_days"] > 7:
            flags.append({"level": "mid", "code": "gap",
                          "message": f"最大断档 {tstats['max_gap_days']} 天，可能数据源中断"})
        if tstats["partial_last_month"]:
            flags.append({"level": "mid", "code": "partial_period",
                          "message": "最后一个月不完整，月度对比需按日均或标注部分周期"})
    if vstats:
        if vstats["negative"]:
            flags.append({"level": "high", "code": "negative",
                          "message": f"{vstats['negative']} 条负值，可能是退款/冲销，应单列而非直接求和"})
        if vstats["top1pct_share"] is not None and vstats["top1pct_share"] > 0.5:
            flags.append({"level": "mid", "code": "long_tail",
                          "message": f"Top1% 记录贡献 {vstats['top1pct_share']:.1%}，强长尾，图表用 TopN"})
        if vstats["median"] and abs(vstats["mean"] / vstats["median"]) > 1.5:
            flags.append({"level": "mid", "code": "skewed",
                          "message": f"均值/中位数 = {vstats['mean'] / vstats['median']:.2f}，右偏，描述用中位数"})
        if vstats["cv"] and vstats["cv"] > 1:
            flags.append({"level": "mid", "code": "volatile",
                          "message": f"CV = {vstats['cv']:.2f}，波动大，月汇总会掩盖脉冲，建议补日粒度"})
        if vstats["zero_ratio"] > 0.6:
            flags.append({"level": "low", "code": "sparse",
                          "message": f"零值占比 {vstats['zero_ratio']:.1%}，稀疏数据，考虑热力图或分面"})
    if dseries:
        vals = sorted(v for _, v in dseries)
        med = percentile(vals, 0.5) or 0
        peak = max(dseries, key=lambda x: x[1])
        if med > 0 and peak[1] > med * 5:
            flags.append({"level": "high", "code": "pulse",
                          "message": f"峰值日 {peak[0]} 为日中位数的 {peak[1] / med:.1f} 倍，疑似一次性脉冲而非趋势"})
    for c in columns:
        if c["null_ratio"] > 0.05:
            flags.append({"level": "mid", "code": "nulls",
                          "message": f"列「{c['name']}」空值 {c['null_ratio']:.1%}，需确认是未采集还是不存在"})
        if c["type"] == "mixed":
            flags.append({"level": "mid", "code": "mixed_type",
                          "message": f"列「{c['name']}」类型混杂（数值 {c['numeric_ratio']:.0%} / 日期 {c['date_ratio']:.0%}），清洗后再统计"})
    for c in cats:
        if c["top1_share"] > 0.8 and c["unique"] > 1:
            flags.append({"level": "low", "code": "concentrated",
                          "message": f"列「{c['name']}」首位占比 {c['top1_share']:.1%}，高度集中，注意单点依赖"})

    order = {"high": 0, "mid": 1, "low": 2}
    flags.sort(key=lambda f: order.get(f["level"], 3))

    # 选一个分组维度用于图表
    breakdown = None
    if cats:
        usable = [c for c in cats if 2 <= c["unique"] <= 25]
        if usable:
            breakdown = min(usable, key=lambda c: (abs(c["unique"] - 8), -c["top1_share"]))
        else:
            breakdown = cats[0]

    kpis = {
        "rows": n,
        "columns": len(header),
        "start": tstats["start"] if tstats else None,
        "end": tstats["end"] if tstats else None,
        "days": tstats["distinct_days"] if tstats else None,
        "missing_days": len(tstats["missing_days"]) if tstats else None,
    }

    return {
        "meta": {
            "source": source_name,
            "rows": n,
            "columns": len(header),
            "date_col": date_col["name"] if date_col else None,
            "value_col": value_col["name"] if value_col else None,
        },
        "kpis": kpis,
        "columns": columns,
        "key_candidates": keys,
        "time": tstats,
        "numeric": vstats,
        "categorical": cats,
        "breakdown_col": breakdown["name"] if breakdown else None,
        "series": {"daily": dseries, "monthly": mseries},
        "flags": flags,
    }


def to_markdown(rep):
    m = rep["meta"]
    lines = [
        f"# 数据诊断报告",
        "",
        f"- 文件：`{m['source']}`",
        f"- 规模：{m['rows']:,} 行 × {m['columns']} 列",
        f"- 日期列：`{m['date_col'] or '未识别'}`；数值列：`{m['value_col'] or '未识别'}`",
        "",
    ]

    t = rep["time"]
    if t:
        lines += [
            "## 时间",
            "",
            f"- 区间：{t['start']} ~ {t['end']}，共 {t['calendar_days']} 个日历日",
            f"- 有数据：{t['distinct_days']} 天；缺失 {len(t['missing_days'])} 天（{t['missing_ratio']:.1%}）",
            f"- 最大断档：{t['max_gap_days']} 天；末月是否不完整：{'是' if t['partial_last_month'] else '否'}",
        ]
        if t["missing_days"]:
            shown = "、".join(t["missing_days"][:12])
            more = "" if len(t["missing_days"]) <= 12 else f" 等 {len(t['missing_days'])} 天"
            lines.append(f"- 缺失日：{shown}{more}")
        lines.append("")

    v = rep["numeric"]
    if v:
        top_share = "—" if v["top1pct_share"] is None else f"{v['top1pct_share']:.1%}"
        lines += [
            "## 数值分布",
            "",
            "| 指标 | 值 |",
            "|---|---|",
            f"| 记录数 | {v['count']:,} 条 |",
            f"| 最小 / P25 / 中位数 / P75 / P90 / 最大 | {v['min']} / {v['p25']} / {v['median']} / {v['p75']} / {v['p90']} / {v['max']} |",
            f"| 均值 / 标准差 / CV | {v['mean']} / {v['std']} / {v['cv']} |",
            f"| 零值占比 | {v['zero_ratio']:.1%} |",
            f"| 负值条数 | {v['negative']} |",
            f"| Top1% 贡献占比 | {top_share} |",
            "",
        ]

    lines += ["## 粒度与主键候选", ""]
    if rep["key_candidates"]:
        lines += ["| 候选键 | 唯一值 | 重复率 |", "|---|---|---|"]
        for k in rep["key_candidates"]:
            lines.append(f"| {' + '.join(k['columns'])} | {k['unique']:,} | {k['duplicate_rate']:.2%} |")
        lines.append("")
        lines.append("> 重复率 > 0.5% 时先确认真实粒度，再谈聚合。")
    else:
        lines.append("未找到可用候选键。")
    lines.append("")

    if rep["categorical"]:
        lines += ["## 分类维度", ""]
        for c in rep["categorical"][:6]:
            top = "、".join(f"{k}({s:.0%})" for k, _, s in c["top"][:5])
            lines.append(f"- **{c['name']}**：{c['unique']} 类，Top1 {c['top1_share']:.1%}，Top5 {c['top5_share']:.1%}；{top}")
        lines.append("")

    lines += ["## 可疑点", ""]
    if rep["flags"]:
        level_cn = {"high": "高", "mid": "中", "low": "低"}
        for f in rep["flags"]:
            lines.append(f"- [{level_cn.get(f['level'], f['level'])}] {f['message']}")
    else:
        lines.append("未发现明显异常，仍需核对口径。")
    lines.append("")
    lines += [
        "## 接下来",
        "",
        "1. 逐条确认上面的可疑点，能解释的写进口径说明，不能解释的先查数据源。",
        "2. 写清「一行代表什么」和「能回答 / 不能回答」。",
        "3. 存量与增量分开算，再决定看板的第一屏。",
        "",
    ]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="数据诊断：粒度、时间、分布、可疑点")
    ap.add_argument("input", help="CSV / TSV / XLSX 路径")
    ap.add_argument("--out", default="diagnosis_out", help="输出目录")
    ap.add_argument("--date-col", help="指定日期列名")
    ap.add_argument("--value-col", help="指定数值列名")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    header, rows = load_table(args.input)
    if not rows:
        raise SystemExit("没有数据行")
    columns = infer_types(header, rows)
    by_name = {c["name"]: c for c in columns}

    date_col = by_name.get(args.date_col) if args.date_col else pick_date_col(columns)
    value_col = by_name.get(args.value_col) if args.value_col else pick_value_col(columns)
    if args.date_col and not date_col:
        raise SystemExit(f"找不到日期列：{args.date_col}")
    if args.value_col and not value_col:
        raise SystemExit(f"找不到数值列：{args.value_col}")

    rep = build_report(header, rows, columns, date_col, value_col,
                       source_name=os.path.basename(args.input))
    os.makedirs(args.out, exist_ok=True)

    md_path = os.path.join(args.out, "diagnosis.md")
    json_path = os.path.join(args.out, "diagnosis.json")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(to_markdown(rep))
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)

    print(f"行数 {rep['kpis']['rows']:,}  列数 {rep['kpis']['columns']}")
    if rep["time"]:
        t = rep["time"]
        print(f"时间 {t['start']} ~ {t['end']}  有数据 {t['distinct_days']} 天  缺失 {len(t['missing_days'])} 天")
    if rep["key_candidates"]:
        k = rep["key_candidates"][0]
        print(f"主键候选 {'+'.join(k['columns'])}  重复率 {k['duplicate_rate']:.2%}")
    print(f"可疑点 {len(rep['flags'])} 条")
    print(f"报告 {os.path.abspath(md_path)}")
    print(f"数据 {os.path.abspath(json_path)}")


if __name__ == "__main__":
    main()
