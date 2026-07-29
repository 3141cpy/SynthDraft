# Tasks

> 本 spec 使用 CodeRabbit CLI（WSL `/home/ht/.local/bin/coderabbit`，v0.7.1，已认证用户 3141cpy）对全项目代码进行 AI 审查，并通过"审查 → 2 次复核 → 修复 → 再审查 → 提交"闭环确保代码质量。所有审查报告保存到 `backend/tmp_audit_logs/`。八荣八耻原则贯穿全程。

## 阶段一：工作区清理与基准 commit

- [x] Task 1: 处理未提交变更并创建审查基准 commit
  - [x] SubTask 1.1: 检查当前 `.gitignore`，确认是否已排除：`.env`、`.venv/`、`node_modules/`、`.next/`、`__pycache__/`、`*.pyc`、`tmp_audit_logs/`、`tmp_metrics/`、`tmp_realtest/`、`tmp_review_images/`、`tmp_state/`、`tmp_audit_outputs/`、`tmp_p1_gate_logs/`、`.playwright_browsers/`、`yolo11n.pt`、`*.log`、`bin/`、`obj/`、`*.SLDPRT`、`*.SLDASM`、`~$*`。缺失的补上
  - [x] SubTask 1.2: 确认 `backend/.env` 不会被提交（若已被 tracked，`git rm --cached backend/.env`）
  - [x] SubTask 1.3: `git add .` 暂存所有有效变更（spec 文件、.gitignore、源码修复等），排除被 .gitignore 忽略的文件
  - [x] SubTask 1.4: `git commit -m "chore: prepare codebase for coderabbit review"` 创建审查基准 commit
  - [x] SubTask 1.5: 记录基准 commit SHA（`git rev-parse HEAD`），作为二次审查的 `--base-commit` 参数

## 阶段二：首次全方位代码审查

- [x] Task 2: 调用 CodeRabbit 进行全项目审查（首轮）
  - [x] SubTask 2.1: 先尝试整体审查：`wsl /home/ht/.local/bin/coderabbit review --committed --agent` 审查已提交代码（即全量代码），收集 NDJSON 输出
  - [x] SubTask 2.2: 若整体审查因 diff 过大超时或失败，按模块拆分：
    - `wsl /home/ht/.local/bin/coderabbit review --committed --agent --dir backend`
    - `wsl /home/ht/.local/bin/coderabbit review --committed --agent --dir frontend`
    - `wsl /home/ht/.local/bin/coderabbit review --committed --agent --dir solidworks_addin`
    - `wsl /home/ht/.local/bin/coderabbit review --committed --agent --dir docs`
  - [x] SubTask 2.3: 解析 NDJSON 输出，按 severity（critical / major / minor）分组，统计每类数量
  - [x] SubTask 2.4: 汇总报告到 `backend/tmp_audit_logs/coderabbit-review-1.md`，含：审查时间、审查范围、issue 总数、按 severity 分级的 issue 列表（每条含文件路径、行号、问题描述、建议修复方案）
  - [x] SubTask 2.5: 若 CodeRabbit 因网络/认证/配额问题失败，排查后重试（最多 3 次），仍失败则记录原因并通知用户

## 阶段三：2 次复核确认

- [x] Task 3: 对 CodeRabbit 发现的每个 critical / major 问题进行 2 次复核
  - [x] SubTask 3.1: 第 1 次复核（技术确认）：对每个 critical / major issue，读对应源码，确认问题是否真实存在
    - 标记为：真问题 / 误报 / 已被其他逻辑覆盖
    - 对误报：记录误报原因（如 CodeRabbit 未理解上下文、框架约定、测试代码等）
  - [x] SubTask 3.2: 第 2 次复核（业务确认）：对真问题从业务影响角度确认是否需要修复
    - 标记为：必须修（critical / 影响功能 / 安全漏洞）/ 建议修（major / 可维护性）/ 可忽略（minor / 风格）
    - 对可忽略：记录忽略理由
  - [x] SubTask 3.3: 汇总复核结果到 `coderabbit-review-1.md` 的"复核结论"章节，每条 issue 附 2 次复核结论与理由
  - [x] SubTask 3.4: 列出"必须修" + "建议修"清单，作为 Task 4 的输入

## 阶段四：针对性修复

- [x] Task 4: 按八荣八耻原则修复确认需修复的问题
  - [x] SubTask 4.1: 对每个"必须修"问题：
    - 先读源码理解上下文（以认真查询为荣）
    - 查询真实接口/类型/签名（不瞎猜，以认真查询为荣）
    - 最小化修改（以谨慎重构为荣）
    - 复用现有工具/组件（以复用现有为荣）
    - 修复后跑相关模块测试（以主动测试为荣）
  - [x] SubTask 4.2: 对每个"建议修"问题：同上原则修复，若修复成本过高或风险过大，记录理由并降级为"可忽略"
  - [x] SubTask 4.3: 修复过程记录到 `backend/tmp_audit_logs/coderabbit-fixes.md`，每条修复含：原 issue 描述、修复方案、修改文件列表、修复 commit hash
  - [x] SubTask 4.4: 按模块分批 commit（`fix(backend): ...` / `fix(frontend): ...` / `fix(solidworks): ...`），commit message 遵循 conventional commits 规范
  - [x] SubTask 4.5: 所有修复完成后，汇总修改文件清单与修复统计

## 阶段五：端到端全面测试

- [x] Task 5: 运行端到端全面测试确保无回归
  - [x] SubTask 5.1: 后端测试：`cd backend; .\.venv\Scripts\python.exe -m pytest tests/ -v --tb=short`，确认全部通过（若个别测试因环境依赖失败，记录原因并标注是否阻塞）— 46/46 passed
  - [x] SubTask 5.2: 前端测试：`cd frontend; npm run lint; npx tsc --noEmit; npx vitest run; npm run build`，确认全部通过 — lint clean / tsc 0 errors / vitest 30/30 / build success
  - [x] SubTask 5.3: 关键 e2e 链路验证：启动后端 + 前端，curl 验证 `GET /api/v1/healthz` 200、`POST /api/v1/uploads` 201、`POST /api/v1/reviews` 202、`POST /api/v1/generations` 202、`GET /api/v1/kb/clauses?query=...` 200
  - [x] SubTask 5.4: 若测试失败，回到 Task 4 修复后重测（红绿循环）
  - [x] SubTask 5.5: 测试全部通过后 `git commit -m "test: verify all tests pass after coderabbit fixes"`（若有未提交改动）

## 阶段六：二次审查确认

- [x] Task 6: 再次调用 CodeRabbit 审查确认问题都已修复
  - [x] SubTask 6.1: `git add . && git commit -m "chore: pre-second-review checkpoint"`（若有未提交改动）
  - [x] SubTask 6.2: 执行 `wsl /home/ht/.local/bin/coderabbit review --committed --agent --base-commit <Task 1 记录的基准 SHA>` 审查修复后的 diff
  - [x] SubTask 6.3: 收集 NDJSON 输出，汇总到 `backend/tmp_audit_logs/coderabbit-review-2.md`
  - [x] SubTask 6.4: 对比首轮与二轮报告，确认所有"必须修" + "建议修"问题都已解决，量化"已解决 / 新发现 / 残留"三类问题数
  - [x] SubTask 6.5: 若二轮发现新 critical / major 问题，回到 Task 3 复核 → Task 4 修复 → Task 5 测试 → Task 6 再审，直到无残留 — **触发迭代修复循环（详见末尾"迭代审查与修复循环记录"）**

## 阶段七：提交至 GitHub

- [ ] Task 7: 提交至 GitHub 仓库
  - [ ] SubTask 7.1: 最终确认 `git status` 无未提交改动
  - [ ] SubTask 7.2: 确认 `git log --oneline` 清晰，commits 顺序合理
  - [ ] SubTask 7.3: `git push -u origin master`（远程仓库默认分支为 master）
    - 若远程已有内容且冲突，先 `git pull --rebase origin master` 再 push
    - **禁止** force push 到 master（除非用户明确要求且确认安全）
  - [ ] SubTask 7.4: 验证 push 成功：`git remote get-url origin` + `curl -s -o /dev/null -w "%{http_code}" https://github.com/3141cpy/SynthDraft` 确认仓库可访问
  - [ ] SubTask 7.5: 生成最终交付报告 `backend/tmp_audit_logs/coderabbit-final-delivery.md`，含：两轮审查对比、修复统计、测试结果、GitHub 提交记录

# Task Dependencies

- Task 1（工作区清理）阻塞所有后续任务
- Task 2（首次审查）阻塞 Task 3
- Task 3（复核确认）阻塞 Task 4
- Task 4（修复）阻塞 Task 5
- Task 5（测试）阻塞 Task 6
- Task 6（二次审查）阻塞 Task 7
- 若 Task 6 发现新问题，回到 Task 3 循环

# 验证策略

- 每次修复后必须跑相关模块的测试（后端 pytest 或前端 vitest）
- 每次修复后必须 `git commit` 保留可回溯记录
- 二次审查报告必须对比首轮，量化"已解决 / 新发现 / 残留"三类问题数
- 最终 push 前必须确认 `git log --oneline` 清晰、`git status` 干净
- 全程遵循八荣八耻原则，每个修复前读源码、查接口、最小化改动

# 迭代审查与修复循环记录

> Task 6 在执行过程中触发多轮迭代修复，本节记录每轮审查的 findings 数、关键发现、对应修复 commit 与状态，确保可回溯。

## 二审（coderabbit-review-2）— 第二轮审查
- **审查范围**：以基准 commit 为 base，审查首轮修复后的 diff（含 backend / frontend / solidworks_addin）
- **findings 数**：5 major
- **关键发现**：
  - auth：匿名访问范围过宽（`backend/app/api/deps.py`）
  - secrets：secret 校验仅覆盖 production，遗漏 staging 等非 dev 环境（`backend/app/config.py`）
  - null checks：worker_pool `_session` 在 shutdown / submit / health_check 路径未防御 None（`backend/app/services/solidworks/worker_pool.py`）
  - 其他 2 条 major（详见 `coderabbit-review-2-backend.ndjson`）
- **修复 commit**：`539ad29 fix: address remaining CodeRabbit second-round findings (auth, secrets, null checks)`
- **状态**：✅ 全部 5 条已修复

## 最终审查 1（coderabbit-review-final）— 第三轮审查
- **审查范围**：审查二审修复后的 diff
- **findings 数**：1 major
- **关键发现**：
  - APP_ENV 在非 development 值时未 fail-closed（`backend/app/config.py`），存在配置漂移风险
- **修复 commit**：`14887a8 fix: fail closed for non-development APP_ENV values (CodeRabbit final review)`
- **状态**：✅ 已修复

## 最终审查 2（coderabbit-review-final-2）— 第四轮审查
- **审查范围**：审查最终审查 1 修复后的 diff
- **findings 数**：1 major
- **关键发现**：
  - DATABASE_URL 未校验，允许使用不安全的默认凭据（`backend/app/config.py`）
- **修复 commit**：`6ef0698 fix: validate DATABASE_URL for insecure default credential (CodeRabbit final)`
- **状态**：✅ 已修复

## 最终审查 3（coderabbit-review-final-3）— 第五轮审查（rate-limited）
- **审查范围**：审查最终审查 2 修复后的 diff
- **findings 数**：未取得（CodeRabbit API 触发 rate limit）
- **状态**：⏳ 需等待约 32 分钟后重试，确认无残留后才能进入 Task 7（push）
- **影响**：阻塞 Task 7 的执行；当前 4 轮审查共修复 7 条后续发现的 major issue（5 + 1 + 1），代码已 commit 但未 push

## 迭代修复累计统计
- 首轮：171 findings（backend 133 + frontend 20 + solidworks_addin 18）→ 2 次复核确认 35 must-fix → commit `7451578` 修复
- 额外修复（sanitization fail-closed，strict mode）：commit `65f3f6b`
- 二审 + 3 轮最终审查累计新增 major findings：7（5 + 1 + 1）→ 全部修复
- 未完成：最终审查 3 因 rate limit 未取得结果，需重试
