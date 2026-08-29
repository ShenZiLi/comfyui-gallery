# 画镜 ArtMirror 一键打包：build/build.ps1 → dist/画镜ArtMirror.exe
$ErrorActionPreference = "Stop"
$BuildDir = Split-Path -Parent $MyInvocation.MyCommand.Path   # build/
$Proj = Split-Path -Parent $BuildDir                          # 项目根
$VenvPy = Join-Path $Proj "backend\.venv\Scripts\python.exe"

if (-not (Test-Path $VenvPy)) {
    Write-Host "未找到 backend\.venv，请先运行 uv sync 或 启动.bat。"
    exit 1
}

# 1) 确保 pyinstaller
& $VenvPy -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "安装 pyinstaller…"
    & $VenvPy -m pip install --disable-pip-version-check -q "pyinstaller>=6.0"
    if ($LASTEXITCODE -ne 0) { Write-Host "pyinstaller 安装失败"; exit 1 }
}

# 2) 用品牌 512 图生成多尺寸 icon.ico
$iconSrc = Join-Path $Proj "frontend\assets\icons\icon-512.png"
$iconOut = Join-Path $BuildDir "icon.ico"
if (-not (Test-Path $iconOut)) {
    & $VenvPy -c @"
from PIL import Image
im = Image.open(r'$iconSrc').convert('RGBA')
im.save(r'$iconOut', format='ICO', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])
print('icon ->', r'$iconOut')
"@
}

# 3) 打包（在 build/ 下执行，spec 内路径相对 SPECPATH；dist 输出到项目根 dist/）
Push-Location $BuildDir
& $VenvPy -m PyInstaller --noconfirm --clean --distpath "$Proj\dist" --workpath "$BuildDir\build" "build.spec"
$code = $LASTEXITCODE
Pop-Location
if ($code -ne 0) { Write-Host "PyInstaller 构建失败"; exit 1 }

# 4) 校验产物
$exe = Join-Path $Proj "dist\画镜ArtMirror.exe"
if (-not (Test-Path $exe)) { Write-Host "构建完成但未找到产物：$exe"; exit 1 }
$size = (Get-Item $exe).Length / 1MB
Write-Host ("打包完成：{0}（{1:N1} MB）" -f $exe, $size)
