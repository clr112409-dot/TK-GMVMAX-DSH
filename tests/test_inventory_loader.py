# -*- coding: utf-8 -*-
"""inventory_loader 账龄口径与品牌配置测试。"""
import json
import shutil
import sys
import uuid
from pathlib import Path

import openpyxl
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "TK-GMVMAX"))

import inventory_loader as il  # noqa: E402


def base_row(**over):
    row = {
        "Goods ID": "G1", "Goods Reference Code": "SZW011-BLK", "Goods Name": "Solestorm-X",
        "Inventory Status": "健康", "Available Inventory (units)": 10,
        "In-Transit: Total Inventory (units)": 2, "Reserved (units)": 1,
        "Last 30 days sales": 3,
        "Inventory Aged 0-30 Days": 1, "Inventory Aged 31-60 Days": 2,
        "Inventory Aged 61-90 Days": 3, "Inventory Aged 91-120 Days": 4,
        "Inventory Aged 121-180 Days": 5, "Inventory Aged 181-270 Days": 6,
        "Inventory Aged 271-365 Days": 7, "Inventory Aged over 365 Days": 8,
    }
    row.update(over)
    return row


@pytest.fixture
def tmpdir():
    base = Path(__file__).resolve().parent / ".tmp_inv"
    base.mkdir(exist_ok=True)
    d = base / f"case_{uuid.uuid4().hex}"
    d.mkdir()
    yield d
    shutil.rmtree(d, ignore_errors=True)


def write_xlsx(path, rows):
    pd.DataFrame(rows).to_excel(path, index=False)


def test_aging_over_90_sums_detail_buckets(tmpdir):
    path = tmpdir / "kcxq.xlsx"
    write_xlsx(path, [base_row()])
    payload = il._parse_file(path)
    assert payload["skus"][0]["aging_over_90"] == 30  # 4+5+6+7+8
    assert payload["aging"]["91-120"] == 4 and payload["aging"]["over 365"] == 8


def test_aging_over_90_fallback_to_dedicated_column(tmpdir):
    path = tmpdir / "kcxq.xlsx"
    row = base_row()
    for key in ["Inventory Aged 91-120 Days", "Inventory Aged 121-180 Days",
                "Inventory Aged 181-270 Days", "Inventory Aged 271-365 Days",
                "Inventory Aged over 365 Days"]:
        row[key] = 0
    row["Inventory Aged over 90 Days"] = 9
    write_xlsx(path, [row])
    payload = il._parse_file(path)
    assert payload["skus"][0]["aging_over_90"] == 9


def test_brand_config_override(tmpdir, monkeypatch):
    (tmpdir / il.BRAND_CONFIG_NAME).write_text(
        json.dumps({"CustomBrand": ["solestorm"]}), encoding="utf-8"
    )
    path = tmpdir / "kcxq.xlsx"
    write_xlsx(path, [base_row()])
    old = il.KCXQ_DIRS
    il.KCXQ_DIRS = [tmpdir]
    try:
        payload = il._parse_file(path)
        assert payload["brands"].get("CustomBrand", {}).get("skus") == 1
        assert payload["warnings"] == []
    finally:
        il.KCXQ_DIRS = old


def test_brand_config_invalid_falls_back(tmpdir, monkeypatch):
    (tmpdir / il.BRAND_CONFIG_NAME).write_text("not json", encoding="utf-8")
    path = tmpdir / "kcxq.xlsx"
    write_xlsx(path, [base_row()])
    old = il.KCXQ_DIRS
    il.KCXQ_DIRS = [tmpdir]
    try:
        payload = il._parse_file(path)
        assert payload["brands"].get("Solestorm", {}).get("skus") == 1
        assert any("无法读取" in w for w in payload["warnings"])
    finally:
        il.KCXQ_DIRS = old


def test_blank_rows_skipped(tmpdir):
    path = tmpdir / "kcxq.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Goods ID", "Goods Reference Code", "Goods Name", "Inventory Status",
               "Available Inventory (units)", "In-Transit: Total Inventory (units)",
               "Reserved (units)", "Last 30 days sales"])
    ws.append(["G1", "SZW011", "Name", "健康", 10, 2, 1, 3])
    ws.append([None, None, None, None, None, None, None, None])
    ws.append(["", "", "", "", "", "", "", ""])
    wb.save(path)
    payload = il._parse_file(path)
    assert payload["totals"]["total_skus"] == 1
    assert payload["inventory_status"] == {"健康": 1}


def test_normalize_status_aliases():
    assert il._normalize_status("Out of Stock") == "缺货"
    assert il._normalize_status("low_stock") == "即将缺货"
    assert il._normalize_status("Healthy") == "健康"
    assert il._normalize_status("缺货") == "缺货"
    assert il._normalize_status("自定义状态") == "自定义状态"


def test_extract_product_code():
    assert il._extract_product_code("SZW011-BLK-RED") == "SZW011"
    assert il._extract_product_code("sku12345") == "sku12345"
    assert il._extract_product_code("!!!123") == "UNKNOWN"
    assert il._extract_product_code("") == "UNKNOWN"


def test_parse_file_status_mapping(tmpdir):
    path = tmpdir / "kcxq.xlsx"
    write_xlsx(path, [base_row(**{"Inventory Status": "Out of Stock"})])
    payload = il._parse_file(path)
    assert payload["inventory_status"] == {"缺货": 1}
    assert payload["skus"][0]["status"] == "缺货"
    assert payload["brands"]["Solestorm"]["oos"] == 1


def test_parse_file_unknown_product_code_warning(tmpdir):
    path = tmpdir / "kcxq.xlsx"
    write_xlsx(path, [base_row(**{"Goods Reference Code": "!!!123"})])
    payload = il._parse_file(path)
    assert payload["skus"][0]["product_code"] == "UNKNOWN"
    assert any("产品代码无法识别" in w for w in payload["warnings"])
