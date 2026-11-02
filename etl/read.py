"""R0 读取：原始 Excel → 全文本 DataFrame，并记录可复现元信息。"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from .config import md5_of


def read_raw(xlsx_path: Path | str, cfg: dict) -> tuple[pd.DataFrame, dict]:
    """读取原始数据。全部按文本读入，防止 Excel 自动把编号/年份转成数值。"""
    xlsx_path = Path(xlsx_path)
    sheet_index = int(cfg["read"]["sheet_index"])

    df = pd.read_excel(xlsx_path, sheet_name=sheet_index, dtype=str)
    original_columns = [str(c) for c in df.columns]
    df.columns = [c.strip() for c in original_columns]

    meta = {
        "input_file": xlsx_path.name,
        "input_path": str(xlsx_path),
        "input_md5": md5_of(xlsx_path),
        "sheet_index": sheet_index,
        "raw_rows": int(len(df)),
        "raw_cols": int(len(df.columns)),
        "columns": list(df.columns),
        "columns_with_outer_space": [
            c for c in original_columns if c != c.strip()
        ],
        "python_version": sys.version.split()[0],
        "pandas_version": pd.__version__,
        "numpy_version": _numpy_version(),
    }
    return df, meta


def _numpy_version() -> str:
    try:
        import numpy

        return numpy.__version__
    except Exception:  # pragma: no cover - 防御性
        return "unknown"
