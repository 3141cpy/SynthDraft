<#
.SYNOPSIS
    SynthDraft 开发环境一键启动脚本（Windows PowerShell）
.DESCRIPTION
    1. 检查并创建 .env（从 .env.example 拷贝）
    2. 启动 Docker Compose 全部服务
    3. 输出各服务访问地址
.NOTES
    需要先安装 Docker Desktop 并启动 Docker 引擎。
#>

param(
    [switch]$Rebuild,
    [switch]$Down,
    [switch]$Logs
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$InfraDir = Join-Path $RepoRoot "infra"

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "  [!]  $msg" -ForegroundColor Yellow }

if ($Down) {
    Write-Step "停止所有 SynthDraft 服务"
    Push-Location $InfraDir
    docker compose --env-file .env down
    Pop-Location
    Write-Ok "已停止"
    exit 0
}

# 1. 检查 Docker
Write-Step "检查 Docker 引擎"
$dockerOk = $false
try {
    docker info *> $null
    $dockerOk = $LASTEXITCODE -eq 0
} catch { }
if (-not $dockerOk) {
    Write-Warn "Docker 未运行，请先启动 Docker Desktop"
    exit 1
}
Write-Ok "Docker 引擎正常"

# 2. 检查 .env
Push-Location $InfraDir
$envFile = Join-Path $InfraDir ".env"
$envExample = Join-Path $InfraDir ".env.example"
if (-not (Test-Path $envFile)) {
    if (Test-Path $envExample) {
        Write-Step "从 .env.example 创建 .env"
        Copy-Item $envExample $envFile
        Write-Ok ".env 已创建（请按需修改密码/密钥）"
    } else {
        Write-Warn "未找到 .env.example，请手动创建 .env"
        Pop-Location
        exit 1
    }
} else {
    Write-Ok ".env 已存在"
}

# 3. 启动服务
Write-Step "启动 Docker Compose 服务"
$composeArgs = @("compose", "--env-file", ".env", "up", "-d")
if ($Rebuild) {
    $composeArgs += "--build"
}
& docker @composeArgs
if ($LASTEXITCODE -ne 0) {
    Write-Warn "docker compose 启动失败"
    Pop-Location
    exit 1
}
Pop-Location

# 4. 输出访问地址
Write-Step "服务访问地址"
Write-Host ""
Write-Host "  FastAPI 文档:    http://localhost:8000/docs"        -ForegroundColor White
Write-Host "  健康检查:        http://localhost:8000/api/v1/healthz" -ForegroundColor White
Write-Host "  就绪检查:        http://localhost:8000/api/v1/readyz"  -ForegroundColor White
Write-Host "  MinIO 控制台:    http://localhost:9001"               -ForegroundColor White
Write-Host "  Qdrant 控制台:   http://localhost:6333/dashboard"     -ForegroundColor White
Write-Host "  PostgreSQL:      localhost:5432"                     -ForegroundColor White
Write-Host "  Redis:           localhost:6379"                     -ForegroundColor White
Write-Host "  Ollama API:      http://localhost:11434"             -ForegroundColor White
Write-Host ""

if ($Logs) {
    Write-Step "跟踪日志（Ctrl+C 退出）"
    Push-Location $InfraDir
    docker compose --env-file .env logs -f
    Pop-Location
}

Write-Ok "启动完成"
