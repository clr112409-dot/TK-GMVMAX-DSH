"""common.py - 跨模块共享的公共工具函数。"""
from __future__ import annotations

import sys
from pathlib import Path


def app_dir() -> Path:
    """应用根目录：打包为 exe 时返回 exe 所在目录，否则返回项目目录。

    daily_data / SKU Matching Table / KCXQ 数据文件夹都放在该目录下，
    分享给他人后数据目录始终跟随程序位置。
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent
