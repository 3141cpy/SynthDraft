<#
.SYNOPSIS
    卸载 SynthDraft SolidWorks Add-in。
.DESCRIPTION
    步骤：
    1. 注销 COM 类型（regasm /unregister）。
    2. 删除 SolidWorks Add-in 注册表项。
    3. 删除 SynthDraft 配置注册表项（可选）。
    4. 删除安装目录与文件。
    5. 显示卸载结果。
.PARAMETER KeepConfig
    保留 HKCU\Software\SynthDraft 配置（后端 URL 等）。
.EXAMPLE
    .\uninstall.ps1
    .\uninstall.ps1 -KeepConfig
#>
[CmdletBinding()]
param(
    [switch]$KeepConfig
)

$ErrorActionPreference = "Stop"
$ProgId = "SynthDraft.AddIn"
$AddInClsid = "{B5E8F2A1-3C4D-4E9F-8A2B-1D3E5F7A9C2D}"
$AddInGuid = $AddInClsid.TrimStart("{").TrimEnd("}")
$InstallDir = Join-Path $env:ProgramData "SynthDraft\AddIn"
$RegKeySolidWorksAddIns = "HKCU:\Software\SolidWorks\AddIns\$AddInGuid"
$RegKeySynthDraft = "HKCU:\Software\SynthDraft"

function Write-Step([string]$msg) { Write-Host "[STEP] $msg" -ForegroundColor Cyan }
function Write-Ok([string]$msg)   { Write-Host "[ OK ] $msg" -ForegroundColor Green }
function Write-Warn([string]$msg) { Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Write-Err([string]$msg)  { Write-Host "[FAIL] $msg" -ForegroundColor Red }

# ===== Step 1: 注销 COM =====
Write-Step "1/4 注销 COM 类型..."
$installedDll = Join-Path $InstallDir "SynthDraftAddIn.dll"
$regasm = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\regasm.exe"
if (Test-Path $installedDll) {
    if (Test-Path $regasm) {
        & $regasm /unregister $installedDll 2>&1 | ForEach-Object {
            if ($_ -match "successfully|unregister") { Write-Ok $_ } else { Write-Host $_ }
        }
        Write-Ok "COM 类型已注销"
    } else {
        Write-Warn "regasm.exe 不存在，跳过 COM 注销"
    }
} else {
    Write-Warn "安装目录无 DLL，可能已卸载: $installedDll"
}

# 兜底：直接删除 HKCR\CLSID\{GUID}
$hkcrClsid = "HKCU:\Software\Classes\CLSID\$AddInClsid"
if (Test-Path $hkcrClsid) {
    Remove-Item $hkcrClsid -Force -Recurse -ErrorAction SilentlyContinue
    Write-Ok "已删除 HKCU\Software\Classes\CLSID\$AddInClsid"
}
$hkcrProgId = "HKCU:\Software\Classes\$ProgId"
if (Test-Path $hkcrProgId) {
    Remove-Item $hkcrProgId -Force -Recurse -ErrorAction SilentlyContinue
    Write-Ok "已删除 HKCU\Software\Classes\$ProgId"
}

# ===== Step 2: 删除 SolidWorks Add-in 注册表项 =====
Write-Step "2/4 删除 SolidWorks Add-in 注册表项..."
if (Test-Path $RegKeySolidWorksAddIns) {
    Remove-Item $RegKeySolidWorksAddIns -Force -Recurse
    Write-Ok "已删除: $RegKeySolidWorksAddIns"
} else {
    Write-Warn "注册表项不存在（可能已卸载）: $RegKeySolidWorksAddIns"
}
# 同步清理 AddInsStartup\{GUID} 启动加载项
$RegKeySolidWorksAddInsStartup = "HKCU:\Software\SolidWorks\AddInsStartup\$AddInGuid"
if (Test-Path $RegKeySolidWorksAddInsStartup) {
    Remove-Item $RegKeySolidWorksAddInsStartup -Force -Recurse
    Write-Ok "已删除: $RegKeySolidWorksAddInsStartup"
}

# ===== Step 3: 删除 SynthDraft 配置（可选）=====
Write-Step "3/4 处理 SynthDraft 配置..."
if ($KeepConfig) {
    Write-Warn "保留 SynthDraft 配置（HKCU\Software\SynthDraft）"
} else {
    if (Test-Path $RegKeySynthDraft) {
        Remove-Item $RegKeySynthDraft -Force -Recurse
        Write-Ok "已删除: $RegKeySynthDraft"
    } else {
        Write-Warn "SynthDraft 配置不存在"
    }
}

# ===== Step 4: 删除安装目录 =====
Write-Step "4/4 删除安装目录..."
if (Test-Path $InstallDir) {
    Remove-Item $InstallDir -Force -Recurse -ErrorAction SilentlyContinue
    if (-not (Test-Path $InstallDir)) {
        Write-Ok "已删除: $InstallDir"
    } else {
        Write-Warn "部分文件未能删除（可能被占用），请手动删除: $InstallDir"
    }
} else {
    Write-Warn "安装目录不存在: $InstallDir"
}

Write-Host ""
Write-Host "==========================================" -ForegroundColor Green
Write-Host " SynthDraft Add-in 卸载完成！" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
Write-Host " 请重启 SolidWorks 以确保插件已卸载。" -ForegroundColor Yellow
Write-Host ""
