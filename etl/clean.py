"""R1–R7 / R11–R12：清洗与标准化。

每条规则都返回被改动的行数/列数，写入 counters，供质量报告与对账使用。
本模块不写任何文件，便于单独测试。
"""

from __future__ import annotations

import re

import pandas as pd

from .common import IssueLog, is_true, to_num


# ---------------------------------------------------------------------------
# R1 去空格 + 空字符串转缺失
# ---------------------------------------------------------------------------
def apply_r1_strip(df: pd.DataFrame, cfg: dict, log: IssueLog, counters: dict) -> pd.DataFrame:
    affected: dict[str, int] = {}
    for col in df.columns:
        s = df[col]
        if not (pd.api.types.is_string_dtype(s) or s.dtype == object):
            continue
        stripped = s.str.strip()
        # 只统计"真有内容且被改动"的单元格；NaN 与 NaN 的不等比较结果为 True，
        # 若不显式排除会把空值误计为"已修正"。
        changed = s.notna() & (stripped != s)
        n = int(changed.sum())
        if n:
            affected[col] = n
            if col == cfg["columns"]["community"]:
                # 小区名 2890/2890 全部带尾随空格（D1），逐行留痕代价过高，
                # 这里只记录汇总计数，明细在质量报告里给样例。
                for row_no in df.index[changed][:5]:
                    log.add("R1", row_no + 1, col, "trailing_space",
                            raw_value=s.loc[row_no], fixed_value=stripped.loc[row_no])
            else:
                for row_no in df.index[changed]:
                    log.add("R1", row_no + 1, col, "trailing_space",
                            raw_value=s.loc[row_no], fixed_value=stripped.loc[row_no])
        df[col] = stripped.replace("", pd.NA)
    counters["R1_changed_cells"] = affected
    counters["R1_changed_total"] = int(sum(affected.values()))
    return df


# ---------------------------------------------------------------------------
# R2 丢弃装修冗余基线列（D2）
# ---------------------------------------------------------------------------
def apply_r2_drop_baseline(df: pd.DataFrame, cfg: dict, log: IssueLog, counters: dict) -> pd.DataFrame:
    col = cfg["onehot"]["redundant_baseline_column"]
    if col not in df.columns:
        raise AssertionError(f"R2: 期望存在冗余基线列 {col!r}，实际列中不存在")
    n_true = int(is_true(df[col]).sum())
    counters["R2_redundant_baseline_column"] = col
    counters["R2_redundant_baseline_true_rows"] = n_true
    log.add("R2", None, col, "redundant_baseline_dropped",
            raw_value=f"True={n_true}", fixed_value="<列已丢弃>")
    return df.drop(columns=[col])


# ---------------------------------------------------------------------------
# R3 丢弃全部 one-hot 列，回归原文字段
# ---------------------------------------------------------------------------
def apply_r3_drop_onehot(df: pd.DataFrame, cfg: dict, log: IssueLog, counters: dict) -> pd.DataFrame:
    drop_cols = list(cfg["onehot"]["drop_columns"])
    baseline = cfg["onehot"]["redundant_baseline_column"]
    # 冗余基线列已由 R2 先行丢弃，允许其不在当前列中；其余列缺失视为数据源异常
    missing = [c for c in drop_cols if c not in df.columns and c != baseline]
    if missing:
        raise AssertionError(f"R3: 以下 one-hot 列在原始数据中不存在：{missing}")

    true_counts = {}
    for col in drop_cols:
        if col not in df.columns:
            continue
        true_counts[col] = int(is_true(df[col]).sum())

    counters["R3_dropped_count"] = len([c for c in drop_cols if c in df.columns])
    counters["R3_true_counts"] = true_counts
    # 交叉校验：区 one-hot 求和应等于"所在区"原文的计数
    district_col = cfg["columns"]["district"]
    if district_col in df.columns:
        mismatch = {}
        actual = df[district_col].value_counts().to_dict()
        for name, cnt in true_counts.items():
            if name in actual or name in {"东城", "丰台", "亦庄开发区", "大兴", "密云", "平谷",
                                          "延庆", "怀柔", "房山", "昌平", "朝阳", "海淀",
                                          "石景山", "西城", "通州", "门头沟", "顺义"}:
                if int(actual.get(name, 0)) != cnt:
                    mismatch[name] = {"onehot": cnt, "text": int(actual.get(name, 0))}
        counters["R3_district_onehot_mismatch"] = mismatch
    return df.drop(columns=[c for c in drop_cols if c in df.columns])


# ---------------------------------------------------------------------------
# R4 朝向多值拆分（D4）
# ---------------------------------------------------------------------------
def apply_r4_orientation(df: pd.DataFrame, cfg: dict, log: IssueLog, counters: dict):
    col = cfg["columns"]["orientation"]
    standard = list(cfg["orientation"]["standard"])
    pattern = cfg["orientation"]["split_pattern"]
    rank = {d: i for i, d in enumerate(standard)}

    dirs_list: list[list[str]] = []
    illegal_tokens: dict[str, int] = {}
    multi = 0

    for row_no, value in enumerate(df[col], start=1):
        if pd.isna(value):
            dirs_list.append([])
            log.add("R4", row_no, col, "orientation_missing", raw_value=None)
            continue
        tokens = [t for t in re.split(pattern, str(value).strip()) if t]
        bad = [t for t in tokens if t not in rank]
        if bad:
            for t in bad:
                illegal_tokens[t] = illegal_tokens.get(t, 0) + 1
            log.add("R4", row_no, col, "orientation_token_illegal",
                    raw_value=value, fixed_value=" ".join(t for t in tokens if t in rank))
        uniq = sorted({t for t in tokens if t in rank}, key=lambda d: rank[d])
        if len(uniq) > 1:
            multi += 1
        dirs_list.append(uniq)

    df = df.copy()
    df["_orientation_dirs"] = dirs_list
    df["_orientation_text"] = [" ".join(d) for d in dirs_list]

    orient_rows = []
    for row_no, dirs in enumerate(dirs_list, start=1):
        for d in dirs:
            orient_rows.append({"source_row_no": row_no, "direction": d})

    dist: dict[str, int] = {}
    for dirs in dirs_list:
        for d in dirs:
            dist[d] = dist.get(d, 0) + 1

    counters["R4_multi_value_rows"] = multi
    counters["R4_orientation_rows"] = len(orient_rows)
    counters["R4_direction_distribution"] = dict(sorted(dist.items(), key=lambda kv: -kv[1]))
    counters["R4_illegal_tokens"] = illegal_tokens
    counters["R4_missing"] = int(sum(1 for d in dirs_list if not d))
    return df, orient_rows


# ---------------------------------------------------------------------------
# R5 楼层解析（D3）
# ---------------------------------------------------------------------------
def build_floor_parser(cfg: dict):
    compiled = []
    for item in cfg["floor"]["patterns"]:
        compiled.append(
            {
                "kind": item["kind"],
                "regex": re.compile(item["regex"]),
                "level_group": int(item["level_group"]),
                "total_group": int(item["total_group"]),
            }
        )
    fixed_level = dict(cfg["floor"].get("fixed_level", {}))
    fallback = cfg["floor"]["fallback_level"]

    def parse(text):
        if pd.isna(text):
            return fallback, None, "missing"
        s = str(text).strip()
        for item in compiled:
            m = item["regex"].match(s)
            if not m:
                continue
            if item["level_group"] == 0:
                level = fixed_level.get(item["kind"], fallback)
            else:
                level = m.group(item["level_group"])
            total = int(m.group(item["total_group"]))
            return level, total, item["kind"]
        return fallback, None, "unparsed"

    return parse


def apply_r5_floor(df: pd.DataFrame, cfg: dict, log: IssueLog, counters: dict) -> pd.DataFrame:
    col = cfg["columns"]["floor"]
    parse = build_floor_parser(cfg)
    levels, totals, kinds = [], [], []
    for row_no, value in enumerate(df[col], start=1):
        level, total, kind = parse(value)
        levels.append(level)
        totals.append(total)
        kinds.append(kind)
        if kind in ("unparsed", "missing"):
            log.add("R5", row_no, col, f"floor_{kind}", raw_value=value, fixed_value=level)

    df = df.copy()
    df["_floor_level"] = levels
    df["_floor_total"] = totals
    df["_floor_kind"] = kinds
    kind_counts: dict[str, int] = {}
    for k in kinds:
        kind_counts[k] = kind_counts.get(k, 0) + 1
    counters["R5_floor_kind_counts"] = dict(sorted(kind_counts.items()))
    counters["R5_floor_level_counts"] = (
        df["_floor_level"].value_counts().to_dict()
    )
    return df


# ---------------------------------------------------------------------------
# R6 户型解析（D5）
# ---------------------------------------------------------------------------
def apply_r6_layout(df: pd.DataFrame, cfg: dict, log: IssueLog, counters: dict) -> pd.DataFrame:
    layout_col = cfg["columns"]["layout"]
    room_col = cfg["columns"]["room"]
    hall_col = cfg["columns"]["hall"]
    regex = re.compile(cfg["layout"]["regex"])
    abnormal_set = set(cfg["layout"]["abnormal_layouts"])

    rooms, halls, abnormal = [], [], []
    unparsed = 0
    mismatch_room = 0
    mismatch_hall = 0

    for row_no, (layout, room_s, hall_s) in enumerate(
        zip(df[layout_col], df[room_col], df[hall_col]), start=1
    ):
        m = regex.match(str(layout).strip()) if pd.notna(layout) else None
        if not m:
            unparsed += 1
            rooms.append(None)
            halls.append(None)
            log.add("R6", row_no, layout_col, "layout_unparsed", raw_value=layout)
        else:
            r, h = int(m.group(1)), int(m.group(2))
            rooms.append(r)
            halls.append(h)
            if pd.notna(room_s) and int(float(room_s)) != r:
                mismatch_room += 1
                log.add("R6", row_no, room_col, "room_mismatch",
                        raw_value=f"户型={layout},室列={room_s}", fixed_value=r)
            if pd.notna(hall_s) and int(float(hall_s)) != h:
                mismatch_hall += 1
                log.add("R6", row_no, hall_col, "hall_mismatch",
                        raw_value=f"户型={layout},厅列={hall_s}", fixed_value=h)
        abnormal.append(1 if str(layout).strip() in abnormal_set else 0)

    df = df.copy()
    df["_room"] = rooms
    df["_hall"] = halls
    df["_abnormal_layout"] = abnormal
    counters["R6_unparsed"] = unparsed
    counters["R6_room_mismatch"] = mismatch_room
    counters["R6_hall_mismatch"] = mismatch_hall
    counters["R6_abnormal_layout_rows"] = int(sum(abnormal))
    counters["R6_layout_variety"] = int(df[layout_col].nunique())
    df["_zero_hall_rows"] = [1 if (h == 0) else 0 for h in halls]
    counters["R6_zero_hall_rows"] = int(sum(df["_zero_hall_rows"]))
    return df


# ---------------------------------------------------------------------------
# R7 数值转换（范围校验在 validate 中执行）
# ---------------------------------------------------------------------------
def apply_r7_numeric(df: pd.DataFrame, cfg: dict, log: IssueLog, counters: dict) -> pd.DataFrame:
    cols = cfg["columns"]
    df = df.copy()
    df["_area"] = to_num(df[cols["area"]])
    df["_total_price"] = to_num(df[cols["total_price"]])
    df["_unit_price"] = to_num(df[cols["unit_price"]])
    df["_house_age"] = to_num(df[cols["house_age"]])

    for src, dst in [
        (cols["area"], "_area"),
        (cols["total_price"], "_total_price"),
        (cols["unit_price"], "_unit_price"),
        (cols["house_age"], "_house_age"),
    ]:
        bad = df[dst].isna()
        for row_no in df.index[bad]:
            log.add("R7", row_no + 1, src, "not_numeric", raw_value=df.loc[row_no, src])
        counters[f"R7_nan_{dst}"] = int(bad.sum())

    # 单价一致性：单价 = 总价(万) × 10000 / 面积
    calc = (df["_total_price"] * 10000.0 / df["_area"]).round(2)
    dev = (calc - df["_unit_price"]).abs()
    counters["R7_unit_price_max_dev"] = float(dev.max(skipna=True))
    counters["R7_unit_price_dev_gt_tolerance"] = int(
        (dev > float(cfg["validation"]["unit_price_tolerance"])).sum()
    )
    df["_unit_price_calc"] = calc
    df["_unit_price_dev"] = dev
    return df


# ---------------------------------------------------------------------------
# R11 伪街道标记（数据集特有：12 个 "XX其他" 聚合桶）
# ---------------------------------------------------------------------------
def apply_r11_pseudo_street(df: pd.DataFrame, cfg: dict, log: IssueLog, counters: dict) -> pd.DataFrame:
    street_col = cfg["columns"]["street"]
    district_col = cfg["columns"]["district"]
    suffix = cfg["street"]["pseudo_suffix"]
    df = df.copy()
    flags = []
    names = {}
    combos = {}
    prefix_mismatch = {}
    for row_no, (street, district) in enumerate(
        zip(df[street_col], df[district_col]), start=1
    ):
        if pd.notna(street) and str(street).endswith(suffix):
            flags.append(1)
            name = str(street)
            names[name] = names.get(name, 0) + 1
            combos[(str(district), name)] = True
            prefix = name[: -len(suffix)]
            if prefix != str(district):
                # 街道前缀指向的区与所在区不一致：行政区归属可疑，需人工确认
                prefix_mismatch[f"{district} / {name}"] = (
                    prefix_mismatch.get(f"{district} / {name}", 0) + 1
                )
                log.add("R11", row_no, street_col, "pseudo_street_prefix_mismatch",
                        raw_value=f"所在区={district}, 街道={name}",
                        fixed_value="保留原文，仅标记")
        else:
            flags.append(0)
    df["_is_pseudo_street"] = flags
    counters["R11_pseudo_street_names"] = dict(sorted(names.items()))
    counters["R11_pseudo_street_name_count"] = len(names)
    counters["R11_pseudo_street_combos"] = len(combos)
    counters["R11_pseudo_street_rows"] = int(sum(flags))
    counters["R11_prefix_mismatch"] = dict(sorted(prefix_mismatch.items()))
    counters["R11_prefix_mismatch_count"] = len(prefix_mismatch)
    return df


# ---------------------------------------------------------------------------
# R12 房源标签与"近地铁" one-hot 合并
# ---------------------------------------------------------------------------
def apply_r1r2_tag_check(df: pd.DataFrame, cfg: dict, log: IssueLog, counters: dict) -> pd.DataFrame:
    """必须在 R3 丢弃 one-hot 之前调用：用标签列与 one-hot 列交叉校验。"""
    tag_col = cfg["columns"]["tag"]
    label = cfg["tag"]["near_subway_label"]
    onehot_col = "近地铁"

    tag_near = df[tag_col].astype("str").str.strip().eq(label)
    if onehot_col in df.columns:
        onehot_near = is_true(df[onehot_col])
        diff = int((tag_near != onehot_near).sum())
        counters["R12_tag_vs_onehot_diff"] = diff
        for row_no in df.index[(tag_near != onehot_near)][:10]:
            log.add("R12", row_no + 1, tag_col, "tag_onehot_mismatch",
                    raw_value=df.loc[row_no, tag_col], fixed_value=bool(onehot_near.loc[row_no]))
    else:
        counters["R12_tag_vs_onehot_diff"] = None

    counters["R12_tag_values"] = sorted(df[tag_col].astype("str").str.strip().unique().tolist())
    counters["R12_near_subway_rows"] = int(tag_near.sum())

    df = df.copy()
    df["_near_subway"] = tag_near.astype(int).tolist()
    return df
