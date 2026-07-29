<#
.SYNOPSIS
    安装 SynthDraft SolidWorks Add-in。
.DESCRIPTION
    步骤：
    1. 验证 SolidWorks 已安装（ HKLM\SOFTWARE\SolidWorks\SOLIDWORKS [SetupPath] ）。
    2. 验证 SynthDraftAddIn.dll 已编译。
    3. 复制 DLL + 互操作依赖到 %ProgramData%\SynthDraft\AddIn\。
    4. 使用 regasm /codebase 注册 COM 类型库（HKCR）。
    5. 写入 SolidWorks Add-in 注册表项（HKCU\Software\SolidWorks\AddIns\{GUID}）。
    6. 写入后端 URL 配置（HKCU\Software\SynthDraft\backend_url）。
    7. 显示安装结果与重启 SolidWorks 提示。
.PARAMETER BackendUrl
    SynthDraft 后端 URL，默认 http://localhost:8000。
.PARAMETER Force
    覆盖已存在的安装。
.EXAMPLE
    .\install.ps1 -BackendUrl http://192.168.1.100:8000
#>
[CmdletBinding()]
param(
    [string]$BackendUrl = "http://localhost:8000",
    [string]$RedistPath = "",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$ProgId = "SynthDraft.AddIn"
$AddInClsid = "{B5E8F2A1-3C4D-4E9F-8A2B-1D3E5F7A9C2D}"
$AddInGuid = $AddInClsid.TrimStart("{").TrimEnd("}")
$InstallDir = Join-Path $env:ProgramData "SynthDraft\AddIn"
$RegKeySolidWorksAddIns = "HKCU:\Software\SolidWorks\AddIns\$AddInGuid"
$RegKeySynthDraft = "HKCU:\Software\SynthDraft"

# 支持 SOLIDWORKS_API_REDIST 环境变量覆盖 interop DLL 路径
if ([string]::IsNullOrEmpty($RedistPath) -and $env:SOLIDWORKS_API_REDIST) {
    $RedistPath = $env:SOLIDWORKS_API_REDIST
}

function Write-Step([string]$msg) { Write-Host "[STEP] $msg" -ForegroundColor Cyan }
function Write-Ok([string]$msg)   { Write-Host "[ OK ] $msg" -ForegroundColor Green }
function Write-Warn([string]$msg) { Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Write-Err([string]$msg)  { Write-Host "[FAIL] $msg" -ForegroundColor Red }

# ===== Step 0: 验证 .NET Framework 4.8 前置条件 =====
Write-Step "0/7 验证 .NET Framework 4.8 前置条件..."
try {
    $netRelease = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full' -Name Release -ErrorAction Stop).Release
    # .NET Framework 4.8 = Release 528040; 4.8.1 = 533320
    if ($netRelease -ge 528040) {
        Write-Ok ".NET Framework 4.8+ 已安装 (Release=$netRelease)"
    } else {
        Write-Err ".NET Framework 4.8 未安装 (Release=$netRelease, 需要 >= 528040)"
        exit 1
    }
} catch {
    Write-Err "无法读取 .NET Framework 版本: $($_.Exception.Message)"
    Write-Err "请确认 .NET Framework 4.8 已安装（Release >= 528040）"
    exit 1
}

# ===== Step 1: 验证 SolidWorks 安装 =====
Write-Step "1/7 验证 SolidWorks 安装..."
# 多策略查找 SolidWorks 安装路径：
# 1) HKLM\SOFTWARE\SolidWorks\SolidWorks <Version>\SetupPath （官方推荐，但本机为空）
# 2) HKLM Uninstall 注册表 InstallLocation （SolidWorks 2024/2025 SP03 在此登记）
# 3) 已知路径兜底扫描
$swSetupPath = $null

# Strategy 1: SolidWorks 注册表
$swReg = Get-ItemProperty "HKLM:\SOFTWARE\SolidWorks\SOLIDWORKS" -ErrorAction SilentlyContinue
if ($swReg -and $swReg.SetupPath) { $swSetupPath = $swReg.SetupPath }
if (-not $swSetupPath) {
    # 枚举所有 SolidWorks <Version> 子键
    Get-ChildItem "HKLM:\SOFTWARE\SolidWorks" -ErrorAction SilentlyContinue | ForEach-Object {
        if ($_.PSChildName -like "SolidWorks *") {
            $p = Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue
            if ($p -and $p.SetupPath) { $swSetupPath = $p.SetupPath }
        }
    }
}

# Strategy 2: Uninstall 注册表（本机实际使用此路径）
if (-not $swSetupPath) {
    Get-ChildItem "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall" -ErrorAction SilentlyContinue | ForEach-Object {
        $p = Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue
        if ($p.DisplayName -like "SOLIDWORKS 20*" -and $p.InstallLocation) {
            # 优先选 2025 版本
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
        "C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS",
        "E:\gong ju zi liao\jianmo huatu\SOLIDWORKS"
    )
    foreach ($c in $candidates) {
        if (Test-Path (Join-Path $c "SLDWORKS.exe")) {
            $swSetupPath = $c
            break
        }
    }
}

if (-not $swSetupPath) {
    Write-Err "未检测到 SolidWorks 安装。请确认 SolidWorks 已安装。"
    Write-Err "尝试位置: HKLM\SOFTWARE\SolidWorks\*, HKLM Uninstall, 常见路径"
    exit 1
}
$swSetupPath = $swSetupPath.TrimEnd('\')
$swExe = Join-Path $swSetupPath "SLDWORKS.exe"
if (-not (Test-Path $swExe)) {
    Write-Err "SolidWorks 可执行文件不存在: $swExe"
    exit 1
}
# 构造一个伪 swReg 对象供后续使用
$swReg = [PSCustomObject]@{ SetupPath = $swSetupPath }
Write-Ok "SolidWorks 已安装: $swExe"

# ===== Step 2: 验证 DLL 已编译 =====
Write-Step "2/7 验证 SynthDraftAddIn.dll..."
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$dllSource = Join-Path $scriptDir "bin\Release\SynthDraftAddIn.dll"
if (-not (Test-Path $dllSource)) {
    Write-Err "未找到编译产物: $dllSource"
    Write-Err "请先执行 build: csc.exe /target:library /out:bin\Release\SynthDraftAddIn.dll ..."
    exit 1
}
$dllVersion = (Get-Item $dllSource).VersionInfo.FileVersion
Write-Ok "DLL 已就绪: $dllSource (v$dllVersion)"

# ===== Step 3: 复制文件到 ProgramData =====
Write-Step "3/7 复制文件到 $InstallDir..."
if ((Test-Path $InstallDir) -and -not $Force) {
    $existing = Get-ChildItem $InstallDir -Filter "SynthDraftAddIn.dll" -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Warn "目标目录已存在 DLL。使用 -Force 覆盖。"
        exit 1
    }
}
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

# 复制主 DLL
Copy-Item $dllSource $InstallDir -Force

# 复制 SolidWorks 互操作 DLL（如有，否则依赖 GAC/嵌入类型）
# 支持 -RedistPath 参数或 SOLIDWORKS_API_REDIST 环境变量覆盖路径
if ($RedistPath -and (Test-Path $RedistPath)) {
    $swRedist = $RedistPath
    Write-Ok "使用自定义 interop 路径: $swRedist"
} else {
    $swRedist = Join-Path $swReg.SetupPath "api\redist"
}
$interopDlls = @(
    "SolidWorks.Interop.sldworks.dll",
    "SolidWorks.Interop.swconst.dll",
    "SolidWorks.Interop.swpublished.dll",
    "SolidWorks.Interop.swcommands.dll"
)
foreach ($dll in $interopDlls) {
    $src = Join-Path $swRedist $dll
    $dst = Join-Path $InstallDir $dll
    if (Test-Path $src) {
        # 仅在目标不存在时复制（互操作 DLL 通常已在 GAC）
        if (-not (Test-Path $dst)) {
            Copy-Item $src $dst -Force
            Write-Ok "复制 $dll"
        }
    }
}

# 复制安装清单（用于版本检查）
$manifest = @{
    version     = $dllVersion
    clsid       = $AddInClsid
    progid      = $ProgId
    install_dir = $InstallDir
    backend_url = $BackendUrl
    install_time = (Get-Date).ToString("o")
} | ConvertTo-Json
$manifest | Set-Content (Join-Path $InstallDir "manifest.json") -Encoding UTF8
Write-Ok "manifest.json 已写入"

# ===== Step 4: COM 注册（per-user HKCU，无需管理员）=====
Write-Step "4/7 COM 注册 (per-user HKCU)..."
# 优先使用 per-user HKCU 注册（无需管理员权限）
# 备选：regasm /codebase（需管理员，HKLM 全局注册）
$installedDll = Join-Path $InstallDir "SynthDraftAddIn.dll"
$assembly = "SynthDraftAddIn, Version=1.0.0.0, Culture=neutral, PublicKeyToken=null"
$class = "SynthDraftAddIn.SynthDraftAddIn"
$runtimeVersion = "v4.0.30319"
$clsidRoot = "HKCU:\Software\Classes\CLSID\$AddInClsid"
$progidRoot = "HKCU:\Software\Classes\$ProgId"

# 清理旧注册
if (Test-Path $clsidRoot) { Remove-Item $clsidRoot -Force -Recurse -ErrorAction SilentlyContinue }
if (Test-Path $progidRoot) { Remove-Item $progidRoot -Force -Recurse -ErrorAction SilentlyContinue }

# 写 CLSID
New-Item -Path $clsidRoot -Force | Out-Null
Set-ItemProperty -Path $clsidRoot -Name "(Default)" -Value $class
New-Item -Path "$clsidRoot\InprocServer32" -Force | Out-Null
Set-ItemProperty -Path "$clsidRoot\InprocServer32" -Name "(Default)" -Value $installedDll
Set-ItemProperty -Path "$clsidRoot\InprocServer32" -Name "Class" -Value $class
Set-ItemProperty -Path "$clsidRoot\InprocServer32" -Name "Assembly" -Value $assembly
Set-ItemProperty -Path "$clsidRoot\InprocServer32" -Name "RuntimeVersion" -Value $runtimeVersion
Set-ItemProperty -Path "$clsidRoot\InprocServer32" -Name "CodeBase" -Value $installedDll
# Implemented Categories: {62C8FE65-4EBB-45e7-B440-6E39B2CDBF29} = .NET Managed Component
New-Item -Path "$clsidRoot\Implemented Categories\{62C8FE65-4EBB-45e7-B440-6E39B2CDBF29}" -Force | Out-Null

# 写 ProgID
New-Item -Path $progidRoot -Force | Out-Null
Set-ItemProperty -Path $progidRoot -Name "(Default)" -Value $class
New-Item -Path "$progidRoot\CLSID" -Force | Out-Null
Set-ItemProperty -Path "$progidRoot\CLSID" -Name "(Default)" -Value $AddInClsid

# 验证
$inproc = Get-ItemProperty "$clsidRoot\InprocServer32" -ErrorAction SilentlyContinue
if ($inproc -and $inproc.'(Default)' -eq $installedDll) {
    Write-Ok "Per-user COM 注册成功"
    Write-Ok "InprocServer32: $($inproc.'(Default)')"
} else {
    Write-Err "Per-user COM 注册失败"
    exit 1
}

# ===== Step 5: 写入 SolidWorks Add-in 注册表项 =====
Write-Step "5/7 写入 SolidWorks Add-in 注册表项..."
if (-not (Test-Path "HKCU:\Software\SolidWorks\AddIns")) {
    New-Item -Path "HKCU:\Software\SolidWorks\AddIns" -Force | Out-Null
}
if (Test-Path $RegKeySolidWorksAddIns) {
    Remove-Item $RegKeySolidWorksAddIns -Force
}
New-Item -Path $RegKeySolidWorksAddIns -Force | Out-Null
# AddIns\{GUID} 仅保留注册元数据：Default=1（启用）、Title、Description。
Set-ItemProperty -Path $RegKeySolidWorksAddIns -Name "(Default)" -Value 1 -Type DWord
Set-ItemProperty -Path $RegKeySolidWorksAddIns -Name "Title" -Value "SynthDraft 审图插件" -Type String
Set-ItemProperty -Path $RegKeySolidWorksAddIns -Name "Description" -Value "SynthDraft SolidWorks Add-in for AI engineering drawing review" -Type String
# 启动加载由独立的 AddInsStartup\{GUID} 键控制（Default=1 表示 SolidWorks 启动时自动加载）。
$RegKeySolidWorksAddInsStartup = "HKCU:\Software\SolidWorks\AddInsStartup\$AddInGuid"
if (-not (Test-Path "HKCU:\Software\SolidWorks\AddInsStartup")) {
    New-Item -Path "HKCU:\Software\SolidWorks\AddInsStartup" -Force | Out-Null
}
if (Test-Path $RegKeySolidWorksAddInsStartup) {
    Remove-Item $RegKeySolidWorksAddInsStartup -Force
}
New-Item -Path $RegKeySolidWorksAddInsStartup -Force | Out-Null
Set-ItemProperty -Path $RegKeySolidWorksAddInsStartup -Name "(Default)" -Value 1 -Type DWord
Write-Ok "注册表项已写入: $RegKeySolidWorksAddIns (Default=1)"
Write-Ok "启动加载项已写入: $RegKeySolidWorksAddInsStartup (Default=1)"

# ===== Step 6: 写入后端 URL 配置 =====
Write-Step "6/7 写入后端 URL 配置..."
if (-not (Test-Path $RegKeySynthDraft)) {
    New-Item -Path $RegKeySynthDraft -Force | Out-Null
}
Set-ItemProperty -Path $RegKeySynthDraft -Name "backend_url" -Value $BackendUrl -Type String
Set-ItemProperty -Path $RegKeySynthDraft -Name "version" -Value $dllVersion -Type String
Write-Ok "后端 URL: $BackendUrl"

# ===== Step 7: 完成提示 =====
Write-Step "7/7 安装完成。"
Write-Host ""
Write-Host "==========================================" -ForegroundColor Green
Write-Host " SynthDraft Add-in 安装成功！" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
Write-Host " 版本:        $dllVersion"
Write-Host " CLSID:       $AddInClsid"
Write-Host " ProgID:      $ProgId"
Write-Host " 安装目录:    $InstallDir"
Write-Host " 后端 URL:    $BackendUrl"
Write-Host " 注册表:      $RegKeySolidWorksAddIns"
Write-Host ""
Write-Host " 请重启 SolidWorks，在菜单栏看到「SynthDraft 审图」。" -ForegroundColor Yellow
Write-Host " 如菜单未出现，请在 SolidWorks 选项 → 插件中勾选 SynthDraft。" -ForegroundColor Yellow
Write-Host ""
