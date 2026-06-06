@echo off
REM ============================================================
REM  smart-coupon-engine  Windows 一键启动
REM  双击本文件：自动建虚拟环境 + 装依赖 + 启动对客网站
REM  详细说明见 RUN_ON_WINDOWS.md
REM ============================================================
chcp 65001 >nul
cd /d "%~dp0"

echo [1/3] 检查 Python ...
python --version
if errorlevel 1 (
  echo.
  echo 没有检测到 Python。请先安装 Python 3.10+ 并勾选 "Add to PATH"。
  echo 下载地址：https://www.python.org/downloads/
  pause
  exit /b 1
)

echo [2/3] 准备虚拟环境并安装依赖（首次较慢，请耐心等待）...
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
)
".venv\Scripts\python.exe" -m pip install --upgrade pip setuptools wheel

set "PYTHONPATH="
".venv\Scripts\python.exe" -m pip install -e .
if errorlevel 1 (
  echo.
  echo 装包失败，自动切换到兜底方案：装依赖 + 设置 PYTHONPATH ...
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo 依赖安装仍失败。可尝试国内镜像：
    echo   .venv\Scripts\python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
    pause
    exit /b 1
  )
  set "PYTHONPATH=src"
)

echo [3/3] 启动网站，稍后请用浏览器打开： http://localhost:8000
echo 按 Ctrl + C 可停止服务。
".venv\Scripts\python.exe" -m uvicorn coupon_engine.api.main:app --port 8000
pause
