from __future__ import annotations

import argparse
import gzip
import json
import secrets
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from data_loader import aggregate_material_tags, load_data, material_lifecycle, missing_dates, source_signature, _normalize_id
from inventory_loader import inventory_signature, load_inventory


BASE_DIR = Path(__file__).resolve().parent
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", BASE_DIR)) if getattr(sys, "frozen", False) else BASE_DIR
STATIC_FILE = RESOURCE_DIR / "static" / "dashboard.html"
INVENTORY_FILE = RESOURCE_DIR / "static" / "inventory.html"

# /static/* 白名单：仅允许这些文件，防止路径遍历。
STATIC_ALLOWED = {
    "app.css": "text/css; charset=utf-8",
    "app.js": "application/javascript; charset=utf-8",
    "inventory.css": "text/css; charset=utf-8",
    "inventory.js": "application/javascript; charset=utf-8",
}

# /api/data 响应缓存：源文件（daily_data、SKU 匹配表）未变化时直接复用，
# 避免每次刷新页面都重新解析全部 Excel。gzip 压缩版本单独缓存，避免重复压缩。
_CACHE_LOCK = threading.Lock()
_DATA_CACHE: dict = {"sig": None, "body": None, "body_gz": None}
# P0-1：DataFrame 级缓存（按源文件 signature 复用 load_data 的解析结果），
# /api/top 与 /api/data 共用，避免每次请求重新解析全部 Excel。
_DF_CACHE: dict = {"sig": None, "data": None, "mapping": None, "notes": None}


def _load_data_cached():
    """load_data() 结果缓存：源文件未变化时直接复用内存 DataFrame。"""
    sig = source_signature()
    with _CACHE_LOCK:
        if _DF_CACHE["sig"] == sig and _DF_CACHE["data"] is not None:
            return _DF_CACHE["data"], _DF_CACHE["mapping"], _DF_CACHE["notes"]
    data, mapping, notes = load_data()
    with _CACHE_LOCK:
        if _DF_CACHE["sig"] != sig:
            _DF_CACHE.update(sig=sig, data=None, mapping=None, notes=None)
        _DF_CACHE["data"] = data
        _DF_CACHE["mapping"] = mapping
        _DF_CACHE["notes"] = notes
    return data, mapping, notes


def _build_data_payload() -> dict:
    data, mapping, notes = _load_data_cached()
    if data.empty:
        return {"meta": {"error": "没有读取到 daily_data 中的 Excel 文件。"}, "rows": []}
    data = data.copy()
    material_tags = aggregate_material_tags(data)
    lifecycle = material_lifecycle(data)
    missing = missing_dates(data)
    data["统计日期"] = data["统计日期"].dt.strftime("%Y-%m-%d")
    # Keep the API compact while retaining all dashboard dimensions.
    keep = [
        "统计日期", "产品名称", "商品 ID", "广告计划名称", "广告计划 ID",
        "创意作品类型", "视频标题", "视频 ID", "TikTok 账号", "状态", "授权类型",
        "成本", "SKU 订单数", "平均下单成本", "总收入", "ROI", "商品广告曝光数",
        "商品广告点击数", "商品广告点击率", "广告转化率", "广告视频播放达 2 秒播放率",
        "广告视频播放达 6 秒播放率", "广告视频播放达 25% 播放率",
        "广告视频播放达 50% 播放率", "广告视频播放达 75% 播放率",
        "广告视频完播率", "素材标识", "素材标签", "是否已匹配产品",
    ]
    keep = [c for c in keep if c in data.columns]
    rows = json.loads(data[keep].to_json(orient="records", force_ascii=False))
    return {
        "meta": {
            "rows": len(data),
            "files": int(data["来源文件"].nunique()),
            "mapping": len(mapping),
            "min_date": data["统计日期"].min(),
            "max_date": data["统计日期"].max(),
            "notes": notes,
            "signature": source_signature(),
            "material_tags": material_tags,
            "material_lifecycle": lifecycle,
            "missing_dates": missing,
        },
        "rows": rows,
    }


def _build_meta_payload() -> dict:
    """轻量数据概况（P0-2）：只返回 meta 聚合统计，不含 rows，响应 <10KB。

    material_tags/material_lifecycle 以计数形式返回（各标签/各阶段多少个），
    避免逐素材全量映射占用传输与 token。
    """
    data, mapping, notes = _load_data_cached()
    if data.empty:
        return {"error": "没有读取到 daily_data 中的 Excel 文件。"}
    import collections
    material_tags = aggregate_material_tags(data)
    lifecycle = material_lifecycle(data)
    missing = missing_dates(data)
    return {
        "rows": int(len(data)),
        "files": int(data["来源文件"].nunique()),
        "mapping": len(mapping),
        "min_date": str(data["统计日期"].min().date()),
        "max_date": str(data["统计日期"].max().date()),
        "notes": notes,
        "missing_dates": [str(d) for d in missing],
        "material_tags_count": dict(collections.Counter(material_tags.values())),
        "material_lifecycle_count": dict(collections.Counter(v.get("stage") or "未知" for v in lifecycle.values())),
    }


def _filter_product(df, product: str):
    """product 参数统一语义（top/trend/lifecycle 共用）：

    按“产品名称 / 商品 ID”做包含匹配，大小写不敏感、按字面量匹配（product 中的
    正则特殊字符不会产生正则语义）。库存数据由插件侧按“产品代码 / SKU / 商品名”匹配。
    """
    product = (product or "").strip().lower()
    if not product:
        return df
    name = df["产品名称"].astype(str).str.lower()
    pid = df["商品 ID"].astype(str).str.lower()
    mask = name.str.contains(product, na=False, regex=False) | pid.str.contains(product, na=False, regex=False)
    return df[mask]


def _build_trend_payload(params: dict) -> dict:
    """按天趋势聚合（P1-4）。

    参数：product（产品过滤）、date_from/date_to（区间）、days（可选 N：
    自动把数据分成"近 N 天"与"前 N 天"两段并返回环比 change）。
    返回按天序列（统计日期/总收入/成本/SKU订单数/曝光/点击）与合计。
    """
    data, mapping, notes = _load_data_cached()
    if data.empty:
        return {"error": "没有读取到 daily_data 中的 Excel 文件。"}
    import pandas as pd
    df = data.copy()
    df = _filter_product(df, params.get("product", ""))
    date_from = params.get("date_from", "")
    date_to = params.get("date_to", "")
    if date_from:
        df = df[df["统计日期"] >= pd.Timestamp(date_from)]
    if date_to:
        df = df[df["统计日期"] <= pd.Timestamp(date_to)]
    if df.empty:
        return {"error": "所选范围内没有数据。"}

    def agg_series(sub):
        g = sub.groupby("统计日期").agg(
            总收入=("总收入", "sum"), 成本=("成本", "sum"),
            SKU订单数=("SKU 订单数", "sum"), 曝光=("商品广告曝光数", "sum"),
            点击=("商品广告点击数", "sum"),
        ).reset_index()
        g["统计日期"] = g["统计日期"].dt.strftime("%Y-%m-%d")
        for col in ("总收入", "成本", "SKU订单数", "曝光", "点击"):
            g[col] = g[col].fillna(0)
        return json.loads(g.to_json(orient="records", force_ascii=False))

    def totals(series):
        rev = sum(float(r["总收入"]) for r in series)
        cost = sum(float(r["成本"]) for r in series)
        return {
            "收入": round(rev, 2),
            "成本": round(cost, 2),
            "订单": int(sum(float(r["SKU订单数"]) for r in series)),
            "ROI": round(rev / cost, 2) if cost else 0,
        }

    days_n = 0
    raw_days = params.get("days", "")
    if raw_days:
        try:
            days_n = max(1, min(int(raw_days), 90))
        except (TypeError, ValueError):
            days_n = 0
    if days_n:
        max_date = df["统计日期"].max()
        recent = agg_series(df[df["统计日期"] >= max_date - pd.Timedelta(days=days_n - 1)])
        prev = agg_series(df[(df["统计日期"] >= max_date - pd.Timedelta(days=2 * days_n - 1))
                             & (df["统计日期"] <= max_date - pd.Timedelta(days=days_n))])
        t_recent, t_prev = totals(recent), totals(prev)
        change = {}
        for key in ("收入", "成本", "订单", "ROI"):
            base = t_prev.get(key) or 0
            change[key + "环比%"] = round((t_recent.get(key) - base) / base * 100, 1) if base else None
        return {
            "days": days_n,
            "recent": {"days": recent, "totals": t_recent},
            "previous": {"days": prev, "totals": t_prev},
            "change": change,
        }
    series = agg_series(df)
    return {"days": series, "totals": totals(series)}


def _build_lifecycle_payload(params: dict) -> dict:
    """素材生命周期清单（P1-5）。

    参数：stage（可选，阶段过滤：新素材/新起量/稳定/衰退中/已停投/零消耗/待观察）、
    product（可选，产品过滤）、limit（返回行数，默认 50）。
    每条素材附聚合指标（总收入/成本/SKU订单数/曝光/点击、视频标题、产品名称），
    按总收入降序排列。
    """
    data, mapping, notes = _load_data_cached()
    if data.empty:
        return {"error": "没有读取到 daily_data 中的 Excel 文件。"}
    import pandas as pd
    df = data.copy()
    df = _filter_product(df, params.get("product", ""))
    date_from = params.get("date_from", "")
    date_to = params.get("date_to", "")
    if date_from:
        df = df[df["统计日期"] >= pd.Timestamp(date_from)]
    if date_to:
        df = df[df["统计日期"] <= pd.Timestamp(date_to)]
    if df.empty:
        return {"error": "所选范围内没有数据。"}
    lifecycle = material_lifecycle(df)
    agg = (
        df.groupby("素材标识", dropna=False)
        .agg(
            总收入=("总收入", "sum"), 成本=("成本", "sum"),
            SKU订单数=("SKU 订单数", "sum"), 曝光=("商品广告曝光数", "sum"),
            点击=("商品广告点击数", "sum"), 视频标题=("视频标题", "first"),
            产品名称=("产品名称", "first"),
        )
        .reset_index()
    )
    agg_map = {}
    for rec in agg.to_dict(orient="records"):
        agg_map[_normalize_id(rec.get("素材标识"))] = rec
    rows = []
    for mid, info in lifecycle.items():
        extra = agg_map.get(mid, {})
        row = dict(info)
        row["素材标识"] = mid
        row["总收入"] = round(float(extra.get("总收入") or 0), 2)
        row["成本"] = round(float(extra.get("成本") or 0), 2)
        row["SKU订单数"] = int(extra.get("SKU订单数") or 0)
        row["曝光"] = int(extra.get("曝光") or 0)
        row["点击"] = int(extra.get("点击") or 0)
        row["视频标题"] = extra.get("视频标题") or ""
        row["产品名称"] = extra.get("产品名称") or ""
        rows.append(row)
    stage = params.get("stage", "")
    if stage:
        rows = [r for r in rows if r.get("stage") == stage]
    rows.sort(key=lambda r: r.get("总收入") or 0, reverse=True)
    try:
        limit = max(1, min(int(params.get("limit", 50)), 200))
    except (TypeError, ValueError):
        limit = 50
    stage_count: dict = {}
    for r in rows:
        s = r.get("stage") or "未知"
        stage_count[s] = stage_count.get(s, 0) + 1
    return {
        "total": len(rows),
        "stage": stage or None,
        "stage_count": stage_count,
        "rows": rows[:limit],
    }


def _build_top_payload(params: dict) -> dict:
    """按视频 ID 聚合广告数据并返回 Top N（P0-1：聚合下沉到服务端）。

    参数：product（产品名称包含匹配）、metric（revenue/orders/roi/impressions）、
    date_from/date_to（统计日期区间，YYYY-MM-DD）、limit（返回行数）。
    数据源复用 load_data() 的解析缓存，聚合在内存 DataFrame 上完成。
    """
    data, mapping, notes = _load_data_cached()
    if data.empty:
        return {"meta": {"error": "没有读取到 daily_data 中的 Excel 文件。"}, "rows": []}
    import pandas as pd
    df = data.copy()
    df = _filter_product(df, params.get("product", ""))
    date_from = params.get("date_from", "")
    date_to = params.get("date_to", "")
    if date_from:
        df = df[df["统计日期"] >= pd.Timestamp(date_from)]
    if date_to:
        df = df[df["统计日期"] <= pd.Timestamp(date_to)]
    df["视频 ID"] = df["视频 ID"].fillna("N/A").astype(str)
    g = df.groupby("视频 ID", dropna=False).agg(
        总收入=("总收入", "sum"),
        成本=("成本", "sum"),
        SKU订单数=("SKU 订单数", "sum"),
        曝光=("商品广告曝光数", "sum"),
        点击=("商品广告点击数", "sum"),
        视频标题=("视频标题", "first"),
        素材标识=("素材标识", "first"),
        素材标签=("素材标签", "first"),
    ).reset_index()
    g["总收入"] = g["总收入"].fillna(0)
    g["成本"] = g["成本"].fillna(0)
    g["SKU订单数"] = g["SKU订单数"].fillna(0)
    g["曝光"] = g["曝光"].fillna(0)
    g["点击"] = g["点击"].fillna(0)
    metric = params.get("metric", "revenue")
    if metric == "roi":
        g["ROI"] = (g["总收入"] / g["成本"].replace(0, float("nan"))).fillna(0)
        g = g.sort_values("ROI", ascending=False)
    else:
        key = {"revenue": "总收入", "orders": "SKU订单数", "impressions": "曝光"}.get(metric, "总收入")
        g = g.sort_values(key, ascending=False)
    try:
        limit = max(1, min(int(params.get("limit", 10)), 50))
    except (TypeError, ValueError):
        limit = 10
    top = g.head(limit)
    return {
        "total_videos": int(g.shape[0]),
        "rows": json.loads(top.to_json(orient="records", force_ascii=False)),
    }


def _cached_data_body(gzipped: bool = False) -> bytes:
    """源文件未变时复用上次序列化结果，否则重新解析并更新缓存。

    未压缩版本（body）始终缓存，gzip 版本（body_gz）按需缓存；
    任一入口先命中后，另一入口都无需重新解析 Excel。
    """
    sig = source_signature()
    key = "body_gz" if gzipped else "body"
    with _CACHE_LOCK:
        if _DATA_CACHE["sig"] == sig:
            if _DATA_CACHE[key] is not None:
                return _DATA_CACHE[key]
            if gzipped and _DATA_CACHE["body"] is not None:
                compressed = gzip.compress(_DATA_CACHE["body"], compresslevel=6)
                _DATA_CACHE["body_gz"] = compressed
                return compressed
    payload = json.dumps(_build_data_payload(), ensure_ascii=False).encode("utf-8")
    body = gzip.compress(payload, compresslevel=6) if gzipped else payload
    with _CACHE_LOCK:
        if _DATA_CACHE["sig"] != sig:
            _DATA_CACHE.update(sig=sig, body=None, body_gz=None)
        _DATA_CACHE["body"] = payload
        if gzipped:
            _DATA_CACHE["body_gz"] = body
    return body


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "TK-GMVMAX-FBT/1.0"

    # --token 访问令牌：None 表示不启用鉴权（默认仅本机 127.0.0.1 的模式）。
    # main() 启动前写入该类属性；局域网模式未显式指定令牌时自动生成。
    auth_token: str | None = None

    def _authorized(self) -> bool:
        """/api/* 鉴权：令牌可通过 query 的 token 参数、X-TK-Token 头或 Bearer 头提供。"""
        token = type(self).auth_token
        if not token:
            return True
        query = parse_qs(urlparse(self.path).query)
        if token in query.get("token", []):
            return True
        if self.headers.get("X-TK-Token") == token:
            return True
        if self.headers.get("Authorization") == f"Bearer {token}":
            return True
        return False

    def _send(self, content: bytes, content_type: str, status: int = 200, precompressed: bool = False,
              extra_headers: dict | None = None) -> None:
        """响应统一出口：小文件按需现场 gzip，precompressed 表示 content 已是 gzip。

        支持 gzip 时自动压缩（Content-Encoding: gzip），浏览器 fetch 会自动解压。
        """
        if precompressed:
            content_encoding = "gzip"
        elif len(content) > 1024 and "gzip" in self.headers.get("Accept-Encoding", ""):
            content = gzip.compress(content, compresslevel=6)
            content_encoding = "gzip"
        else:
            content_encoding = None
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        if content_encoding:
            self.send_header("Content-Encoding", content_encoding)
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):  # noqa: N802
        """请求统一入口：任何未捕获异常都转成 JSON 500，避免浏览器端连接 reset。"""
        try:
            self._route_get()
        except (BrokenPipeError, ConnectionResetError):
            # 客户端提前断开，无需也无法响应。
            return
        except Exception as exc:  # noqa: BLE001 - 本地面板需要把错误内容回给浏览器
            try:
                payload = json.dumps(
                    {"error": f"服务器内部错误: {exc}"}, ensure_ascii=False
                ).encode("utf-8")
                self._send(payload, "application/json; charset=utf-8", 500)
            except Exception:
                # 响应通道已损坏时只能放弃。
                pass

    def _route_get(self) -> None:
        path = urlparse(self.path).path
        if path.startswith("/api/") and not self._authorized():
            payload = json.dumps(
                {"error": "未授权：请在 URL 携带 token 参数，或设置 X-TK-Token / Authorization 请求头。"},
                ensure_ascii=False,
            ).encode("utf-8")
            self._send(payload, "application/json; charset=utf-8", 401)
            return
        if path.startswith("/static/"):
            name = path[len("/static/"):]
            if name in STATIC_ALLOWED:
                self._send((RESOURCE_DIR / "static" / name).read_bytes(), STATIC_ALLOWED[name])
            else:
                self._send(b"Not Found", "text/plain; charset=utf-8", 404)
            return
        if path in {"/", "/index.html"}:
            self._send(STATIC_FILE.read_bytes(), "text/html; charset=utf-8")
            return
        if path == "/api/lifecycle":
            query = parse_qs(urlparse(self.path).query)
            params = {k: (v[0] if v else "") for k, v in query.items()}
            payload = _build_lifecycle_payload(params)
            self._send(json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
            return
        if path == "/api/trend":
            query = parse_qs(urlparse(self.path).query)
            params = {k: (v[0] if v else "") for k, v in query.items()}
            payload = _build_trend_payload(params)
            self._send(json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
            return
        if path == "/api/signature":
            # P2-9：轻量签名端点（几字节），供插件对比源文件是否变化以失效缓存。
            self._send(json.dumps({"signature": source_signature()}).encode("utf-8"), "application/json; charset=utf-8")
            return
        if path == "/api/inventory-signature":
            # 库存文件签名（几字节）：插件查询库存前对比，KCXQ 更新后立即失效插件缓存。
            self._send(json.dumps({"signature": inventory_signature()}).encode("utf-8"), "application/json; charset=utf-8")
            return
        if path == "/api/meta":
            self._send(json.dumps(_build_meta_payload(), ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
            return
        if path == "/api/top":
            query = parse_qs(urlparse(self.path).query)
            params = {k: (v[0] if v else "") for k, v in query.items()}
            payload = _build_top_payload(params)
            self._send(json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
            return
        if path == "/api/data":
            gzipped = "gzip" in self.headers.get("Accept-Encoding", "")
            self._send(_cached_data_body(gzipped=gzipped), "application/json; charset=utf-8", precompressed=gzipped)
            return
        if path == "/inventory":
            self._send(INVENTORY_FILE.read_bytes(), "text/html; charset=utf-8")
            return
        if path == "/api/inventory":
            etag = inventory_signature()
            if self.headers.get("If-None-Match") == etag:
                # 库存文件未变化：返回 304，前端 60 秒轮询几乎零成本。
                self.send_response(304)
                self.send_header("Cache-Control", "no-store")
                self.send_header("ETag", etag)
                self.end_headers()
                return
            payload = load_inventory()
            self._send(json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8", extra_headers={"ETag": etag})
            return
        self._send(b"Not Found", "text/plain; charset=utf-8", 404)

    def log_message(self, format, *args):  # noqa: A002
        print(f"[{self.log_date_time_string()}] {format % args}")


def _ensure_data_dirs() -> None:
    """数据文件夹不存在时自动创建，并放入说明文件。"""
    for folder in ["daily_data", "SKU Matching Table", "KCXQ"]:
        d = BASE_DIR / folder
        if not d.exists():
            try:
                d.mkdir()
                (d / "说明.txt").write_text(
                    "把数据 Excel 文件放到这个文件夹，然后刷新面板页面即可。",
                    encoding="utf-8",
                )
            except OSError:
                pass


def _lan_urls(port: int) -> list[str]:
    """获取本机在局域网中的访问地址（用于 --host 0.0.0.0 时的提示）。"""
    urls = []
    try:
        import socket

        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            urls.append(f"http://{s.getsockname()[0]}:{port}")
        finally:
            s.close()
    except OSError:
        pass
    return urls


def _bind_server(port: int, host: str = "127.0.0.1"):
    """绑定端口，占用时自动尝试下一个端口。"""
    for _ in range(50):
        try:
            return ThreadingHTTPServer((host, port), DashboardHandler)
        except OSError:
            port += 1
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="TK-GMVMAX-FBT 本地面板（广告素材 + FBT 库存）")
    parser.add_argument("--port", type=int, default=8501)
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="监听地址：默认 127.0.0.1 仅本机访问；填 0.0.0.0 可让手机/局域网内其他设备访问",
    )
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    parser.add_argument(
        "--token",
        default=None,
        help="访问令牌：设置后 /api/* 必须携带该令牌；--host 0.0.0.0 时未提供则自动生成。",
    )
    args = parser.parse_args()
    token = args.token
    if not token and args.host in ("0.0.0.0", "::"):
        # 局域网监听默认启用鉴权，避免经营数据被局域网内任何人直接读取。
        token = secrets.token_urlsafe(12)
    DashboardHandler.auth_token = token
    _ensure_data_dirs()
    server = _bind_server(args.port, args.host)
    if server is None:
        print("端口被占用无法启动，请关闭其他面板后重试。")
        return
    port = server.server_address[1]
    token_part = f"?token={token}" if token else ""
    open_url = f"http://127.0.0.1:{port}{token_part}"
    if args.host in ("0.0.0.0", "::"):
        print(f"TK-GMVMAX-FBT面板已启动：http://127.0.0.1:{port}{token_part}")
        for url in _lan_urls(port):
            print(f"局域网访问地址（手机或其他设备）：{url}{token_part}")
        print(f"访问令牌（token）：{token}")
        print("若其他设备无法访问，请检查 Windows 防火墙是否放行 Python。")
    else:
        open_url = f"http://{args.host}:{port}{token_part}"
        print(f"TK-GMVMAX-FBT面板已启动：{open_url}")
        if token:
            print(f"访问令牌（token）：{token}")
    print("每次更新数据后，刷新浏览器即可读取最新数据。")
    print("关闭本窗口即停止面板。")
    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(open_url)).start()
    print("新增 daily_data 文件后，刷新浏览器即可读取最新数据。")
    # 后台预热：提前解析 Excel 并构建 DataFrame / gzip 缓存，首个请求无需等待 ~40 秒。
    threading.Thread(target=lambda: (_load_data_cached(), _cached_data_body(gzipped=True)), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在关闭面板。")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
