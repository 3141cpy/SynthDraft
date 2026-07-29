# Celery solo pool 启动脚本（Windows 兼容）
# 用法：在 backend 目录下运行 .\scripts\start_celery_solo.ps1
# solo pool 单线程顺序执行，避免 Windows prefork 池卡死问题

$ErrorActionPreference = "Stop"

# 切换到 backend 目录
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendDir = Split-Path -Parent $scriptDir
Set-Location $backendDir

# 激活虚拟环境
$venvActivate = Join-Path $backendDir ".venv\Scripts\Activate.ps1"
if (Test-Path $venvActivate) {
    & $venvActivate
    Write-Host "[INFO] Virtual environment activated" -ForegroundColor Green
} else {
    Write-Host "[WARN] Virtual environment not found at $venvActivate" -ForegroundColor Yellow
}

# 启动 Celery worker with solo pool
Write-Host "[INFO] Starting Celery worker with --pool=solo ..." -ForegroundColor Cyan
celery -A app.celery_app worker --pool=solo --loglevel=info --queues=default,reviews,generations,sketch,collaboration
