# Windows 一键启动部署 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 提供 Windows 双击 `.bat` 一键启动体验：自动检测 Python、创建/复用 `.venv`、安装依赖、启动服务并打开浏览器。

**Architecture:** 根目录 `启动.bat` 作为双击入口，绕过执行策略调用 `start.ps1`；`start.ps1` 负责完整流程（检测 → venv → pip install → 后台 uvicorn → 轮询 health → 开浏览器 → 保持窗口/退出清理）；`backend/requirements.txt` 为纯 pip 依赖清单。纯 pip 方案，不依赖 uv。

**Tech Stack:** Windows Batch + PowerShell + Python venv/pip + FastAPI/uvicorn（现有）。

**Spec:** `docs/superpowers/specs/2026-08-29-windows-one-click-deploy-design.md`

---

### Task 1: 生成 backend/requirements.txt

**Files:**
- Create: `backend/requirements.txt`

- [ ] **Step 1: 创建 requirements.txt**

内容（来自 `backend/pyproject.toml` 运行依赖，`requires-python >=3.11`）：

```
fastapi>=0.115
uvicorn[standard]>=0.32
sqlmodel>=0.0.22
pydantic-settings>=2.6
pillow>=11.0
httpx>=0.27
python-multipart>=0.0.9
send2trash>=1.8
```

- [ ] **Step 2: 验证依赖可解析**

运行：`cd backend; python -m pip install --disable-pip-version-check --dry-run -r requirements.txt -q`
预期：无报错，输出「Would install ...」清单（列出上述 8 个包）。

- [ ] **Step 3: 提交**

```bash
git add backend/requirements.txt
git commit -m "chore: 为纯 pip 部署生成 requirements.txt"
```

---

### Task 2: 创建 start.ps1（核心启动逻辑）

**Files:**
- Create: `start.ps1`（项目根目录）

- [ ] **Step 1: 创建 start.ps1**

完整内容：

```powershell
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
```

- [ ] **Step 2: 验证 PowerShell 语法**

运行：`powershell -NoProfile -Command "$tokens=$null;$errors=$null; [System.Management.Automation.Language.Parser]::ParseFile('C:\Project\Code\ArtMirror\start.ps1',[ref]$tokens,[ref]$errors) | Out-Null; if($errors.Count){$errors | ForEach-Object {$_.Message}; exit 1} else {'语法 OK'}"`
预期：输出「语法 OK」。

- [ ] **Step 3: 验证「端口占用」路径（当前服务已在 8000 运行）**

运行：`cd C:\Project\Code\ArtMirror; powershell -NoProfile -ExecutionPolicy Bypass -File start.ps1`，输入回车退出。
预期：检测到端口 8000 被占用 → 提示「视为画镜已在运行」→ 尝试打开浏览器 → 按回车退出；不创建/破坏现有 `.venv` 与服务。

- [ ] **Step 4: 提交**

```bash
git add start.ps1
git commit -m "feat: 一键启动脚本 start.ps1（检测/venv/依赖/启动/开浏览器）"
```

---

### Task 3: 创建 启动.bat（双击入口）

**Files:**
- Create: `启动.bat`（项目根目录，UTF-8 编码）

- [ ] **Step 1: 创建 启动.bat**

完整内容（需以 UTF-8 保存，含中文窗口标题）：

```bat
@echo off
chcp 65001 >nul
title 画镜 ArtMirror 一键启动
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
```

- [ ] **Step 2: 验证文件与编码**

运行：`Get-Content "C:\Project\Code\ArtMirror\启动.bat"` 与 `powershell -NoProfile -ExecutionPolicy Bypass -Command "& { $null = [System.Management.Automation.Language.Parser]::ParseFile('C:\Project\Code\ArtMirror\start.ps1',[ref]$null,[ref]$null) }"`
预期：能读取 bat 内容（chcp/title/powershell 调用三行）；start.ps1 可解析。

- [ ] **Step 3: 提交**

```bash
git add "启动.bat"
git commit -m "feat: 双击入口 启动.bat"
```

---

### Task 4: README 新增「小白快速启动」章节

**Files:**
- Modify: `README.md`（在「部署流程」之前插入）

- [ ] **Step 1: 编辑 README.md**

在 `## 部署流程` 之前插入：

```markdown
## 小白快速启动（Windows）

1. 安装 **Python 3.11 或更高**（[python.org 下载](https://www.python.org/downloads/)，安装时勾选 **Add Python to PATH**）
2. 双击项目根目录的 **`启动.bat`**
3. 首次会自动创建虚拟环境并安装依赖（约 1-3 分钟），之后秒启
4. 启动完成后自动打开浏览器进入图库；窗口保持运行，**按回车键停止服务并退出**

> 服务地址：http://127.0.0.1:8000/gallery.html（手动访问也可）
```

- [ ] **Step 2: 验证插入成功**

运行：`Select-String -Path "C:\Project\Code\ArtMirror\README.md" -Pattern "小白快速启动"`
预期：命中该标题行。

- [ ] **Step 3: 提交**

```bash
git add README.md
git commit -m "docs: README 新增小白快速启动章节"
```

---

### Task 5: 端到端核对

**Files:** 无新增

- [ ] **Step 1: 确认关键路径一致**

运行：
```powershell
Test-Path "C:\Project\Code\ArtMirror\启动.bat"
Test-Path "C:\Project\Code\ArtMirror\start.ps1"
Test-Path "C:\Project\Code\ArtMirror\backend\requirements.txt"
Select-String -Path "C:\Project\Code\ArtMirror\README.md" -Pattern "启动.bat"
```
预期：四个均为 True/命中。

- [ ] **Step 2: 确认未破坏现有环境**

运行：`curl.exe -s http://127.0.0.1:8000/api/health`
预期：服务仍返回 `{"status":"ok",...}`（脚本「端口占用」路径不干扰现有运行）。

- [ ] **Step 3: 提交（若 Task 1-4 均已提交则跳过）**

---

## Self-Review

- **Spec 覆盖**：双击入口（Task 3）、纯 pip + venv（Task 2）、Python 缺失提示（Task 2 step1 第 1 步）、自动开浏览器（Task 2 第 7 步）、端口占用（Task 2 第 2 步）、requirements.txt（Task 1）、README 章节（Task 4）—— 全部覆盖。
- **占位符**：无 TBD/TODO，所有代码完整给出。
- **类型一致性**：`start.ps1` 内 `$Venv/$venvPy/$Url/$Port/$Backend` 命名在 Task 2 步骤内自洽；`启动.bat` 调用 `start.ps1` 路径一致。
