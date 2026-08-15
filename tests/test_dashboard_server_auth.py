# -*- coding: utf-8 -*-
"""dashboard_server 鉴权与 401 兜底的 pytest 用例。"""
import json
import shutil
import sys
import threading
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "TK-GMVMAX"))

import dashboard_server as ds  # noqa: E402


@pytest.fixture
def token_server():
    old_token = ds.DashboardHandler.auth_token
    ds.DashboardHandler.auth_token = "s3cret-token"
    server = ds.ThreadingHTTPServer(("127.0.0.1", 0), ds.DashboardHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield port
    server.shutdown()
    server.server_close()
    ds.DashboardHandler.auth_token = old_token


def get(port, path, headers=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def test_api_requires_token(token_server):
    port = token_server
    code, body = get(port, "/api/meta")
    assert code == 401, (code, body)
    payload = json.loads(body)
    assert "token" in payload.get("error", "")

    code, _ = get(port, "/api/meta?token=wrong")
    assert code == 401

    code, _ = get(port, "/api/meta?token=s3cret-token")
    assert code == 200

    code, _ = get(port, "/api/meta", {"X-TK-Token": "s3cret-token"})
    assert code == 200

    code, _ = get(port, "/api/meta", {"Authorization": "Bearer s3cret-token"})
    assert code == 200


def test_static_pages_open_without_token(token_server):
    """HTML 壳子与静态资源不携带业务数据，允许未授权打开；数据接口受保护。"""
    port = token_server
    code, _ = get(port, "/")
    assert code == 200
    code, _ = get(port, "/static/app.js")
    assert code == 200
    code, _ = get(port, "/api/signature")
    assert code == 401


def test_inventory_signature_endpoint(token_server):
    """插件依赖该端点检测 KCXQ 更新；同样受令牌保护，未放数据时签名为 none。"""
    port = token_server
    code, _ = get(port, "/api/inventory-signature")
    assert code == 401
    code, body = get(port, "/api/inventory-signature?token=s3cret-token")
    assert code == 200
    payload = json.loads(body)
    assert payload.get("signature") == "none"


def test_inventory_signature_changes_with_kcxq():
    """库存签名是插件失效缓存的事实来源：KCXQ 文件变化时签名必须变化。"""
    import inventory_loader as il

    base = Path(__file__).resolve().parent / ".tmp_inv"
    base.mkdir(exist_ok=True)
    d = base / f"kcxq_{uuid.uuid4().hex}"
    d.mkdir()
    old_dirs = il.KCXQ_DIRS
    il.KCXQ_DIRS = [d]
    try:
        pd.DataFrame({"A": [1]}).to_excel(d / "a.xlsx", index=False)
        sig1 = ds.inventory_signature()
        pd.DataFrame({"A": [2]}).to_excel(d / "b.xlsx", index=False)
        sig2 = ds.inventory_signature()
        assert sig1 and sig1 != sig2
    finally:
        il.KCXQ_DIRS = old_dirs
        shutil.rmtree(base, ignore_errors=True)
