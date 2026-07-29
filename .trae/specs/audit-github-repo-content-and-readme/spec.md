# GitHub 仓库内容审计与 README 重写 Spec

## Why
项目已首次 push 到公开 GitHub 仓库 `https://github.com/3141cpy/SynthDraft`，但当前仓库内容存在以下问题：
1. **README.md 严重过时**：仍标注"P0 阶段、Task 1 已完成"，但项目实际已完成 P0/P1/P2 全部任务及多轮迭代优化（V2-V4 验证、LLM 提示词优化、前端 polish、CodeRabbit 全方位审查等）。目录结构标注"frontend 待创建"但前端已完整实现。
2. **仓库内容混杂**：包含开发过程产物（`.trae/specs/` 下 20+ 个迭代修复 spec、gate 报告）、调试脚本（`backend/tests/debug_*.py`）、任务验证脚本（`verify_task*.py`）、测试输出（`verify_task8_report.json`）等不应出现在公开仓库的文件。
3. **缺失关键开源项目标配文件**：无 LICENSE、无 CONTRIBUTING.md、无 .github/ 目录。
4. **缺少前端技术栈信息**：README 技术栈表仅列后端，未包含 Next.js / TypeScript / Tailwind / shadcn/ui。
5. **用户明确要求**：细致认真检查"哪些文件该传、哪些不该传"，README 怎么写需搞清楚，push 后需复查仓库情况。

## What Changes
- **审计当前 366 个被跟踪文件**：逐类别（`.trae/` / `ai/` / `backend/` / `docs/` / `frontend/` / `infra/` / `kb/` / `solidworks_addin/` / 根目录）分类为"保留 / 移除 / 待定"，生成审计清单
- **清理不该上传的文件**：从 git 跟踪中移除调试脚本、过程产物、临时报告等（仅在 git 层面 untrack，不删除本地工作区文件）
- **重写 README.md**：反映项目真实当前状态（P0-P2 完成 + 多轮优化），补全前端技术栈、功能列表、架构说明、开源标配章节
- **新增 LICENSE 文件**：采用 MIT 许可证（适合企业可二次开发的开源项目）
- **新增 .github/ 目录**：包含 Issue / PR 模板（最小化，不引入 CI/CD）
- **复查 GitHub 远程仓库**：push 后通过 `git ls-remote` + GitHub API 验证仓库文件清单、无残留大文件、无敏感信息
- **二次 CodeRabbit 审查（可选）**：对 README 和清理后的仓库结构做最终一致性检查

## Impact
- Affected specs: `coderabbit-full-review-and-fix`（最终交付后的收尾）
- Affected code: 
  - 根目录：`README.md`（重写）、新增 `LICENSE`、新增 `.github/`
  - `.gitignore`（可能补充忽略规则）
  - `backend/tests/`（移除 debug_*.py、verify_task*.py 的 git 跟踪）
  - `solidworks_addin/verify_task8_report.json`（移除跟踪）
  - `.trae/specs/` 下的迭代修复 spec（评估是否保留）
- **不影响任何业务代码功能**，纯仓库治理与文档完善

## ADDED Requirements

### Requirement: 仓库文件分类审计
系统 SHALL 对当前 git 跟踪的所有文件进行分类审计，输出明确的"保留 / 移除 / 待定"清单。

#### Scenario: 调试脚本处理
- **WHEN** 发现 `backend/tests/debug_*.py` 等纯调试用脚本
- **THEN** 从 git 跟踪移除（`git rm --cached`），保留本地文件，并在 `.gitignore` 中添加忽略规则

#### Scenario: 过程产物处理
- **WHEN** 发现 `.trae/specs/` 下的迭代修复 spec（如 `further-reduce-llm-hallucination-v4/`）
- **THEN** 保留主 spec（`ai-engineering-design-assistant/`）和 `coderabbit-full-review-and-fix/`（作为质量记录），移除其余迭代过程 spec

### Requirement: README.md 全面重写
README.md SHALL 准确反映项目当前真实状态，包含开源项目标配章节。

#### Scenario: 项目状态更新
- **WHEN** 阅读 README 项目状态章节
- **THEN** 显示"P0-P2 全部完成 + 多轮质量优化（V2-V4 验证、LLM 幻觉优化、前端 polish、CodeRabbit 审查 0 issues）"

#### Scenario: 技术栈完整性
- **WHEN** 阅读技术栈表
- **THEN** 同时包含后端（FastAPI/Celery/PostgreSQL/Redis/Qdrant/MinIO/Ollama）和前端（Next.js 14/TypeScript/Tailwind/shadcn/ui）技术栈

### Requirement: 开源标配文件
仓库根目录 SHALL 包含 LICENSE 和基础 .github 模板。

#### Scenario: LICENSE
- **WHEN** 检查仓库根目录
- **THEN** 存在 MIT LICENSE 文件，年份和版权人正确

### Requirement: 远程仓库复查
push 完成后 SHALL 对远程仓库进行复查，确认无问题。

#### Scenario: 大文件检查
- **WHEN** 检查远程仓库所有 blob
- **THEN** 无任何 >50MB 的二进制文件（playwright chromium / yolo 模型等已被清理）

#### Scenario: 敏感信息检查
- **WHEN** 扫描远程仓库内容
- **THEN** 无 `.env` 文件、无硬编码密钥、无内部 IP/凭据

## MODIFIED Requirements

### Requirement: .gitignore 补充
在现有 .gitignore 基础上补充忽略规则，覆盖本次清理的文件类别：
- `backend/tests/debug_*.py`
- `backend/tests/verify_task*.py`（保留 `backend/tests/test_*.py` 真正的单元测试）
- `backend/tests/realtest_*.py`
- `solidworks_addin/verify_task*_report.json`
- `.trae/specs/` 下的迭代修复 spec（通过具体路径或模式）

## REMOVED Requirements

### Requirement: 过时的 P0 阶段标注
**Reason**: README 中"P0 阶段、Task 1 已完成"的标注已严重过时
**Migration**: 重写为当前真实状态
