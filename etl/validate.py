"""R7 范围校验、R8 极值标记、R9 分桶复算，以及全流程断言。

本模块只做校验与标记，不删除任何原始记录 —— 依据 D7：
极值必须留痕，不得静默删除。
"""

from __future__ import annotations

import pandas as pd

from .common import IssueLog


# ---------------------------------------------------------------------------
# R7 范围校验 → 产出拒收掩码（本数据集预期为 0 行）
# ---------------------------------------------------------------------------
def validate_ranges(df: pd.DataFrame, cfg: dict, log: IssueLog, counters: dict) -> pd.Series:
    v = cfg["validation"]
    checks = [
        ("_area", v["area_min"], v["area_max"], cfg["columns"]["area"]),
        ("_total_price", v["total_price_min"], None, cfg["columns"]["total_price"]),
        ("_house_age", v["house_age_min"], v["house_age_max"], cfg["columns"]["house_age"]),
        ("_room", v["room_min"], v["room_max"], cfg["columns"]["room"]),
        ("_hall", v["hall_min"], v["hall_max"], cfg["columns"]["hall"]),
    ]

    reject = pd.Series(False, index=df.index)
    detail: dict[str, int] = {}

    for col, low, high, display in checks:
        s = df[col]
        bad = s.isna()
        if low is not None:
            bad = bad | (s < low)
        if high is not None:
            bad = bad | (s > high)
        bad = bad.fillna(True)
        n = int(bad.sum())
        detail[display] = n
        for row_no in df.index[bad]:
            log.add("R7", row_no + 1, display, "out_of_range",
                    raw_value=df.loc[row_no, col],
                    fixed_value=f"[{low}, {high}]")
        reject = reject | bad

    counters["R7_out_of_range_by_field"] = detail
    counters["R7_reject_rows"] = int(reject.sum())
    return reject


# ---------------------------------------------------------------------------
# R8 极值标记（全局分位截尾，只标记不删除）
# ---------------------------------------------------------------------------
def mark_outliers(df: pd.DataFrame, cfg: dict, log: IssueLog, counters: dict) -> pd.DataFrame:
    q_low = float(cfg["outlier"]["quantile_low"])
    q_high = float(cfg["outlier"]["quantile_high"])

    df = df.copy()
    per_metric = {}
    flag_any = pd.Series(0, index=df.index, dtype="int64")

    for col, display in [
        ("_area", cfg["columns"]["area"]),
        ("_total_price", cfg["columns"]["total_price"]),
        ("_unit_price", cfg["columns"]["unit_price"]),
    ]:
        s = df[col]
        lo = float(s.quantile(q_low))
        hi = float(s.quantile(q_high))
        mask = ((s < lo) | (s > hi)).fillna(False)
        per_metric[display] = {
            "p_low": round(lo, 2),
            "p_high": round(hi, 2),
            "flagged_rows": int(mask.sum()),
        }
        df[f"_outlier_{col.strip('_')}"] = mask.astype("int64")
        flag_any = flag_any | mask.astype("int64")
        for row_no in df.index[mask]:
            direction = "high" if s.loc[row_no] > hi else "low"
            log.add("R8", row_no + 1, display, f"outlier_{direction}",
                    raw_value=round(float(s.loc[row_no]), 2),
                    fixed_value=f"保留并标记（阈值 P{int(q_low * 100) if q_low < 0.01 else q_low * 100}"
                                f"–P{q_high * 100}）")

    df["_is_outlier"] = flag_any
    counters["R8_per_metric"] = per_metric
    counters["R8_outlier_rows"] = int(flag_any.sum())
    counters["R8_deleted_rows"] = 0
    return df


# ---------------------------------------------------------------------------
# R9 分桶复算：校验原始"面积区间/总价区间"的口径（区间列本身不入库）
# ---------------------------------------------------------------------------
def _bucketize(value, boundaries, labels, left_closed: bool):
    if pd.isna(value):
        return None
    for i, b in enumerate(boundaries):
        hit = (value < b) if left_closed else (value <= b)
        if hit:
            return labels[i]
    return labels[-1]


def recompute_buckets(df: pd.DataFrame, cfg: dict, log: IssueLog, counters: dict) -> pd.DataFrame:
    b = cfg["buckets"]
    df = df.copy()

    result = {}
    for key, value_col, src_key, boundaries_key, labels_key in [
        ("area", "_area", "area_bucket_src", "area_boundaries", "area_labels"),
        ("total", "_total_price", "total_bucket_src", "total_boundaries", "total_labels"),
    ]:
        boundaries = list(b[boundaries_key])
        labels = list(b[labels_key])
        src = df[cfg["columns"][src_key]]

        best = None
        for convention, left_closed in [("left_closed", True), ("left_open", False)]:
            computed = [
                _bucketize(v, boundaries, labels, left_closed) for v in df[value_col]
            ]
            cmp_mask = src.notna()
            match = int(
                sum(1 for i in df.index[cmp_mask] if computed[i] == src.loc[i])
            )
            total_cmp = int(cmp_mask.sum())
            info = {
                "convention": convention,
                "compared_rows": total_cmp,
                "matched_rows": match,
                "match_rate": round(match / total_cmp, 6) if total_cmp else None,
            }
            if best is None or match > best[1]["matched_rows"]:
                best = (convention, info, computed)
        convention, info, computed = best
        info["src_null_rows"] = int(src.isna().sum())
        info["computed_null_rows"] = int(sum(1 for c in computed if c is None))
        result[key] = info
        df[f"_{key}_bucket_recomputed"] = computed

        # 不匹配的行留痕
        cmp_mask = src.notna()
        for i in df.index[cmp_mask]:
            if computed[i] != src.loc[i]:
                log.add("R9", i + 1, cfg["columns"][f"{key}_bucket_src"], "bucket_mismatch",
                        raw_value=src.loc[i], fixed_value=computed[i])

    counters["R9_bucket_check"] = result
    return df


# ---------------------------------------------------------------------------
# 断言集合：返回 (名称, 是否通过, 说明) 列表
# ---------------------------------------------------------------------------
def build_assertions(df, orient_rows, meta, counters, cfg, rejected_rows: int):
    exp = cfg["expect"]
    checks = []

    def check(name, actual, expected, note=""):
        ok = (actual == expected)
        checks.append({
            "name": name,
            "actual": actual,
            "expected": expected,
            "passed": bool(ok),
            "note": note,
        })
        return ok

    funnel_ok = (meta["raw_rows"] == len(df) + rejected_rows)
    checks.append({
        "name": "行数漏斗自洽（原始 = 入库 + 拒收）",
        "actual": f'{meta["raw_rows"]} = {len(df)} + {rejected_rows}',
        "expected": f'{exp["raw_rows"]} = {exp["loaded_rows"]} + {exp["rejected_rows"]}',
        "passed": bool(funnel_ok),
        "note": "唯一能证明清洗过程没有静默丢数据",
    })

    check("原始行数", meta["raw_rows"], exp["raw_rows"])
    check("原始列数", meta["raw_cols"], exp["raw_cols"])
    check("入库行数", len(df), exp["loaded_rows"])
    check("区数量", int(df[cfg["columns"]["district"]].nunique()), exp["districts"])
    check(
        "街道数量（区,街道 组合）",
        int(df.groupby([cfg["columns"]["district"], cfg["columns"]["street"]]).ngroups),
        exp["streets"],
        "注意：237 是街道名字去重数，区+街道组合才是 264",
    )
    check(
        "街道名去重数",
        int(df[cfg["columns"]["street"]].nunique()),
        exp["street_name_only"],
        "26 个街道名跨区重名，故组合数 264 > 名字数 237",
    )
    check(
        "小区数量（区,小区 组合）",
        int(df.groupby([cfg["columns"]["district"], cfg["columns"]["community"]]).ngroups),
        exp["communities"],
        "手册事实卡 1864 是小区名去重数；绿地中央广场跨昌平/通州，组合为 1865",
    )
    check(
        "小区名去重数",
        int(df[cfg["columns"]["community"]].nunique()),
        exp["community_name_only"],
        "跨区同名小区 1 个（绿地中央广场）",
    )
    check("朝向关联行数", len(orient_rows), exp["orientation_rows"])
    r1_cells = counters.get("R1_changed_cells", {})
    check("R1 修正单元格总数", counters.get("R1_changed_total"), exp["r1_changed_cells"],
          "小区名 2890 + 结构 1 + 楼层 1；空值不计入")
    check("R1 小区名受影响行数", r1_cells.get(cfg["columns"]["community"]),
          exp["r1_community_cells"], "D1：小区名 2890/2890 全部带尾随空格")
    check("单价公式误差超限行数", counters.get("R7_unit_price_dev_gt_tolerance"),
          exp["unit_price_error_rows"])
    check("单价中位数（插值法）", float(round(df["_unit_price"].median(), 2)),
          exp["median_unit_price"], f'手册上中位数对照值 {exp["median_unit_price_upper"]}')
    check("总价中位数", float(round(df["_total_price"].median(), 2)), exp["median_total_price"])
    check("面积中位数（插值法）", float(round(df["_area"].median(), 2)),
          exp["median_area"], f'手册上中位数对照值 {exp["median_area_upper"]}')
    check("伪街道名称数", counters.get("R11_pseudo_street_name_count"), exp["pseudo_street_names"])
    check("伪街道（区,街道）组合数", counters.get("R11_pseudo_street_combos"),
          exp["pseudo_street_combos"],
          "同一伪街道名可出现在多个区，组合数 16 > 名称数 12")
    check("伪街道前缀与所在区不一致数", counters.get("R11_prefix_mismatch_count"),
          exp["pseudo_street_prefix_mismatch"],
          "如：海淀区下出现“昌平其他”，行政区归属可疑，仅标记不改写")
    check("伪街道覆盖行数", counters.get("R11_pseudo_street_rows"), exp["pseudo_street_rows"])
    check("极值标记行删除数", counters.get("R8_deleted_rows"), 0, "D7：只标记不删除")
    check("极值标记行数（三指标并集）", counters.get("R8_outlier_rows"), exp["outlier_flagged_rows"])
    check("非常规户型行数", counters.get("R6_abnormal_layout_rows"), exp["abnormal_layout_rows"])

    # 楼层解析五类计数（手册 R5 只列了 3 类，实测为 5 类 + 兜底）
    kinds = counters.get("R5_floor_kind_counts", {})
    for kind, expected in [
        ("labeled", exp["floor_labeled"]),
        ("topbottom", exp["floor_topbottom"]),
        ("pure", exp["floor_pure"]),
        ("basement", exp["floor_basement"]),
        ("stacked", exp["floor_stacked"]),
        ("unparsed", exp["floor_unparsed"]),
    ]:
        check(f"楼层形态 {kind}", kinds.get(kind, 0), expected)

    # 区间口径复算：应 100% 命中非空原始值
    for key, info in counters.get("R9_bucket_check", {}).items():
        check(
            f"区间口径复算命中率（{key}）",
            info.get("match_rate"),
            exp["bucket_match_rate"],
            f"采用口径 {info.get('convention')}，比较 {info.get('compared_rows')} 行",
        )

    return checks
