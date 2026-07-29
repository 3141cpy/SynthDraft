# SynthDraft SolidWorks Add-in 实施规格

> change-id: `implement-solidworks-addin`
> 关联项目：`d:\SynthDraft`（主项目 spec：`ai-engineering-design-assistant` 中 Task 8 原为 P1 可选跳过项，本 spec 将其落地实现）
> 实施模式：直接编码 + 编译验证（已部分实现 8.1/8.2/8.3，本 spec 聚焦完成剩余 8.4 + 全量编译 + 注册 + 自检）

## Why

主项目 `ai-engineering-design-assistant` 在 P1 阶段将 Task 8（SolidWorks Add-in, C#/.NET）标记为"可选，按 spec 跳过"。现用户要求正式落地该 Add-in，使 SolidWorks 用户可在 SolidWorks 内直接调用 SynthDraft 的审图/优化能力，无需切换到 Web 控制台，形成"SolidWorks 客户端 → SynthDraft 后端 → SolidWorks 客户端"闭环。

当前状态（截至本 spec 创建时）：
- SubTask 8.1（创建 Add-in 项目）：✅ 已实现 `solidworks_addin\SynthDraftAddIn.csproj` + `SynthDraftAddIn.cs` + `BackendClient.cs` + `Properties\AssemblyInfo.cs`
- SubTask 8.2（命令栏按钮：上传审图/查看审查结果/一键优化）：✅ 已实现三个回调方法
- SubTask 8.3（HTTP/WebSocket 与 Web 后端通信）：✅ 已实现 `BackendClient.cs`（HttpClient + ClientWebSocket）
- SubTask 8.4（安装包与版本更新机制）：⏸️ 未实现（install.ps1 / uninstall.ps1 / version.json / check_update.ps1）
- 编译验证：⏸️ 未通过（MSBuild 报 MSB3644 缺 .NET 4.8 引用程序集；csc.exe 显式引用路径待落地）
- COM 注册验证：⏸️ 未通过（regasm + 注册表 HKLM\SOFTWARE\SolidWorks\AddIns）
- 自检脚本：⏸️ 未编写 `verify_task8.ps1`
- 安装说明：⏸️ 未编写 `README.md`

## What Changes

### 新增（本 spec 范围内的新增项）
- **新增 安装脚本** `solidworks_addin\install.ps1`：编译 DLL → regasm 注册 COM → 写入 SolidWorks AddIns 注册表项 → 写入 HKCU\Software\SynthDraft\backend_url 配置 → 校验 SolidWorks interop DLL 可达
- **新增 卸载脚本** `solidworks_addin\uninstall.ps1`：regasm /u 反注册 → 删除 SolidWorks AddIns 注册表项 → 清理 HKCU\Software\SynthDraft 配置（可选保留）
- **新增 版本清单** `solidworks_addin\version.json`：记录 add-in 版本号、兼容 SolidWorks 版本范围、后端 API 版本、最小 .NET Framework 版本、下载地址（用于版本更新）
- **新增 版本检查脚本** `solidworks_addin\check_update.ps1`：读取本地 version.json → 拉取远端版本清单 → 比对版本号 → 提示用户是否更新（不自动安装，遵循用户确认原则）
- **新增 自检脚本** `solidworks_addin\verify_task8.ps1`：检查源文件存在性 → 检查 csproj 配置正确性 → 尝试编译 → 检查 regasm 注册结果 → 检查注册表项写入 → 检查 backend_url 配置 → 输出 8.x 全 SubTask 验证报告
- **新增 安装说明** `solidworks_addin\README.md`：环境前置条件 / 一键安装步骤 / 手动安装步骤 / 卸载步骤 / 配置后端地址 / 故障排查 / 版本更新流程

### 修复（已实现代码中需修复的问题）
- **修复 编译错误**：解决 MSBuild MSB3644（缺 .NET 4.8 targeting pack）问题，确保 `SynthDraftAddIn.csproj` 可通过 MSBuild 或 csc.exe 成功编译为 DLL
- **修复 引用路径**：SolidWorks interop DLL 路径硬编码为 `D:\Program Files\SolidWorks Corp\SOLIDWORKS\api\redist\`，需在 install.ps1 / csproj 中支持环境变量 `SOLIDWORKS_API_REDIST` 覆盖
- **修复 COM 注册**：确保 `[Guid]` / `[ProgId]` / `[ComVisible(true)]` 三项属性正确，regasm 注册后可在 SolidWorks 加载

### 验证（本 spec 必须完成的验证项）
- **编译验证**：`SynthDraftAddIn.dll` 成功生成到 `bin\Release\`
- **注册验证**：regasm 注册后 `HKLM\SOFTWARE\SolidWorks\AddIns\{B5E8F2A1-3C4D-4E9F-8A2B-1D3E5F7A9C2D}` 注册表项存在
- **配置验证**：`HKCU\Software\SynthDraft\backend_url` 可被 BackendClient.GetBackendUrl() 正确读取
- **自检验证**：`verify_task8.ps1` 全部检查点通过（含降级路径：SolidWorks 未运行时跳过加载验证，仅验证注册与配置）

## Impact

- **Affected specs**：
  - `ai-engineering-design-assistant`：Task 8 由"⏸️ 跳过"变更为"✅ 实现"，需在主 tasks.md 中勾选 Task 8 全部 SubTask
  - 无其他 spec 受影响（Task 8 为独立模块，不与 Task 7/9/10/11 产生代码耦合）
- **Affected code**：
  - `d:\SynthDraft\solidworks_addin\`（新增 install.ps1 / uninstall.ps1 / version.json / check_update.ps1 / verify_task8.ps1 / README.md）
  - `d:\SynthDraft\solidworks_addin\SynthDraftAddIn.csproj`（可能修复引用路径）
  - `d:\SynthDraft\solidworks_addin\bin\Release\SynthDraftAddIn.dll`（编译产物）
  - `d:\SynthDraft\solidworks_addin\bin\Release\SynthDraftAddIn.tlb`（regasm 产出的类型库）
  - Windows 注册表：`HKLM\SOFTWARE\SolidWorks\AddIns\{B5E8F2A1-3C4D-4E9F-8A2B-1D3E5F7A9C2D}`（COM 注册）
  - Windows 注册表：`HKCU\Software\SynthDraft\backend_url`（后端地址配置）
- **Affected docs**：
  - 主项目 `docs\architecture.md` / `docs\deployment.md` 中"可选 SolidWorks Add-in"描述需更新为"已实现"，但本 spec 不负责修改主项目文档（属于后续 Task 18 范围）

## ADDED Requirements

### Requirement: SolidWorks Add-in 安装包

系统 SHALL 提供一键安装 PowerShell 脚本 `install.ps1`，在 Windows 环境下完成以下步骤：
1. 校验前置条件（.NET Framework 4.8+ / SolidWorks 2022+ / regasm.exe 可达）
2. 支持 `SOLIDWORKS_API_REDIST` 环境变量覆盖 interop DLL 路径
3. 调用 MSBuild 或 csc.exe 编译 `SynthDraftAddIn.csproj` 生成 DLL
4. 调用 regasm 注册 COM 类型库（`/codebase /tlb`）
5. 写入 `HKLM\SOFTWARE\SolidWorks\AddIns\{B5E8F2A1-3C4D-4E9F-8A2B-1D3E5F7A9C2D}` 注册表项（Default=1 启用，Title/Description 字符串）
6. 写入 `HKCU\Software\SynthDraft\backend_url`（默认 `http://localhost:8000`，支持参数覆盖）
7. 输出安装结果摘要（成功/失败 + 各步骤状态）

#### Scenario: 正常安装

- **WHEN** 用户在管理员 PowerShell 中执行 `.\install.ps1`，环境满足前置条件
- **THEN** 脚本输出"安装成功"，DLL 已生成、COM 已注册、注册表项已写入、backend_url 已配置
- **AND** 下次启动 SolidWorks 时，"SynthDraft 审图"命令组出现在菜单栏与工具栏

#### Scenario: 缺少 .NET Framework 4.8

- **WHEN** 用户执行 `.\install.ps1`，但系统仅有 .NET Framework 4.7
- **THEN** 脚本输出"前置条件不满足：需要 .NET Framework 4.8+"，退出码 1，不执行后续步骤

#### Scenario: SolidWorks 未安装

- **WHEN** 用户执行 `.\install.ps1`，但 `SOLIDWORKS_API_REDIST` 环境变量未设置且默认路径 `D:\Program Files\SolidWorks Corp\SOLIDWORKS\api\redist\` 不存在
- **THEN** 脚本输出"未找到 SolidWorks interop DLL，请通过 -RedistPath 参数或 SOLIDWORKS_API_REDIST 环境变量指定"，退出码 1

### Requirement: SolidWorks Add-in 卸载脚本

系统 SHALL 提供卸载 PowerShell 脚本 `uninstall.ps1`，完成以下步骤：
1. 调用 regasm `/u` 反注册 COM 类型库
2. 删除 `HKLM\SOFTWARE\SolidWorks\AddIns\{B5E8F2A1-3C4D-4E9F-8A2B-1D3E5F7A9C2D}` 注册表项
3. 可选删除 `HKCU\Software\SynthDraft` 配置（参数 `-RemoveConfig` 控制）
4. 不删除编译产物 DLL/TLB（参数 `-RemoveFiles` 控制是否删除）

#### Scenario: 正常卸载

- **WHEN** 用户在管理员 PowerShell 中执行 `.\uninstall.ps1`
- **THEN** 脚本输出"卸载成功"，COM 反注册完成、AddIns 注册表项删除、配置保留（默认）、DLL 文件保留（默认）
- **AND** 下次启动 SolidWorks 时，"SynthDraft 审图"命令组不再出现

### Requirement: 版本清单文件

系统 SHALL 提供 `version.json` 文件，包含以下字段：
- `version`：语义化版本号（如 `1.0.0`）
- `solidworks_compatibility`：兼容 SolidWorks 版本范围（如 `2022-2025`）
- `backend_api_version`：兼容后端 API 版本（如 `v1`）
- `dotnet_framework`：最小 .NET Framework 版本（如 `4.8`）
- `release_date`：发布日期（ISO 8601）
- `download_url`：远端下载地址（空字符串表示无远端更新源）
- `checksum`：DLL SHA256 校验和（空字符串表示未计算）

#### Scenario: 版本清单读取

- **WHEN** `check_update.ps1` 读取本地 `version.json`
- **THEN** 返回包含上述全部字段的对象，缺失字段视为空字符串

### Requirement: 版本更新检查脚本

系统 SHALL 提供 `check_update.ps1` 脚本，完成以下步骤：
1. 读取本地 `version.json`
2. 从 `download_url` 拉取远端版本清单（HTTP GET，超时 10 秒）
3. 比对版本号（语义化版本比较）
4. 输出检查结果（最新/有更新 + 新版本号 + 下载地址）
5. 不自动下载安装，仅提示用户手动更新（遵循用户确认原则）

#### Scenario: 有新版本可用

- **WHEN** 本地版本 `1.0.0`，远端版本 `1.1.0`
- **THEN** 脚本输出"发现新版本 1.1.0，下载地址：xxx，请手动下载安装"

#### Scenario: 远端不可达

- **WHEN** `download_url` 为空字符串或 HTTP 请求超时
- **THEN** 脚本输出"无法检查更新（远端不可达），当前版本 1.0.0"，退出码 0（非错误）

### Requirement: 自检脚本

系统 SHALL 提供 `verify_task8.ps1` 脚本，对照本 spec 全部要求逐项验证，输出结构化报告：
1. 检查源文件存在性（csproj/cs/BackendClient.cs/AssemblyInfo.cs）
2. 检查 csproj 配置正确性（TargetFramework=v4.8 / ComVisible / Guid / ProgId）
3. 检查 SolidWorks interop DLL 引用路径可达
4. 执行编译（MSBuild 优先，csc.exe 回退）
5. 检查编译产物 DLL 存在
6. 执行 regasm 注册（若未注册）
7. 检查 `HKLM\SOFTWARE\SolidWorks\AddIns\{B5E8F2A1-3C4D-4E9F-8A2B-1D3E5F7A9C2D}` 注册表项存在
8. 检查 `HKCU\Software\SynthDraft\backend_url` 配置可读
9. 检查安装脚本 install.ps1 / uninstall.ps1 / version.json / check_update.ps1 / README.md 全部存在
10. 输出汇总：x/y PASS + 失败项清单

#### Scenario: 全部检查通过

- **WHEN** 环境完备，所有文件存在，编译注册成功
- **THEN** 脚本输出"verify_task8: 10/10 PASS"，退出码 0

#### Scenario: 部分检查失败

- **WHEN** 编译失败或注册表项缺失
- **THEN** 脚本输出"verify_task8: 7/10 PASS，失败项：[编译, 注册表, backend_url]"，退出码 1

### Requirement: 安装说明文档

系统 SHALL 提供 `README.md` 安装说明文档，包含以下章节：
1. 环境前置条件（.NET Framework 4.8+ / SolidWorks 2022+ / 管理员权限）
2. 一键安装（`.\install.ps1`）
3. 手动安装（编译 + regasm + 注册表编辑）
4. 卸载（`.\uninstall.ps1`）
5. 配置后端地址（修改 `HKCU\Software\SynthDraft\backend_url`）
6. 故障排查（常见问题 + 解决方案）
7. 版本更新流程（`.\check_update.ps1`）

#### Scenario: 用户按文档操作

- **WHEN** 新用户阅读 README.md 后执行一键安装
- **THEN** 用户能成功安装 Add-in 并在 SolidWorks 中看到"SynthDraft 审图"命令组

## MODIFIED Requirements

### Requirement: 主项目 Task 8 状态

主项目 `ai-engineering-design-assistant/tasks.md` 中 Task 8 的状态由"⏸️ 跳过（P1 可选）"变更为"✅ 实现（本 spec 完成后）"。本 spec 完成验证后，需在主 tasks.md 中勾选 SubTask 8.1/8.2/8.3/8.4。

## REMOVED Requirements

无删除项。

## 技术约束（遵循八荣八耻原则）

1. **以瞎猜接口为耻**：所有 SolidWorks API 调用必须基于已验证的签名（已通过反射 `SolidWorks.Interop.sldworks.dll` 确认）
2. **以脱离实际为耻**：编译必须实测通过，不接受"理论可编译"
3. **以主观假设为耻**：注册表项路径必须实测写入，不接受"应该写入了"
4. **以避重就轻为耻**：编译失败必须定位根因（MSB3644 / 引用缺失 / 代码错误），不得绕过
5. **以敷衍了事为耻**：自检脚本必须覆盖全部 SubTask，不得只检查 happy path
6. **以掩盖问题为耻**：环境限制（如 SolidWorks 未安装）必须如实标注，不得谎报通过
