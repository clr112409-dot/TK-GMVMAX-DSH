# -*- coding: utf-8 -*-
"""data_loader 核心逻辑的 pytest 回归测试。"""
import json
import shutil
import sys
import uuid
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "TK-GMVMAX"))

import data_loader as dl  # noqa: E402


ROW = {
    "Product ID": "1001", "Campaign name": "C1", "Video ID": "111", "Video title": "T1",
    "Cost": 10, "SKU orders": 1, "Gross revenue": 20,
    "Product ad impressions": 100, "Product ad clicks": 10,
}


@pytest.fixture
def isolated_dirs():
    """把 data_loader 指向工作区内的临时目录，避免污染真实数据/系统临时目录。"""
    base = Path(__file__).resolve().parent / ".tmp"
    base.mkdir(exist_ok=True)
    # 注意：不用 tempfile.mkdtemp（其 tmpXXXX 目录在本沙箱内无法继续创建子目录），
    # 改用普通 uuid 目录名。
    root = base / f"case_{uuid.uuid4().hex}"
    root.mkdir()
    daily = root / "daily_data"
    sku = root / "sku"
    daily.mkdir()
    sku.mkdir()
    old_daily = dl.DAILY_DATA_DIR
    old_sku = dl.MATCHING_TABLE_DIR
    dl.DAILY_DATA_DIR = daily
    dl.MATCHING_TABLE_DIR = sku
    yield daily, sku
    dl.DAILY_DATA_DIR = old_daily
    dl.MATCHING_TABLE_DIR = old_sku
    shutil.rmtree(root, ignore_errors=True)


def write_daily(daily: Path, name: str, rows: list[dict]) -> None:
    pd.DataFrame(rows).to_excel(daily / name, index=False)


# ---------- 日期解析 ----------

def test_parse_full_date_formats():
    assert dl._parse_report_date("2026-08-12.xlsx") == pd.Timestamp("2026-08-12")
    assert dl._parse_report_date("2026.08.12.xlsx") == pd.Timestamp("2026-08-12")
    assert dl._parse_report_date("2026_08_12.xlsx") == pd.Timestamp("2026-08-12")
    assert dl._parse_report_date("20260812.xlsx") == pd.Timestamp("2026-08-12")


def test_parse_month_day_inference():
    assert dl._parse_report_date("8.13.xlsx", today=datetime(2026, 8, 15)) == pd.Timestamp("2026-08-13")
    assert dl._parse_report_date("8-13.xlsx", today=datetime(2026, 8, 15)) == pd.Timestamp("2026-08-13")
    assert dl._parse_report_date("8_13.xlsx", today=datetime(2026, 8, 15)) == pd.Timestamp("2026-08-13")
    assert dl._parse_report_date("12.31.xlsx", today=datetime(2026, 8, 15)) == pd.Timestamp("2025-12-31")


def test_unparseable_returns_nat():
    assert pd.isna(dl._parse_report_date("report.xlsx"))
    assert pd.isna(dl._parse_report_date("2026-13-01.xlsx"))


def test_load_data_skips_unparseable_file(isolated_dirs):
    daily, _ = isolated_dirs
    write_daily(daily, "2026-08-12.xlsx", [ROW])
    write_daily(daily, "report.xlsx", [ROW])
    data, _, notes = dl.load_data()
    assert len(data) == 1
    assert data.iloc[0]["统计日期"] == pd.Timestamp("2026-08-12")
    assert any("report.xlsx" in n and "跳过" in n for n in notes)


# ---------- 第一批回归：锁文件 / schema 校验 ----------

def test_load_data_lock_file_filtered(isolated_dirs):
    daily, sku = isolated_dirs
    write_daily(daily, "8.13.xlsx", [ROW])
    pd.DataFrame({"商品 ID": ["1001"], "产品名称": ["测试产品"]}).to_excel(
        sku / "商品SKU匹配表.xlsx", index=False
    )
    (sku / "~$商品SKU匹配表.xlsx").write_bytes(b"lock")
    data, mapping, _ = dl.load_data()
    assert len(data) == 1
    assert data.iloc[0]["产品名称"] == "测试产品"
    assert "~$" not in dl.source_signature()


def test_load_data_required_column_skip(isolated_dirs):
    daily, _ = isolated_dirs
    write_daily(daily, "8.13.xlsx", [ROW])
    write_daily(daily, "8.14.xlsx", [{"Product ID": "2001", "Cost": 5}])
    data, _, notes = dl.load_data()
    assert len(data) == 1
    assert any("8.14.xlsx" in n and "缺少必需列" in n for n in notes)


def test_load_data_corrupt_mapping_safe(isolated_dirs):
    daily, sku = isolated_dirs
    write_daily(daily, "8.13.xlsx", [ROW])
    (sku / "SKU坏表.xlsx").write_bytes(b"not a real xlsx")
    data, _, notes = dl.load_data()
    assert len(data) == 1
    assert data.iloc[0]["产品名称"] == "未匹配产品"
    assert any("无法读取 SKU 匹配表" in n for n in notes)


def test_normalize_columns_case_insensitive():
    frame = pd.DataFrame({
        "product id": ["1"], "gross revenue": [2], "cost": [1],
        "sku orders": [1], "product ad impressions": [3], "product ad clicks": [1],
    })
    norm = dl._normalize_columns(frame)
    assert norm.columns.tolist() == [
        "商品 ID", "总收入", "成本", "SKU 订单数", "商品广告曝光数", "商品广告点击数",
    ]


# ---------- NaT 防御 ----------

def test_material_lifecycle_ignores_nat():
    df = pd.DataFrame({
        "素材标识": ["M1"],
        "统计日期": [pd.NaT],
        "成本": [1.0],
        "总收入": [2.0],
    })
    assert dl.material_lifecycle(df) == {}


# ---------- 货币告警 ----------

def test_currency_warning(isolated_dirs):
    daily, _ = isolated_dirs
    write_daily(daily, "8.13.xlsx", [{**ROW, "Currency": "CNY"}])
    data, _, notes = dl.load_data()
    assert len(data) == 1
    assert any("非 USD 货币" in n and "CNY" in n for n in notes)


def test_currency_usd_no_warning(isolated_dirs):
    daily, _ = isolated_dirs
    write_daily(daily, "8.13.xlsx", [{**ROW, "Currency": "USD"}])
    _, _, notes = dl.load_data()
    assert not any("非 USD 货币" in n for n in notes)


# ---------- 生命周期规则配置 ----------

@pytest.fixture
def tmp_rules_dir(monkeypatch):
    base = Path(__file__).resolve().parent / ".tmp"
    base.mkdir(exist_ok=True)
    d = base / f"rules_{uuid.uuid4().hex}"
    d.mkdir()
    monkeypatch.setattr(dl, "BASE_DIR", d)
    yield d
    shutil.rmtree(d, ignore_errors=True)


def test_lifecycle_rules_config_override(tmp_rules_dir):
    (tmp_rules_dir / dl.LIFECYCLE_CONFIG_NAME).write_text(
        json.dumps({"new_days": 3, "compare_days": 2, "decline_threshold": 0.5}), encoding="utf-8"
    )
    rules, warning = dl._lifecycle_rules()
    assert rules == {"new_days": 3, "compare_days": 2, "decline_threshold": 0.5}
    assert warning is None


def test_lifecycle_rules_invalid_fallback(tmp_rules_dir):
    (tmp_rules_dir / dl.LIFECYCLE_CONFIG_NAME).write_text("not json", encoding="utf-8")
    rules, warning = dl._lifecycle_rules()
    assert rules == dl.DEFAULT_LIFE_CYCLE_RULES
    assert warning and "无法读取" in warning


def test_source_signature_includes_rules_config(tmp_rules_dir):
    (tmp_rules_dir / dl.LIFECYCLE_CONFIG_NAME).write_text("{}", encoding="utf-8")
    assert dl.LIFECYCLE_CONFIG_NAME in dl.source_signature()
