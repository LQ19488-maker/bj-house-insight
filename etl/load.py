"""R10 维度构建 + 产物落盘。

产物（全部 UTF-8 with BOM，Excel 双击不乱码）：
    cleaned_house.csv        主表（3NF：只存外键，姓名在维度表）
    cleaned_orientation.csv  朝向拆表（一房多行）
    dim_district.csv         17
    dim_street.csv           264（关键在于 (区,街道) 组合，而非街道名去重数 237）
    dim_community.csv        1864
    run_meta.json            运行元信息 + 产物 MD5（可复现比对用）
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .common import json_safe
from .config import md5_of


HOUSE_COLUMNS = [
    "source_row_no",
    "district_id",
    "street_id",
    "community_id",
    "room",
    "hall",
    "area",
    "total_price",
    "unit_price",
    "floor_level",
    "floor_total",
    "floor_raw",
    "orientation_text",
    "decoration",
    "structure",
    "house_age",
    "near_subway",
    "is_outlier",
    "abnormal_layout",
]

ORIENTATION_COLUMNS = ["source_row_no", "direction"]

ISSUE_COLUMNS = ["rule", "row_no", "field", "issue_type", "raw_value", "fixed_value"]

DIM_DISTRICT_COLUMNS = [
    "district_id", "district_name", "house_count",
    "avg_unit_price", "median_unit_price", "median_total_price", "avg_area", "avg_age",
]
DIM_STREET_COLUMNS = [
    "street_id", "district_id", "street_name", "is_pseudo",
    "house_count", "avg_unit_price", "median_total_price",
]
DIM_COMMUNITY_COLUMNS = [
    "community_id", "district_id", "street_id", "community_name",
    "house_count", "avg_unit_price", "median_total_price", "avg_area", "avg_age",
]


def build_dimensions(df: pd.DataFrame, cfg: dict, log, counters: dict):
    """构建三级行政区维度（R10）。名称标准化后按 (上级, 名称) 去重，不可跨区合并。"""
    district_col = cfg["columns"]["district"]
    street_col = cfg["columns"]["street"]
    community_col = cfg["columns"]["community"]

    df = df.copy()

    # 1) 区
    districts = sorted(df[district_col].dropna().unique().tolist())
    district_id = {name: i for i, name in enumerate(districts, start=1)}
    df["district_id"] = df[district_col].map(district_id).astype("Int64")

    # 2) 街道（联合主键 district_id + name）
    street_pairs = sorted(
        {(district_id[d], s) for d, s in zip(df[district_col], df[street_col]) if pd.notna(s)}
    )
    street_id = {pair: i for i, pair in enumerate(street_pairs, start=1)}
    df["street_id"] = [
        street_id.get((int(d), s)) if pd.notna(s) and pd.notna(d) else None
        for d, s in zip(df["district_id"], df[street_col])
    ]
    df["street_id"] = pd.array(df["street_id"], dtype="Int64")

    # 3) 小区（联合主键 district_id + name）
    community_pairs = sorted(
        {(district_id[d], c) for d, c in zip(df[district_col], df[community_col]) if pd.notna(c)}
    )
    community_id = {pair: i for i, pair in enumerate(community_pairs, start=1)}
    df["community_id"] = [
        community_id.get((int(d), c)) if pd.notna(c) and pd.notna(d) else None
        for d, c in zip(df["district_id"], df[community_col])
    ]
    df["community_id"] = pd.array(df["community_id"], dtype="Int64")

    # 4) 一个小区是否跨多个街道（应极少，需留痕）
    span = (
        df.dropna(subset=["community_id", "street_id"])
        .groupby("community_id")["street_id"]
        .nunique()
    )
    conflict = span[span > 1]
    for cid in conflict.index:
        rows = df[df["community_id"] == cid]
        log.add("R10", int(rows["source_row_no"].iloc[0]), community_col,
                "community_spans_multiple_streets",
                raw_value=f'小区={rows[community_col].iloc[0]}',
                fixed_value=f"街道数={int(conflict.loc[cid])}")
    counters["R10_district_count"] = len(districts)
    counters["R10_street_count"] = len(street_pairs)
    counters["R10_community_count"] = len(community_pairs)
    counters["R10_street_name_only_count"] = int(df[street_col].nunique(dropna=True))
    counters["R10_community_name_only_count"] = int(df[community_col].nunique(dropna=True))
    counters["R10_community_spans_multiple_streets"] = int(len(conflict))

    # 5) 维度聚合（供前端/接口直接读取，避免每次实时聚合）
    g_district = df.groupby("district_id").agg(
        house_count=("source_row_no", "size"),
        avg_unit_price=("_unit_price", "mean"),
        median_unit_price=("_unit_price", "median"),
        median_total_price=("_total_price", "median"),
        avg_area=("_area", "mean"),
        avg_age=("_house_age", "mean"),
    ).round(2).reset_index()
    g_district["district_name"] = g_district["district_id"].map(
        {v: k for k, v in district_id.items()}
    )

    g_street = df.groupby("street_id").agg(
        district_id=("district_id", "first"),
        house_count=("source_row_no", "size"),
        avg_unit_price=("_unit_price", "mean"),
        median_total_price=("_total_price", "median"),
        max_pseudo=("_is_pseudo_street", "max"),
    ).round(2).reset_index()
    inv_street = {v: k for k, v in street_id.items()}
    g_street["street_name"] = g_street["street_id"].map(lambda i: inv_street[int(i)][1])
    g_street["is_pseudo"] = g_street.pop("max_pseudo").astype(int)

    street_mode = (
        df.dropna(subset=["street_id"])
        .groupby("community_id")["street_id"]
        .agg(lambda s: s.mode().iloc[0] if len(s.mode()) else s.iloc[0])
    )
    g_community = df.groupby("community_id").agg(
        district_id=("district_id", "first"),
        house_count=("source_row_no", "size"),
        avg_unit_price=("_unit_price", "mean"),
        median_total_price=("_total_price", "median"),
        avg_area=("_area", "mean"),
        avg_age=("_house_age", "mean"),
    ).round(2).reset_index()
    g_community["street_id"] = g_community["community_id"].map(street_mode)
    inv_community = {v: k for k, v in community_id.items()}
    g_community["community_name"] = g_community["community_id"].map(lambda i: inv_community[int(i)][1])

    dim_district = g_district[DIM_DISTRICT_COLUMNS].sort_values("district_id").reset_index(drop=True)
    dim_street = g_street[DIM_STREET_COLUMNS].sort_values("street_id").reset_index(drop=True)
    dim_community = (
        g_community[DIM_COMMUNITY_COLUMNS].sort_values("community_id").reset_index(drop=True)
    )
    return df, dim_district, dim_street, dim_community


def build_house_frame(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    cols = cfg["columns"]
    out = pd.DataFrame({
        "source_row_no": df["source_row_no"].astype("int64"),
        "district_id": df["district_id"],
        "street_id": df["street_id"],
        "community_id": df["community_id"],
        "room": pd.array(df["_room"], dtype="Int64"),
        "hall": pd.array(df["_hall"], dtype="Int64"),
        "area": df["_area"].round(2),
        "total_price": df["_total_price"].round(2),
        "unit_price": df["_unit_price"].round(2),
        "floor_level": df["_floor_level"],
        "floor_total": pd.array(df["_floor_total"], dtype="Int64"),
        "floor_raw": df[cols["floor"]],
        "orientation_text": df["_orientation_text"],
        "decoration": df[cols["decoration"]],
        "structure": df[cols["structure"]],
        "house_age": df["_house_age"].astype("Int64"),
        "near_subway": df["_near_subway"].astype("int64"),
        "is_outlier": df["_is_outlier"].astype("int64"),
        "abnormal_layout": df["_abnormal_layout"].astype("int64"),
    })
    return out[HOUSE_COLUMNS].sort_values("source_row_no").reset_index(drop=True)


def write_csv(df: pd.DataFrame, path: Path) -> str:
    df.to_csv(path, index=False, encoding="utf-8-sig", lineterminator="\n")
    return md5_of(path)


def write_outputs(
    out_dir: Path,
    house: pd.DataFrame,
    orient_rows: list,
    dim_district: pd.DataFrame,
    dim_street: pd.DataFrame,
    dim_community: pd.DataFrame,
    meta: dict,
    counters: dict,
    assertions: list,
    issues: list | None = None,
) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    orient = pd.DataFrame(orient_rows, columns=ORIENTATION_COLUMNS).sort_values(
        ["source_row_no", "direction"]
    ).reset_index(drop=True)

    issues_df = pd.DataFrame(issues or [], columns=ISSUE_COLUMNS)

    artifacts = {}
    artifacts["cleaned_house.csv"] = write_csv(house, out_dir / "cleaned_house.csv")
    artifacts["cleaned_orientation.csv"] = write_csv(orient, out_dir / "cleaned_orientation.csv")
    artifacts["dim_district.csv"] = write_csv(dim_district, out_dir / "dim_district.csv")
    artifacts["dim_street.csv"] = write_csv(dim_street, out_dir / "dim_street.csv")
    artifacts["dim_community.csv"] = write_csv(dim_community, out_dir / "dim_community.csv")
    artifacts["data_quality_issue.csv"] = write_csv(issues_df, out_dir / "data_quality_issue.csv")

    run_meta = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rules_version": meta.get("rules_version"),
        "input": {
            "file": meta["input_file"],
            "md5": meta["input_md5"],
            "raw_rows": meta["raw_rows"],
            "raw_cols": meta["raw_cols"],
        },
        "runtime": {
            "python": meta["python_version"],
            "pandas": meta["pandas_version"],
            "numpy": meta["numpy_version"],
        },
        "row_funnel": {
            "raw": meta["raw_rows"],
            "loaded": int(len(house)),
            "rejected": meta["raw_rows"] - int(len(house)),
        },
        "outputs": {
            "rows": {
                "cleaned_house.csv": int(len(house)),
                "cleaned_orientation.csv": int(len(orient)),
                "dim_district.csv": int(len(dim_district)),
                "dim_street.csv": int(len(dim_street)),
                "dim_community.csv": int(len(dim_community)),
                "data_quality_issue.csv": int(len(issues_df)),
            },
            "md5": artifacts,
        },
        "assertions_passed": all(a["passed"] for a in assertions),
        "assertions_failed": [a["name"] for a in assertions if not a["passed"]],
    }
    (out_dir / "run_meta.json").write_text(
        json.dumps(json_safe(run_meta), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"artifacts": artifacts, "run_meta": run_meta, "orientation_rows": int(len(orient))}
