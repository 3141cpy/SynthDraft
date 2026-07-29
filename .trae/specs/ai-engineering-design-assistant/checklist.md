# Checklist

本清单用于系统性验证 spec 中各项需求与决策是否落实。每项验证须基于实际代码/文档/系统行为，遵循"以主动测试为荣，以跳过验证为耻"原则。

## 调研充分性验证

- [ ] 智能审图领域已调研 ≥ 5 个对标产品/项目（CoLab AutoReview / PKPM-AIChecker / InspectMind / 数匠云 / BLUEPRINT / BeesFPD）
- [ ] AI 生成 CAD 领域已调研 ≥ 5 个对标项目（Zoo / Text-to-CadQuery / CAD-HLLM / AssemCAD / VideoCAD / GenCAD 等）
- [ ] SolidWorks 二次开发已确认支持语言、API 能力、部署约束（含 SLDPRT/SLDASM 必须依赖 SolidWorks API 的硬约束）
- [ ] CAD 文件解析库已对比 ezdxf / ODA File Converter / OpenCASCADE / FreeCAD / CadQuery / ACadSharp 等方案
- [ ] 国标规范体系已查询确认（GB/T 1182/4457.4/17450/1804/131/18229/50001 等），覆盖审图核心条文
- [ ] 所有调研结论附明确来源 URL，无臆造接口或业务（遵循"以瞎猜接口为耻"、"以臆想业务为耻"）

## 技术栈选型验证

- [ ] 后端语言（Python）与 Web 框架（FastAPI）已确认，匹配 AI/CAD 生态
- [ ] CAD 处理栈组合（ezdxf + ODA + pythonOCC + FreeCAD + CadQuery）能力覆盖 DXF/DWG/STEP/IGES 读写与几何校验
- [ ] SolidWorks 桥接方案（win32com + 可选 C# Add-in）已确认 API 可达性
- [ ] AI 模型选型区分多模态（Qwen2.5-VL）、LLM（Qwen2.5-Coder/DeepSeek）、Embedding（bge-m3）、OCR（PaddleOCR）、检测（YOLOv11）
- [ ] 向量库（Qdrant）+ RAG 框架（LlamaIndex）已确认支持条文级检索与原文引用
- [ ] 前端栈（Next.js 14 + Tailwind + shadcn/ui）与图纸查看方案已确认
- [ ] 私有化部署方案确认所有 AI 模型支持本地推理（无强制外部 API 依赖）

## 架构设计验证

- [ ] 架构图体现"AI 服务无状态 + SolidWorks Worker 有状态"分离原则
- [ ] LLM 与几何引擎解耦：LLM 不算坐标/角度，几何校验交由 pythonOCC/FreeCAD
- [ ] 审图管线遵循"几何预处理 → 结构化转译 → LLM 推理 → 双重验证 → 报告闭环"五步法
- [ ] 混合检索（稀疏 + 密集）+ 区域级重排机制已纳入设计
- [ ] 全链路 tracing（OpenTelemetry）+ WebSocket 进度推送已纳入设计
- [ ] 沙箱执行（CadQuery 代码）+ 静态扫描已纳入设计

## 智能审图模块需求验证

- [ ] 支持 4 种输入：SLDPRT/SLDASM、DWG/DXF、PDF、图片（PNG/JPG）
- [ ] 输出包含：合规性评分（0-100）、缺陷列表、定位标注、修改建议
- [ ] 每条缺陷结构化字段完整：类别、严重等级、坐标、条文引用、修改建议
- [ ] 关键结论必须引用规范原文条款编号（防 LLM 幻觉）
- [ ] 中等复杂度零件审图 ≤ 5 分钟
- [ ] 支持"一键触发图纸优化"协同智能生成模块
- [ ] 审图结果可溯源（规范原文 + 图纸坐标 + 推理链路）
- [ ] 支持用户反馈（误报/采纳）回流知识库

## 智能生成模块需求验证

- [ ] 支持 2 种输入：自然语言描述、手绘草图
- [ ] 输出包含：可编辑 CAD 文件（DXF/STEP/IGES）+ SolidWorks 原生文件（SLDPRT/SLDASM）
- [ ] 自然语言生成采用 LLM → CadQuery 代码 → 沙箱执行 → 几何校验 → 输出 管线
- [ ] SolidWorks 原生文件生成通过 Worker Pool + SolidWorks API 完成
- [ ] 装配体生成采用 AssemCAD 公理化范式（类型化零件 + port + mate + 工程公理 + 确定性验证）
- [ ] 生成代码用户可编辑并重新执行
- [ ] 支持多轮对话修改（参数 diff + 增量更新）
- [ ] 生成后自动调用审图模块自检
- [ ] 草图转 CAD 明确标注"草图级精度"并强制人工校准

## 工程规范知识库需求验证

- [x] 支持规范条文结构化存储（条款号/标题/正文/表格/图示/引用关系）✅ Task 14/15（ClauseRecord schema + enterprise_import 三格式解析 + standard_library 15 条预置）
- [x] 支持版本管理（同规范多版本并存）✅ Task 15.3（version_manager.py register/list/latest/deprecate/compare + 自动 supersede）
- [x] 支持按主题/条款号/关键词混合检索 ✅ Task 15 修复（retriever.py 新增 clause_id_filter 精确匹配 + API /clauses 暴露 clause_id 参数）
- [x] P0 覆盖：GB/T 1182、GB/T 4457.4、GB/T 17450、GB/T 1804、GB/T 131、GB/T 18229 ✅ standard_profile.py _DEFAULT_NATIONAL_STANDARDS 6 条
- [x] P1 覆盖：GB/T 4458 系列、GB/T 14665、ISO 128、ISO 1101 ✅ Task 15.1（standard_library.py 4458.1-.6 + 14665 + ISO 128-1/128-24 + ISO 1101）
- [x] P2 覆盖：JB/T 8836 等行业规范、企业自定义规范 ✅ Task 15.2 + 14.1（standard_library.py 5 条行业 + enterprise_import.py 企业自定义导入）

## 私有化部署与安全验证

- [x] 所有 AI 模型（LLM/VLM/Embedding/OCR）支持本地 GPU 推理 ✅ Task 13.1（vllm_provider.py + 量化配置 + Ollama 降级）
- [x] 规范知识库可完全本地化 ✅ Task 13.2（build_offline_package.py 收集模型/规范/依赖 + OFFLINE_MODE）
- [x] SolidWorks Worker 可在企业内网运行 ✅ Task 7（worker_pool.py + Celery 队列解耦，Linux AI ↔ Windows Worker）
- [x] 商业 API 增强模式仅发送脱敏文本，不发送原始图纸 ✅ Task 13.3（desensitize.py 8 类脱敏 + COMMERCIAL_API_MODE strict/optional/off）
- [x] 用户可随时切换纯本地模式 ✅ Task 13.3（OFFLINE_MODE + .env 切换 + COMMERCIAL_API_MODE=off）
- [x] CadQuery/Python 代码沙箱执行（Docker 隔离 + 资源限制 + 网络隔离 + 白名单 API + 静态扫描）⚠️ Task 13 复核（P0 阶段 subprocess 隔离 + 静态扫描 + 白名单 + timeout 降级；Docker 容器级隔离待 P1+，设计已纳入）

## 风险与应对预案验证

- [ ] R1（SolidWorks 闭源）：架构分离 + Worker 池化 + 降级输出路径已设计
- [ ] R2（LLM 几何精度不足）：LLM 与几何引擎解耦原则已写入架构
- [ ] R3（LLM 幻觉）：RAG + 双重验证 + 引用原文 + 用户反馈迭代已设计
- [x] R4（规范复杂）：知识库结构化 + 多版本并存 + 冲突提示已设计 ✅ Task 14.2 + 15.3（conflict_detector 4 类冲突 + version_manager 多版本 + standard_profile 多套切换）
- [ ] R5（VLM 精度）：区域检测 + 区域受限 OCR + 微调 + 精度分级已设计
- [ ] R6（SolidWorks 稳定性）：Worker 进程隔离 + 超时 + 重试 + 健康检查已设计
- [ ] R7（草图精度）：精度标注 + 强制人工校准已设计
- [ ] R8（上下文超限）：分层 RAG + 长上下文模型 + 摘要压缩已设计
- [x] R9（数据安全）：私有化为默认 + 脱敏传输 + 等保/ISO 合规目标已设定 ✅ Task 13.3 + 13.4（OFFLINE_MODE + desensitize + compliance.py 等保三级/ISO 27001 + audit_log）
- [x] R10（代码执行安全）：沙箱 + 静态扫描已设计 ✅ Task 13 复核（sandbox.py STATIC_VIOLATIONS + 白名单 + subprocess 隔离）
- [ ] R11（许可证成本）：仅最终生成调用 SolidWorks + 中间过程用 CadQuery/FreeCAD + 无 SolidWorks 输出路径已设计
- [ ] R12（跨平台）：Docker 化 AI 服务 + 独立 Windows SolidWorks 节点 + 消息队列解耦已设计

## 任务计划验证

- [ ] tasks.md 覆盖 spec 中所有需求（审图/生成/知识库/私有化）
- [ ] tasks.md 按 P0/P1/P2 优先级分阶段，符合"先打通基础自动化，再增强图像理解，最后集成标准知识审查"三阶段原则
- [ ] 每个任务可验证、可独立交付用户可见进展
- [ ] 任务依赖关系明确，并行化机会标注
- [ ] 无过度设计或非必要任务（遵循"以复用现有为荣，以创造接口为耻"）

## 八荣八耻原则符合性验证

- [ ] **以瞎猜接口为耻，以认真查询为荣**：所有 API（SolidWorks、ezdxf、ODA、CadQuery 等）均经查询确认，非臆想
- [ ] **以模糊执行为耻，以寻求确认为荣**：技术选型关键决策点通过 AskUserQuestion 与用户确认
- [ ] **以臆想业务为耻，以人类确认为荣**：业务流程（审图/生成/协同闭环）需求规格明确，待用户确认后实施
- [ ] **以创造接口为耻，以复用现有为荣**：优先复用 ezdxf/ODA/pythonOCC/FreeCAD/CadQuery/LlamaIndex/Qdrant 等成熟组件
- [ ] **以跳过验证为耻，以主动测试为荣**：每个任务含验证步骤，checklist 强制基于实际行为验证
- [ ] **以破坏架构为耻，以遵循规范为荣**：架构原则（解耦/混合智能/私有化优先）明确，实施时遵循
- [ ] **以假装理解为耻，以诚实无知为荣**：调研结论附来源，不确定处明确标注待验证
- [ ] **以盲目修改为耻，以谨慎重构为荣**：绿地项目无重构风险，但后续迭代须遵循 spec
