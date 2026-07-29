# CodeRabbit 全方位代码审查与修复 Spec

## Why
项目已历经多轮开发（V2-V4 验证、LLM 提示词优化、前端 polish、运行时测试补充、a11y critical 修复），代码库规模较大（backend FastAPI + Celery + frontend Next.js + solidworks_addin + kb tools + docs），但尚未经过专业 AI 代码审查工具的系统性扫描。需引入 CodeRabbit 进行全方位深入审查，识别潜在 bug、安全漏洞、性能问题、可维护性隐患，并通过"审查 → 2 次复核确认 → 修复 → 再审查 → 提交"的闭环确保代码质量达到可交付标准。

## 环境现状（已就绪，无需重复准备）
- **git**：已 `git init`，remote `origin https://github.com/3141cpy/SynthDraft.git` 已关联，已有 1 个 commit `c37f41e chore: initial commit before coderabbit review`，当前分支 `master`
- **CodeRabbit CLI**：安装在 WSL `/home/ht/.local/bin/coderabbit`，版本 `0.7.1`，已通过 GitHub OAuth 认证（用户 `3141cpy`）
- **调用方式**：`wsl /home/ht/.local/bin/coderabbit <command>`（PowerShell 中调用 WSL 的绝对路径，避免 PATH 问题）
- **工作区状态**：有未提交变更（`.gitignore` 修改、`.trae/specs/coderabbit-full-review-and-fix/` 删除、新增 `backend/.env` / `backend/tmp_audit_logs/` / `frontend/tmp_audit_logs/` / `solidworks_addin/bin/` 等）

## What Changes
- 处理工作区未提交变更：将 `tmp_audit_logs/` / `tmp_metrics/` / `tmp_realtest/` / `tmp_review_images/` / `tmp_state/` / `tmp_audit_outputs/` / `.playwright_browsers/` / `yolo11n.pt` / `*.log` / `bin/` / `obj/` 等加入 `.gitignore`，commit 剩余有效变更
- 调用 CodeRabbit CLI 对全项目代码进行首次全方位审查（backend / frontend / solidworks_addin / docs 四大模块），产出结构化 findings
- 对 CodeRabbit 发现的每个 critical / major 问题进行 **2 次独立复核确认**（技术确认 + 业务确认），区分真问题 / 误报 / 已被其他逻辑覆盖
- 对确认需修复的问题按八荣八耻原则进行最小化修复（复用现有、遵循规范、谨慎重构、认真查询、主动测试）
- 运行端到端全面测试（后端 pytest + 前端 lint/tsc/vitest/build + 关键 e2e 链路），确保修复未引入回归
- 再次调用 CodeRabbit 审查确认所有确认需修复的问题都已解决
- 确认彻底无问题后提交至 GitHub 仓库 `https://github.com/3141cpy/SynthDraft`

## Impact
- Affected specs: 无直接受影响 spec（本 spec 是横向质量保障）
- Affected code: 全项目代码（`backend/app/`、`frontend/src/`、`solidworks_addin/`、`docs/`）
- 新增产出：
  - `backend/tmp_audit_logs/coderabbit-review-1.md`（首轮审查报告 + 2 次复核结论）
  - `backend/tmp_audit_logs/coderabbit-fixes.md`（修复记录）
  - `backend/tmp_audit_logs/coderabbit-review-2.md`（复审报告 + 对比首轮）
  - `backend/tmp_audit_logs/coderabbit-final-delivery.md`（最终交付报告）

## ADDED Requirements

### Requirement: CodeRabbit 全方位代码审查
系统 SHALL 通过 CodeRabbit CLI（WSL `/home/ht/.local/bin/coderabbit`）对项目全量代码进行 AI 审查，覆盖 backend、frontend、solidworks_addin、docs 四大模块。

#### Scenario: 首次审查完成
- **WHEN** CodeRabbit 审查全项目代码完成
- **THEN** 产出按 severity（critical / major / minor）分级的 findings 列表，每条 finding 含文件路径、行号、问题描述、建议修复方案
- **AND** 报告保存到 `backend/tmp_audit_logs/coderabbit-review-1.md`
- **AND** 若单次审查因 diff 过大超时，按模块拆分（`--dir backend`、`--dir frontend`、`--dir solidworks_addin`）分别审查后合并

### Requirement: 2 次复核确认机制
对 CodeRabbit 发现的每个 critical / major 问题，MUST 进行 2 次独立的人工复核确认，避免误报导致的无效修改。

#### Scenario: 问题确认
- **WHEN** CodeRabbit 报告一个 critical 或 major 问题
- **THEN** 第 1 次复核（技术确认）：读对应源码，确认问题是否真实存在
  - 标记为：真问题 / 误报 / 已被其他逻辑覆盖
  - 对误报：记录误报原因（如 CodeRabbit 未理解上下文）
- **AND** 第 2 次复核（业务确认）：对真问题从业务影响角度确认是否需要修复
  - 标记为：必须修（critical / 影响功能 / 安全漏洞）/ 建议修（major / 可维护性）/ 可忽略（minor / 风格）
- **AND** 每条问题记录 2 次复核结论与理由，写入 `coderabbit-review-1.md` 的"复核结论"章节

### Requirement: 针对性修复
对确认需要修复的问题，MUST 按八荣八耻原则进行最小化修复。

#### Scenario: 修复完成
- **WHEN** 问题修复完成
- **THEN** 修复前已读源码理解上下文（以认真查询为荣，不瞎猜接口）
- **AND** 修复复用现有工具/组件（以复用现有为荣，未创造重复接口）
- **AND** 修复最小化，未引入不必要改动（以谨慎重构为荣，未盲目修改无关代码）
- **AND** 修复未破坏现有架构（以遵循规范为荣）
- **AND** 修复后跑相关模块测试（以主动测试为荣，未跳过验证）
- **AND** 修复记录写入 `coderabbit-fixes.md`（原 issue、修复方案、修改文件、commit hash）

### Requirement: 端到端全面测试
修复完成后，MUST 运行端到端全面测试确保无回归。

#### Scenario: 测试通过
- **WHEN** 修复完成
- **THEN** 后端 pytest 全部通过（或失败项已记录原因且非阻塞）
- **AND** 前端 `npm run lint` + `npx tsc --noEmit` + `npx vitest run` + `npm run build` 全部通过
- **AND** 关键 e2e 链路（`GET /api/v1/healthz` 200 / `POST /api/v1/uploads` 201 / `POST /api/v1/reviews` 202 / `POST /api/v1/generations` 202 / `GET /api/v1/kb/clauses` 200）返回预期状态码

### Requirement: 二次审查确认
修复并测试通过后，MUST 再次调用 CodeRabbit 审查确认所有确认需修复的问题都已解决。

#### Scenario: 二次审查无残留
- **WHEN** 第二次 CodeRabbit 审查完成
- **THEN** 首轮确认需修复的 critical / major 问题全部已解决
- **AND** 报告保存到 `backend/tmp_audit_logs/coderabbit-review-2.md`
- **AND** 对比首轮与二轮报告，量化"已解决 / 新发现 / 残留"三类问题数
- **AND** 若二轮发现新 critical / major 问题，回到复核 → 修复 → 测试 → 再审循环，直到无残留

### Requirement: 提交至 GitHub
确认彻底无问题后，MUST 提交至 GitHub 仓库 `https://github.com/3141cpy/SynthDraft`。

#### Scenario: 提交成功
- **WHEN** 二次审查确认无残留问题
- **THEN** 代码 commit 并 push 到远程仓库
- **AND** commit message 遵循 conventional commits 规范
- **AND** 不提交敏感文件（`.env` / credentials / 大文件等，遵循 `.gitignore`）
- **AND** push 成功后验证 `https://github.com/3141cpy/SynthDraft` 代码可见

## MODIFIED Requirements
无（本 spec 为新增质量保障流程）

## REMOVED Requirements
无
