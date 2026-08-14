# ============================================================
# TK-GMVMAX-DSH 安装/更新脚本（目标机运行）
# 用法（推荐，自动下载全部文件）：
#   irm https://raw.githubusercontent.com/clr112409-dot/TK-GMVMAX-DSH/main/install.ps1 | iex
# 或（已 clone/解压仓库到本地）：
#   powershell -ExecutionPolicy Bypass -File install.ps1
#
# 首次安装：自动完成下载、复制插件、注册 cordis.patch.yml、设置环境变量、
#           安装 Python 依赖、创建数据目录、冒烟测试。
# 再次运行（更新）：自动对比已安装版本，有新版则覆盖更新（幂等，自动备份配置），
#           版本相同则提示已是最新（可用 -Force 强制重装）。
#
# 仓库固定解压到 $HOME\TK-GMVMAX-DSH（可在目标机直接修改，更新时保留数据目录）。
# ============================================================
param([switch]$Force)
$ErrorActionPreference = 'Stop'

$REPO = 'clr112409-dot/TK-GMVMAX-DSH'
$ZIP_URL = "https://github.com/$REPO/archive/refs/heads/main.zip"
$RAW_URL = "https://raw.githubusercontent.com/$REPO/main"
$WORK_DIR = Join-Path $env:USERPROFILE 'TK-GMVMAX-DSH'

Write-Host '=== TK-GMVMAX-DSH 安装/更新脚本 ===' -ForegroundColor Cyan

# ---------- 0. 确定仓库文件位置 ----------
$SCRIPT_DIR = if ($PSScriptRoot) { $PSScriptRoot } else { $null }
$TKDASH_DIR = if ($SCRIPT_DIR) { Join-Path $SCRIPT_DIR 'tkdash-host' } else { $null }
$GMVMAX_DIR = if ($SCRIPT_DIR) { Join-Path $SCRIPT_DIR 'TK-GMVMAX' } else { $null }

if (-not $TKDASH_DIR -or -not (Test-Path (Join-Path $TKDASH_DIR 'index.js'))) {
  Write-Host '未找到本地仓库文件，正在从 GitHub 下载...' -ForegroundColor Yellow
  $tmp = Join-Path $env:TEMP ('tkdash-download-' + [guid]::NewGuid().ToString('N'))
  New-Item -ItemType Directory -Force -Path $tmp | Out-Null
  $zip = Join-Path $tmp 'repo.zip'
  try {
    Invoke-WebRequest -Uri $ZIP_URL -OutFile $zip -UseBasicParsing -TimeoutSec 120
  } catch {
    Write-Host "下载失败：$($_.Exception.Message)" -ForegroundColor Red
    Write-Host '请检查网络能否访问 github.com（必要时配置代理），或手动下载仓库 zip 解压后运行 install.ps1。' -ForegroundColor Yellow
    exit 1
  }
  Expand-Archive -Path $zip -DestinationPath $tmp -Force
  $extracted = Get-ChildItem $tmp -Directory | Where-Object { $_.Name -like 'TK-GMVMAX-DSH-*' } | Select-Object -First 1
  if (-not $extracted) { Write-Host '下载内容解压失败' -ForegroundColor Red; exit 1 }
  $srcDir = $extracted.FullName
  $TKDASH_DIR = Join-Path $srcDir 'tkdash-host'
  $GMVMAX_DIR = Join-Path $srcDir 'TK-GMVMAX'

  # 固定工作区：把下载内容落到 $HOME\TK-GMVMAX-DSH（保留已有数据文件）
  New-Item -ItemType Directory -Force -Path $WORK_DIR | Out-Null
  $workGMVMAX = Join-Path $WORK_DIR 'TK-GMVMAX'
  foreach ($d in @('daily_data', 'KCXQ', 'SKU Matching Table')) {
    $dst = Join-Path $workGMVMAX $d
    New-Item -ItemType Directory -Force -Path $dst | Out-Null
    if (Test-Path (Join-Path $GMVMAX_DIR $d)) {
      Get-ChildItem (Join-Path $GMVMAX_DIR $d) -File -ErrorAction SilentlyContinue |
        Copy-Item -Destination $dst -Force -ErrorAction SilentlyContinue
    }
  }
  # 覆盖代码文件（不删除目标目录，避免数据丢失；已存在数据目录保持不动）
  Copy-Item (Join-Path $srcDir 'tkdash-host') (Join-Path $WORK_DIR 'tkdash-host') -Recurse -Force
  Copy-Item (Join-Path $srcDir 'TK-GMVMAX\*') $workGMVMAX -Recurse -Force
  Copy-Item (Join-Path $srcDir 'install.ps1') (Join-Path $WORK_DIR 'install.ps1') -Force -ErrorAction SilentlyContinue
  Copy-Item (Join-Path $srcDir 'README.md') (Join-Path $WORK_DIR 'README.md') -Force -ErrorAction SilentlyContinue
  $TKDASH_DIR = Join-Path $WORK_DIR 'tkdash-host'
  $GMVMAX_DIR = $workGMVMAX
  Write-Host "仓库已就位于固定工作区: $WORK_DIR（后续更新/修改都在这里）" -ForegroundColor Green
}
if (-not (Test-Path (Join-Path $TKDASH_DIR 'index.js')) -or -not (Test-Path (Join-Path $GMVMAX_DIR 'dashboard_server.py'))) {
  Write-Host '仓库文件不完整（缺少 tkdash-host/index.js 或 TK-GMVMAX/dashboard_server.py）' -ForegroundColor Red
  exit 1
}

# ---------- 1. 定位 dsh 安装目录 ----------
function Find-DshRoot {
  $candidates = @()
  try { $npmRoot = npm root -g 2>$null; if ($npmRoot) { $candidates += (Join-Path $npmRoot '@deepseek-ai\dsh') } } catch {}
  $candidates += "$env:APPDATA\npm\node_modules\@deepseek-ai\dsh"
  $candidates += "$env:USERPROFILE\AppData\Roaming\npm\node_modules\@deepseek-ai\dsh"
  if ($env:DSH_ROOT) { $candidates += $env:DSH_ROOT }
  foreach ($c in $candidates) {
    if ($c -and (Test-Path (Join-Path $c 'package.json'))) { return $c }
  }
  return $null
}

$dshRoot = Find-DshRoot
if (-not $dshRoot) {
  Write-Host '未找到 dsh 安装目录（@deepseek-ai/dsh）。请先安装 dsh web 后重试。' -ForegroundColor Red
  Write-Host '若 dsh 在自定义位置，请设置环境变量 DSH_ROOT 指向其目录后重跑。' -ForegroundColor Yellow
  exit 1
}
Write-Host "[1/8] dsh 目录: $dshRoot" -ForegroundColor Green

# ---------- 2. 版本对比（已安装 vs 仓库新版） ----------
$destPlugin = Join-Path $dshRoot 'node_modules\tkdash-host'
$installedPkg = Join-Path $destPlugin 'package.json'
$remotePkg = Join-Path $TKDASH_DIR 'package.json'

$installedVersion = $null
if (Test-Path $installedPkg) {
  try { $installedVersion = (Get-Content $installedPkg -Raw -Encoding UTF8 | ConvertFrom-Json).version } catch {}
}
$remoteVersion = $null
try { $remoteVersion = (Get-Content $remotePkg -Raw -Encoding UTF8 | ConvertFrom-Json).version } catch {}

if ($installedVersion -and $remoteVersion -and $installedVersion -eq $remoteVersion -and -not $Force) {
  Write-Host "[2/8] 已安装版本 v$installedVersion 与仓库最新版一致，无需更新。" -ForegroundColor Green
  Write-Host '      如需强制重装请加 -Force 参数（irm | iex 场景：irm ... | iex -Force 不适用，请下载脚本后运行 powershell -File install.ps1 -Force）' -ForegroundColor Yellow
  exit 0
}
if ($installedVersion) {
  Write-Host "[2/8] 版本更新: v$installedVersion -> v$remoteVersion" -ForegroundColor Yellow
} else {
  Write-Host "[2/8] 首次安装（v$remoteVersion）" -ForegroundColor Green
}

# ---------- 3. 复制 tkdash-host 插件 ----------
New-Item -ItemType Directory -Force -Path $destPlugin | Out-Null
Copy-Item (Join-Path $TKDASH_DIR 'package.json') (Join-Path $destPlugin 'package.json') -Force
Copy-Item (Join-Path $TKDASH_DIR 'index.js') (Join-Path $destPlugin 'index.js') -Force
Write-Host '[3/8] 插件已复制到 dsh/node_modules/tkdash-host' -ForegroundColor Green

# ---------- 4. 注册 cordis.patch.yml（幂等 + 备份） ----------
$profileDir = Join-Path $env:USERPROFILE '.dsh\profiles\web'
$patchFile = Join-Path $profileDir 'cordis.patch.yml'
New-Item -ItemType Directory -Force -Path $profileDir | Out-Null
$pluginUrl = 'file:///' + ($destPlugin -replace '\\', '/') + '/index.js'

if (Test-Path $patchFile) {
  $content = Get-Content $patchFile -Raw -Encoding UTF8
  if ($content -match 'tkdash-host') {
    Write-Host '[4/8] cordis.patch.yml 已包含 tkdash-host，跳过注册' -ForegroundColor Green
  } else {
    Copy-Item $patchFile ($patchFile + '.bak-' + (Get-Date -Format 'yyyyMMdd-HHmmss')) -Force
    $block = @"

# TK-GMVMAX 看板宿主插件（由 install.ps1 自动添加）
- insert:
    - id: tkdash-host
      name: '$pluginUrl'
"@
    Add-Content -Path $patchFile -Value $block -Encoding UTF8
    Write-Host '[4/8] 已注册 tkdash-host 到 cordis.patch.yml（原文件已备份）' -ForegroundColor Green
  }
} else {
  $newContent = @"
# Your patch layer for this dsh profile, applied after every bundle layer:
# a top-level YAML array of loader patch entries (id-targeted config
# overrides, disables, and insert lists; `!!js` expressions allowed).

# TK-GMVMAX 看板宿主插件（由 install.ps1 自动添加）
- insert:
    - id: tkdash-host
      name: '$pluginUrl'
"@
  Set-Content -Path $patchFile -Value $newContent -Encoding UTF8
  Write-Host '[4/8] 已创建 cordis.patch.yml 并注册 tkdash-host' -ForegroundColor Green
}

# ---------- 5. 设置环境变量 ----------
$python = $null
try { $python = (Get-Command python -ErrorAction Stop).Source } catch {}
if (-not $python) { try { $python = (Get-Command py -ErrorAction Stop).Source } catch {} }
if (-not $python) {
  Write-Host '未找到 python，请安装 Python 3.10+ 并勾选 "Add to PATH"，然后重新运行本脚本。' -ForegroundColor Red
  exit 1
}
[Environment]::SetEnvironmentVariable('DSH_TKDASH_ROOT', $GMVMAX_DIR, 'User')
[Environment]::SetEnvironmentVariable('DSH_TKDASH_PYTHON', $python, 'User')
Write-Host "[5/8] 环境变量已设置: DSH_TKDASH_ROOT=$GMVMAX_DIR" -ForegroundColor Green
Write-Host "            DSH_TKDASH_PYTHON=$python" -ForegroundColor Green

# ---------- 6. Python 依赖检查 ----------
Write-Host '[6/8] 检查 Python 依赖...' -ForegroundColor Green
$depOk = $true
foreach ($mod in @('pandas', 'openpyxl')) {
  & $python -c "import $mod" 2>$null
  if ($LASTEXITCODE -ne 0) { $depOk = $false }
}
if (-not $depOk) {
  Write-Host '缺少 pandas / openpyxl，正在安装...' -ForegroundColor Yellow
  & $python -m pip install --upgrade pandas openpyxl
  if ($LASTEXITCODE -ne 0) {
    Write-Host 'pip 安装失败，请手动执行: python -m pip install pandas openpyxl' -ForegroundColor Red
    exit 1
  }
}
Write-Host '[6/8] Python 依赖就绪' -ForegroundColor Green

# ---------- 7. 创建数据目录 ----------
foreach ($d in @('daily_data', 'KCXQ', 'SKU Matching Table')) {
  New-Item -ItemType Directory -Force -Path (Join-Path $GMVMAX_DIR $d) | Out-Null
}
Write-Host '[7/8] 数据目录已创建: daily_data / KCXQ / "SKU Matching Table"' -ForegroundColor Green

# ---------- 8. 冒烟测试看板服务 ----------
Write-Host '[8/8] 冒烟测试看板服务（约 30 秒）...' -ForegroundColor Green
$smokeOk = $false
$wasRunning = $false
try {
  try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8501/api/meta' -UseBasicParsing -TimeoutSec 3; if ($r.StatusCode -eq 200) { $wasRunning = $true } } catch {}
  $proc = Start-Process -FilePath $python -ArgumentList @((Join-Path $GMVMAX_DIR 'dashboard_server.py'), '--port', '8501', '--no-browser') -PassThru -WindowStyle Hidden
  for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    try {
      $resp = Invoke-WebRequest -Uri 'http://127.0.0.1:8501/api/meta' -UseBasicParsing -TimeoutSec 3
      if ($resp.StatusCode -eq 200) { $smokeOk = $true; break }
    } catch {}
    if ($proc.HasExited) { break }
  }
  if (-not $smokeOk) { try { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue } catch {} }
} catch {}
if ($smokeOk) {
  Write-Host '[8/8] 看板服务启动正常，数据解析 OK' -ForegroundColor Green
  if (-not $wasRunning) { try { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue } catch {} }
} else {
  Write-Host '[8/8] 警告：冒烟测试未通过（服务可能已在运行或启动较慢）。重启 dsh 后宿主会自动再试。' -ForegroundColor Yellow
}

Write-Host ''
Write-Host '========================================' -ForegroundColor Cyan
if ($installedVersion) {
  Write-Host "更新完成：v$installedVersion -> v$remoteVersion" -ForegroundColor Cyan
  Write-Host '  1. 重启 dsh web 使新插件代码生效（宿主插件在启动时加载）'
  Write-Host '  2. 若 8501 看板服务正在运行，需重启 dsh 或手动结束旧 python 进程，否则服务仍是旧代码'
} else {
  Write-Host '安装完成！接下来：' -ForegroundColor Cyan
  Write-Host '  1. 重启 dsh web（关闭后重新启动）'
  Write-Host '  2. 把数据文件放入对应目录：'
  Write-Host "     - 广告日报 Excel  -> $GMVMAX_DIR\daily_data"
  Write-Host "     - 库存 Excel      -> $GMVMAX_DIR\KCXQ"
  Write-Host "     - SKU 匹配表      -> $GMVMAX_DIR\SKU Matching Table"
  Write-Host '  3. 重启后看板服务自动启动（http://127.0.0.1:8501），dashboard_query 工具全局可用'
}
Write-Host "工作区: $WORK_DIR（在此修改代码后，可自行 git 推送或让作者代推）" -ForegroundColor Cyan
Write-Host '========================================' -ForegroundColor Cyan
