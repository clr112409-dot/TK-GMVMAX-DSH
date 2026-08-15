# -*- coding: utf-8 -*-
"""SKU 匹配表读取规则（表头校验 / 冲突告警 / 最新文件）测试。"""
import os
import shutil
import sys
import uuid
from pathlib import Path

import openpyxl
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "TK-GMVMAX"))

import data_loader as dl  # noqa: E402


@pytest.fixture
def matching_dir(monkeypatch):
    base = Path(__file__).resolve().parent / ".tmp_matching"
    base.mkdir(exist_ok=True)
    d = base / f"case_{uuid.uuid4().hex}"
    d.mkdir()
    old = dl.MATCHING_TABLE_DIR
    dl.MATCHING_TABLE_DIR = d
    yield d
    dl.MATCHING_TABLE_DIR = old
    shutil.rmtree(d, ignore_errors=True)


def test_title_row_detected(matching_dir):
    path = matching_dir / "SKU.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["SKU 匹配表", ""])
    ws.append(["商品 ID", "产品名称"])
    ws.append(["1001", "Alpha"])
    wb.save(path)
    table, notes = dl._read_matching_table()
    assert len(table) == 1 and table.iloc[0]["产品名称"] == "Alpha"
    assert not any("表头无法识别" in n for n in notes)


def test_conflict_warning_keeps_last(matching_dir):
    path = matching_dir / "SKU.xlsx"
    pd.DataFrame({"商品 ID": ["1001", "1001"], "产品名称": ["Alpha", "Beta"]}).to_excel(path, index=False)
    table, notes = dl._read_matching_table()
    assert len(table) == 1 and table.iloc[0]["产品名称"] == "Beta"
    assert any("多个不同产品名称" in n for n in notes)


def test_latest_modified_file_selected(matching_dir):
    older = matching_dir / "SKU_old.xlsx"
    newer = matching_dir / "SKU_new.xlsx"
    pd.DataFrame({"商品 ID": ["1001"], "产品名称": ["Old"]}).to_excel(older, index=False)
    pd.DataFrame({"商品 ID": ["1001"], "产品名称": ["New"]}).to_excel(newer, index=False)
    os.utime(older, (1_600_000_000, 1_600_000_000))
    os.utime(newer, (1_700_000_000, 1_700_000_000))
    table, notes = dl._read_matching_table()
    assert table.iloc[0]["产品名称"] == "New"
    assert any("已选用最新修改的 SKU_new.xlsx" in n for n in notes)


def test_unknown_headers_warn_but_read(matching_dir):
    path = matching_dir / "SKU.xlsx"
    pd.DataFrame({"A": ["1001"], "B": ["Alpha"]}).to_excel(path, index=False)
    table, notes = dl._read_matching_table()
    assert len(table) == 1 and table.iloc[0]["产品名称"] == "Alpha"
    assert any("表头无法识别" in n for n in notes)


def test_too_few_columns_returns_empty_with_note(matching_dir):
    path = matching_dir / "SKU.xlsx"
    pd.DataFrame({"A": ["1001"]}).to_excel(path, index=False)
    table, notes = dl._read_matching_table()
    assert table.empty
    assert any("少于两列" in n for n in notes)
