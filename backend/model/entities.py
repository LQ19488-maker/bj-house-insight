"""实体定义：数据库行 → 领域对象的唯一转换点。

repository 返回 sqlite3.Row，本层把它转成 dataclass（不返回 Row 给上层），
service 只处理 dataclass / 基本类型，dto 再把它们渲染成响应结构。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

FLOOR_LEVELS = ("低", "中", "高", "顶层", "底层", "地下", "上叠", "未知")
DECORATIONS = ("毛坯", "简装", "精装", "其他")
STRUCTURES = ("板楼", "塔楼", "板塔结合", "独栋别墅", "平房")
DIRECTIONS = ("东", "南", "西", "北", "东北", "东南", "西南", "西北")


def _f(v: Any) -> float | None:
    return None if v is None else float(v)


def _i(v: Any) -> int | None:
    return None if v is None else int(v)


@dataclass
class House:
    house_id: int
    district_id: int
    district_name: str
    street_id: int
    street_name: str
    community_id: int
    community_name: str
    room: int
    hall: int
    area: float
    total_price: float
    unit_price: float
    floor_level: str | None
    floor_total: int | None
    house_age: int | None
    decoration: str | None
    structure: str | None
    near_subway: int
    orientation_text: str | None
    is_outlier: int
    abnormal_layout: int
    directions: list[str] = field(default_factory=list)

    @classmethod
    def from_row(cls, row) -> "House":
        return cls(
            house_id=_i(row["house_id"]),
            district_id=_i(row["district_id"]),
            district_name=row["district_name"],
            street_id=_i(row["street_id"]),
            street_name=row["street_name"],
            community_id=_i(row["community_id"]),
            community_name=row["community_name"],
            room=_i(row["room"]),
            hall=_i(row["hall"]),
            area=round(_f(row["area"]), 2),
            total_price=round(_f(row["total_price"]), 2),
            unit_price=round(_f(row["unit_price"]), 2),
            floor_level=row["floor_level"],
            floor_total=_i(row["floor_total"]),
            house_age=_i(row["house_age"]),
            decoration=row["decoration"],
            structure=row["structure"],
            near_subway=_i(row["near_subway"]),
            orientation_text=row["orientation_text"],
            is_outlier=_i(row["is_outlier"]),
            abnormal_layout=_i(row["abnormal_layout"]),
        )


@dataclass
class District:
    district_id: int
    district_name: str
    house_count: int
    avg_unit_price: float | None
    median_unit_price: float | None
    median_total_price: float | None
    avg_area: float | None
    avg_age: float | None

    @classmethod
    def from_row(cls, row) -> "District":
        return cls(
            district_id=_i(row["district_id"]),
            district_name=row["district_name"],
            house_count=_i(row["house_count"]),
            avg_unit_price=_f(row["avg_unit_price"]),
            median_unit_price=_f(row["median_unit_price"]),
            median_total_price=_f(row["median_total_price"]),
            avg_area=_f(row["avg_area"]),
            avg_age=_f(row["avg_age"]),
        )


@dataclass
class Street:
    street_id: int
    district_id: int
    street_name: str
    is_pseudo: int
    house_count: int

    @classmethod
    def from_row(cls, row) -> "Street":
        return cls(
            street_id=_i(row["street_id"]),
            district_id=_i(row["district_id"]),
            street_name=row["street_name"],
            is_pseudo=_i(row.get("is_pseudo") if hasattr(row, "get") else row["is_pseudo"]),
            house_count=_i(row["house_count"]),
        )


@dataclass
class Community:
    community_id: int
    community_name: str
    district_id: int
    district_name: str
    street_id: int
    street_name: str
    house_count: int
    avg_unit_price: float | None
    median_total_price: float | None
    avg_area: float | None
    avg_age: float | None

    @classmethod
    def from_row(cls, row) -> "Community":
        return cls(
            community_id=_i(row["id"]),
            community_name=row["name"],
            district_id=_i(row["district_id"]),
            district_name=row["district_name"],
            street_id=_i(row["street_id"]),
            street_name=row["street_name"],
            house_count=_i(row["house_count"]),
            avg_unit_price=_f(row["avg_unit_price"]),
            median_total_price=_f(row["median_total_price"]),
            avg_area=_f(row["avg_area"]),
            avg_age=_f(row["avg_age"]),
        )


@dataclass
class SimilarItem:
    house_id: int
    community_name: str
    street_name: str
    area: float
    total_price: float
    unit_price: float
    house_age: int | None
    match_level: str
    area_diff_pct: float
    age_diff: int

    def to_dict(self) -> dict:
        return {
            "house_id": self.house_id,
            "community_name": self.community_name,
            "street_name": self.street_name,
            "area": round(self.area, 2),
            "total_price": round(self.total_price, 2),
            "unit_price": round(self.unit_price, 2),
            "house_age": self.house_age,
            "match_level": self.match_level,
            "area_diff_pct": round(self.area_diff_pct, 2),
            "age_diff": self.age_diff,
        }
