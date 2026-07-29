# 前端运行时测试补充 Spec

## Why

`polish-frontend-design-system` spec 的 9 阶段 22 任务已全部实施完成，但**阶段九（全面实际测试）的 Task 19-21** 因本机未安装 Google Chrome、Chrome DevTools MCP 与 browser_use agent 均无法驱动浏览器，导致以下运行时证据缺失：

- Task 19：4 页面 × 2 主题 × 4 断点 = 32 张视觉回归截图
- Task 20：5 条主链路端到端实测（含截图与网络请求证据）
- Task 21：交互专项、5 条异常路径、a11y 自动化扫描、性能基线、跨浏览器差异

原验证报告 `frontend/tmp_audit_logs/frontend_polish_verification_report.md` 中这些项标注为"代码审查通过，未做运行时验证"。用户明确要求"在最后阶段进行全面实际测试 确保功能无异常 各页面显示正常 所有交互正常"，因此需要补做完整运行时证据链。

本 spec 利用 `trae-remote-official:separateweb-capture`（全页截图 + UI 项裁剪）、`agent-browser` skill（Rust 客户端浏览器自动化）、`dogfood` skill（系统性 QA 探索 + 结构化报告含截图/录屏/重现步骤）三个工具补齐缺失的运行时证据，**不修改任何前端代码**，只产出测试证据并更新验证报告。

## What Changes

- **不修改前端代码**：本 spec 仅产出测试证据（截图、录屏、报告），不改动 `frontend/src/` 下任何文件
- 补做 Task 19：用 `agent-browser` 或 `separateweb-capture` 在 4 断点（375/768/1024/1440）× 2 主题（light/dark）× 4 页面（`/`/`/review`/`/generate`/`/kb`）= 32 张全页截图，保存到 `frontend/tmp_audit_logs/screenshots/`，命名 `{page}-{theme}-{breakpoint}.png`
- 补做 Task 20：用 `dogfood` skill 系统性探索 5 条主链路（`/review` 拖拽+点击上传、`/generate` 自然语言+草图、`/kb` 检索、`/` 系统状态），每条链路保存截图与重现步骤
- 补做 Task 21：交互专项（主题持久化/移动端抽屉/Cmd+Enter/Esc/`/`键/复制下载反馈/取消确认/Toast）、5 条异常路径（Offline/WS 阻断/超限/422/轮询超时）、a11y 自动化（axe 扫描或手动 Tab 遍历）、性能基线（LCP/CLS/INP）、跨浏览器（Edge/Chrome/Firefox 可用者）
- 更新 `frontend/tmp_audit_logs/frontend_polish_verification_report.md`：把"未执行运行时"项替换为实际证据，确认三项结论"功能无异常 / 各页面显示正常 / 所有交互正常"
- 产出 `frontend/tmp_audit_logs/dogfood-report.md`：dogfood skill 的结构化 QA 报告

## Impact

- Affected specs: `polish-frontend-design-system`（补完其 Task 19-21 的运行时证据）
- Affected code: 无代码改动；仅产出测试证据文件到 `frontend/tmp_audit_logs/`
- 依赖服务：前端 dev server（`http://localhost:3000`）+ 后端（`http://localhost:8000`，healthz ok，LLM/VLM available）

## ADDED Requirements

### Requirement: 运行时视觉回归证据

The system SHALL 产出 32 张全页截图，覆盖 4 页面 × 2 主题 × 4 断点的全组合，每张截图文件名遵循 `{page}-{theme}-{breakpoint}.png` 格式，人工检查布局无错位、文字无溢出、对比度可读、暗色下无残留 light 色、移动端抽屉可开关。

#### Scenario: 视觉回归截图齐全
- **WHEN** 测试执行完成
- **THEN** `frontend/tmp_audit_logs/screenshots/` 下存在 32 张截图
- **AND** 每张截图视觉无异常

### Requirement: 端到端链路实测证据

The system SHALL 对 5 条主链路（`/review` 拖拽+点击、`/generate` 自然语言+草图、`/kb` 检索、`/` 系统状态）各执行一次端到端实测，保存截图与网络请求证据。

#### Scenario: 链路通过
- **WHEN** 执行某条主链路
- **THEN** 全流程走通并保存截图证据
- **AND** 网络请求状态码符合预期

### Requirement: 交互专项与异常路径验证

The system SHALL 验证 9 项交互专项（主题持久化/移动端抽屉/Cmd+Enter/Esc/`/`键/复制下载反馈/取消确认/Toast 自动消失）与 5 条异常路径（Offline/WS 阻断/超限/422/轮询超时），每项保存截图或录屏证据。

#### Scenario: 交互正常
- **WHEN** 触发某交互
- **THEN** 行为符合预期并保存证据

### Requirement: 验证报告更新

The system SHALL 更新 `frontend_polish_verification_report.md`，把 Task 19-21 的"未执行运行时"项替换为实际证据引用，并保留三项结论"功能无异常 / 各页面显示正常 / 所有交互正常"。

#### Scenario: 报告完整
- **WHEN** 所有测试执行完成
- **THEN** 报告含测试矩阵表、截图清单、5 条主链路通过情况、交互专项结果、异常路径结果
- **AND** 三项结论基于实际运行时证据

## MODIFIED Requirements

### Requirement: 测试工具链

原 `polish-frontend-design-system` spec 的 Task 19-21 指定用 Chrome DevTools MCP + browser_use agent，现改为 `agent-browser`（Rust 客户端，不依赖系统 Chrome）+ `separateweb-capture`（全页截图）+ `dogfood`（系统性 QA 探索），因本机无 Chrome 但 agent-browser 自带浏览器引擎。

## REMOVED Requirements

无（不删除任何原 spec 要求，只补做证据）
