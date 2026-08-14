from __future__ import annotations

from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from typing import Iterable

import pandas as pd

from common import app_dir


BASE_DIR = app_dir()
DAILY_DATA_DIR = BASE_DIR / "daily_data"
MATCHING_TABLE_DIR = BASE_DIR / "SKU Matching Table"

# 新版 TikTok 后台导出表头（英文）→ 面板内部列名（中文）
HEADER_MAP = {
    "Campaign name": "广告计划名称",
    "Campaign ID": "广告计划 ID",
    "Product ID": "商品 ID",
    "Creative type": "创意作品类型",
    "Video title": "视频标题",
    "Video ID": "视频 ID",
    "TikTok account": "TikTok 账号",
    "Time posted": "发布时间",
    "Status": "状态",
    "Exploration secondary status": "探索次级状态",
    "Authorization type": "授权类型",
    "Cost": "成本",
    "SKU orders": "SKU 订单数",
    "Cost per order": "平均下单成本",
    "Gross revenue": "总收入",
    "Product ad impressions": "商品广告曝光数",
    "Product ad clicks": "商品广告点击数",
    "Product ad click rate": "商品广告点击率",
    "Ad conversion rate": "广告转化率",
    "2-second ad video view rate": "广告视频播放达 2 秒播放率",
    "6-second ad video view rate": "广告视频播放达 6 秒播放率",
    "25% ad video view rate": "广告视频播放达 25% 播放率",
    "50% ad video view rate": "广告视频播放达 50% 播放率",
    "75% ad video view rate": "广告视频播放达 75% 播放率",
    "100% ad video view rate": "广告视频完播率",
    "Currency": "货币",
}

# 创意作品类型：英文导出值 → 中文
CREATIVE_TYPE_MAP = {
    "Video": "视频",
    "Images": "图片",
    "Product card": "商品卡片",
    "Product Card": "商品卡片",
    "Image": "图片",
    "Video Landing Page": "视频落地页",
    "Live": "直播",
}

# 授权类型：英文导出值 → 中文（展示用）
AUTH_TYPE_MAP = {
    "TikTok Shop official account": "TikTok Shop 官方账号",
    "Affiliate mass authorization": "达人批量授权",
    "Video code": "视频码",
    "Business Center": "商业中心",
}

ID_COLUMNS = ["商品 ID", "广告计划 ID", "视频 ID"]
NUMERIC_COLUMNS = [
    "成本", "SKU 订单数", "平均下单成本", "总收入", "ROI",
    "商品广告曝光数", "商品广告点击数", "商品广告点击率", "广告转化率",
    "广告视频播放达 2 秒播放率", "广告视频播放达 6 秒播放率",
    "广告视频播放达 25% 播放率", "广告视频播放达 50% 播放率",
    "广告视频播放达 75% 播放率", "广告视频完播率",
]
RATE_COLUMNS = [
    "商品广告点击率", "广告转化率", "广告视频播放达 2 秒播放率",
    "广告视频播放达 6 秒播放率", "广告视频播放达 25% 播放率",
    "广告视频播放达 50% 播放率", "广告视频播放达 75% 播放率",
    "广告视频完播率",
]

DISPLAY_COLUMNS = [
    "统计日期", "产品名称", "商品 ID", "广告计划名称", "创意作品类型",
    "视频标题", "视频 ID", "TikTok 账号", "状态", "授权类型", "成本",
    "SKU 订单数", "总收入", "ROI", "商品广告曝光数", "商品广告点击数",
    "商品广告点击率", "广告转化率", "广告视频播放达 2 秒播放率",
    "广告视频播放达 6 秒播放率", "广告视频播放达 25% 播放率",
    "广告视频播放达 50% 播放率", "广告视频播放达 75% 播放率",
    "广告视频完播率", "素材标签",
]

# 素材标签分类阈值的唯一来源：行级与素材级标签均使用此常量，前端不再自行计算。
TAG_THRESHOLDS = {"high_roi": 8.0, "low_roi": 1.5, "min_orders": 1}


def _daily_files() -> list[Path]:
    """daily_data 下的 xlsx 文件（跳过 Excel 临时锁文件 ~$*.xlsx），按文件名日期排序。"""
    if not DAILY_DATA_DIR.exists():
        return []
    files = [p for p in DAILY_DATA_DIR.glob("*.xlsx") if not p.name.startswith("~$")]
    return sorted(files, key=lambda p: _parse_report_month_day(p.name) or (99, 99))


def source_signature() -> str:
    """Return a cache key that changes when source files are added or updated."""
    files = list(_daily_files())
    files += list(MATCHING_TABLE_DIR.glob("*.xlsx")) if MATCHING_TABLE_DIR.exists() else []
    parts = [f"{p.name}:{p.stat().st_mtime_ns}:{p.stat().st_size}" for p in sorted(files)]
    return "|".join(parts)


def _normalize_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """把英文表头转换为面板内部中文列名；中文表头保持原样。"""
    renamed = {col: HEADER_MAP.get(str(col).strip(), str(col).strip()) for col in frame.columns}
    return frame.rename(columns=renamed)


def _normalize_id(value: object) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "n/a", "na", "-"}:
        return "N/A"
    # Excel sometimes exposes an integer ID as a float string.
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return text


def _parse_report_month_day(filename: str) -> tuple[int, int] | None:
    """从文件名解析 (月, 日)，无法识别时返回 None。"""
    stem = Path(filename).stem.strip()
    for fmt in ("%m.%d", "%m-%d", "%m_%d"):
        try:
            # 补一个固定年份消除无年份解析的歧义（Python 3.15 起无年份解析将变更行为）。
            parsed = datetime.strptime(f"2000-{stem}", f"%Y-{fmt}")
            return parsed.month, parsed.day
        except ValueError:
            continue
    return None


def _parse_report_date(filename: str) -> pd.Timestamp:
    """从文件名解析统计日期，跨年数据也能正确推断年份。

    文件名只有月.日（如 12.31.xlsx）。以今天为参考：若该月日晚于今天，
    说明属于上一年（例如今天 8 月，文件夹中的 12.31 是去年 12 月）。
    """
    month_day = _parse_report_month_day(filename)
    if month_day is None:
        return pd.NaT
    month, day = month_day
    today = datetime.now()
    year = today.year - 1 if (month, day) > (today.month, today.day) else today.year
    return pd.Timestamp(year=year, month=month, day=day)


def _numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(
        series.astype(str).str.replace(",", "", regex=False).str.strip().replace({"-": None, "N/A": None, "nan": None}),
        errors="coerce",
    ).fillna(0.0)


def _read_matching_table() -> pd.DataFrame:
    files = sorted(MATCHING_TABLE_DIR.glob("*.xlsx")) if MATCHING_TABLE_DIR.exists() else []
    if not files:
        return pd.DataFrame(columns=["商品 ID", "产品名称"])
    path = next((p for p in files if "SKU" in p.name or "sku" in p.name.lower()), files[0])
    table = pd.read_excel(path, dtype=str)
    if table.shape[1] < 2:
        return pd.DataFrame(columns=["商品 ID", "产品名称"])
    table = table.iloc[:, :2].copy()
    table.columns = ["商品 ID", "产品名称"]
    table["商品 ID"] = table["商品 ID"].map(_normalize_id)
    table["产品名称"] = table["产品名称"].fillna("未命名产品").astype(str).str.strip()
    table = table.drop_duplicates(subset=["商品 ID"], keep="last")
    return table


def load_data() -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """Load all daily reports, attach product names, and return quality notes."""
    files = _daily_files()
    quality_notes: list[str] = []
    frames: list[pd.DataFrame] = []

    for path in files:
        try:
            frame = pd.read_excel(path, dtype=str)
        except Exception as exc:  # pragma: no cover - surfaced in the UI
            quality_notes.append(f"无法读取 {path.name}: {exc}")
            continue
        if frame.empty:
            quality_notes.append(f"{path.name} 没有数据行")
            continue
        frame.columns = [str(c).strip() for c in frame.columns]
        frame = _normalize_columns(frame)
        frame["统计日期"] = _parse_report_date(path.name)
        frame["来源文件"] = path.name
        frames.append(frame)

    if not frames:
        return pd.DataFrame(), _read_matching_table(), quality_notes + ["daily_data 文件夹中没有可读取的 xlsx 文件。"]

    data = pd.concat(frames, ignore_index=True, sort=False)
    for col in ID_COLUMNS:
        if col in data.columns:
            data[col] = data[col].map(_normalize_id)
    for col in ["视频标题", "TikTok 账号", "状态", "授权类型", "创意作品类型", "货币"]:
        if col in data.columns:
            data[col] = data[col].fillna("N/A").astype(str).replace({"nan": "N/A"})
    if "创意作品类型" in data.columns:
        data["创意作品类型"] = data["创意作品类型"].replace(CREATIVE_TYPE_MAP)
    if "授权类型" in data.columns:
        data["授权类型"] = data["授权类型"].replace(AUTH_TYPE_MAP)
    for col in NUMERIC_COLUMNS:
        if col in data.columns:
            data[col] = _numeric(data[col])
        else:
            data[col] = 0.0

    mapping = _read_matching_table()
    data = data.merge(mapping, on="商品 ID", how="left")
    data["产品名称"] = data["产品名称"].fillna("未匹配产品")
    data["统计日期"] = pd.to_datetime(data["统计日期"], errors="coerce")

    # 新版表头不再提供 ROI 列，统一用 总收入/成本 计算；旧版保留原 ROI 作为兜底。
    data["计算ROI"] = data["总收入"].div(data["成本"].replace(0, pd.NA)).fillna(data["ROI"]).fillna(0)
    data["ROI"] = data["计算ROI"]
    data["素材标识"] = data.apply(_material_label, axis=1)
    data["素材标签"] = data.apply(lambda row: classify_material(row, **TAG_THRESHOLDS), axis=1)
    data["是否已匹配产品"] = data["产品名称"].ne("未匹配产品")
    data["来源文件"] = data["来源文件"].astype(str)

    unmatched = int((~data["是否已匹配产品"]).sum())
    if unmatched:
        quality_notes.append(f"有 {unmatched:,} 行数据未匹配到产品名称。")
    invalid_dates = int(data["统计日期"].isna().sum())
    if invalid_dates:
        quality_notes.append(f"有 {invalid_dates:,} 行数据无法从文件名识别统计日期。")
    miss = missing_dates(data)
    if miss:
        shown = "、".join(miss[:10]) + (" 等" if len(miss) > 10 else "")
        quality_notes.append(f"统计日期缺失 {len(miss)} 天：{shown}（daily_data 可能漏放文件）")
    return data, mapping, quality_notes


def _material_label(row: pd.Series) -> str:
    video_id = _normalize_id(row.get("视频 ID"))
    if video_id != "N/A":
        return video_id
    return f"{row.get('创意作品类型', '素材')} | {row.get('广告计划名称', '未命名计划')} | {row.get('商品 ID', 'N/A')}"


def classify_material(row: pd.Series, high_roi: float, low_roi: float, min_orders: int) -> str:
    cost = float(row.get("成本", 0) or 0)
    orders = float(row.get("SKU 订单数", 0) or 0)
    roi = float(row.get("计算ROI", row.get("ROI", 0)) or 0)
    clicks = float(row.get("商品广告点击数", 0) or 0)
    impressions = float(row.get("商品广告曝光数", 0) or 0)
    if cost > 0 and orders <= 0:
        return "有花费无订单"
    if impressions > 0 and clicks <= 0:
        return "有曝光无点击"
    if orders >= min_orders and roi >= high_roi:
        return "爆款素材"
    if roi >= high_roi:
        return "高效素材"
    if cost > 0 and roi < low_roi:
        return "低效素材"
    if orders > 0:
        return "正常素材"
    return "待观察"


def apply_material_labels(data: pd.DataFrame, high_roi: float, low_roi: float, min_orders: int) -> pd.DataFrame:
    result = data.copy()
    result["素材标签"] = result.apply(lambda row: classify_material(row, high_roi, low_roi, min_orders), axis=1)
    return result


# 素材生命周期判定阈值的唯一来源（前端只消费结果，不重复计算）。
LIFE_CYCLE_RULES = {
    "new_days": 7,             # 投放 ≤7 天视为新素材
    "compare_days": 7,         # 对比窗口天数（近 7 天 vs 前 7 天）
    "decline_threshold": 0.3,  # 近 7 天 ROI 较前 7 天下降 ≥30% 视为衰退中
}


def material_lifecycle(data: pd.DataFrame) -> dict[str, dict]:
    """按素材标识计算生命周期指标，返回 {素材标识: {...}}。

    指标：first_date 首投日期、days_active 投放天数（相对数据范围末日）、
    roi_recent / roi_prev（近 N 天 / 前 N 天 ROI）、roi_change（变化率，前段无
    花费时为 None）、stage（生命周期分类：新素材 / 衰退中 / 稳定 / 待观察）。

    分类规则（LIFE_CYCLE_RULES）：
    - 新素材：投放天数 ≤ new_days；
    - 衰退中：近 N 天有花费、前 N 天有花费，且 roi_change ≤ -decline_threshold；
    - 稳定：前 N 天有花费（有可比基线）且未达衰退；
    - 待观察：其余（前 N 天无花费或总无花费，无法比较）。
    """
    if data.empty or "素材标识" not in data.columns or "统计日期" not in data.columns:
        return {}
    days = int(LIFE_CYCLE_RULES["compare_days"])
    end = data["统计日期"].max()
    start_recent = end - pd.Timedelta(days=days - 1)
    start_prev = end - pd.Timedelta(days=2 * days - 1)

    def _roi(frame: pd.DataFrame) -> float | None:
        if frame.empty:
            return None
        cost = float(frame["成本"].sum())
        if cost <= 0:
            return None
        return float(frame["总收入"].sum()) / cost

    result: dict[str, dict] = {}
    for mid, group in data.groupby("素材标识"):
        recent = group[group["统计日期"] >= start_recent]
        prev = group[(group["统计日期"] >= start_prev) & (group["统计日期"] < start_recent)]
        roi_recent = _roi(recent)
        roi_prev = _roi(prev)
        roi_change = None
        if roi_recent is not None and roi_prev:
            roi_change = (roi_recent - roi_prev) / roi_prev
        first_date = group["统计日期"].min().strftime("%Y-%m-%d")
        days_active = int((end - group["统计日期"].min()).days) + 1
        if recent.empty:
            stage = "已停投"
        elif days_active <= int(LIFE_CYCLE_RULES["new_days"]):
            stage = "新素材"
        elif roi_change is not None and roi_change <= -LIFE_CYCLE_RULES["decline_threshold"]:
            stage = "衰退中"
        elif roi_change is not None:
            stage = "稳定"
        elif roi_recent is None:
            stage = "零消耗"
        elif roi_prev is None:
            stage = "新起量"
        else:
            stage = "待观察"
        result[_normalize_id(mid)] = {
            "first_date": first_date,
            "days_active": days_active,
            "roi_recent": round(roi_recent, 4) if roi_recent is not None else None,
            "roi_prev": round(roi_prev, 4) if roi_prev is not None else None,
            "roi_change": round(roi_change, 4) if roi_change is not None else None,
            "stage": stage,
        }
    return result


def missing_dates(data: pd.DataFrame) -> list[str]:
    """检测 daily_data 覆盖区间内的缺失统计日期。

    按月份分组检测（7 月与 8 月文件并存时各月独立判断）：
    每月取该月已有的最小/最大日期作为区间，区间内缺少的日期即视为缺失。
    返回 ISO 格式日期列表，如 ["2026-07-15", "2026-08-02"]。
    """
    if data.empty or "统计日期" not in data.columns:
        return []
    dates = data["统计日期"].dropna()
    if dates.empty:
        return []
    missing: list[str] = []
    for _, month_dates in dates.groupby(dates.dt.to_period("M")):
        month_dates = month_dates.dt.normalize().sort_values()
        full = pd.date_range(month_dates.min(), month_dates.max(), freq="D")
        have = set(month_dates)
        for day in full:
            if day not in have:
                missing.append(day.strftime("%Y-%m-%d"))
    return missing


def aggregate_material_tags(data: pd.DataFrame) -> dict[str, str]:
    """按素材标识聚合后分类，返回 {素材标识: 素材标签}（素材级标签）。

    与行级 素材标签 字段使用同一 classify_material 与 TAG_THRESHOLDS，
    保证前端展示的素材排行榜标签与后端口径一致。
    """
    if data.empty or "素材标识" not in data.columns:
        return {}
    agg = (
        data.groupby("素材标识", as_index=False)
        .agg(
            **{
                "成本": ("成本", "sum"),
                "SKU 订单数": ("SKU 订单数", "sum"),
                "总收入": ("总收入", "sum"),
                "商品广告曝光数": ("商品广告曝光数", "sum"),
                "商品广告点击数": ("商品广告点击数", "sum"),
            }
        )
    )
    agg["计算ROI"] = agg["总收入"].div(agg["成本"].replace(0, pd.NA)).fillna(0)
    tags: dict[str, str] = {}
    for rec in agg.to_dict(orient="records"):
        tags[_normalize_id(rec.get("素材标识"))] = classify_material(rec, **TAG_THRESHOLDS)
    return tags


def aggregate_metrics(data: pd.DataFrame, group_cols: Iterable[str] | None = None) -> pd.DataFrame:
    group_cols = list(group_cols or [])
    if data.empty:
        return pd.DataFrame(columns=group_cols)
    numeric_sum = [
        "成本", "SKU 订单数", "总收入", "商品广告曝光数", "商品广告点击数"
    ]
    if group_cols:
        result = data.groupby(group_cols, dropna=False, as_index=False)[numeric_sum].sum()
    else:
        result = pd.DataFrame({col: [data[col].sum()] for col in numeric_sum})
    result["ROI"] = result["总收入"].div(result["成本"].replace(0, pd.NA)).fillna(0)
    result["平均下单成本"] = result["成本"].div(result["SKU 订单数"].replace(0, pd.NA)).fillna(0)
    result["商品广告点击率"] = result["商品广告点击数"].div(result["商品广告曝光数"].replace(0, pd.NA)).fillna(0)
    result["广告转化率"] = result["SKU 订单数"].div(result["商品广告点击数"].replace(0, pd.NA)).fillna(0)
    result["收入占比"] = result["总收入"].div(result["总收入"].sum() or 1)
    return result


def export_xlsx(data: pd.DataFrame) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        data.to_excel(writer, index=False, sheet_name="Dashboard Export")
    return output.getvalue()
