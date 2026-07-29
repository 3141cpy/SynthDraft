# Tasks

本任务清单对照 spec.md 拆解 SynthDraft 最终验收与修复工作。任务按"先依赖检查 → 再启动服务 → 再各模块实测 → 最后汇总报告"的串行依赖链组织，避免并行化引入的服务状态竞态。

## 阶段一：依赖项主动检查与修复（前置门控）

- [x] Task 1: 依赖项主动检查与缺失项立即安装
  - [x] SubTask 1.1: Python 包主动检查（`pip list` 对比 `backend/requirements.txt`，**缺失包立即 `pip install`**，版本冲突立即修复）
  - [x] SubTask 1.2: 系统工具主动检查与配置（SolidWorks 已确认本地安装 / ODA File Converter 检查+配置 / FreeCAD 检查+降级 / pythonOCC 检查+安装 / .NET Framework 4.8 检查 / MSBuild / csc.exe 检查）
  - [x] SubTask 1.3: SolidWorks interop DLL 主动检查（4 个 DLL：sldworks/swconst/swpublished/swcommands，路径不一致则**主动更新 csproj HintPath**）
  - [x] SubTask 1.4: 生成依赖项检查报告 `backend/tmp_audit_logs/dependency_check.md`（标注每项 PASS/INSTALLED/ENV-LIMIT + 修复动作）

## 阶段二：后端服务主动启动与验证

- [x] Task 2: 主动启动后端服务并验证真实可用
  - [x] SubTask 2.1: **主动启动** Docker Desktop（若未运行，`Start-Process` 启动），等待 Docker 引擎就绪（轮询 `docker info`，超时 120 秒）
  - [x] SubTask 2.2: **主动启动** Docker Compose 服务（postgres / redis / qdrant / ollama，`docker-compose up -d`），等待容器健康
  - [x] SubTask 2.3: **主动拉取** Ollama 模型（qwen2.5-coder:7b / bge-m3，若未拉取则 `docker exec ollama ollama pull`）
  - [x] SubTask 2.4: 验证端口映射可达（5433/6379/6333/11434）
  - [x] SubTask 2.5: **主动启动** FastAPI 服务（`uvicorn app.main:app --host 0.0.0.0 --port 8000`），验证 `GET /healthz` 返回 HTTP 200
  - [x] SubTask 2.6: **主动启动** Celery worker（`celery -A app.celery_app worker --loglevel=info --pool=solo`，Windows 用 solo 避免 prefork 卡死），验证 worker 进程存在
  - [x] SubTask 2.7: 若 Celery worker 仍卡死，记录根因并准备 `task.apply()` 同步执行方案（标注 SYNC-BYPASS）

## 阶段三：Task 8 SolidWorks Add-in 自检验证

- [x] Task 3: Task 8 自检验证（48 项检查点）
  - [x] SubTask 3.1: 检查 `verify_task8.ps1` 是否存在，若不存在则实现
  - [x] SubTask 3.2: 执行 `verify_task8.ps1`，记录 48 项检查点结果
  - [x] SubTask 3.3: 验证编译产物 `bin\Release\SynthDraftAddIn.dll` 存在且非空（>10KB）
  - [x] SubTask 3.4: 验证 COM 注册（HKCU per-user 注册表项存在）
  - [x] SubTask 3.5: 验证安装脚本（install.ps1 / uninstall.ps1 / check-version.ps1 / build.ps1）全部存在且功能正确
  - [x] SubTask 3.6: 验证 backend_url 配置可读（HKCU\Software\SynthDraft\backend_url）
  - [x] SubTask 3.7: 环境限制项（如 HKLM 需管理员权限）如实标注 ENV-LIMIT
  - [x] SubTask 3.8: 勾选 `implement-solidworks-addin/checklist.md` 全部通过项
  - [x] SubTask 3.9: 更新主项目 `ai-engineering-design-assistant/tasks.md` 中 Task 8 状态为 ✅ 实现

## 阶段四：后端 API 真实路径测试

- [x] Task 4: 健康检查端点真实路径测试
  - [x] SubTask 4.1: `GET /healthz` 真实调用并记录响应
  - [x] SubTask 4.2: `GET /api/v1/health/` 真实调用并记录响应
  - [x] SubTask 4.3: 验证响应字段（status / version / dependencies）

- [x] Task 5: 上传与审图真实路径测试
  - [x] SubTask 5.1: `POST /api/v1/uploads/` 上传 DXF 样本，记录 file_key
  - [x] SubTask 5.2: `POST /api/v1/reviews/` 提交审图任务，记录 task_id
  - [x] SubTask 5.3: 轮询 `GET /api/v1/reviews/{task_id}` 直到 completed（或确认 worker 卡死）
  - [x] SubTask 5.4: 若 worker 卡死，运行 `_task8_review_sync.py` 同步执行审图管线
  - [x] SubTask 5.5: 验证审图结果（compliance_score / defects / report_path 真实存在 / review_mode）
  - [x] SubTask 5.6: 验证 HTML 报告文件 size > 0

- [x] Task 6: 文本生成真实路径测试
  - [x] SubTask 6.1: `POST /api/v1/generations/` 提交 text→step 任务，记录 task_id
  - [x] SubTask 6.2: 轮询直到 completed（或确认 worker 卡死）
  - [x] SubTask 6.3: 若 worker 卡死，运行 `_task8_gen_sync.py` 同步执行生成管线
  - [x] SubTask 6.4: 验证生成结果（mode / execution.output_files 真实存在 / geometry_validation.is_valid / volume > 0）
  - [x] SubTask 6.5: 标注路径类型（REAL-PATH llm / FALLBACK-PATH template / SYNC-BYPASS）

- [x] Task 7: 知识库端点真实路径测试
  - [x] SubTask 7.1: `POST /api/v1/kb/index` 索引 GB/T 1182 / GB/T 4457.4 文档
  - [x] SubTask 7.2: `POST /api/v1/kb/search` 检索"尺寸标注"相关条款
  - [x] SubTask 7.3: 验证返回字段（clause_id / standard_ref / text）
  - [x] SubTask 7.4: 标注 embedding 模型与路径类型

- [x] Task 8: LLM 流式端点真实路径测试
  - [x] SubTask 8.1: 准备 `_task8_llm_req.json` 请求体并写入文件
  - [x] SubTask 8.2: `curl -N --data-binary @file` 调用 `/api/v1/llm/stream`
  - [x] SubTask 8.3: 验证 SSE 流含 `data:` 行 + `[DONE]` 终止标记
  - [x] SubTask 8.4: 标注 LLM provider（ollama / openai-compatible / deepseek）

- [x] Task 9: 草图端点真实路径测试
  - [x] SubTask 9.1: 读取 sketch.py 端点签名，确认请求 schema
  - [x] SubTask 9.2: `POST /api/v1/sketch/parse`（或对应路径）调用
  - [x] SubTask 9.3: 验证返回 parameters / bbox 字段
  - [x] SubTask 9.4: 标注 VLM 可用性与路径类型

- [x] Task 10: 协同闭环端点真实路径测试
  - [x] SubTask 10.1: 准备 `_task8_collab_req.json` 含 3 条真实缺陷
  - [x] SubTask 10.2: `POST /api/v1/collaboration/optimize` 调用
  - [x] SubTask 10.3: 记录 HTTP 状态（202/422/409）与响应片段
  - [x] SubTask 10.4: 若 202，轮询 task 状态直到 completed/failed

- [x] Task 11: 可观测性端点真实路径测试
  - [x] SubTask 11.1: `GET /api/v1/observability/queue-status` 调用
  - [x] SubTask 11.2: 验证返回 worker_count / queues / alerts 字段
  - [x] SubTask 11.3: 验证队列名包含 reviews / generations / sketch
  - [x] SubTask 11.4: 记录 worker 卡死时的 queue-status 真实快照

- [x] Task 12: 生成后端 API 真实路径测试报告
  - [x] SubTask 12.1: 整理所有测试记录为端点粒度章节
  - [x] SubTask 12.2: 生成汇总表（Endpoint × Method × Status × Verdict × Path-Type × Notes）
  - [x] SubTask 12.3: 写入 `backend/tmp_audit_logs/task8_backend_realtest.md`

## 阶段五：SolidWorks Worker 真实路径测试（SolidWorks 已确认本地安装）

- [x] Task 13: SolidWorks 会话管理实测
  - [x] SubTask 13.1: 实测 `sw_session.py` 的 SwSession 类（start_session / open_document / close_document / stop_session）
  - [x] SubTask 13.2: 验证 SolidWorks 进程实际启动与退出
  - [x] SubTask 13.3: 若会话启动失败，**优先排查根因**（win32com 未安装则 `pip install pywin32`，许可证未激活则提示用户）
  - [x] SubTask 13.4: 只有超出能力范围（如许可证需付费激活）才标注 ENV-LIMIT

- [x] Task 14: Worker 池与并发控制实测
  - [x] SubTask 14.1: 实测 `worker_pool.py` 的 WorkerPool 类（acquire / release / get_status）
  - [x] SubTask 14.2: 验证 Semaphore 并发控制有效
  - [x] SubTask 14.3: 验证健康检查与自动重启机制

- [x] Task 15: 许可证管理实测
  - [x] SubTask 15.1: 实测 `license.py` 的 SolidWorksLicenseManager 类（acquire / release / get_status）
  - [x] SubTask 15.2: 验证计数控制（超限拒绝）
  - [x] SubTask 15.3: 验证主动探测机制
  - [x] SubTask 15.4: 若许可证不可用，**优先排查**（检查 SolidWorks 是否已激活）

- [x] Task 16: SLDPRT/SLDASM 读取实测
  - [x] SubTask 16.1: 实测 `reader.py` 读取功能（特征树 / 尺寸 / 形位公差 / 表面粗糙度 / 技术要求 / 明细栏）
  - [x] SubTask 16.2: 若无真实 SLDPRT 样本文件，**主动创建测试样本**（通过 writer.py 生成或使用 SolidWorks 自带样本）
  - [x] SubTask 16.3: 若确实无法获取样本，明确标注 ENV-LIMIT 并说明根因

- [x] Task 17: SLDPRT/SLDASM 生成实测
  - [x] SubTask 17.1: 实测 `writer.py` 生成功能（new_document / open_template / import_step 三条路径）
  - [x] SubTask 17.2: 若生成失败，**记录失败原因并尝试修复**（如 API 签名错误则查询 SolidWorks API Help 修正）

- [x] Task 18: 生成 SolidWorks Worker 真实路径测试报告
  - [x] SubTask 18.1: 整理所有测试记录为模块粒度章节
  - [x] SubTask 18.2: 写入 `backend/tmp_audit_logs/solidworks_worker_realtest.md`

## 阶段六：VLM 模块代码审查

- [x] Task 19: region_detector.py 代码审查
  - [x] SubTask 19.1: 审查 YOLOv11 模型加载逻辑（含 ultralytics 未安装时的降级路径）
  - [x] SubTask 19.2: 审查区域检测输出 schema（标题栏/修订表/明细栏/视图区/标注区）
  - [x] SubTask 19.3: 审查错误处理与日志记录
  - [x] SubTask 19.4: 审查与 region_ocr.py 的接口契约

- [x] Task 20: vlm_ocr.py 代码审查
  - [x] SubTask 20.1: 审查 VLM provider 切换逻辑（ollama / openai-compatible / anthropic）
  - [x] SubTask 20.2: 审查图像编码逻辑（base64 / URL）
  - [x] SubTask 20.3: 审查 OCR 结果解析与结构化输出
  - [x] SubTask 20.4: 审查降级路径（VLM 不可用时的兜底）

- [x] Task 21: sketch_parser.py 代码审查
  - [x] SubTask 21.1: 审查草图解析逻辑（参数提取 / bbox 计算）
  - [x] SubTask 21.2: 审查 VLM 调用与降级路径
  - [x] SubTask 21.3: 审查与 sketch_to_cadquery.py 的接口契约
  - [x] SubTask 21.4: 审查错误处理与日志记录

- [x] Task 22: 生成 VLM 代码审查报告
  - [x] SubTask 22.1: 整理审查记录为模块粒度章节
  - [x] SubTask 22.2: 写入 `backend/tmp_audit_logs/vlm_code_review.md`

## 阶段七：问题修复与完善

- [x] Task 23: 修复测试中发现的问题
  - [x] SubTask 23.1: 修复 P0 问题（阻塞性 bug），修复后重新测试
  - [x] SubTask 23.2: 修复 P1 问题（影响功能但可降级），记录修复方案
  - [x] SubTask 23.3: P2 问题视情况修复，无法修复的在报告中标注

## 阶段八：最终交付报告

- [x] Task 24: 生成最终交付报告
  - [x] SubTask 24.1: 汇总 Task 8 验证结果（48 项检查点通过率）
  - [x] SubTask 24.2: 汇总后端 API 真实路径测试结果（端点 × 状态 × 路径类型矩阵）
  - [x] SubTask 24.3: 汇总 SolidWorks Worker 真实路径测试结果（模块 × 状态矩阵）
  - [x] SubTask 24.4: 汇总 VLM 代码审查结果（模块 × 审查项矩阵）
  - [x] SubTask 24.5: 汇总依赖项检查结果（依赖 × 状态矩阵）
  - [x] SubTask 24.6: 生成问题清单（含 file:line 引用 + 修复状态）
  - [x] SubTask 24.7: 生成环境限制清单（ENV-LIMIT 项 + 根因 + 建议）
  - [x] SubTask 24.8: 写入结论（PASS / CONDITIONAL_PASS / FAIL）
  - [x] SubTask 24.9: 写入 `backend/tmp_audit_logs/final_acceptance_report.md`

# Task Dependencies

- Task 1（依赖检查）→ 所有后续 Task（需先确认依赖完整）
- Task 2（服务启动）→ Task 4-12（后端 API 测试需服务运行）
- Task 2（服务启动）→ Task 13-18（SolidWorks Worker 测试需服务运行，SolidWorks 部分独立于 Docker）
- Task 3（Task 8 自检）独立于 Task 2，可与 Task 2 并行
- Task 4-11（后端 API 各端点测试）相互独立，可并行
- Task 12（后端 API 报告）依赖 Task 4-11 全部完成
- Task 13-17（SolidWorks Worker 各模块测试）相互独立，可并行
- Task 18（SolidWorks Worker 报告）依赖 Task 13-17 全部完成
- Task 19-21（VLM 代码审查）相互独立，可并行
- Task 22（VLM 审查报告）依赖 Task 19-21 全部完成
- Task 23（问题修复）依赖 Task 3/12/18/22 全部完成（需先发现问题）
- Task 24（最终报告）依赖 Task 23 完成（需先修复问题）

# 并行化建议

- 第一波（并行）：Task 1（依赖检查）|| Task 3（Task 8 自检）|| Task 19-21（VLM 代码审查）
- 第二波（串行）：Task 2（服务启动，依赖 Task 1 完成）
- 第三波（并行）：Task 4-11（后端 API 各端点测试）|| Task 13-17（SolidWorks Worker 各模块测试）
- 第四波（并行）：Task 12（后端 API 报告）|| Task 18（SolidWorks Worker 报告）|| Task 22（VLM 审查报告）
- 第五波（串行）：Task 23（问题修复）→ Task 24（最终报告）

# 阶段门控

1. Task 1 依赖检查必须实测执行，缺失依赖需立即安装，不得绕过
2. Task 2 服务启动必须实测验证，不得仅理论分析
3. Task 3 Task 8 自检必须实测执行 verify_task8.ps1，环境限制项如实标注
4. Task 4-11 后端 API 测试必须真实 HTTP 调用，不得仅因 TCP 连接成功即 PASS
5. Task 13-17 SolidWorks Worker 测试必须真实调用，SolidWorks 未安装时如实标注 ENV-LIMIT
6. Task 19-21 VLM 代码审查必须基于代码实际阅读，不得主观断言
7. Task 23 问题修复必须遵循"谨慎重构"原则，最小改动，不破坏架构
8. Task 24 最终报告必须实事求是标注，不可将 FALLBACK-PATH / ENV-LIMIT / FAIL 标为 PASS
