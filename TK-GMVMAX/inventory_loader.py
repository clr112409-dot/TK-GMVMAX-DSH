"""inventory_loader.py - 读取 KCXQ 文件夹中的最新库存 Excel 并生成面板数据。
数据文件按日期命名，放在 KCXQ 文件夹中；每次覆盖/更新后无需重启，刷新页面即可。
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import openpyxl

from common import app_dir


BASE_DIR = app_dir()

# 库存数据文件夹：面板目录下的 KCXQ
KCXQ_DIRS = [
    BASE_DIR / "KCXQ",
]

_cache: dict = {"sig": None, "payload": None}

# 品牌识别关键词：Goods Name 中出现关键词即归入对应品牌，未匹配归入「其他」。
# 新增品牌时在此补充即可，前端展示直接使用本模块计算结果，不做二次判断。
BRAND_KEYWORDS = {"Solestorm": ["solestorm"], "Zorwalk": ["zorwalk"]}


def _detect_brand(goods_name: str) -> str:
    """按 BRAND_KEYWORDS 从商品名识别品牌，未匹配返回「其他」。"""
    nm = (goods_name or "").lower()
    for brand, keywords in BRAND_KEYWORDS.items():
        if any(keyword in nm for keyword in keywords):
            return brand
    return "其他"


def _candidate_files() -> list[Path]:
    """返回所有候选 KCXQ 目录下的 xlsx 文件（跳过 Excel 临时锁文件），按修改时间最新优先。"""
    files: list[Path] = []
    for d in KCXQ_DIRS:
        if d.exists():
            files += [p for p in d.glob("*.xlsx") if not p.name.startswith("~$")]
    files.sort(key=lambda p: p.stat().st_mtime_ns, reverse=True)
    return files


def inventory_signature() -> str:
    files = _candidate_files()
    if not files:
        return "none"
    f = files[0]
    return f"{f.name}:{f.stat().st_mtime_ns}:{f.stat().st_size}"


def _num(v) -> float:
    if v is None or v == "-" or v == "":
        return 0.0
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def _parse_file(path: Path) -> dict:
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb[wb.sheetnames[0]]
    headers = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
    data = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        r = {}
        for i, h in enumerate(headers):
            r[h] = row[i] if i < len(row) else None
        data.append(r)

    summary: dict = {}

    statuses: dict = {}
    for r in data:
        s = r.get("Inventory Status") or "未知"
        statuses[s] = statuses.get(s, 0) + 1
    summary["inventory_status"] = statuses

    tags: dict = {}
    for r in data:
        t = r.get("Goods Tag") or "未知"
        tags[t] = tags.get(t, 0) + 1
    summary["goods_tags"] = tags

    avail = sum(_num(r.get("Available Inventory (units)")) for r in data)
    transit = sum(_num(r.get("In-Transit: Total Inventory (units)")) for r in data)
    reserved = sum(_num(r.get("Reserved (units)")) for r in data)
    excess = sum(_num(r.get("Excess Units")) for r in data)
    sales30 = sum(_num(r.get("Last 30 days sales")) for r in data)

    summary["totals"] = {
        "available": avail,
        "transit": transit,
        "reserved": reserved,
        "excess": excess,
        "total_skus": len(data),
        "total_sales_30d": sales30,
    }
    summary["sales"] = {
        "total_30d": sales30,
        "skus_with_data": len([r for r in data if _num(r.get("Last 30 days sales")) > 0]),
    }

    aging_buckets = [
        "Inventory Aged 0-30 Days",
        "Inventory Aged 31-60 Days",
        "Inventory Aged 61-90 Days",
        "Inventory Aged 91-120 Days",
        "Inventory Aged 121-180 Days",
        "Inventory Aged 181-270 Days",
        "Inventory Aged 271-365 Days",
        "Inventory Aged over 365 Days",
    ]
    aging = {}
    for b in aging_buckets:
        total = sum(_num(r.get(b)) for r in data)
        aging[b.replace("Inventory Aged ", "").replace(" Days", "")] = total
    summary["aging"] = aging

    dos_dist = {"zero": 0, "low_under30": 0, "healthy_30to90": 0, "overstock_over90": 0}
    for r in data:
        v = r.get("Days of Supply (next 30 days)")
        if v is None or v == "-" or v == "":
            continue
        try:
            d = float(str(v))
            if d == 0:
                dos_dist["zero"] += 1
            elif d < 30:
                dos_dist["low_under30"] += 1
            elif d < 90:
                dos_dist["healthy_30to90"] += 1
            else:
                dos_dist["overstock_over90"] += 1
        except (TypeError, ValueError):
            pass
    summary["dos_distribution"] = dos_dist

    vol_dist = {"0": 0, "1-10": 0, "11-50": 0, "51-100": 0, "100+": 0}
    for r in data:
        v = _num(r.get("Last 30 days sales"))
        if v == 0:
            vol_dist["0"] += 1
        elif v <= 10:
            vol_dist["1-10"] += 1
        elif v <= 50:
            vol_dist["11-50"] += 1
        elif v <= 100:
            vol_dist["51-100"] += 1
        else:
            vol_dist["100+"] += 1
    summary["sales_volume"] = vol_dist

    brands = {}
    for r in data:
        brand = _detect_brand(str(r.get("Goods Name", "") or ""))
        if brand not in brands:
            brands[brand] = {"skus": 0, "available": 0, "transit": 0, "sales_30d": 0, "oos": 0}
        brands[brand]["skus"] += 1
        brands[brand]["available"] += _num(r.get("Available Inventory (units)"))
        brands[brand]["transit"] += _num(r.get("In-Transit: Total Inventory (units)"))
        brands[brand]["sales_30d"] += _num(r.get("Last 30 days sales"))
        if r.get("Inventory Status") == "缺货":
            brands[brand]["oos"] += 1
    summary["brands"] = brands

    sku_list = []
    for r in data:
        sku_list.append({
            "goods_id": r.get("Goods ID", ""),
            "product_code": re.sub(r"^([A-Z]+\d+).*", r"\1", str(r.get("Goods Reference Code", "") or ""))[:20],
            "sku": r.get("Goods Reference Code", ""),
            "name": r.get("Goods Name", ""),
            "available": _num(r.get("Available Inventory (units)")),
            "transit": _num(r.get("In-Transit: Total Inventory (units)")),
            "reserved": _num(r.get("Reserved (units)")),
            "sales_30d": _num(r.get("Last 30 days sales")),
            "sales_60d": _num(r.get("Last 60 days sales")),
            "sales_90d": _num(r.get("Last 90 days sales")),
            "sell_through": _num(r.get("Sell-through Rate (last 30 days)")),
            "status": r.get("Inventory Status", ""),
            "dos_30d": _num(r.get("Days of Supply (next 30 days)")),
            "demand_30d": _num(r.get("Demand Forecast (next 30 days)")),
            "datel_avail_30d": _num(r.get("Days of Total Stock Left (next 30 days)")),
            "aging_0_30": _num(r.get("Inventory Aged 0-30 Days")),
            "aging_31_60": _num(r.get("Inventory Aged 31-60 Days")),
            "aging_61_90": _num(r.get("Inventory Aged 61-90 Days")),
            "aging_over_90": _num(r.get("Inventory Aged over 90 Days")),
            "replenishment_date": r.get("Replenishment Ship Date", ""),
            "replenishment_qty": r.get("Replenishment Quantity", ""),
        })
    summary["skus"] = sku_list
    summary["top_skus"] = sorted(sku_list, key=lambda x: -x["sales_30d"])[:30]
    return summary


def load_inventory() -> dict:
    """返回最新库存数据（带缓存，源文件变化时自动重读）。找不到文件时返回带 error 的结构。"""
    files = _candidate_files()
    if not files:
        return {"meta": {"error": "没有在 KCXQ 文件夹中找到库存 Excel 文件。"}}
    f = files[0]
    sig = inventory_signature()
    if _cache["sig"] != sig or _cache["payload"] is None:
        _cache["sig"] = sig
        _cache["payload"] = _parse_file(f)
    payload = dict(_cache["payload"])
    payload["meta"] = {
        "file": f.name,
        "updated": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        "rows": len(payload.get("skus", [])),
    }
    return payload


if __name__ == "__main__":
    import json
    result = load_inventory()
    print(json.dumps(result.get("meta", {}), ensure_ascii=False))
    print("totals:", json.dumps(result.get("totals", {}), ensure_ascii=False))
