<#
.SYNOPSIS
    编译 SynthDraft SolidWorks Add-in。
.DESCRIPTION
    使用 Roslyn csc.exe (VS 2019 BuildTools) 或 .NET Framework 4.x csc.exe 编译。
    输出到 bin\Release\SynthDraftAddIn.dll。
.EXAMPLE
    .\build.ps1
    .\build.ps1 -Configuration Debug
#>
[CmdletBinding()]
param(
    [ValidateSet("Release","Debug")]
    [string]$Configuration = "Release"
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$outDir = Join-Path $scriptDir "bin\$Configuration"
$dllPath = Join-Path $outDir "SynthDraftAddIn.dll"

function Write-Step([string]$msg) { Write-Host "[STEP] $msg" -ForegroundColor Cyan }
function Write-Ok([string]$msg)   { Write-Host "[ OK ] $msg" -ForegroundColor Green }
function Write-Err([string]$msg)  { Write-Host "[FAIL] $msg" -ForegroundColor Red }

# ===== Step 1: 找 csc.exe =====
Write-Step "1/4 定位 csc.exe..."
$cscCandidates = @(
    "C:\Program Files (x86)\Microsoft Visual Studio\2019\BuildTools\MSBuild\Current\Bin\Roslyn\csc.exe",
    "C:\Program Files\Microsoft Visual Studio\2022\Community\MSBuild\Current\Bin\Roslyn\csc.exe",
    "C:\Program Files\Microsoft Visual Studio\2022\Professional\MSBuild\Current\Bin\Roslyn\csc.exe",
    "C:\Program Files\Microsoft Visual Studio\2022\BuildTools\MSBuild\Current\Bin\Roslyn\csc.exe",
    "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
)
$csc = $cscCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $csc) {
    Write-Err "未找到 csc.exe。请安装 Visual Studio BuildTools 或 .NET Framework SDK。"
    exit 1
}
Write-Ok "csc.exe: $csc"

# ===== Step 2: 验证 SolidWorks 互操作 DLL =====
Write-Step "2/4 验证 SolidWorks 互操作 DLL..."
# 多策略查找 SolidWorks 安装路径
$swSetupPath = $null
# Strategy 1: SolidWorks 注册表
$swReg = Get-ItemProperty "HKLM:\SOFTWARE\SolidWorks\SOLIDWORKS" -ErrorAction SilentlyContinue
if ($swReg -and $swReg.SetupPath) { $swSetupPath = $swReg.SetupPath }
if (-not $swSetupPath) {
    Get-ChildItem "HKLM:\SOFTWARE\SolidWorks" -ErrorAction SilentlyContinue | ForEach-Object {
        if ($_.PSChildName -like "SolidWorks *") {
            $p = Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue
            if ($p -and $p.SetupPath) { $swSetupPath = $p.SetupPath }
        }
    }
}
# Strategy 2: Uninstall 注册表
if (-not $swSetupPath) {
    Get-ChildItem "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall" -ErrorAction SilentlyContinue | ForEach-Object {
        $p = Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue
        if ($p.DisplayName -like "SOLIDWORKS 20*" -and $p.InstallLocation) {
            if (-not $swSetupPath -or $p.DisplayName -like "*2025*") {
                $swSetupPath = $p.InstallLocation
            }
        }
    }
}
# Strategy 3: 已知路径兜底
if (-not $swSetupPath) {
    $candidates = @(
        "D:\Program Files\SolidWorks Corp\SOLIDWORKS",
        "D:\Program Files\SOLIDWORKS Corp\SOLIDWORKS",
        "C:\Program Files\SolidWorks Corp\SOLIDWORKS",
        "C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS"
    )
    foreach ($c in $candidates) {
        if (Test-Path (Join-Path $c "SLDWORKS.exe")) { $swSetupPath = $c; break }
    }
}
if (-not $swSetupPath) {
    Write-Err "未检测到 SolidWorks 安装。"
    exit 1
}
$swSetupPath = $swSetupPath.TrimEnd('\')
$swReg = [PSCustomObject]@{ SetupPath = $swSetupPath }
$swRedist = Join-Path $swSetupPath "api\redist"
$requiredInterops = @(
    "SolidWorks.Interop.sldworks.dll",
    "SolidWorks.Interop.swconst.dll",
    "SolidWorks.Interop.swpublished.dll",
    "SolidWorks.Interop.swcommands.dll"
)
foreach ($dll in $requiredInterops) {
    $path = Join-Path $swRedist $dll
    if (-not (Test-Path $path)) {
        Write-Err "缺少互操作 DLL: $path"
        exit 1
    }
}
Write-Ok "SolidWorks 互操作 DLL 路径: $swRedist"

# ===== Step 3: 编译 =====
Write-Step "3/4 编译 (Configuration=$Configuration)..."
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

$fw = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319"
$refs = @(
    "/r:`"$fw\System.dll`"",
    "/r:`"$fw\System.Core.dll`"",
    "/r:`"$fw\System.Drawing.dll`"",
    "/r:`"$fw\System.Net.Http.dll`"",
    "/r:`"$fw\System.Net.WebSockets.Client.dll`"",
    "/r:`"$fw\System.Web.dll`"",
    "/r:`"$fw\System.Web.Extensions.dll`"",
    "/r:`"$fw\System.Windows.Forms.dll`"",
    "/r:`"$fw\System.Xml.dll`"",
    "/r:`"$fw\System.Xml.Linq.dll`"",
    "/r:`"$fw\Microsoft.CSharp.dll`"",
    "/r:`"$swRedist\SolidWorks.Interop.sldworks.dll`"",
    "/r:`"$swRedist\SolidWorks.Interop.swconst.dll`"",
    "/r:`"$swRedist\SolidWorks.Interop.swpublished.dll`"",
    "/r:`"$swRedist\SolidWorks.Interop.swcommands.dll`""
)

$sources = @(
    (Join-Path $scriptDir "SynthDraftAddIn.cs"),
    (Join-Path $scriptDir "BackendClient.cs"),
    (Join-Path $scriptDir "Properties\AssemblyInfo.cs")
)

$define = if ($Configuration -eq "Debug") { "/define:DEBUG;TRACE" } else { "/define:TRACE" }
$debug = if ($Configuration -eq "Debug") { "/debug:full" } else { "/optimize+" }

# 仅 Roslyn csc 支持 /langversion:7.3
$langVer = if ($csc -match "Roslyn") { "/langversion:7.3" } else { "" }

$args = @("/nologo", "/target:library", "/out:`"$dllPath`"", "/platform:anycpu", $define, $debug, $langVer) + $refs + $sources
& $csc @args 2>&1 | ForEach-Object {
    if ($_ -match "error") { Write-Err $_ }
    elseif ($_ -match "warning") { Write-Host $_ -ForegroundColor Yellow }
    else { Write-Host $_ }
}

if ($LASTEXITCODE -ne 0) {
    Write-Err "编译失败 (exit $LASTEXITCODE)"
    exit 1
}
if (-not (Test-Path $dllPath)) {
    Write-Err "未生成 DLL: $dllPath"
    exit 1
}

# ===== Step 4: 显示编译结果 =====
Write-Step "4/4 编译结果"
$dllInfo = Get-Item $dllPath
Write-Ok "DLL: $($dllInfo.FullName)"
Write-Ok "大小: $($dllInfo.Length) bytes"
Write-Ok "版本: $($dllInfo.VersionInfo.FileVersion)"
Write-Ok "时间: $($dllInfo.LastWriteTime)"
Write-Host ""
Write-Host "下一步: 执行 .\install.ps1 安装到 SolidWorks" -ForegroundColor Cyan
