"""导出静态数据，供 GitHub Pages 的静态模式使用。

    python tools/export_static.py

产物（写入 frontend/public/data/）：
    houses.json   2890 条房源（含区/街道/小区名，约 70 KB gzip）
    meta.json     区/街道字典 + 筛选项 + 首页 KPI
    quality.json  数据质量报告（P8 只读展示用）

为什么只导出"原始数据"而不导出聚合结果：
    2890 条在浏览器内存里做筛选、排序、聚合、分位、溢价都是毫秒级，
    导出原始数据反而让静态站的图表、筛选、估价全部与后端口径一致，
    不需要维护第二套预聚合产物。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

DATA = ROOT / "data"
OUT = ROOT / "frontend" / "public" / "data"

HOUSE_COLS = [
    "id", "did", "dname", "sid", "sname", "cid", "cname",
    "room", "hall", "area", "total", "unit",
    "floor_level", "floor_total", "age", "deco", "struct",
    "subway", "outlier", "abnormal", "orient"
]

FLOOR_LEVELS = ["低", "中", "高", "顶层", "底层", "地下", "上叠", "未知"]
DECORATIONS = ["精装", "简装", "其他", "毛坯"]
STRUCTURES = ["板楼", "塔楼", "板塔结合", "独栋别墅", "平房"]
DIRECTIONS = ["东", "南", "西", "北", "东北", "东南", "西南", "西北"]

ORIENT_ORDER = ["东南", "东北", "西南", "西北", "东", "南", "西", "北"]


def to_num(series):
    return pd.to_numeric(series, errors="coerce")


def build_houses() -> dict:
    house = pd.read_csv(DATA / "cleaned_house.csv", encoding="utf-8-sig")
    district = pd.read_csv(DATA / "dim_district.csv", encoding="utf-8-sig")
    street = pd.read_csv(DATA / "dim_street.csv", encoding="utf-8-sig")
    community = pd.read_csv(DATA / "dim_community.csv", encoding="utf-8-sig")
    orient = pd.read_csv(DATA / "cleaned_orientation.csv", encoding="utf-8-sig")

    # 房源 → 标准方向（按固定顺序拼接）
    rank = {d: i for i, d in enumerate(ORIENT_ORDER)}
    grouped = {}
    for row_no, direction in zip(orient["source_row_no"], orient["direction"]):
        grouped.setdefault(int(row_no), []).append(direction)
    orient_text = {
        k: " ".join(sorted(set(v), key=lambda d: rank.get(d, 99)))
        for k, v in grouped.items()
    }

    d_name = dict(zip(district["district_id"], district["district_name"]))
    s_name = dict(zip(street["street_id"], street["street_name"]))
    c_name = dict(zip(community["community_id"], community["community_name"]))

    rows = []
    for r in house.itertuples(index=False):
        rows.append([
            int(r.source_row_no),                       # id（与 app.db 的 house.id 一致）
            int(r.district_id), d_name.get(int(r.district_id), ""),
            int(r.street_id), s_name.get(int(r.street_id), ""),
            int(r.community_id), c_name.get(int(r.community_id), ""),
            int(r.room), int(r.hall),
            round(float(r.area), 2),
            round(float(r.total_price), 2),
            round(float(r.unit_price), 2),
            r.floor_level,
            None if pd.isna(r.floor_total) else int(r.floor_total),
            None if pd.isna(r.house_age) else int(r.house_age),
            r.decoration, r.structure,
            int(r.near_subway), int(r.is_outlier), int(r.abnormal_layout),
            orient_text.get(int(r.source_row_no), "")
        ])

    # 按 id 排序，保证两种数据源返回顺序一致
    rows.sort(key=lambda x: x[0])
    return {"cols": HOUSE_COLS, "rows": rows}


def build_meta() -> dict:
    house = pd.read_csv(DATA / "cleaned_house.csv", encoding="utf-8-sig")
    district = pd.read_csv(DATA / "dim_district.csv", encoding="utf-8-sig")
    street = pd.read_csv(DATA / "dim_street.csv", encoding="utf-8-sig")
    community = pd.read_csv(DATA / "dim_community.csv", encoding="utf-8-sig")

    area = to_num(house["area"])
    total = to_num(house["total_price"])
    unit = to_num(house["unit_price"])
    age = to_num(house["house_age"])

    n = len(house)
    mid_total = sorted(total.dropna().tolist())
    median_total = None
    if mid_total:
        k = (len(mid_total) - 1) // 2
        median_total = round(
            mid_total[k] if len(mid_total) % 2 else (mid_total[k] + mid_total[k + 1]) / 2, 2
        )

    kpi = {
        "house_count": int(n),
        "avg_unit_price": round(float(unit.mean()), 2),
        "weighted_unit_price": round(float((total * 10000).sum() / area.sum()), 2),
        "median_total_price": median_total,
        "community_count": int(community["community_id"].nunique()),
    }

    districts = [
        {
            "district_id": int(r.district_id),
            "district_name": r.district_name,
            "house_count": int(r.house_count),
            "avg_unit_price": round(float(r.avg_unit_price), 2),
            "median_unit_price": round(float(r.median_unit_price), 2),
            "median_total_price": round(float(r.median_total_price), 2),
            "avg_area": round(float(r.avg_area), 2),
            "avg_age": round(float(r.avg_age), 2),
        }
        for r in district.itertuples(index=False)
    ]

    streets = [
        {
            "street_id": int(r.street_id),
            "district_id": int(r.district_id),
            "street_name": r.street_name,
            "is_pseudo": int(r.is_pseudo),
            "house_count": int(r.house_count),
            "avg_unit_price": None if pd.isna(r.avg_unit_price) else round(float(r.avg_unit_price), 2),
            "median_total_price": (None if pd.isna(r.median_total_price)
                                   else round(float(r.median_total_price), 2)),
        }
        for r in street.itertuples(index=False)
    ]

    filters = {
        "decoration": DECORATIONS,
        "structure": STRUCTURES,
        "direction": DIRECTIONS,
        "floor_level": FLOOR_LEVELS,
        "ranges": {
            "total_price": [round(float(total.min()), 2), round(float(total.max()), 2)],
            "area": [round(float(area.min()), 2), round(float(area.max()), 2)],
            "house_age": [int(age.min()), int(age.max())],
            "room": [int(to_num(house["room"]).min()), int(to_num(house["room"]).max())],
            "hall": [int(to_num(house["hall"]).min()), int(to_num(house["hall"]).max())],
        },
    }

    return {"kpi": kpi, "districts": districts, "streets": streets, "filters": filters}


def build_quality() -> dict:
    rep = json.loads((DATA / "quality_report.json").read_text(encoding="utf-8"))
    keep = [
        "meta", "row_funnel", "assertions", "assertions_summary", "rules_triggered",
        "issues_total", "r1_changed_total", "r1_changed_cells", "outlier_summary",
        "pseudo_streets", "cardinality", "price_caliber", "percentiles",
        "median_convention", "community_scale",
    ]
    out = {k: rep[k] for k in keep if k in rep}
    # 静态站不需要问题样例明细，避免体积膨胀
    out["assertions"] = out.get("assertions", [])
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)

    houses = build_houses()
    meta = build_meta()
    quality = build_quality()

    payloads = {
        "houses.json": houses,
        "meta.json": meta,
        "quality.json": quality,
    }
    for name, obj in payloads.items():
        path = OUT / name
        path.write_text(
            json.dumps(obj, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8"
        )
        print(f"生成 frontend/public/data/{name:<14} {path.stat().st_size / 1024:8.1f} KB")

    print(f"\n房源 {len(houses['rows'])} 行 × {len(houses['cols'])} 列；"
          f"区 {len(meta['districts'])} / 街道 {len(meta['streets'])}")
    print(f"KPI：{meta['kpi']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
