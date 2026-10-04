param([int]$Port = 8000, [switch]$NoBrowser, [switch]$Lan)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    throw '请先运行 setup.ps1 安装项目依赖。'
}
if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'frontend\out\index.html'))) {
    throw '前端尚未构建，请先运行 setup.ps1。'
}
$taskUrl = "http://127.0.0.1:$Port"
$taskBind = '127.0.0.1'
$env:HOST = $taskBind
$env:PORT = "$Port"
if ($Lan) {
    $taskNetworks = @(Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -and $_.IPv4Address })
    $taskAddress = $taskNetworks | ForEach-Object { $_.IPv4Address.IPAddress } | Where-Object { $_ -match '^(10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.)' } | Select-Object -First 1
    if (-not $taskAddress) { throw '未找到局域网 IPv4 地址。请先连接 Wi-Fi 或有线网络。' }
    $taskBind = '0.0.0.0'
    $taskUrl = "http://${taskAddress}:$Port"
    $env:HOST = $taskBind
    $env:LAN_ADDRESS = $taskAddress
    $env:PUBLIC_BASE_URL = $taskUrl
}
$taskExisting = $null
try { $taskExisting = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 2 } catch {}
if ($taskExisting) {
    if ($taskExisting.algorithm -ne 'Deep SARSA') { throw "端口 $Port 已被其他服务占用。" }
    if ($Lan) {
        $taskSharing = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/access" -TimeoutSec 2
        if ($taskSharing.mode -ne 'lan' -or $taskSharing.share_url -ne $taskUrl) { throw '当前仍有旧的本机服务运行。请先关闭原启动窗口，再运行手机共享启动.cmd。' }
    }
    Write-Host "系统已运行：$taskUrl"
    if (-not $NoBrowser) { Start-Process $taskUrl }
    exit 0
}
Write-Host "三只松鼠营销工作台：$taskUrl"
if ($Lan) { Write-Host '手机和电脑连接同一 Wi-Fi 后，可在网页的“手机访问”中扫码。' }
Write-Host '关闭当前终端窗口会停止服务。'
if (-not $NoBrowser) {
    $taskBrowser = {
        param($taskWebUrl)
        for ($taskTry=0; $taskTry -lt 30; $taskTry++) {
            try {
                $taskReady = Invoke-RestMethod -Uri "$taskWebUrl/api/health" -TimeoutSec 1
                if ($taskReady.status -eq 'ok') { Start-Process $taskWebUrl; break }
            } catch {}
            Start-Sleep -Milliseconds 1000
        }
    }
    Start-Job -ScriptBlock $taskBrowser -ArgumentList $taskUrl | Out-Null
}
& $taskPython -m uvicorn backend.main:app --host $taskBind --port $Port
exit $LASTEXITCODE
