#!/bin/bash
# 画镜 ArtMirror 一键启动（macOS）
# 双击本文件（启动Web端-Mac.command）或终端执行：bash 启动Web端-Mac.command
set -e
cd "$(dirname "$0")"

ROOT="$(pwd)"
PORT=8000
URL="http://127.0.0.1:$PORT"

say()  { echo "==> $*"; }
fail() { echo "错误: $*"; echo "按回车键退出"; read -r _; exit 1; }

say "画镜 ArtMirror 一键启动"

# 1) 端口已被占用 → 视为服务已在运行，直接打开浏览器（免环境依赖）
if lsof -iTCP:"$PORT" -sTCP:LISTEN -P 2>/dev/null | grep -q LISTEN; then
    echo "端口 $PORT 已被占用，视为画镜已在运行，直接打开浏览器…"
    open "$URL/gallery.html"
    exit 0
fi

# 2) 检测 Python（>= 3.11）
if ! command -v python3 >/dev/null 2>&1; then
    fail "未检测到 python3。请到 https://www.python.org/downloads/ 安装 Python 3.11 或更高版本后重试。"
fi
VER="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo 0.0)"
MAJ="${VER%%.*}"; MIN="${VER##*.}"
if [ "$MAJ" -lt 3 ] || { [ "$MAJ" -eq 3 ] && [ "$MIN" -lt 11 ]; }; then
    fail "当前 Python 版本 $VER 过低，需要 3.11 或更高。"
fi
say "检测到 Python $VER"

# 3) 首次：创建虚拟环境
VENVPY="$ROOT/.venv/bin/python"
if [ ! -x "$VENVPY" ]; then
    say "首次运行：创建虚拟环境…"
    python3 -m venv "$ROOT/.venv" || fail "创建虚拟环境失败，请将上方错误信息截图反馈。"
fi

# 4) 安装依赖（幂等，已装则秒过）；-e . 以可编辑模式安装 artmirror 真源
say "检查依赖（首次需联网下载，请稍候）…"
if command -v uv >/dev/null 2>&1; then
    uv pip install --python "$VENVPY" -r requirements.txt -e . || fail "依赖安装失败，请将上方错误信息截图反馈。"
else
    "$VENVPY" -m pip install --disable-pip-version-check -r requirements.txt -e . || fail "依赖安装失败，请将上方错误信息截图反馈。"
fi

# 5) 启动服务（后台，日志输出到终端）
say "启动服务…"
mkdir -p "$ROOT/data"
"$VENVPY" -m uvicorn launchers.web.main:app --host 127.0.0.1 --port "$PORT" &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null' EXIT INT TERM

# 6) 轮询健康检查（最多约 60s）
say "等待服务就绪…"
READY=0
for _ in $(seq 1 60); do
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then break; fi
    if curl -sf --max-time 2 "$URL/api/health" >/dev/null 2>&1; then READY=1; break; fi
    sleep 1
done
if [ "$READY" -ne 1 ]; then
    echo "服务未就绪（请查看上方日志）。"
    exit 1
fi

# 7) 打开浏览器
say "打开浏览器…"
open "$URL/gallery.html" || echo "（无法自动打开浏览器，请手动访问 $URL/gallery.html）"
echo ""
echo "画镜已启动："
echo "  图库：$URL/gallery.html"
echo "  设置：$URL/settings.html"
echo "按 Ctrl+C 停止服务并退出（不要直接关闭窗口）。"

wait "$SERVER_PID"
