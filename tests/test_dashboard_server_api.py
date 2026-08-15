# -*- coding: utf-8 -*-
"""dashboard_server 接口参数语义（product 统一匹配 / lifecycle 日期过滤）测试。"""
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "TK-GMVMAX"))

import dashboard_server as ds  # noqa: E402


def make_df():
    rows = []
    for mid, pid, name, dates in [
        ("M1", "1001", "Alpha 鞋", ["2026-08-01", "2026-08-02", "2026-08-03"]),
        ("M2", "1002", "Beta 鞋", ["2026-08-15", "2026-08-16", "2026-08-17"]),
    ]:
        for d in dates:
            rows.append({
                "统计日期": pd.Timestamp(d), "素材标识": mid, "产品名称": name, "商品 ID": pid,
                "成本": 1.0, "总收入": 2.0, "SKU 订单数": 1,
                "商品广告曝光数": 10, "商品广告点击数": 2, "视频标题": mid,
            })
    return pd.DataFrame(rows)


@pytest.fixture
def load_mock(monkeypatch):
    df = make_df()
    mapping = pd.DataFrame(columns=["商品 ID", "产品名称"])
    monkeypatch.setattr(ds, "_load_data_cached", lambda: (df, mapping, []))
    return df


def test_filter_product_case_insensitive_and_id():
    df = make_df()
    out = ds._filter_product(df, "alpha")
    assert set(out["素材标识"]) == {"M1"}
    out = ds._filter_product(df, "1002")
    assert set(out["素材标识"]) == {"M2"}
    out = ds._filter_product(df, "")
    assert len(out) == len(df)


def test_filter_product_literal_regex_chars():
    df = make_df()
    # "+" 应作为字面量匹配，而不是正则含义导致报错或误匹配。
    out = ds._filter_product(df, "a+b")
    assert out.empty


def test_lifecycle_date_from_filters(load_mock):
    payload = ds._build_lifecycle_payload({"date_from": "2026-08-15"})
    assert payload["total"] == 1
    assert payload["rows"][0]["素材标识"] == "M2"


def test_lifecycle_date_to_filters(load_mock):
    payload = ds._build_lifecycle_payload({"date_to": "2026-08-14"})
    assert payload["total"] == 1
    assert payload["rows"][0]["素材标识"] == "M1"


def test_lifecycle_product_and_date_combined(load_mock):
    payload = ds._build_lifecycle_payload({"product": "beta", "date_from": "2026-08-01", "date_to": "2026-08-20"})
    assert payload["total"] == 1
    assert payload["rows"][0]["素材标识"] == "M2"


def test_lifecycle_empty_range_error(load_mock):
    payload = ds._build_lifecycle_payload({"date_from": "2026-09-01"})
    assert "error" in payload and "没有数据" in payload["error"]
