from __future__ import annotations

import json
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

# 面板核心指标必需列：任一缺失说明 TikTok 导出表头已变化，整文件跳过并告警，
# 而不是静默补 0（静默归零会让运营基于错误数据做决策）。
REQUIRED_COLUMNS = [
    "商品 ID", "成本", "总收入", "SKU 订单数",
    "商品广告曝光数", "商品广告点击数",
]

# 展示用文本列：缺失时补 "N/A"，保证下游聚合（top/lifecycle/前端）不会因缺列崩溃。
TEXT_COLUMNS = [
    "视频标题", "TikTok 账号", "状态", "授权类型",
    "创意作品类型", "货币", "广告计划名称",
]


def _xlsx_files(directory: Path) -> list[Path]:
    """目录下的 xlsx 文件（跳过 Excel 临时锁文件 ~$*.xlsx），按名称排序。

    所有读取 Excel 的入口（daily_data、SKU 匹配表）都必须经过这里，
    否则用户用 Excel 打开文件时，锁文件会被误当成数据源解析。
    """
    if not directory.exists():
        return []
    return sorted(p for p in directory.glob("*.xlsx") if not p.name.startswith("~$"))


def _daily_files() -> list[Path]:
    """daily_data 下的 xlsx 文件，按统计日期排序（无法识别日期的排最后）。"""
    def sort_key(path: Path):
        d = _parse_report_date(path.name)
        return (bool(pd.isna(d)), d if not pd.isna(d) else pd.Timestamp.min)
    return sorted(_xlsx_files(DAILY_DATA_DIR), key=sort_key)


def source_signature() -> str:
    """Return a cache key that changes when source files are added or updated."""
    files = list(_daily_files())
    files += _xlsx_files(MATCHING_TABLE_DIR)
    lifecycle_config = BASE_DIR / LIFECYCLE_CONFIG_NAME
    if lifecycle_config.exists():
        files.append(lifecycle_config)
    parts = [f"{p.name}:{p.stat().st_mtime_ns}:{p.stat().st_size}" for p in sorted(files)]
    return "|".join(parts)


# 表头映射的大小写不敏感索引：TikTok 导出表头大小写变化时仍能识别。
HEADER_MAP_CI = {k.casefold(): v for k, v in HEADER_MAP.items()}


def _normalize_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """把英文表头转换为面板内部中文列名；中文表头保持原样，英文大小写不敏感。"""
    renamed = {}
    for col in frame.columns:
        name = str(col).strip()
        renamed[col] = HEADER_MAP.get(name) or HEADER_MAP_CI.get(name.casefold()) or name
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


# 文件名完整日期格式：优先解析，避免跨年推断把去年同月数据错归今年。
DATE_FORMATS = ("%Y-%m-%d", "%Y.%m.%d", "%Y_%m_%d", "%Y%m%d")


def _parse_report_month_day(filename: str) -> tuple[int, int] | None:
    """从文件名解析 (月, 日)，无法识别时返回 None。

    仅处理无年份月日格式（8.13 / 8-13 / 8_13）。
    """
    stem = Path(filename).stem.strip()
    for fmt in ("%m.%d", "%m-%d", "%m_%d"):
        try:
            # 补一个固定年份消除无年份解析的歧义（Python 3.15 起无年份解析将变更行为）。
            parsed = datetime.strptime(f"2000-{stem}", f"%Y-{fmt}")
            return parsed.month, parsed.day
        except ValueError:
            continue
    return None


def _parse_report_date(filename: str, today: datetime | None = None) -> pd.Timestamp:
    """从文件名解析统计日期，无法识别时返回 pd.NaT。

    支持：
      - 完整日期：2026-08-12 / 2026.08.12 / 2026_08_12 / 20260812（优先，无跨年歧义）
      - 月日（按“晚于今天归上一年”推断）：8.13 / 8-13 / 8_13

    today 参数仅供测试/确定性推断；生产默认使用当前日期。
    """
    stem = Path(filename).stem.strip()
    for fmt in DATE_FORMATS:
        try:
            parsed = datetime.strptime(stem, fmt)
            return pd.Timestamp(parsed)
        except ValueError:
            continue
    month_day = _parse_report_month_day(filename)
    if month_day is None:
        return pd.NaT
    month, day = month_day
    ref = today or datetime.now()
    year = ref.year - 1 if (month, day) > (ref.month, ref.day) else ref.year
    return pd.Timestamp(year=year, month=month, day=day)


def _numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(
        series.astype(str).str.replace(",", "", regex=False).str.strip().replace({"-": None, "N/A": None, "nan": None}),
        errors="coerce",
    ).fillna(0.0)


# SKU 匹配表表头别名：用于校验前两列确实是 商品 ID / 产品名称。
MATCHING_ID_HEADERS = {"商品 id", "商品id", "product id", "product_id", "sku id", "sku_id", "goods id"}
MATCHING_NAME_HEADERS = {"产品名称", "产品名", "product name", "product_name", "goods name"}


def _matching_headers_ok(table: pd.DataFrame) -> bool:
    if table.shape[1] < 2:
        return False
    cols = [str(c).strip().lower() for c in table.columns[:2]]
    return cols[0] in MATCHING_ID_HEADERS and cols[1] in MATCHING_NAME_HEADERS


def _read_matching_table() -> tuple[pd.DataFrame, list[str]]:
    """读取 SKU 匹配表，返回 (映射表, 质量提示)。

    规则：
    - 文件名含 sku 的文件优先；同组内取最新修改的一个；
    - 表头校验（商品 ID / 产品名称），含标题行的表格自动改用第二行作表头；
    - 同一商品 ID 对应多个不同产品名称时保留最后一条并告警。
    """
    files = _xlsx_files(MATCHING_TABLE_DIR)
    if not files:
        return pd.DataFrame(columns=["商品 ID", "产品名称"]), []
    notes: list[str] = []
    pool = [p for p in files if "sku" in p.name.lower()] or files
    path = max(pool, key=lambda p: p.stat().st_mtime_ns)
    if len(files) > 1:
        notes.append(f"SKU 匹配表目录有 {len(files)} 个 xlsx 文件，已选用最新修改的 {path.name}。")

    table = pd.read_excel(path, dtype=str).iloc[:, :2].copy()
    if not _matching_headers_ok(table):
        # 常见情形：第一行是标题行（如「SKU 匹配表」），真正的表头在第二行。
        try:
            retry = pd.read_excel(path, dtype=str, header=1).iloc[:, :2].copy()
        except Exception:
            retry = pd.DataFrame()
        if _matching_headers_ok(retry):
            table = retry
        else:
            notes.append(f"{path.name} 表头无法识别（期待 商品 ID / 产品名称），已按前两列读取。")
    if table.shape[1] < 2:
        return pd.DataFrame(columns=["商品 ID", "产品名称"]), [f"{path.name} 少于两列，无法作为 SKU 匹配表。"]
    table.columns = ["商品 ID", "产品名称"]
    table["商品 ID"] = table["商品 ID"].map(_normalize_id)
    table["产品名称"] = table["产品名称"].fillna("未命名产品").astype(str).str.strip()
    conflicts = table.duplicated(subset=["商品 ID"], keep=False)
    if conflicts.any():
        n_conflict = int((table[conflicts].groupby("商品 ID")["产品名称"].nunique() > 1).sum())
        if n_conflict:
            notes.append(f"{path.name} 有 {n_conflict} 个商品 ID 对应多个不同产品名称，已保留最后一条。")
    table = table.drop_duplicates(subset=["商品 ID"], keep="last")
    return table, notes


def _read_matching_table_safe() -> tuple[pd.DataFrame, list[str]]:
    """读取 SKU 匹配表；文件损坏/被占用时返回空表 + 告警，而不是让整个看板崩溃。"""
    try:
        return _read_matching_table()
    except Exception as exc:  # pragma: no cover - 取决于用户文件状态
        return pd.DataFrame(columns=["商品 ID", "产品名称"]), [f"无法读取 SKU 匹配表: {exc}"]


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
        # schema 校验：核心指标列缺失 = 表头已变化，跳过该文件并告警（fail-closed）。
        missing = [c for c in REQUIRED_COLUMNS if c not in frame.columns]
        if missing:
            quality_notes.append(f"{path.name} 缺少必需列（{', '.join(missing)}），已跳过：TikTok 导出表头可能已变化。")
            continue
        report_date = _parse_report_date(path.name)
        if pd.isna(report_date):
            quality_notes.append(
                f"{path.name} 文件名无法识别统计日期，已跳过（支持 2026-08-12、20260812、8.13 等格式）。"
            )
            continue
        frame["统计日期"] = report_date
        frame["来源文件"] = path.name
        frames.append(frame)

    if not frames:
        mapping, map_notes = _read_matching_table_safe()
        return pd.DataFrame(), mapping, quality_notes + map_notes + ["daily_data 文件夹中没有可读取的 xlsx 文件。"]

    data = pd.concat(frames, ignore_index=True, sort=False)
    for col in ID_COLUMNS:
        if col in data.columns:
            data[col] = data[col].map(_normalize_id)
        else:
            data[col] = "N/A"
    for col in TEXT_COLUMNS:
        if col in data.columns:
            data[col] = data[col].fillna("N/A").astype(str).replace({"nan": "N/A"})
        else:
            data[col] = "N/A"
    if "创意作品类型" in data.columns:
        data["创意作品类型"] = data["创意作品类型"].replace(CREATIVE_TYPE_MAP)
    if "授权类型" in data.columns:
        data["授权类型"] = data["授权类型"].replace(AUTH_TYPE_MAP)
    for col in NUMERIC_COLUMNS:
        if col in data.columns:
            data[col] = _numeric(data[col])
        else:
            data[col] = 0.0

    mapping, map_notes = _read_matching_table_safe()
    quality_notes.extend(map_notes)
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
    # 货币告警：面板前端目前按 USD 展示金额，多币种数据会被静默加总。
    currencies = set()
    for value in data["货币"].astype(str).str.strip().str.upper():
        if value and value not in {"N/A", "NAN", "NONE", "NA", "-"}:
            currencies.add(value)
    non_usd = sorted(currencies - USD_CURRENCY_LABELS)
    if non_usd:
        quality_notes.append(f"检测到非 USD 货币（{', '.join(non_usd)}）：面板金额目前统一按 USD 展示，跨币种汇总可能不准确。")
    _, lifecycle_warning = _lifecycle_rules()
    if lifecycle_warning:
        quality_notes.append(lifecycle_warning)
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
        return "低效素材"  # 原"有花费无订单"，并入低效
    if impressions > 0 and clicks <= 0:
        return "低效素材"  # 原"有曝光无点击"，并入低效
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
# 可在面板根目录放 lifecycle_rules.json 覆盖（{"new_days": 7, "compare_days": 7, "decline_threshold": 0.3}）。
DEFAULT_LIFE_CYCLE_RULES = {
    "new_days": 7,             # 投放 ≤7 天视为新素材
    "compare_days": 7,         # 对比窗口天数（近 7 天 vs 前 7 天）
    "decline_threshold": 0.3,  # 近 7 天 ROI 较前 7 天下降 ≥30% 视为衰退中
}
LIFECYCLE_CONFIG_NAME = "lifecycle_rules.json"

# 金额展示货币约定：前端按 USD 展示；出现其他币种时写入数据质量告警。
USD_CURRENCY_LABELS = {"USD", "US$", "$", "US DOLLAR", "USD DOLLAR", "DOLLAR"}


def _lifecycle_rules() -> tuple[dict, str | None]:
    """返回生命周期规则与配置告警；配置缺失/损坏时回退内置规则。"""
    rules = dict(DEFAULT_LIFE_CYCLE_RULES)
    path = BASE_DIR / LIFECYCLE_CONFIG_NAME
    if not path.exists():
        return rules, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - 配置错误回退默认即可
        return rules, f"无法读取 {path.name}: {exc}，已使用内置生命周期规则。"
    if not isinstance(data, dict):
        return rules, f"{path.name} 格式无效（应为 {{new_days, compare_days, decline_threshold}}），已使用内置生命周期规则。"
    warning = None
    for key in rules:
        if key not in data:
            continue
        value = data[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            warning = f"{path.name} 的 {key} 值无效，该项已使用内置值。"
            continue
        rules[key] = float(value) if key == "decline_threshold" else int(value)
    return rules, warning


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
    # 防御：丢弃无日期行，避免 NaT.strftime 崩溃（load_data 已跳过无法识别日期的文件）。
    data = data[data["统计日期"].notna()]
    if data.empty:
        return {}
    rules, _ = _lifecycle_rules()
    days = int(rules["compare_days"])
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
        elif days_active <= int(rules["new_days"]):
            stage = "新素材"
        elif roi_change is not None and roi_change <= -rules["decline_threshold"]:
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
