"""通用工具：问题台账、数值转换、JSON 安全化。"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd


@dataclass
class IssueLog:
    """数据质量问题台账。

    每条记录对应未来 data_quality_issue 表的一行：
    (rule, row_no, field, issue_type, raw_value, fixed_value)
    """

    records: list = field(default_factory=list)

    def add(self, rule, row_no, field_name, issue_type, raw_value=None, fixed_value=None):
        self.records.append(
            {
                "rule": str(rule),
                "row_no": None if row_no is None else int(row_no),
                "field": None if field_name is None else str(field_name),
                "issue_type": str(issue_type),
                "raw_value": None if raw_value is None else str(raw_value),
                "fixed_value": None if fixed_value is None else str(fixed_value),
            }
        )

    def __len__(self):
        return len(self.records)

    def count_by_rule(self):
        out = {}
        for r in self.records:
            out[r["rule"]] = out.get(r["rule"], 0) + 1
        return dict(sorted(out.items()))

    def count_by_type(self):
        out = {}
        for r in self.records:
            key = f'{r["rule"]}|{r["issue_type"]}'
            out[key] = out.get(key, 0) + 1
        return dict(sorted(out.items()))

    def rows_for(self, rule):
        return [r for r in self.records if r["rule"] == rule]


def to_num(series: pd.Series) -> pd.Series:
    """稳健转数值：无法解析的记为 NaN，统一 float64（不用可空类型，避免比较歧义）。"""
    return pd.to_numeric(series, errors="coerce").astype("float64")


def is_true(series: pd.Series) -> pd.Series:
    """one-hot 列 → 布尔序列（兼容 True/"True"/"TRUE"）。"""
    return series.astype("str").str.strip().str.upper().eq("TRUE")


def json_safe(obj):
    """把 numpy 标量 / NaN / pd.NA 转成 JSON 可序列化的原生类型。"""
    if isinstance(obj, dict):
        return {str(k): json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(v) for v in obj]
    if obj is None or obj is pd.NaT:
        return None
    if obj is pd.NA:
        return None
    if hasattr(obj, "item") and not isinstance(obj, (str, bytes)):
        try:
            obj = obj.item()
        except Exception:  # pragma: no cover - 防御性
            pass
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj
