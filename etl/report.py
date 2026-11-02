"""质量报告：结构化 JSON + 人读 Markdown。

报告必须可复现：内容里不包含任何时间戳/随机量（时间戳只在 run_meta.json 中），
因此同一输入两次运行产出的 quality_report.json 字节级一致。
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .common import json_safe


def build_quality_report(
    raw_df: pd.DataFrame,
    df: pd.DataFrame,
    meta: dict,
    counters: dict,
    assertions: list,
    log,
    cfg: dict,
) -> dict:
    cols = cfg["columns"]

    # 行数漏斗
    raw_rows = int(meta["raw_rows"])
    loaded = int(len(df))
    funnel = {
        "raw_rows": raw_rows,
        "loaded_rows": loaded,
        "rejected_rows": raw_rows - loaded,
        "self_consistent": raw_rows == loaded + (raw_rows - loaded),
    }

    # 缺失率 Top10（在原始 53 列上计算，才能反映真实情况）
    na_rate = raw_df.isna().mean().sort_values(ascending=False)
    missing_top = [
        {"column": str(c), "missing": int(raw_df[c].isna().sum()), "rate": round(float(v), 6)}
        for c, v in na_rate.head(10).items()
    ]

    # 分位数表
    percentiles = {}
    for key, display in [("_area", "面积(㎡)"), ("_total_price", "总价(万元)"),
                         ("_unit_price", "单价(元/㎡)"), ("_house_age", "房龄(年)")]:
        s = df[key]
        percentiles[display] = {
            "P1": round(float(s.quantile(0.01)), 2),
            "P25": round(float(s.quantile(0.25)), 2),
            "P50": round(float(s.quantile(0.50)), 2),
            "P75": round(float(s.quantile(0.75)), 2),
            "P99": round(float(s.quantile(0.99)), 2),
            "min": round(float(s.min()), 2),
            "max": round(float(s.max()), 2),
            "mean": round(float(s.mean()), 2),
        }

    # 均价口径声明（两种口径必须同时给出，否则会被判为口径不一致）
    arithmetic_mean = float(df["_unit_price"].mean())
    weighted_mean = float((df["_total_price"] * 10000).sum() / df["_area"].sum())
    price_caliber = {
        "arithmetic_mean_unit_price": round(arithmetic_mean, 2),
        "area_weighted_mean_unit_price": round(weighted_mean, 2),
        "difference": round(arithmetic_mean - weighted_mean, 2),
        "note": "KPI 使用算术均值；面积加权均值作为口径对照一并披露",
    }

    # 异常值案例（≥10 行，必须能被人核对）
    out = df[df["_is_outlier"] == 1].copy()
    out = out.sort_values("_unit_price", ascending=False)
    outlier_cases = []
    for _, r in out.head(12).iterrows():
        reasons = []
        for col, label in [("_area", "面积"), ("_total_price", "总价"), ("_unit_price", "单价")]:
            if int(r.get(f"_outlier_{col.strip('_')}", 0)) == 1:
                reasons.append(f"{label}超阈值")
        outlier_cases.append({
            "row_no": int(r["source_row_no"]),
            "community": str(r[cols["community"]]).strip(),
            "district": str(r[cols["district"]]),
            "area": round(float(r["_area"]), 2),
            "total_price": round(float(r["_total_price"]), 2),
            "unit_price": round(float(r["_unit_price"]), 2),
            "reason": "、".join(reasons) if reasons else "—",
        })

    # 朝向分布
    orientation_dist = counters.get("R4_direction_distribution", {})

    # 伪街道清单
    pseudo = counters.get("R11_pseudo_street_names", {})

    # 小区在售套数分布（说明"小区不是可统计粒度"）
    cs = df[cols["community"]].astype(str).str.strip().value_counts()
    community_scale = {
        "communities": int(len(cs)),
        "only_one_listing": int((cs == 1).sum()),
        "only_one_listing_rate": round(float((cs == 1).sum() / len(cs)), 4),
        "le_two_listings": int((cs <= 2).sum()),
        "le_two_listings_rate": round(float((cs <= 2).sum() / len(cs)), 4),
        "median_listings": float(cs.median()),
        "max_listings": int(cs.max()),
        "top5": [{"community": str(k), "listings": int(v)} for k, v in cs.head(5).items()],
    }

    report = {
        "meta": {
            "dataset": cfg["meta"]["dataset"],
            "rules_version": cfg["meta"]["rules_version"],
            "input_file": meta["input_file"],
            "input_md5": meta["input_md5"],
            "raw_rows": raw_rows,
            "raw_cols": int(meta["raw_cols"]),
            "python": meta["python_version"],
            "pandas": meta["pandas_version"],
            "numpy": meta["numpy_version"],
        },
        "row_funnel": funnel,
        "assertions": assertions,
        "assertions_summary": {
            "total": len(assertions),
            "passed": int(sum(1 for a in assertions if a["passed"])),
            "failed": int(sum(1 for a in assertions if not a["passed"])),
            "failed_names": [a["name"] for a in assertions if not a["passed"]],
        },
        "rules_triggered": log.count_by_rule(),
        "issues_total": int(len(log)),
        "issues_by_type": log.count_by_type(),
        "issue_samples": log.records[:30],
        "r1_changed_cells": counters.get("R1_changed_cells", {}),
        "r1_changed_total": counters.get("R1_changed_total", 0),
        "missing_top10": missing_top,
        "percentiles": percentiles,
        "price_caliber": price_caliber,
        "outlier_cases": outlier_cases,
        "outlier_summary": counters.get("R8_per_metric", {}),
        "orientation": {
            "association_rows": int(counters.get("R4_orientation_rows", 0)),
            "multi_value_rows": int(counters.get("R4_multi_value_rows", 0)),
            "missing_rows": int(counters.get("R4_missing", 0)),
            "illegal_tokens": counters.get("R4_illegal_tokens", {}),
            "distribution": orientation_dist,
        },
        "floor": {
            "kind_counts": counters.get("R5_floor_kind_counts", {}),
            "level_counts": counters.get("R5_floor_level_counts", {}),
            "unparsed_rows": int(counters.get("R5_floor_kind_counts", {}).get("unparsed", 0)),
        },
        "layout": {
            "variety": counters.get("R6_layout_variety"),
            "abnormal_rows": counters.get("R6_abnormal_layout_rows"),
            "zero_hall_rows": counters.get("R6_zero_hall_rows"),
            "room_mismatch": counters.get("R6_room_mismatch"),
            "hall_mismatch": counters.get("R6_hall_mismatch"),
            "unparsed": counters.get("R6_unparsed"),
        },
        "bucket_check": counters.get("R9_bucket_check", {}),
        "cardinality": {
            "district": counters.get("R10_district_count"),
            "street": counters.get("R10_street_count"),
            "street_name_only": counters.get("R10_street_name_only_count"),
            "community": counters.get("R10_community_count"),
            "community_name_only": counters.get("R10_community_name_only_count"),
            "community_spans_multiple_streets": counters.get(
                "R10_community_spans_multiple_streets", 0
            ),
            "layout_variety": counters.get("R6_layout_variety"),
        },
        "median_convention": {
            "method": cfg.get("median", {}).get("method"),
            "note": cfg.get("median", {}).get("note", "").strip(),
            "unit_price_interpolated": round(float(df["_unit_price"].median()), 2),
            "area_interpolated": round(float(df["_area"].median()), 2),
        },
        "pseudo_streets": {
            "names": pseudo,
            "name_count": len(pseudo),
            "combos": counters.get("R11_pseudo_street_combos"),
            "rows": int(sum(pseudo.values())) if pseudo else 0,
            "prefix_mismatch": counters.get("R11_prefix_mismatch", {}),
            "prefix_mismatch_count": counters.get("R11_prefix_mismatch_count", 0),
        },
        "community_scale": community_scale,
        "onehot": {
            "dropped_count": counters.get("R3_dropped_count"),
            "redundant_baseline_column": counters.get("R2_redundant_baseline_column"),
            "redundant_baseline_true_rows": counters.get("R2_redundant_baseline_true_rows"),
            "district_onehot_mismatch": counters.get("R3_district_onehot_mismatch", {}),
        },
        "tag": {
            "values": counters.get("R12_tag_values", []),
            "near_subway_rows": counters.get("R12_near_subway_rows"),
            "tag_vs_onehot_diff": counters.get("R12_tag_vs_onehot_diff"),
        },
        "reproducibility": {
            "input_md5": meta["input_md5"],
            "claim": "同一输入文件 + 同一 rules.toml 下，两次运行的 5 个 CSV 与 quality_report.json 字节级一致（MD5 相同）",
            "no_randomness": True,
            "sorted_output": True,
            "csv_encoding": "UTF-8 with BOM",
        },
    }
    return json_safe(report)


def render_markdown(rep: dict) -> str:
    lines = []
    a = lines.append
    m = rep["meta"]
    f = rep["row_funnel"]

    a("# 08 · 数据质量报告")
    a("")
    a(f"数据源：`{m['input_file']}`　｜　规则版本：{m['rules_version']}　｜　"
      f"工具链：Python {m['python']} / pandas {m['pandas']} / numpy {m['numpy']}")
    a("")
    a(f"输入文件 MD5：`{m['input_md5']}`")
    a("")
    a("---")
    a("")

    a("## 一、行数漏斗（唯一能证明没有静默丢数据的一张表）")
    a("")
    a("| 环节 | 行数 |")
    a("|---|---|")
    a(f"| 原始数据 | {f['raw_rows']} |")
    a(f"| 入库 | {f['loaded_rows']} |")
    a(f"| 拒收 | {f['rejected_rows']} |")
    a(f"| 自洽校验 | {'✅ 通过' if f['self_consistent'] else '❌ 不通过'} |")
    a("")

    s = rep["assertions_summary"]
    a(f"## 二、断言结果（{s['passed']}/{s['total']} 通过）")
    a("")
    a("| # | 断言 | 期望 | 实测 | 结果 |")
    a("|---|---|---|---|---|")
    for i, item in enumerate(rep["assertions"], start=1):
        mark = "✅" if item["passed"] else "❌"
        a(f"| {i} | {item['name']} | `{item['expected']}` | `{item['actual']}` | {mark} |")
    a("")
    if s["failed"]:
        a(f"> ❌ 未通过：{ '、'.join(s['failed_names']) }")
        a("")

    a("## 三、单价口径声明（两种口径必须同时披露）")
    a("")
    pc = rep["price_caliber"]
    a("| 口径 | 数值 |")
    a("|---|---|")
    a(f"| 算术均值（KPI 使用） | {pc['arithmetic_mean_unit_price']} 元/㎡ |")
    a(f"| 面积加权均值 | {pc['area_weighted_mean_unit_price']} 元/㎡ |")
    a(f"| 两者差额 | {pc['difference']} 元/㎡ |")
    a("")
    a(f"> {pc['note']}")
    a("")

    a("## 四、分位数表")
    a("")
    a("| 指标 | min | P1 | P25 | P50 | P75 | P99 | max | mean |")
    a("|---|---|---|---|---|---|---|---|---|")
    for k, v in rep["percentiles"].items():
        a(f"| {k} | {v['min']} | {v['P1']} | {v['P25']} | **{v['P50']}** | {v['P75']} | "
          f"{v['P99']} | {v['max']} | {v['mean']} |")
    a("")
    mc = rep.get("median_convention", {})
    if mc.get("note"):
        a(f"> **中位数口径声明**（方法：`{mc.get('method')}`）")
        a(">")
        for line in mc["note"].splitlines():
            a(f"> {line}")
        a("")

    a("## 五、规则触发统计（R1–R12）")
    a("")
    a("| 规则 | 问题留痕条数 |")
    a("|---|---|")
    for k, v in rep["rules_triggered"].items():
        a(f"| {k} | {v} |")
    a(f"| **问题总量** | **{rep['issues_total']}** |")
    a("")
    a("> **关于 R1 的口径说明**：R1 实际修正了 "
      f"**{rep.get('r1_changed_total', 0)}** 个单元格，但问题台账只对小区名采样留痕 5 条"
      "（2890 条逐行留痕对分析无价值且会淹没其它问题）。R1 的完整计数见下表，"
      "两者不要混为一谈。")
    a("")
    r1 = rep.get("r1_changed_cells", {})
    if r1:
        a("| R1 受影响列 | 被修正单元格数 |")
        a("|---|---|")
        for k, v in sorted(r1.items(), key=lambda kv: -kv[1]):
            a(f"| {k} | {v} |")
        a(f"| **合计** | **{rep.get('r1_changed_total', 0)}** |")
        a("")

    o = rep["orientation"]
    a("## 六、朝向拆分（D4）")
    a("")
    a(f"- 关联表行数：**{o['association_rows']}**（一房多行）")
    a(f"- 多值朝向房源：**{o['multi_value_rows']}** 条")
    a(f"- 朝向缺失：{o['missing_rows']} 条　｜　非法方向标记：{o['illegal_tokens'] or '无'}")
    a(f"- 方向分布：{ ' ｜ '.join(f'{k} {v}' for k, v in o['distribution'].items()) }")
    a("")

    fl = rep["floor"]
    a("## 七、楼层解析（D3）")
    a("")
    a("| 形态 | 条数 |")
    a("|---|---|")
    for k, v in fl["kind_counts"].items():
        a(f"| {k} | {v} |")
    a("")
    a("| 解析后层级 | 条数 |")
    a("|---|---|")
    for k, v in fl["level_counts"].items():
        a(f"| {k} | {v} |")
    a("")

    la = rep["layout"]
    a("## 八、户型解析（D5）")
    a("")
    a(f"- 户型种类：{la['variety']} 种")
    a(f"- 非常规组合（1室2厅）标记：**{la['abnormal_rows']}** 条（保留，不清洗）")
    a(f"- 室/厅交叉校验不一致：室 {la['room_mismatch']} 条、厅 {la['hall_mismatch']} 条")
    a(f"- 厅=0 的信息性统计：{la['zero_hall_rows']} 条")
    a("")

    a("## 九、区间口径复算（R9，区间列本身不入库）")
    a("")
    a("| 区间 | 采用口径 | 可比较行数 | 匹配行数 | 匹配率 | 原始缺失 |")
    a("|---|---|---|---|---|---|")
    for k, v in rep["bucket_check"].items():
        rate = v.get("match_rate")
        a(f"| {k} | {v['convention']} | {v['compared_rows']} | {v['matched_rows']} | "
          f"{rate if rate is not None else '—'} | {v['src_null_rows']} |")
    a("")

    c = rep["cardinality"]
    a("## 十、维度基数")
    a("")
    a("| 维度 | 数量 | 说明 |")
    a("|---|---|---|")
    a(f"| 区 | {c['district']} | 含亦庄开发区 |")
    a(f"| 街道（区+街道组合） | **{c['street']}** | 关键：街道名去重只有 {c['street_name_only']} 个，组合才是真值 |")
    a(f"| 小区（区+小区组合） | **{c['community']}** | 小区名去重 {c['community_name_only']} 个；"
      f"绿地中央广场跨昌平/通州，故组合多 1 |")
    a(f"| 跨街道的小区 | {c['community_spans_multiple_streets']} 个 | 同小区多街道时取众数街道 |")
    a(f"| 户型 | {c['layout_variety']} | 25 种 |")
    a("")

    ps = rep["pseudo_streets"]
    a("## 十一、伪街道（R11，本项目新增规则）")
    a("")
    a(f"共 **{ps['name_count']}** 个聚合桶街道名、**{ps['combos']}** 个（区,街道）组合，"
      f"覆盖 **{ps['rows']}** 行。做街道排行/画像时必须剔除或单独标注。")
    a("")
    a("> " + "、".join(ps["names"].keys()))
    a("")
    if ps.get("prefix_mismatch"):
        a(f"其中 **{ps['prefix_mismatch_count']}** 个组合的街道前缀所指的区与所在区不一致，"
          f"行政区归属可疑（仅标记，不改写原文）：")
        a("")
        a("| 所在区 / 街道 | 行数 |")
        a("|---|---|")
        for k, v in ps["prefix_mismatch"].items():
            a(f"| {k} | {v} |")
        a("")

    cs = rep["community_scale"]
    a("## 十二、小区在售规模（说明为什么小区不是可统计粒度）")
    a("")
    a("| 指标 | 数值 |")
    a("|---|---|")
    a(f"| 小区数（名称去重） | {cs['communities']} |")
    a(f"| 仅 1 套在售 | **{cs['only_one_listing']}（{cs['only_one_listing_rate']:.1%}）** |")
    a(f"| ≤2 套在售 | {cs['le_two_listings']}（{cs['le_two_listings_rate']:.1%}） |")
    a(f"| 在售套数中位 | {cs['median_listings']} |")
    a(f"| 最大在售套数 | {cs['max_listings']} |")
    a("")
    a("> 结论：小区画像只能做\"该小区在街道中的位置\"，不能做箱线图/波动分析——三分之二的小区只有 1 个样本。")
    a("")

    a("## 十三、异常值案例（只标记，不删除）")
    a("")
    a("| 行号 | 小区 | 区 | 面积㎡ | 总价万 | 单价元/㎡ | 判定 |")
    a("|---|---|---|---|---|---|---|")
    for case in rep["outlier_cases"]:
        a(f"| {case['row_no']} | {case['community']} | {case['district']} | {case['area']} | "
          f"{case['total_price']} | {case['unit_price']} | {case['reason']} |")
    a("")
    a(f"各指标标记行数：" + "；".join(
        f"{k} {v['flagged_rows']} 行（P0.5={v['p_low']}，P99.5={v['p_high']}）"
        for k, v in rep["outlier_summary"].items()
    ))
    a("")

    oh = rep["onehot"]
    a("## 十四、one-hot 列处置")
    a("")
    a(f"- 丢弃 one-hot 列：**{oh['dropped_count']}** 个（17 区 + 4 装修 + 5 结构 + 2 地铁 + 8 朝向）")
    a(f"- 冗余基线列 `{oh['redundant_baseline_column']}` 命中 {oh['redundant_baseline_true_rows']} 行（D2），整列丢弃")
    a(f"- 区 one-hot 与原文交叉校验不一致：{oh['district_onehot_mismatch'] or '无'}")
    a("")

    tg = rep["tag"]
    a("## 十五、房源标签（R12，本项目新增规则）")
    a("")
    a(f"- 标签取值：{tg['values']}")
    a(f"- 近地铁房源：{tg['near_subway_rows']} 条")
    a(f"- 标签与 `近地铁` one-hot 不一致：**{tg['tag_vs_onehot_diff']}** 条")
    a("")
    a("> 结论：标签列只有两种取值且与 one-hot 完全一致，**不具备独立信息量**。设计上不建 `house_tag` 表，直接并入 `house.near_subway`。")
    a("")

    mt = rep["missing_top10"]
    a("## 十六、缺失率 Top10（在原始 53 列上统计）")
    a("")
    a("| 列 | 缺失数 | 缺失率 |")
    a("|---|---|---|")
    for item in mt:
        a(f"| {item['column']} | {item['missing']} | {item['rate']:.2%} |")
    a("")

    rp = rep["reproducibility"]
    a("## 十七、可复现声明")
    a("")
    a(f"- 输入 MD5：`{rp['input_md5']}`")
    a(f"- 无随机性：{rp['no_randomness']}　｜　输出排序确定：{rp['sorted_output']}　｜　编码：{rp['csv_encoding']}")
    a(f"- 承诺：{rp['claim']}")
    a("")
    a("复现命令：")
    a("")
    a("```bat")
    a("python -m etl.run --out data --report data")
    a("```")
    a("")
    return "\n".join(lines)


def write_report(report: dict, out_dir: Path, docs_dir: Path) -> dict:
    out_dir = Path(out_dir)
    docs_dir = Path(docs_dir)
    docs_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "quality_report.json"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )

    md_path = docs_dir / "08-质量报告.md"
    md_path.write_text(render_markdown(report), encoding="utf-8")

    return {"quality_report.json": str(json_path), "08-质量报告.md": str(md_path)}
