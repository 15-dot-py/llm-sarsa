param([switch]$RebuildFrontend)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    $taskBundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    if (Test-Path -LiteralPath $taskBundledPython) { & $taskBundledPython -m venv .venv }
    else { py -3.12 -m venv .venv }
    if ($LASTEXITCODE -ne 0) { throw '需要 Python 3.12，请安装后重试。' }
}
& $taskPython -m pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.lock.txt
if ($LASTEXITCODE -ne 0) { throw 'Python 依赖安装失败。' }
if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
if ($RebuildFrontend -or -not (Test-Path -LiteralPath 'frontend\out\index.html')) {
Set-Location -LiteralPath (Join-Path $PSScriptRoot 'frontend')
$env:NEXT_TELEMETRY_DISABLED='1'
$taskBundledPnpm = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules\pnpm\bin\pnpm.cjs'
$taskBundledNode = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe'
if (Test-Path -LiteralPath $taskBundledNode) { $taskNode = $taskBundledNode }
elseif (Get-Command node -ErrorAction SilentlyContinue) { $taskNode = (Get-Command node).Source }
else { throw '构建前端需要 Node.js 22 或更高版本。' }
if (Test-Path -LiteralPath $taskBundledPnpm) { & $taskNode $taskBundledPnpm install --frozen-lockfile }
elseif (Get-Command pnpm -ErrorAction SilentlyContinue) { pnpm install --frozen-lockfile }
else { npm install }
if ($LASTEXITCODE -ne 0) { throw '前端依赖安装失败，请检查网络。' }
& $taskNode .\node_modules\next\dist\bin\next build --webpack
if ($LASTEXITCODE -ne 0) { throw '前端构建失败。' }
}
Set-Location -LiteralPath $PSScriptRoot
& $taskPython -m pytest
if ($LASTEXITCODE -ne 0) { throw '核心测试未通过。' }
Write-Host '安装与验证完成。双击“启动系统.cmd”运行。'
