# Tasks

- [ ] Task 1: 审计当前仓库被跟踪文件并生成分类清单
  - [ ] SubTask 1.1: 逐类别枚举 git 跟踪文件（`.trae/` / `ai/` / `backend/` / `docs/` / `frontend/` / `infra/` / `kb/` / `solidworks_addin/` / 根目录）
  - [ ] SubTask 1.2: 对每个文件标注"保留 / 移除 / 待定"并记录理由
  - [ ] SubTask 1.3: 生成审计清单文档 `backend/tmp_audit_logs/repo-file-audit.md`（不入 git，仅本地参考）

- [ ] Task 2: 清理不该上传的文件（git 层面 untrack，不删本地）
  - [ ] SubTask 2.1: 移除 `backend/tests/debug_*.py`（6 个调试脚本）的 git 跟踪
  - [ ] SubTask 2.2: 评估 `backend/tests/verify_task*.py`（13 个任务验证脚本）——移至 `backend/tests/verification/` 或 untrack，保留 `test_*.py` 真正单元测试
  - [ ] SubTask 2.3: 移除 `solidworks_addin/verify_task8_report.json`（测试输出产物）
  - [ ] SubTask 2.4: 评估 `.trae/specs/` 下 20+ 个迭代 spec——保留主 spec 和 coderabbit 审查 spec，untrack 其余过程 spec
  - [ ] SubTask 2.5: 评估 `backend/tests/_pull_model.py` / `gen_typelib.py` / `realtest_solidworks.py` 等工具脚本
  - [ ] SubTask 2.6: 补充 `.gitignore` 忽略规则覆盖上述清理类别

- [ ] Task 3: 重写 README.md
  - [ ] SubTask 3.1: 更新项目状态为"P0-P2 完成 + 多轮质量优化"
  - [ ] SubTask 3.2: 补全技术栈表（新增前端 Next.js/TypeScript/Tailwind/shadcn/ui 行）
  - [ ] SubTask 3.3: 更新目录结构（反映 frontend 已实现、solidworks_addin 已实现）
  - [ ] SubTask 3.4: 补充核心功能列表（智能审图、智能生成、知识库检索、SolidWorks 集成）
  - [ ] SubTask 3.5: 补充架构说明（Linux AI 服务 + Windows SolidWorks Worker 分离架构）
  - [ ] SubTask 3.6: 添加 LICENSE 引用章节
  - [ ] SubTask 3.7: 修正端点列表（补充前端页面路由 /review /generate /kb）

- [ ] Task 4: 新增开源标配文件
  - [ ] SubTask 4.1: 创建 `LICENSE`（MIT，年份 2024-2026，版权人 3141cpy）
  - [ ] SubTask 4.2: 创建 `.github/ISSUE_TEMPLATE/bug_report.md`
  - [ ] SubTask 4.3: 创建 `.github/ISSUE_TEMPLATE/feature_request.md`
  - [ ] SubTask 4.4: 创建 `.github/PULL_REQUEST_TEMPLATE.md`

- [ ] Task 5: 提交清理与文档更新并 push
  - [ ] SubTask 5.1: `git add` 所有变更（README.md / LICENSE / .github/ / .gitignore / untrack 操作）
  - [ ] SubTask 5.2: commit 并 push 到 origin master

- [ ] Task 6: 远程仓库复查
  - [ ] SubTask 6.1: `git ls-remote` 确认远程 master 分支最新 commit
  - [ ] SubTask 6.2: 克隆远程仓库到临时目录，检查文件清单是否与预期一致
  - [ ] SubTask 6.3: 扫描远程仓库无 >50MB 大文件
  - [ ] SubTask 6.4: 扫描远程仓库无 `.env` / 硬编码密钥 / 敏感信息
  - [ ] SubTask 6.5: 验证 README.md 在 GitHub 上渲染正确
  - [ ] SubTask 6.6: 验证目录结构整洁，无多余过程产物

- [ ] Task 7: 生成最终复查报告
  - [ ] SubTask 7.1: 汇总审计清单、清理操作、README 变更、远程复查结果
  - [ ] SubTask 7.2: 输出 `backend/tmp_audit_logs/github-repo-final-review.md`（本地留存）

# Task Dependencies
- [Task 2] depends on [Task 1]（需先完成审计才能清理）
- [Task 3] 和 [Task 4] 可与 [Task 2] 并行
- [Task 5] 依赖 [Task 2] + [Task 3] + [Task 4] 全部完成
- [Task 6] 依赖 [Task 5]（push 后才能复查远程）
- [Task 7] 依赖 [Task 6]
