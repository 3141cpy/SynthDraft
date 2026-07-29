<#
.SYNOPSIS
    检查 SynthDraft SolidWorks Add-in 远端版本更新。
.DESCRIPTION
    读取本地 version.json，拉取远端版本清单，比较版本号。
    降级逻辑：远端不可达或 download_url 为空时不报错，仅提示。
    不引入 SemVer 库，手写版本比较函数。
.PARAMETER RemoteUrl
    远端版本清单 URL。为空时使用内置默认值。
.EXAMPLE
    .\check_update.ps1
    .\check_update.ps1 -RemoteUrl https://example.com/synthdraft/version.json
#>
[CmdletBinding()]
param(
    [string]$RemoteUrl = ""
)

$ErrorActionPreference = "Continue"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$localVersionPath = Join-Path $scriptDir "version.json"

function Write-Info([string]$msg) { Write-Host "[INFO] $msg" -ForegroundColor Cyan }
function Write-Ok([string]$msg)   { Write-Host "[ OK ] $msg" -ForegroundColor Green }
function Write-Warn([string]$msg) { Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Write-Err([string]$msg)  { Write-Host "[FAIL] $msg" -ForegroundColor Red }

# ===== 手写版本比较函数（不引入 SemVer 库）=====
# 返回值：1 = $a > $b；-1 = $a < $b；0 = 相等
function Compare-Version([string]$a, [string]$b) {
    if ([string]::IsNullOrEmpty($a)) { return -1 }
    if ([string]::IsNullOrEmpty($b)) { return 1 }
    $partsA = $a.Split('.')
    $partsB = $b.Split('.')
    $maxLen = [Math]::Max($partsA.Length, $partsB.Length)
    for ($i = 0; $i -lt $maxLen; $i++) {
        $va = if ($i -lt $partsA.Length) { [int]$partsA[$i] } else { 0 }
        $vb = if ($i -lt $partsB.Length) { [int]$partsB[$i] } else { 0 }
        if ($va -gt $vb) { return 1 }
        if ($va -lt $vb) { return -1 }
    }
    return 0
}

Write-Host "===== SynthDraft Add-in 更新检查 =====" -ForegroundColor Cyan
Write-Host ""

# ===== 读取本地 version.json =====
Write-Info "读取本地版本清单: $localVersionPath"
if (-not (Test-Path $localVersionPath)) {
    Write-Err "本地 version.json 不存在: $localVersionPath"
    Write-Err "无法检查更新（缺少本地版本信息）"
    exit 3
}

try {
    $localVersion = Get-Content $localVersionPath -Raw | ConvertFrom-Json
} catch {
    Write-Err "本地 version.json 解析失败: $($_.Exception.Message)"
    exit 3
}

$localVer = $localVersion.version
Write-Ok "本地版本: $localVer"
Write-Host "  兼容 SolidWorks: $($localVersion.solidworks_compatibility)"
Write-Host "  后端 API 版本:  $($localVersion.backend_api_version)"
Write-Host "  .NET Framework:  $($localVersion.dotnet_framework)"
Write-Host "  发布日期:        $($localVersion.release_date)"
Write-Host ""

# ===== 拉取远端版本清单 =====
if ([string]::IsNullOrEmpty($RemoteUrl)) {
    # 不再使用占位地址（synthdraft.example.com）作为默认值，避免误导用户认为更新检查已执行。
    Write-Warn "未指定 -RemoteUrl，且无内置默认远端版本清单 URL。"
    Write-Warn "请通过 -RemoteUrl 参数指定实际远端版本清单 URL。"
    Write-Host ""
    Write-Host "===== 更新检查结论 =====" -ForegroundColor Cyan
    Write-Host "  状态: 未配置远端 URL，跳过更新检查" -ForegroundColor Yellow
    Write-Host "  本地版本: $localVer" -ForegroundColor White
    Write-Host "  建议: 通过 -RemoteUrl 指定远端版本清单 URL 后重试" -ForegroundColor White
    exit 0
}

Write-Info "拉取远端版本清单: $RemoteUrl"
$remoteVersion = $null
try {
    # 降级逻辑：远端不可达时不报错，仅提示
    $response = Invoke-WebRequest -Uri $RemoteUrl -UseBasicParsing -TimeoutSec 10 -ErrorAction Stop
    $remoteVersion = $response.Content | ConvertFrom-Json
    Write-Ok "远端版本: $($remoteVersion.version)"
} catch {
    # 降级：远端不可达，不报错
    Write-Warn "远端不可达: $($_.Exception.Message)"
    Write-Warn "无法检查更新（远端服务不可用）"
    Write-Host ""
    Write-Host "===== 更新检查结论 =====" -ForegroundColor Cyan
    Write-Host "  状态: 远端不可达，跳过更新检查" -ForegroundColor Yellow
    Write-Host "  本地版本: $localVer" -ForegroundColor White
    Write-Host "  建议: 稍后重试或联系管理员确认远端服务" -ForegroundColor White
    exit 0
}

# ===== 版本比较 =====
Write-Host ""
Write-Host "===== 版本比较 =====" -ForegroundColor Cyan
$cmp = Compare-Version $remoteVersion.version $localVer
switch ($cmp) {
    1 {
        Write-Host "  发现新版本！" -ForegroundColor Green
        Write-Host "  本地版本: $localVer" -ForegroundColor White
        Write-Host "  远端版本: $($remoteVersion.version)" -ForegroundColor Green
        Write-Host "  发布日期: $($remoteVersion.release_date)" -ForegroundColor White
        if (-not [string]::IsNullOrEmpty($remoteVersion.download_url)) {
            Write-Host "  下载地址: $($remoteVersion.download_url)" -ForegroundColor Cyan
            Write-Host "  校验和:   $($remoteVersion.checksum)" -ForegroundColor White
            Write-Host ""
            Write-Host "  更新步骤:" -ForegroundColor Cyan
            Write-Host "    1. 下载新版本到本地" -ForegroundColor White
            Write-Host "    2. 执行 .\uninstall.ps1 卸载旧版本" -ForegroundColor White
            Write-Host "    3. 替换文件后执行 .\install.ps1 安装新版本" -ForegroundColor White
        } else {
            # 降级逻辑：download_url 为空时不报错
            Write-Warn "  远端未提供下载地址（download_url 为空）"
            Write-Host "  请联系管理员获取新版本" -ForegroundColor White
        }
        exit 1
    }
    0 {
        Write-Ok "  版本一致: $localVer"
        Write-Host "  当前已是最新版本" -ForegroundColor Green
        exit 0
    }
    -1 {
        Write-Warn "  本地版本 $localVer 高于远端版本 $($remoteVersion.version)"
        Write-Host "  可能使用了开发版本" -ForegroundColor Yellow
        exit 0
    }
}
