# 画镜 ArtMirror 一键启动（纯 pip 方案）
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Backend = Join-Path $Root "backend"
$Venv = Join-Path $Backend ".venv"
$Port = 8000
$Url = "http://127.0.0.1:$Port"

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

Write-Step "画镜 ArtMirror 一键启动"

# 1) 检测 Python
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Host "未检测到 Python。" -ForegroundColor Red
    Write-Host "请到 https://www.python.org/downloads/ 下载 Python 3.11 或更高版本，安装时勾选 “Add Python to PATH”。"
    Write-Host "安装完成后重新双击 启动.bat 即可。"
    Read-Host "按回车键退出"
    exit 1
}
$ver = (& python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
$parts = $ver -split '\.'
$vmajor = [int]$parts[0]
$vminor = [int]$parts[1]
if ($vmajor -lt 3 -or ($vmajor -eq 3 -and $vminor -lt 11)) {
    Write-Host "当前 Python 版本 $ver 过低，需要 3.11 或更高。" -ForegroundColor Red
    Read-Host "按回车键退出"
    exit 1
}
Write-Step "检测到 Python $ver"

# 2) 端口已被占用 → 视为服务已在运行，直接打开浏览器
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    Write-Host "端口 $Port 已被占用，视为画镜已在运行，直接打开浏览器…"
    Start-Process "$Url/gallery.html"
    Read-Host "按回车键退出"
    exit 0
}

# 3) 首次：创建虚拟环境
$venvPy = Join-Path $Venv "Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Write-Step "首次运行：创建虚拟环境…"
    & python -m venv $Venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host "创建虚拟环境失败。" -ForegroundColor Red
        Read-Host "按回车键退出"
        exit 1
    }
}

# 4) 安装依赖（幂等，已装则秒过）
Write-Step "检查依赖…"
& $venvPy -m pip install --disable-pip-version-check -q -r (Join-Path $Backend "requirements.txt")
if ($LASTEXITCODE -ne 0) {
    Write-Host "依赖安装失败，请将上方错误信息截图反馈。" -ForegroundColor Red
    Read-Host "按回车键退出"
    exit 1
}

# 5) 后台启动服务，日志落盘
Write-Step "启动服务…"
$dataDir = Join-Path $Root "data"
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
$logOut = Join-Path $dataDir "server.log"
$logErr = Join-Path $dataDir "server.err.log"
$proc = Start-Process -FilePath $venvPy -ArgumentList "-m","uvicorn","app.main:app","--host","0.0.0.0","--port","$Port" `
    -WorkingDirectory $Backend `
    -RedirectStandardOutput $logOut -RedirectStandardError $logErr -PassThru

# 6) 轮询健康检查（最多 60s）
Write-Step "等待服务就绪…"
$ready = $false
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 1
    if ($proc.HasExited) { break }
    try {
        $r = Invoke-WebRequest -Uri "$Url/api/health" -UseBasicParsing -TimeoutSec 2
        if ($r.StatusCode -eq 200) { $ready = $true; break }
    } catch {}
}
if (-not $ready) {
    Write-Host "服务启动超时，请查看 data/server.log。" -ForegroundColor Red
    Read-Host "按回车键退出"
    exit 1
}

# 7) 打开浏览器
Write-Step "打开浏览器…"
Start-Process "$Url/gallery.html"

Write-Host ""
Write-Host "画镜已启动：" -ForegroundColor Green
Write-Host "  图库：$Url/gallery.html"
Write-Host "  设置：$Url/settings.html"
Write-Host "按回车键停止服务并退出。"
Read-Host

# 8) 退出时停止服务
if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force }
exit 0
