# 画镜 ArtMirror 一键启动（纯 pip 方案）
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Venv = Join-Path $Root ".venv"
$Port = 8000
$Url = "http://127.0.0.1:$Port"

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Exit-Fail($msg) {
    Write-Host $msg -ForegroundColor Red
    Read-Host "按回车键退出"
    exit 1
}

Write-Step "画镜 ArtMirror 一键启动"

# 1) 端口已被占用 → 视为服务已在运行，直接打开浏览器（免环境依赖）
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    Write-Host "端口 $Port 已被占用，视为画镜已在运行，直接打开浏览器…"
    Start-Process "$Url/gallery.html"
    Read-Host "按回车键退出"
    exit 0
}

# 2) 检测 Python（含版本容错，避免 Microsoft Store 别名等导致崩溃）
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    Exit-Fail "未检测到 Python。`n请到 https://www.python.org/downloads/ 下载 Python 3.11 或更高版本，安装时勾选 “Add Python to PATH”。`n安装完成后重新双击 启动.bat 即可。"
}
$ver = (& python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null).Trim()
if ($LASTEXITCODE -ne 0 -or $ver -notmatch '^\d+\.\d+$') {
    Exit-Fail "无法获取 Python 版本。`n若安装了 Microsoft Store 的 Python 别名，请改用官方 python.org 安装并勾选 Add to PATH。"
}
$parts = $ver -split '\.'
$vmajor = [int]$parts[0]
$vminor = [int]$parts[1]
if ($vmajor -lt 3 -or ($vmajor -eq 3 -and $vminor -lt 11)) {
    Exit-Fail "当前 Python 版本 $ver 过低，需要 3.11 或更高。"
}
Write-Step "检测到 Python $ver"

# 3) 首次：创建虚拟环境
$venvPy = Join-Path $Venv "Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Write-Step "首次运行：创建虚拟环境…"
    & python -m venv $Venv
    if ($LASTEXITCODE -ne 0) { Exit-Fail "创建虚拟环境失败，请将上方错误信息截图反馈。" }
}

# 4) 安装依赖（幂等，已装则秒过；首次展示进度）；-e . 以 src layout 安装 artmirror 真源
Write-Step "检查依赖（首次需联网下载，请稍候）…"
& $venvPy -m pip install --disable-pip-version-check -r (Join-Path $Root "requirements.txt") -e $Root
if ($LASTEXITCODE -ne 0) { Exit-Fail "依赖安装失败，请将上方错误信息截图反馈。" }

# 5) 后台启动服务，日志落盘
Write-Step "启动服务…"
$dataDir = Join-Path $Root "data"
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
$logOut = Join-Path $dataDir "server.log"
$logErr = Join-Path $dataDir "server.err.log"
$proc = $null
try {
    $proc = Start-Process -FilePath $venvPy -ArgumentList "-m","uvicorn","artmirror.main:app","--host","0.0.0.0","--port","$Port" `
        -WorkingDirectory $Root `
        -RedirectStandardOutput $logOut -RedirectStandardError $logErr -PassThru

    # 6) 轮询健康检查（直连不走代理，最多约 60s）
    Write-Step "等待服务就绪…"
    $ready = $false
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Seconds 1
        if ($proc.HasExited) { break }
        try {
            curl.exe -s --noproxy "*" --fail --max-time 2 "$Url/api/health" | Out-Null
            if ($LASTEXITCODE -eq 0) { $ready = $true; break }
        } catch {}
    }
    if (-not $ready) {
        if ($proc.HasExited) { Exit-Fail "服务启动失败，请查看 data\server.err.log。" }
        else { Exit-Fail "服务启动超时，请查看 data\server.err.log。" }
    }

    # 7) 打开浏览器
    Write-Step "打开浏览器…"
    Start-Process "$Url/gallery.html"

    Write-Host ""
    Write-Host "画镜已启动：" -ForegroundColor Green
    Write-Host "  图库：$Url/gallery.html"
    Write-Host "  设置：$Url/settings.html"
    Write-Host "请按回车键停止服务并退出（不要直接关闭窗口）。"
    Read-Host
} finally {
    # 任何退出路径（含异常）都清理后台服务进程，避免残留占用端口
    if ($proc -and -not $proc.HasExited) { Stop-Process -Id $proc.Id -Force }
}
exit 0
