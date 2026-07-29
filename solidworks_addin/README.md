# SynthDraft SolidWorks Add-in

SynthDraft SolidWorks Add-in 提供 SolidWorks 与 SynthDraft 审图/生成平台的深度集成：
- 一键上传当前文档到审图服务
- 查看审查结果并在图纸中高亮缺陷位置
- 基于审图缺陷一键优化图纸

## 环境前置条件

- **.NET Framework 4.8+**（Release ≥ 528040）
  - 检查命令：`(Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full' -Name Release).Release`
- **SolidWorks 2022+**（推荐 SolidWorks 2025）
  - 需安装 SolidWorks API interop DLL（位于 `<SolidWorks>\api\redist\`）
- **管理员权限**（仅 HKLM 全局注册需要；本 Add-in 默认使用 per-user HKCU 注册，无需管理员）
- **SynthDraft 后端服务**运行中（默认 http://localhost:8000）

## 一键安装

以普通用户权限运行（per-user HKCU 注册，无需管理员）：

```powershell
.\install.ps1
```

指定后端地址：

```powershell
.\install.ps1 -BackendUrl http://192.168.1.100:8000
```

覆盖安装（强制覆盖已存在文件）：

```powershell
.\install.ps1 -Force
```

安装脚本自动完成：
1. 验证 SolidWorks 已安装
2. 验证 SynthDraftAddIn.dll 已编译
3. 复制 DLL + interop 依赖到 `%ProgramData%\SynthDraft\AddIn\`
4. 注册 COM 类型（per-user HKCU，无需 regasm 管理员权限）
5. 写入 SolidWorks Add-in 注册表项（HKCU\Software\SolidWorks\AddIns）
6. 写入后端 URL 配置（HKCU\Software\SynthDraft\backend_url）

安装完成后**重启 SolidWorks**，在菜单栏看到「SynthDraft 审图」。如菜单未出现，请在 SolidWorks 选项 → 插件中勾选 SynthDraft。

## 手动安装

### 1. 编译

使用 build.ps1：

```powershell
.\build.ps1
```

或直接调用 csc.exe：

```powershell
csc.exe /target:library /out:bin\Release\SynthDraftAddIn.dll ^
  /r:"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\System.dll" ^
  /r:"D:\Program Files\SolidWorks Corp\SOLIDWORKS\api\redist\SolidWorks.Interop.sldworks.dll" ^
  /r:"D:\Program Files\SolidWorks Corp\SOLIDWORKS\api\redist\SolidWorks.Interop.swconst.dll" ^
  /r:"D:\Program Files\SolidWorks Corp\SOLIDWORKS\api\redist\SolidWorks.Interop.swpublished.dll" ^
  /r:"D:\Program Files\SolidWorks Corp\SOLIDWORKS\api\redist\SolidWorks.Interop.swcommands.dll" ^
  SynthDraftAddIn.cs BackendClient.cs Properties\AssemblyInfo.cs
```

或使用 MSBuild：

```powershell
MSBuild SynthDraftAddIn.csproj /p:Configuration=Release
```

### 2. COM 注册

使用 regasm（需管理员，HKLM 全局注册）：

```powershell
C:\Windows\Microsoft.NET\Framework64\v4.0.30319\regasm.exe /codebase /tlb:SynthDraftAddIn.tlb bin\Release\SynthDraftAddIn.dll
```

或使用 per-user HKCU 注册（无需管理员，install.ps1 默认方式）。

### 3. 注册表项写入

写入 SolidWorks Add-in 注册表项：

```powershell
reg add "HKCU\Software\SolidWorks\AddIns\{B5E8F2A1-3C4D-4E9F-8A2B-1D3E5F7A9C2D}" /ve /t REG_DWORD /d 1 /f
reg add "HKCU\Software\SolidWorks\AddIns\{B5E8F2A1-3C4D-4E9F-8A2B-1D3E5F7A9C2D}" /v Title /t REG_SZ /d "SynthDraft 审图插件" /f
reg add "HKCU\Software\SolidWorks\AddIns\{B5E8F2A1-3C4D-4E9F-8A2B-1D3E5F7A9C2D}" /v Startup /t REG_DWORD /d 1 /f
```

写入后端 URL 配置：

```powershell
reg add "HKCU\Software\SynthDraft" /v backend_url /t REG_SZ /d "http://localhost:8000" /f
```

## 卸载

```powershell
.\uninstall.ps1
```

保留配置（保留 HKCU\Software\SynthDraft 后端 URL 等配置）：

```powershell
.\uninstall.ps1 -KeepConfig
```

卸载脚本自动完成：
1. 注销 COM 类型（regasm /unregister 或删除 HKCU CLSID）
2. 删除 SolidWorks Add-in 注册表项
3. 删除 SynthDraft 配置注册表项（可选）
4. 删除安装目录与文件

## 配置后端地址

后端 URL 存储在注册表 `HKCU\Software\SynthDraft\backend_url`，由 BackendClient.GetBackendUrl() 读取。

查看当前后端地址：

```powershell
reg query "HKCU\Software\SynthDraft" /v backend_url
```

或使用 PowerShell：

```powershell
(Get-ItemProperty 'HKCU:\Software\SynthDraft' -Name backend_url).backend_url
```

修改后端地址：

```powershell
reg add "HKCU\Software\SynthDraft" /v backend_url /t REG_SZ /d "http://192.168.1.100:8000" /f
```

BackendClient 读取逻辑（位于 `BackendClient.cs`）：
- 优先读取 `HKCU\Software\SynthDraft\backend_url`
- 若注册表项不存在或为空，回退到默认值 `http://localhost:8000`

## 版本更新流程

检查本地与远端版本：

```powershell
.\check_update.ps1
```

指定远端版本清单 URL：

```powershell
.\check_update.ps1 -RemoteUrl https://synthdraft.example.com/releases/version.json
```

查看本地已安装版本：

```powershell
.\check-version.ps1
```

更新流程：
1. 运行 `.\check_update.ps1` 检查是否有新版本
2. 若有新版本，下载新版本文件
3. 运行 `.\uninstall.ps1` 卸载旧版本
4. 替换文件后运行 `.\install.ps1` 安装新版本
5. 重启 SolidWorks

## 故障排查

### MSB3644 错误（找不到目标框架）

**现象**：编译时出现 `error MSB3644: The reference assemblies for framework ".NETFramework,Version=v4.8" were not found.`

**根因**：未安装 .NET Framework 4.8 Developer Pack / Targeting Pack。

**修复**：
1. 下载并安装 [.NET Framework 4.8 Developer Pack](https://dotnet.microsoft.com/download/dotnet-framework/thank-you/net48-developer-pack-offline-installer)
2. 或使用 build.ps1 中的 csc.exe 直接编译（不依赖 MSBuild 目标框架引用程序集）

### regasm 找不到

**现象**：`'regasm' is not recognized as an internal or external command.`

**根因**：regasm.exe 未在 PATH 中。

**修复**：使用完整路径调用 regasm：
```powershell
C:\Windows\Microsoft.NET\Framework64\v4.0.30319\regasm.exe /codebase bin\Release\SynthDraftAddIn.dll
```

或使用 install.ps1 的 per-user HKCU 注册方式（无需 regasm）。

### SolidWorks 加载失败

**现象**：安装后 SolidWorks 菜单栏无「SynthDraft 审图」。

**排查步骤**：
1. 确认注册表项存在：`reg query "HKCU\Software\SolidWorks\AddIns\{B5E8F2A1-3C4D-4E9F-8A2B-1D3E5F7A9C2D}"`
2. 确认 DLL 文件存在：`Test-Path "$env:ProgramData\SynthDraft\AddIn\SynthDraftAddIn.dll"`
3. 确认 COM 注册：`reg query "HKCU\Software\Classes\CLSID\{B5E8F2A1-3C4D-4E9F-8A2B-1D3E5F7A9C2D}\InprocServer32"`
4. 在 SolidWorks 选项 → 插件中手动勾选 SynthDraft
5. 查看日志：`%LOCALAPPDATA%\SynthDraft\logs\addin.log`

### backend_url 读取失败

**现象**：Add-in 提示无法连接后端。

**排查步骤**：
1. 确认后端服务运行中：`curl http://localhost:8000/health`
2. 确认注册表配置：`reg query "HKCU\Software\SynthDraft" /v backend_url`
3. 若注册表项不存在，BackendClient 回退到默认值 `http://localhost:8000`
4. 重新写入配置：`.\install.ps1 -BackendUrl http://<后端地址>:8000`

### 编译失败（其他错误）

1. 确认 SolidWorks 已安装且 interop DLL 可达：
   `Test-Path "D:\Program Files\SolidWorks Corp\SOLIDWORKS\api\redist\SolidWorks.Interop.sldworks.dll"`
2. 确认 .NET Framework 4.8 已安装：
   `(Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full' -Name Release).Release` 应 ≥ 528040
3. 查看编译错误详情，常见为 interop DLL 路径不匹配（修改 build.ps1 中的 `$swRedist` 路径）

## 自检

运行自检脚本验证安装完整性：

```powershell
.\verify_task8.ps1
```

自检脚本覆盖 9 大类检查点：
1. 编译验证（csproj / cs / interop 引用 / DLL 产物）
2. COM 注册验证（Guid / ProgId / ComVisible / regasm / 注册表项）
3. 安装脚本 install.ps1 完整性
4. 卸载脚本 uninstall.ps1 完整性
5. 版本清单 version.json 与更新检查 check_update.ps1
6. 自检脚本 verify_task8.ps1 覆盖范围
7. README.md 文档完整性
8. 主项目 tasks.md 状态更新
9. 八荣八耻原则符合性

## 文件清单

| 文件 | 说明 |
|------|------|
| `SynthDraftAddIn.cs` | Add-in 主类，实现 ISwAddin 接口与 3 个命令按钮回调 |
| `BackendClient.cs` | HTTP/WebSocket 客户端，与后端通信 |
| `SynthDraftAddIn.csproj` | MSBuild 项目文件（.NET Framework 4.8） |
| `Properties\AssemblyInfo.cs` | 程序集信息（ComVisible、版本号） |
| `build.ps1` | 编译脚本（csc.exe / MSBuild） |
| `install.ps1` | 一键安装脚本 |
| `uninstall.ps1` | 卸载脚本 |
| `check-version.ps1` | 本地版本检查脚本 |
| `check_update.ps1` | 远端版本更新检查脚本 |
| `version.json` | 版本清单（语义化版本 + 兼容性信息） |
| `verify_task8.ps1` | Task 8 自检脚本（48 项检查点） |
| `README.md` | 本文档 |

## COM 标识

- **CLSID**: `{B5E8F2A1-3C4D-4E9F-8A2B-1D3E5F7A9C2D}`
- **ProgID**: `SynthDraft.AddIn`
- **.NET Framework**: 4.8
- **兼容 SolidWorks**: 2022 / 2023 / 2024 / 2025
