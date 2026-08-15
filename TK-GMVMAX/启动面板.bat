@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo 未找到 Python，请先安装 Python 3.10+ 并勾选 "Add Python to PATH"。
    echo 安装地址：https://www.python.org/downloads/
    pause
    exit /b 1
)

python -c "import pandas, openpyxl" >nul 2>nul
if errorlevel 1 (
    echo 首次运行：正在安装依赖 pandas / openpyxl（约 1-2 分钟）...
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo 依赖安装失败，请手动执行：python -m pip install -r requirements.txt
        pause
        exit /b 1
    )
)

python dashboard_server.py
pause
