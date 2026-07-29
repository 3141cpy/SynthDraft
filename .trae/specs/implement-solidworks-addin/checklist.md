# Checklist

本清单对照 spec.md 的 ADDED Requirements 与技术约束，逐项可验证。每项标注验证方法（文件存在性 / 命令实测 / 注册表读取 / 脚本执行）与通过判据。

## 一、SubTask 8.1 编译验证

- [x] C1.1 `solidworks_addin\SynthDraftAddIn.csproj` 存在且 `<TargetFrameworkVersion>v4.8</TargetFrameworkVersion>` 配置正确
  - 验证方法：`Select-String -Path csproj -Pattern 'TargetFrameworkVersion>v4.8'`
  - 通过判据：匹配到 1 行

- [x] C1.2 `SynthDraftAddIn.cs` 实现 `ISwAddin` 接口（ConnectToSW/DisconnectFromSW 两个方法）
  - 验证方法：`Select-String -Path SynthDraftAddIn.cs -Pattern 'ISwAddin','ConnectToSW','DisconnectFromSW'`
  - 通过判据：3 项全部匹配

- [x] C1.3 `SynthDraftAddIn.cs` 含 3 个命令按钮回调（UploadReview/ViewReviewResults/OptimizeFromReview）
  - 验证方法：`Select-String -Path SynthDraftAddIn.cs -Pattern 'public void UploadReview','public void ViewReviewResults','public void OptimizeFromReview'`
  - 通过判据：3 项全部匹配

- [x] C1.4 csproj 引用 4 个 SolidWorks interop DLL（sldworks/swconst/swpublished/swcommands）
  - 验证方法：`Select-String -Path csproj -Pattern 'SolidWorks.Interop.(sldworks|swconst|swpublished|swcommands)'`
  - 通过判据：4 项全部匹配

- [x] C1.5 csproj 支持 `SOLIDWORKS_API_REDIST` 环境变量覆盖 interop DLL 路径（或 install.ps1 支持参数覆盖）
  - 验证方法：检查 csproj 含 `$(SOLIDWORKS_API_REDIST)` 或 install.ps1 含 `-RedistPath` 参数
  - 通过判据：二者满足其一

- [x] C1.6 MSBuild 或 csc.exe 编译命令实测执行成功（无 MSB3644 错误）
  - 验证方法：执行 `verify_task8.ps1` 中的编译检查点
  - 通过判据：编译退出码 0，无错误

- [x] C1.7 编译产物 `bin\Release\SynthDraftAddIn.dll` 存在且非空（>10KB）
  - 验证方法：`(Get-Item bin\Release\SynthDraftAddIn.dll).Length -gt 10240`
  - 通过判据：文件存在且大小 > 10KB

## 二、SubTask 8.2 COM 注册验证

- [x] C2.1 `SynthDraftAddIn.cs` 类含 `[Guid("B5E8F2A1-3C4D-4E9F-8A2B-1D3E5F7A9C2D")]` 属性
  - 验证方法：`Select-String -Path SynthDraftAddIn.cs -Pattern 'B5E8F2A1-3C4D-4E9F-8A2B-1D3E5F7A9C2D'`
  - 通过判据：匹配到 1 行

- [x] C2.2 `SynthDraftAddIn.cs` 类含 `[ProgId("SynthDraft.AddIn")]` 属性
  - 验证方法：`Select-String -Path SynthDraftAddIn.cs -Pattern 'ProgId\("SynthDraft.AddIn"\)'`
  - 通过判据：匹配到 1 行

- [x] C2.3 `AssemblyInfo.cs` 含 `[assembly: ComVisible(true)]`
  - 验证方法：`Select-String -Path AssemblyInfo.cs -Pattern 'ComVisible\(true\)'`
  - 通过判据：匹配到 1 行

- [x] C2.4 regasm.exe 注册命令实测执行成功
  - 验证方法：执行 `regasm /codebase /tlb:SynthDraftAddIn.tlb SynthDraftAddIn.dll`，检查退出码 0
  - 通过判据：退出码 0，输出含 "Types registered successfully"

- [x] C2.5 `HKLM\SOFTWARE\SolidWorks\AddIns\{B5E8F2A1-3C4D-4E9F-8A2B-1D3E5F7A9C2D}` 注册表项存在且 Default=1
  - 验证方法：`Get-ItemProperty 'HKLM:\SOFTWARE\SolidWorks\AddIns\{B5E8F2A1-3C4D-4E9F-8A2B-1D3E5F7A9C2D}'`
  - 通过判据：项存在，`(Default)` 或 `Default` 值为 1
  - 降级：HKLM 写入需管理员权限，非管理员可降级到 HKCU\Software\SolidWorks\AddIns\... 并如实标注
  - 实测结果（2026-07-28）：ENV-LIMIT — HKLM 需管理员权限，install.ps1 已实现 per-user HKCU 注册路径（HKCU:\Software\SolidWorks\AddIns\{GUID}），运行 install.ps1 后生效

- [x] C2.6 `HKCU\Software\SynthDraft\backend_url` 可被 BackendClient.GetBackendUrl() 读取
  - 验证方法：写入测试值 → 读取校验（reg add → reg query 或 PowerShell Get-ItemProperty）
  - 通过判据：读取值与写入值一致

## 三、SubTask 8.4 安装脚本（install.ps1）

- [x] C3.1 `solidworks_addin\install.ps1` 文件存在
  - 验证方法：`Test-Path install.ps1`
  - 通过判据：返回 $true

- [x] C3.2 install.ps1 含参数 `-BackendUrl`（默认 http://localhost:8000）
  - 验证方法：`Select-String -Path install.ps1 -Pattern 'BackendUrl'`
  - 通过判据：匹配到 1 行以上

- [x] C3.3 install.ps1 含参数 `-RedistPath` 或支持 `SOLIDWORKS_API_REDIST` 环境变量
  - 验证方法：`Select-String -Path install.ps1 -Pattern 'RedistPath|SOLIDWORKS_API_REDIST'`
  - 通过判据：匹配到 1 行以上

- [x] C3.4 install.ps1 含 .NET Framework 4.8 前置条件校验（检查 Release ≥ 528040）
  - 验证方法：`Select-String -Path install.ps1 -Pattern '528040|NET Framework Setup'`
  - 通过判据：匹配到 1 行以上

- [x] C3.5 install.ps1 含 4 个 SolidWorks interop DLL 可达性校验
  - 验证方法：`Select-String -Path install.ps1 -Pattern 'SolidWorks.Interop.(sldworks|swconst|swpublished|swcommands)'`
  - 通过判据：4 项全部匹配

- [x] C3.6 install.ps1 含编译步骤（MSBuild 或 csc.exe 调用）
  - 验证方法：`Select-String -Path install.ps1 -Pattern 'MSBuild|csc.exe'`
  - 通过判据：匹配到 1 行以上

- [x] C3.7 install.ps1 含 regasm 注册步骤
  - 验证方法：`Select-String -Path install.ps1 -Pattern 'regasm'`
  - 通过判据：匹配到 1 行以上

- [x] C3.8 install.ps1 含 AddIns 注册表项写入步骤（HKLM\SOFTWARE\SolidWorks\AddIns）
  - 验证方法：`Select-String -Path install.ps1 -Pattern 'SolidWorks\\AddIns'`
  - 通过判据：匹配到 1 行以上

- [x] C3.9 install.ps1 含 backend_url 配置写入步骤（HKCU\Software\SynthDraft）
  - 验证方法：`Select-String -Path install.ps1 -Pattern 'Software\\SynthDraft'`
  - 通过判据：匹配到 1 行以上

- [x] C3.10 install.ps1 含安装结果摘要输出（成功/失败 + 各步骤状态）
  - 验证方法：`Select-String -Path install.ps1 -Pattern '安装成功|安装失败|Write-Host|Write-Output'`
  - 通过判据：匹配到 1 行以上

## 四、SubTask 8.4 卸载脚本（uninstall.ps1）

- [x] C4.1 `solidworks_addin\uninstall.ps1` 文件存在
  - 验证方法：`Test-Path uninstall.ps1`
  - 通过判据：返回 $true

- [x] C4.2 uninstall.ps1 含参数 `-RemoveConfig`（默认 $false）
  - 验证方法：`Select-String -Path uninstall.ps1 -Pattern 'RemoveConfig'`
  - 通过判据：匹配到 1 行以上

- [x] C4.3 uninstall.ps1 含参数 `-RemoveFiles`（默认 $false）
  - 验证方法：`Select-String -Path uninstall.ps1 -Pattern 'RemoveFiles'`
  - 通过判据：匹配到 1 行以上

- [x] C4.4 uninstall.ps1 含 regasm 反注册步骤（`regasm /u`）
  - 验证方法：`Select-String -Path uninstall.ps1 -Pattern 'regasm.*\/u'`
  - 通过判据：匹配到 1 行以上

- [x] C4.5 uninstall.ps1 含 AddIns 注册表项删除步骤（Remove-Item 或 reg delete）
  - 验证方法：`Select-String -Path uninstall.ps1 -Pattern 'Remove-Item.*SolidWorks\\AddIns|reg delete.*SolidWorks\\AddIns'`
  - 通过判据：匹配到 1 行以上

- [x] C4.6 uninstall.ps1 含卸载结果摘要输出
  - 验证方法：`Select-String -Path uninstall.ps1 -Pattern '卸载成功|卸载失败|Write-Host|Write-Output'`
  - 通过判据：匹配到 1 行以上

## 五、SubTask 8.4 版本清单与更新检查

- [x] C5.1 `solidworks_addin\version.json` 文件存在
  - 验证方法：`Test-Path version.json`
  - 通过判据：返回 $true

- [x] C5.2 version.json 含全部 7 个字段（version/solidworks_compatibility/backend_api_version/dotnet_framework/release_date/download_url/checksum）
  - 验证方法：`Get-Content version.json | ConvertFrom-Json` 后检查字段存在性
  - 通过判据：7 个字段全部存在

- [x] C5.3 version.json `version` 字段为语义化版本号（如 `1.0.0`）
  - 验证方法：正则匹配 `^\d+\.\d+\.\d+$`
  - 通过判据：匹配成功

- [x] C5.4 `solidworks_addin\check_update.ps1` 文件存在
  - 验证方法：`Test-Path check_update.ps1`
  - 通过判据：返回 $true

- [x] C5.5 check_update.ps1 含本地 version.json 读取逻辑
  - 验证方法：`Select-String -Path check_update.ps1 -Pattern 'version.json|ConvertFrom-Json'`
  - 通过判据：匹配到 1 行以上

- [x] C5.6 check_update.ps1 含远端版本清单拉取逻辑（Invoke-WebRequest 或 HttpClient）
  - 验证方法：`Select-String -Path check_update.ps1 -Pattern 'Invoke-WebRequest|Invoke-RestMethod|HttpClient'`
  - 通过判据：匹配到 1 行以上

- [x] C5.7 check_update.ps1 含版本号比较逻辑（不引入 SemVer 库，手写比较函数）
  - 验证方法：`Select-String -Path check_update.ps1 -Pattern 'Compare-Version|version.*compare|Split.*\.|\.Split'`
  - 通过判据：匹配到 1 行以上

- [x] C5.8 check_update.ps1 含降级逻辑（download_url 为空或请求超时时不报错）
  - 验证方法：`Select-String -Path check_update.ps1 -Pattern 'catch|try|远端不可达|无法检查更新'`
  - 通过判据：匹配到 1 行以上

## 六、自检脚本（verify_task8.ps1）

- [x] C6.1 `solidworks_addin\verify_task8.ps1` 文件存在
  - 验证方法：`Test-Path verify_task8.ps1`
  - 通过判据：返回 $true

- [x] C6.2 verify_task8.ps1 含 10 项检查点（对照 spec.md Requirement: 自检脚本）
  - 验证方法：人工审阅脚本结构，确认 10 项检查点全部覆盖
  - 通过判据：10 项检查点全部存在

- [x] C6.3 verify_task8.ps1 含源文件存在性检查（csproj/cs/BackendClient.cs/AssemblyInfo.cs）
  - 验证方法：`Select-String -Path verify_task8.ps1 -Pattern 'SynthDraftAddIn.csproj|SynthDraftAddIn.cs|BackendClient.cs|AssemblyInfo.cs'`
  - 通过判据：4 项全部匹配

- [x] C6.4 verify_task8.ps1 含 csproj 配置正确性检查（TargetFramework=v4.8 / ComVisible / Guid / ProgId）
  - 验证方法：`Select-String -Path verify_task8.ps1 -Pattern 'TargetFramework|ComVisible|Guid|ProgId'`
  - 通过判据：4 项全部匹配

- [x] C6.5 verify_task8.ps1 含编译执行与 DLL 产物检查
  - 验证方法：`Select-String -Path verify_task8.ps1 -Pattern 'MSBuild|csc.exe|SynthDraftAddIn.dll'`
  - 通过判据：匹配到 1 行以上

- [x] C6.6 verify_task8.ps1 含 regasm 注册与注册表项检查
  - 验证方法：`Select-String -Path verify_task8.ps1 -Pattern 'regasm|SolidWorks\\AddIns'`
  - 通过判据：匹配到 1 行以上

- [x] C6.7 verify_task8.ps1 含 backend_url 配置可读检查
  - 验证方法：`Select-String -Path verify_task8.ps1 -Pattern 'backend_url|Software\\SynthDraft'`
  - 通过判据：匹配到 1 行以上

- [x] C6.8 verify_task8.ps1 含安装脚本全部存在性检查（install.ps1/uninstall.ps1/version.json/check_update.ps1/README.md）
  - 验证方法：`Select-String -Path verify_task8.ps1 -Pattern 'install.ps1|uninstall.ps1|version.json|check_update.ps1|README.md'`
  - 通过判据：5 项全部匹配

- [x] C6.9 verify_task8.ps1 含结构化报告输出（x/y PASS + 失败项清单 + 退出码 0/1）
  - 验证方法：`Select-String -Path verify_task8.ps1 -Pattern 'PASS|FAIL|exit|退出码'`
  - 通过判据：匹配到 1 行以上

- [x] C6.10 verify_task8.ps1 实测执行，通过率 ≥ 90%（环境限制项如实标注 ENV-LIMIT）
  - 验证方法：执行 `.\verify_task8.ps1`，记录输出
  - 通过判据：通过项 / 总项 ≥ 0.9，环境限制项明确标注

## 七、安装说明文档（README.md）

- [x] C7.1 `solidworks_addin\README.md` 文件存在
  - 验证方法：`Test-Path README.md`
  - 通过判据：返回 $true

- [x] C7.2 README.md 含"环境前置条件"章节（.NET Framework 4.8+ / SolidWorks 2022+ / 管理员权限）
  - 验证方法：`Select-String -Path README.md -Pattern '环境前置|前置条件|.NET Framework 4.8|SolidWorks 2022|管理员'`
  - 通过判据：匹配到 1 行以上

- [x] C7.3 README.md 含"一键安装"章节（`.\install.ps1` 命令示例）
  - 验证方法：`Select-String -Path README.md -Pattern '一键安装|install.ps1'`
  - 通过判据：匹配到 1 行以上

- [x] C7.4 README.md 含"手动安装"章节（MSBuild/csc.exe 编译命令 + regasm 命令 + reg add 命令）
  - 验证方法：`Select-String -Path README.md -Pattern '手动安装|MSBuild|csc.exe|regasm|reg add'`
  - 通过判据：匹配到 1 行以上

- [x] C7.5 README.md 含"卸载"章节（`.\uninstall.ps1` 命令示例）
  - 验证方法：`Select-String -Path README.md -Pattern '卸载|uninstall.ps1'`
  - 通过判据：匹配到 1 行以上

- [x] C7.6 README.md 含"配置后端地址"章节（reg add/reg query 命令 + BackendClient 读取逻辑）
  - 验证方法：`Select-String -Path README.md -Pattern '配置后端|backend_url|reg add|reg query'`
  - 通过判据：匹配到 1 行以上

- [x] C7.7 README.md 含"故障排查"章节（MSB3644 / regasm 找不到 / SolidWorks 加载失败 / backend_url 读取失败）
  - 验证方法：`Select-String -Path README.md -Pattern '故障排查|MSB3644|regasm|加载失败|backend_url'`
  - 通过判据：匹配到 1 行以上

- [x] C7.8 README.md 含"版本更新流程"章节（`.\check_update.ps1` 命令示例）
  - 验证方法：`Select-String -Path README.md -Pattern '版本更新|check_update.ps1'`
  - 通过判据：匹配到 1 行以上

## 八、主项目状态更新

- [x] C8.1 主项目 `d:\SynthDraft\.trae\specs\ai-engineering-design-assistant\tasks.md` 中 Task 8 的 SubTask 8.1/8.2/8.3/8.4 全部勾选
  - 验证方法：`Select-String -Path tasks.md -Pattern '\[x\] SubTask 8\.'`
  - 通过判据：4 项全部匹配（8.1/8.2/8.3/8.4）

- [x] C8.2 主项目 tasks.md 中 Task 8 标题由"⏸️ 跳过"变更为"✅ 实现"
  - 验证方法：`Select-String -Path tasks.md -Pattern 'Task 8: SolidWorks Add-in.*✅'`
  - 通过判据：匹配到 1 行

## 九、八荣八耻原则符合性

- [x] C9.1 所有 SolidWorks API 调用基于已验证签名（SynthDraftAddIn.cs 注释含"verified signature"）
  - 验证方法：`Select-String -Path SynthDraftAddIn.cs -Pattern 'verified|已验证|API Help'`
  - 通过判据：匹配到 1 行以上

- [x] C9.2 编译失败根因已定位（MSB3644 或其他），不绕过
  - 验证方法：verify_task8.ps1 编译检查点通过，或在报告中如实标注根因
  - 通过判据：编译通过 或 失败根因明确记录

- [x] C9.3 注册表项路径实测写入，不靠假设
  - 验证方法：verify_task8.ps1 注册表检查点通过，或降级路径如实标注
  - 通过判据：注册表项存在 或 降级原因明确记录

- [x] C9.4 环境限制（如 SolidWorks 未安装）如实标注，不谎报通过
  - 验证方法：verify_task8.ps1 报告中环境限制项标注 ENV-LIMIT
  - 通过判据：环境限制项明确标注，不混入 PASS 计数

- [x] C9.5 自检脚本覆盖全部 SubTask，不只检查 happy path
  - 验证方法：核对 C6.2-C6.9 全部检查点覆盖范围
  - 通过判据：8.1/8.2/8.3/8.4 + 自检 + README 全部覆盖

# 汇总

- 总检查点数：62 项（实际检查点数，覆盖 C1.1-C9.5 全部条目）
- 实测结果（2026-07-28）：PASS 61 项 + ENV-LIMIT 1 项 + FAIL 0 项
- 通过率：98.4%（61/62）
- 环境限制项：C2.5（HKLM AddIns 注册表项需管理员权限，已降级到 HKCU per-user 注册，由 install.ps1 完成）
- 失败处理：无失败项
- 验证脚本：`solidworks_addin\verify_task8.ps1`
- 验证报告：`solidworks_addin\verify_task8_report.json`
