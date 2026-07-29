# Checklist

## 阶段一：文件审计

- [ ] 逐类别枚举 git 跟踪的 366 个文件完成
- [ ] 每个文件标注"保留 / 移除 / 待定"及理由
- [ ] 审计清单文档生成（本地 `backend/tmp_audit_logs/repo-file-audit.md`）
- [ ] 识别出所有调试脚本（`debug_*.py`）
- [ ] 识别出所有任务验证脚本（`verify_task*.py`）
- [ ] 识别出所有测试输出产物（`*_report.json` 等）
- [ ] 识别出 `.trae/specs/` 下的迭代过程 spec

## 阶段二：文件清理

- [ ] `backend/tests/debug_*.py`（6 个）已从 git 跟踪移除
- [ ] `backend/tests/verify_task*.py` 已处理（移至 verification/ 子目录或 untrack）
- [ ] `solidworks_addin/verify_task8_report.json` 已从 git 跟踪移除
- [ ] `.trae/specs/` 下迭代过程 spec 已处理（保留主 spec + coderabbit spec）
- [ ] `backend/tests/` 工具脚本（`_pull_model.py` / `gen_typelib.py` / `realtest_solidworks.py`）已处理
- [ ] `.gitignore` 已补充覆盖上述清理类别的忽略规则
- [ ] 清理后 `git ls-files | Measure-Object -Line` 数量合理减少
- [ ] 清理后仍保留所有核心源码（`backend/app/` / `frontend/src/` / `solidworks_addin/*.cs`）

## 阶段三：README.md 重写

- [ ] 项目状态更新为"P0-P2 完成 + 多轮质量优化"
- [ ] 技术栈表包含前端技术（Next.js / TypeScript / Tailwind / shadcn/ui）
- [ ] 目录结构反映 frontend 和 solidworks_addin 已实现
- [ ] 包含核心功能列表（智能审图 / 智能生成 / 知识库 / SolidWorks 集成）
- [ ] 包含架构说明（Linux AI + Windows SolidWorks 分离）
- [ ] 端点列表包含前端页面路由（/review /generate /kb）
- [ ] 包含 LICENSE 引用
- [ ] 移除所有"P0 阶段""待创建"等过时表述
- [ ] README 在 GitHub 上渲染正确（标题层级、表格、代码块）

## 阶段四：开源标配文件

- [ ] `LICENSE` 文件存在且为 MIT 许可证
- [ ] LICENSE 年份和版权人正确
- [ ] `.github/ISSUE_TEMPLATE/bug_report.md` 存在
- [ ] `.github/ISSUE_TEMPLATE/feature_request.md` 存在
- [ ] `.github/PULL_REQUEST_TEMPLATE.md` 存在

## 阶段五：提交与 push

- [ ] 所有变更已 commit（README / LICENSE / .github/ / .gitignore / untrack 操作）
- [ ] commit message 符合规范
- [ ] push 到 origin master 成功
- [ ] 远程 master 分支 commit SHA 与本地一致

## 阶段六：远程仓库复查

- [ ] `git ls-remote origin master` 返回最新 commit
- [ ] 克隆远程仓库到临时目录成功
- [ ] 远程仓库文件清单与预期一致（无多余调试脚本/过程产物）
- [ ] 远程仓库无 >50MB 大文件（`git rev-list --objects --all | git cat-file` 验证）
- [ ] 远程仓库无 `.env` 文件
- [ ] 远程仓库无硬编码密钥（grep 扫描 API_KEY / password / secret）
- [ ] README.md 在 GitHub 网页渲染正确
- [ ] 目录结构整洁，核心源码完整

## 阶段七：最终报告

- [ ] 最终复查报告生成（`backend/tmp_audit_logs/github-repo-final-review.md`）
- [ ] 报告包含：审计清单、清理操作、README 变更、远程复查结果
- [ ] 报告确认所有问题已解决

## 八荣八耻原则落实检查

- [ ] 以认真查询为荣：每个文件的保留/移除决定基于实际阅读内容，非臆想
- [ ] 以寻求确认为荣：待定文件向用户确认而非擅自处理
- [ ] 以复用现有为荣：README 重写复用现有结构，不推翻重做
- [ ] 以主动测试为荣：push 后主动克隆远程仓库验证
- [ ] 以谨慎重构为荣：清理操作仅 untrack 不删本地文件，可回滚
- [ ] 以实事求是为荣：README 内容反映项目真实状态，不夸大不遗漏
