<#
.SYNOPSIS
    检查 SynthDraft SolidWorks Add-in 安装版本与最新版本。
.DESCRIPTION
    读取已安装 manifest.json 与本地编译产物版本，对比显示。
    退出码：0=最新，1=需更新，2=未安装，3=未编译。
.EXAMPLE
    .\check-version.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$AddInClsid = "{B5E8F2A1-3C4D-4E9F-8A2B-1D3E5F7A9C2D}"
$AddInGuid = $AddInClsid.TrimStart("{").TrimEnd("}")
$InstallDir = Join-Path $env:ProgramData "SynthDraft\AddIn"
$RegKeySolidWorksAddIns = "HKCU:\Software\SolidWorks\AddIns\$AddInGuid"
$RegKeySynthDraft = "HKCU:\Software\SynthDraft"

Write-Host "===== SynthDraft Add-in 版本检查 =====" -ForegroundColor Cyan
Write-Host ""

# ===== 已安装版本 =====
$manifestPath = Join-Path $InstallDir "manifest.json"
$installedVersion = $null
$installTime = $null
$backendUrl = $null

if (Test-Path $manifestPath) {
    $manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
    $installedVersion = $manifest.version
    $installTime = $manifest.install_time
    $backendUrl = $manifest.backend_url
    Write-Host "[已安装]" -ForegroundColor Green
    Write-Host "  版本:        $($manifest.version)"
    Write-Host "  CLSID:       $($manifest.clsid)"
    Write-Host "  ProgID:      $($manifest.progid)"
    Write-Host "  安装目录:    $($manifest.install_dir)"
    Write-Host "  后端 URL:    $($manifest.backend_url)"
    Write-Host "  安装时间:    $($manifest.install_time)"
} else {
    Write-Host "[已安装] 未找到 manifest.json" -ForegroundColor Yellow
}

# ===== 注册表状态 =====
Write-Host ""
Write-Host "[注册表]" -ForegroundColor Cyan
$swReg = Get-ItemProperty $RegKeySolidWorksAddIns -ErrorAction SilentlyContinue
if ($swReg) {
    Write-Host "  SolidWorks AddIns 项:    存在" -ForegroundColor Green
    Write-Host "  Default (启用):          $($swReg.'(Default)')"
    Write-Host "  Title:                   $($swReg.Title)"
    Write-Host "  Startup:                 $($swReg.Startup)"
} else {
    Write-Host "  SolidWorks AddIns 项:    不存在" -ForegroundColor Yellow
}

$synthReg = Get-ItemProperty $RegKeySynthDraft -ErrorAction SilentlyContinue
if ($synthReg) {
    Write-Host "  SynthDraft 配置项:       存在" -ForegroundColor Green
    Write-Host "  backend_url:             $($synthReg.backend_url)"
    Write-Host "  version (注册表):        $($synthReg.version)"
} else {
    Write-Host "  SynthDraft 配置项:       不存在" -ForegroundColor Yellow
}

# ===== COM 注册状态 =====
Write-Host ""
Write-Host "[COM 注册]" -ForegroundColor Cyan
$clsidKey = "HKCU:\Software\Classes\CLSID\$AddInClsid"
$clsidReg = Get-ItemProperty $clsidKey -ErrorAction SilentlyContinue
if ($clsidReg) {
    $inproc = (Get-ItemProperty "$clsidKey\InprocServer32" -ErrorAction SilentlyContinue).'(Default)'
    Write-Host "  HKCU CLSID:               存在" -ForegroundColor Green
    Write-Host "  InprocServer32:           $inproc"
} else {
    Write-Host "  HKCU CLSID:               不存在" -ForegroundColor Yellow
}

# ===== 本地最新编译版本 =====
Write-Host ""
Write-Host "[本地最新]" -ForegroundColor Cyan
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$dllSource = Join-Path $scriptDir "bin\Release\SynthDraftAddIn.dll"
if (Test-Path $dllSource) {
    $localVersion = (Get-Item $dllSource).VersionInfo.FileVersion
    $localTime = (Get-Item $dllSource).LastWriteTime
    Write-Host "  DLL:                      $dllSource"
    Write-Host "  版本:                     $localVersion"
    Write-Host "  编译时间:                 $localTime"
} else {
    Write-Host "  未编译：$dllSource 不存在" -ForegroundColor Yellow
    Write-Host "  请先执行 build.ps1 或编译命令。" -ForegroundColor Yellow
    exit 3
}

# ===== 版本对比 =====
Write-Host ""
Write-Host "[对比]" -ForegroundColor Cyan
if (-not $installedVersion) {
    Write-Host "  Add-in 未安装" -ForegroundColor Yellow
    Write-Host "  请执行 .\install.ps1 安装" -ForegroundColor Yellow
    exit 2
} elseif ($localVersion -and ($installedVersion -ne $localVersion)) {
    Write-Host "  已安装版本 $installedVersion 与本地编译版本 $localVersion 不一致" -ForegroundColor Yellow
    Write-Host "  请执行 .\install.ps1 -Force 更新" -ForegroundColor Yellow
    exit 1
} else {
    Write-Host "  版本一致: $installedVersion" -ForegroundColor Green
    exit 0
}
