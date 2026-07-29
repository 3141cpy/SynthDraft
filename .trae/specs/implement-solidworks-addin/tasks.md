# Tasks

本任务清单对照 spec.md 拆解 SynthDraft SolidWorks Add-in（Task 8）的实施工作。SubTask 8.1/8.2/8.3 已实现（前序会话产出），本清单聚焦于完成 8.4 + 全量编译验证 + 注册验证 + 自检脚本 + 安装说明。

实施顺序遵循"先修复编译 → 再补 8.4 安装包 → 再自检验证 → 最后更新主 tasks.md"的串行依赖链，避免并行化引入的注册表/文件系统竞态。

- [x] Task 8.0: 已实现代码确认与基线快照（前序会话产出，本 task 仅做基线确认，不修改代码）
  - [x] SubTask 8.0.1: 确认 `solidworks_addin\SynthDraftAddIn.csproj` 存在且引用 SolidWorks interop DLL（4 个：sldworks/swconst/swpublished/swcommands）
  - [x] SubTask 8.0.2: 确认 `solidworks_addin\SynthDraftAddIn.cs` 实现 ISwAddin 接口 + 3 个命令按钮回调（UploadReview/ViewReviewResults/OptimizeFromReview）
  - [x] SubTask 8.0.3: 确认 `solidworks_addin\BackendClient.cs` 实现 HttpClient + ClientWebSocket 与后端通信
  - [x] SubTask 8.0.4: 确认 `solidworks_addin\Properties\AssemblyInfo.cs` 含 ComVisible/Guid/Version 元数据

- [ ] Task 8.1: 编译验证与修复（修复 MSB3644 + 实测 DLL 生成）
  - [ ] SubTask 8.1.1: 定位 .NET Framework 4.8 引用程序集路径（优先 `C:\Program Files (x86)\Reference Assemblies\Microsoft\Framework\.NETFramework\v4.8`，回退 `C:\Windows\Microsoft.NET\Framework64\v4.0.30319`）
  - [ ] SubTask 8.1.2: 定位 MSBuild.exe 路径（优先 VS 2022 BuildTools，回退 Windows SDK），记录实际可用路径
  - [ ] SubTask 8.1.3: 尝试 MSBuild 编译 `SynthDraftAddIn.csproj`（Release 配置），记录输出日志
  - [ ] SubTask 8.1.4: 若 MSBuild 失败，回退到 csc.exe 显式编译（指定 `/target:library` + `/reference:` 全部依赖 + `/out:bin\Release\SynthDraftAddIn.dll`）
  - [ ] SubTask 8.1.5: 若 interop DLL 路径硬编码导致失败，在 csproj 中支持 `SOLIDWORKS_API_REDIST` 环境变量（条件 HintPath）
  - [ ] SubTask 8.1.6: 验证编译产物 `bin\Release\SynthDraftAddIn.dll` 存在且非空（>10KB）
  - [ ] SubTask 8.1.7: 记录编译命令与依赖路径，写入 README.md"手动安装"章节

- [ ] Task 8.2: COM 注册验证（regasm + 注册表实测写入）
  - [ ] SubTask 8.2.1: 定位 regasm.exe 路径（.NET Framework 4.8 对应 `C:\Windows\Microsoft.NET\Framework64\v4.0.30319\regasm.exe` 或 Framework32 版本）
  - [ ] SubTask 8.2.2: 执行 `regasm /codebase /tlb:SynthDraftAddIn.tlb SynthDraftAddIn.dll` 注册 COM 类型库
  - [ ] SubTask 8.2.3: 验证 `HKLM\SOFTWARE\SolidWorks\AddIns\{B5E8F2A1-3C4D-4E9F-8A2B-1D3E5F7A9C2D}` 注册表项存在（Default=1）
  - [ ] SubTask 8.2.4: 验证 `HKCU\Software\SynthDraft\backend_url` 可被 BackendClient.GetBackendUrl() 读取（写入测试值后读取校验）
  - [ ] SubTask 8.2.5: 记录 regasm 命令与注册表路径，写入 README.md"手动安装"章节

- [ ] Task 8.3: 安装脚本实现（SubTask 8.4 第 1 部分）
  - [ ] SubTask 8.3.1: 实现 `solidworks_addin\install.ps1`，参数 `-BackendUrl`（默认 http://localhost:8000）`-RedistPath`（默认环境变量 SOLIDWORKS_API_REDIST 或 D:\Program Files\SolidWorks Corp\SOLIDWORKS\api\redist\）
  - [ ] SubTask 8.3.2: install.ps1 前置条件校验：.NET Framework 4.8+（检查 `HKLM\SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full\Release` ≥ 528040）
  - [ ] SubTask 8.3.3: install.ps1 SolidWorks interop DLL 可达性校验（4 个 DLL 全部存在）
  - [ ] SubTask 8.3.4: install.ps1 编译步骤（复用 Task 8.1 的 MSBuild/csc.exe 命令）
  - [ ] SubTask 8.3.5: install.ps1 regasm 注册步骤（复用 Task 8.2 命令）
  - [ ] SubTask 8.3.6: install.ps1 注册表写入步骤（AddIns 项 Default=1 + Title + Description）
  - [ ] SubTask 8.3.7: install.ps1 backend_url 配置写入步骤（HKCU\Software\SynthDraft\backend_url）
  - [ ] SubTask 8.3.8: install.ps1 输出安装结果摘要（每步骤 ✓/✗ + 失败项详情 + 退出码）

- [ ] Task 8.4: 卸载脚本实现（SubTask 8.4 第 2 部分）
  - [ ] SubTask 8.4.1: 实现 `solidworks_addin\uninstall.ps1`，参数 `-RemoveConfig`（默认 $false）`-RemoveFiles`（默认 $false）
  - [ ] SubTask 8.4.2: uninstall.ps1 regasm 反注册步骤（`regasm /u SynthDraftAddIn.dll`）
  - [ ] SubTask 8.4.3: uninstall.ps1 删除 AddIns 注册表项步骤
  - [ ] SubTask 8.4.4: uninstall.ps1 可选删除 HKCU\Software\SynthDraft 配置（-RemoveConfig 控制）
  - [ ] SubTask 8.4.5: uninstall.ps1 可选删除 bin\Release 编译产物（-RemoveFiles 控制）
  - [ ] SubTask 8.4.6: uninstall.ps1 输出卸载结果摘要

- [ ] Task 8.5: 版本清单与更新检查（SubTask 8.4 第 3 部分）
  - [ ] SubTask 8.5.1: 实现 `solidworks_addin\version.json`，字段：version/solidworks_compatibility/backend_api_version/dotnet_framework/release_date/download_url/checksum
  - [ ] SubTask 8.5.2: 实现 `solidworks_addin\check_update.ps1`，读取本地 version.json
  - [ ] SubTask 8.5.3: check_update.ps1 拉取远端版本清单（HTTP GET，超时 10 秒，download_url 为空时降级）
  - [ ] SubTask 8.5.4: check_update.ps1 语义化版本比较（major.minor.patch 数值比较，不引入 SemVer 库，手写比较函数）
  - [ ] SubTask 8.5.5: check_update.ps1 输出检查结果（最新/有更新 + 新版本号 + 下载地址 + 提示手动更新）

- [ ] Task 8.6: 自检脚本实现
  - [ ] SubTask 8.6.1: 实现 `solidworks_addin\verify_task8.ps1`，对照 spec.md ADDED Requirements 中的 10 项检查点
  - [ ] SubTask 8.6.2: verify_task8.ps1 检查源文件存在性（csproj/cs/BackendClient.cs/AssemblyInfo.cs/install.ps1/uninstall.ps1/version.json/check_update.ps1/README.md）
  - [ ] SubTask 8.6.3: verify_task8.ps1 检查 csproj 配置正确性（TargetFramework=v4.8 / ComVisible=true / Guid 存在 / ProgId 存在）
  - [ ] SubTask 8.6.4: verify_task8.ps1 检查 interop DLL 引用路径可达（4 个 DLL）
  - [ ] SubTask 8.6.5: verify_task8.ps1 执行编译并检查 DLL 产物（复用 Task 8.1 命令）
  - [ ] SubTask 8.6.6: verify_task8.ps1 执行 regasm 注册并检查注册表项（复用 Task 8.2 命令）
  - [ ] SubTask 8.6.7: verify_task8.ps1 检查 backend_url 配置可读
  - [ ] SubTask 8.6.8: verify_task8.ps1 输出结构化报告（x/y PASS + 失败项清单 + 退出码 0/1）
  - [ ] SubTask 8.6.9: verify_task8.ps1 实测执行，记录通过率（环境限制项如实标注 ENV-LIMIT）

- [ ] Task 8.7: 安装说明文档
  - [ ] SubTask 8.7.1: 实现 `solidworks_addin\README.md`，章节：环境前置条件 / 一键安装 / 手动安装 / 卸载 / 配置后端地址 / 故障排查 / 版本更新流程
  - [ ] SubTask 8.7.2: README.md 环境前置条件章节（.NET Framework 4.8+ / SolidWorks 2022+ / 管理员权限 / regasm.exe 可达）
  - [ ] SubTask 8.7.3: README.md 一键安装章节（`.\install.ps1 -BackendUrl http://your-backend:8000`）
  - [ ] SubTask 8.7.4: README.md 手动安装章节（MSBuild/csc.exe 编译命令 + regasm 命令 + 注册表 reg add 命令，全部来自 Task 8.1/8.2 实测记录）
  - [ ] SubTask 8.7.5: README.md 卸载章节（`.\uninstall.ps1` + 可选参数说明）
  - [ ] SubTask 8.7.6: README.md 配置后端地址章节（reg add / reg query 命令 + BackendClient.GetBackendUrl() 读取逻辑说明）
  - [ ] SubTask 8.7.7: README.md 故障排查章节（MSB3644 / regasm 找不到 / SolidWorks 加载失败 / backend_url 读取失败 等常见问题 + 解决方案）
  - [ ] SubTask 8.7.8: README.md 版本更新流程章节（`.\check_update.ps1` + 手动更新步骤）

- [ ] Task 8.8: 全量自检与主项目状态更新
  - [ ] SubTask 8.8.1: 执行 `verify_task8.ps1`，确认全部检查点通过或如实标注环境限制
  - [ ] SubTask 8.8.2: 在主项目 `d:\SynthDraft\.trae\specs\ai-engineering-design-assistant\tasks.md` 中勾选 Task 8 的 SubTask 8.1/8.2/8.3/8.4（由"⏸️ 跳过"变更为"✅ 实现"）
  - [ ] SubTask 8.8.3: 在本 spec 的 checklist.md 中勾选全部通过的检查点

# Task Dependencies

- Task 8.0（基线确认）→ 所有后续 Task（确认已实现代码作为修复基线）
- Task 8.1（编译验证与修复）→ Task 8.2（COM 注册需 DLL 产物）→ Task 8.3（install.ps1 复用编译/注册命令）
- Task 8.3（install.ps1）↔ Task 8.4（uninstall.ps1）可并行（互不依赖）
- Task 8.5（version.json + check_update.ps1）独立于 Task 8.3/8.4，可并行
- Task 8.6（verify_task8.ps1）依赖 Task 8.1/8.2/8.3/8.4/8.5 全部完成（自检需覆盖全部产物）
- Task 8.7（README.md）依赖 Task 8.1/8.2（需复用实测编译/注册命令）
- Task 8.8（全量自检 + 主项目状态更新）依赖 Task 8.6/8.7 全部完成

# 并行化建议

- 阶段一（串行）：Task 8.0 → Task 8.1 → Task 8.2（编译与注册存在强依赖）
- 阶段二（并行）：Task 8.3 || Task 8.4 || Task 8.5（三个独立产物，可并行实现）
- 阶段三（串行）：Task 8.6 → Task 8.7 → Task 8.8（自检需覆盖全部产物，README 需复用自检命令）

# 阶段门控

1. Task 8.1 编译验证必须实测通过，不得绕过 MSB3644 错误
2. Task 8.2 COM 注册必须实测写入注册表，不得仅理论分析
3. Task 8.6 verify_task8.ps1 必须实测执行，环境限制项如实标注
4. Task 8.8 主项目 tasks.md 状态更新前必须确认 verify_task8.ps1 全部通过或环境限制已标注
