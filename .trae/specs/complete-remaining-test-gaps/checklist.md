# Checklist

本清单用于系统性验证 `complete-remaining-test-gaps` spec 中所有 Requirement 是否落实。每项必须基于实际证据(日志/产出文件/截图)打勾,不可主观断言。

## Task 1: 草图 VLM 尺寸幻觉误判 PASS 修复

- [x] `tmp_audit_logs/25_sketch_vlm_dimension_retest.md` 已生成,含期望值/实际值/偏差比例
- [x] 草图样本已准备(已知尺寸: 外圆 φ100 + 中心孔 φ20 + 厚度 10mm)
- [x] 期望值已记录(radius=50, thickness=10, inner_radius=10)
- [x] 调用 `sketch_parser.parse_sketch()` 真实推理,VLM 返回 `parameters` 已记录
- [x] VLM 返回尺寸与期望值偏差已计算(若偏差超 2 倍标 FAIL)
- [x] bbox 格式已校验(`[x1,y1,x2,y2]` vs `[x,y,w,h]`)
- [x] `_normalize_bbox` 对越界值的处理已验证(0.85+0.4>1.0 是否被钳制)
- [x] 最终结论基于真实偏差比例(PASS 或 FAIL),不可仅因"返回非空"即 PASS
- [x] 若标 FAIL:已明确说明"VLM 对草图尺寸识别存在严重幻觉,不可用于生产"

> 证据: 25_sketch_vlm_dimension_retest.md 记录 VLM=minicpm-v:latest, elapsed=12.43s; radius 期望 50.0 实际 10 偏差 5.00x FAIL; thickness 期望 10.0 实际 2 偏差 5.00x FAIL; bbox=[0.5,0.49,0.78,0.6] 格式判为 [x1,y1,x2,y2] 但 _normalize_bbox 按 [x,y,w,h] 处理导致语义错误; 最终结论 FAIL

## Task 2: HTML 报告模板渲染 vlm_ocr_extras 修复

- [x] `tmp_audit_logs/26_html_vlm_ocr_render.md` 已生成
- [x] HTML 报告模板文件已定位(路径记录)
- [x] 模板源码已读取,`vlm_ocr_extras` 未渲染原因已确认
- [x] 模板已修改,增加 "VLM OCR 识别结果" 区块
- [x] 区块包含所有非空字段:title / drawing_number / material / scale / dimensions / technical_requirements / surface_roughness / tolerance / vlm_model
- [x] 重新调用 `generate_review_report()` 生成 HTML
- [x] 用字符串搜索验证 `title="SynthDraft Sample"` 等字段值在 HTML 中出现
- [x] 修改前后 HTML 对比已记录(搜索结果从空到非空)
- [x] 不可再标"已知模板限制,非阻塞性"即视为 PASS

> 证据: 26_html_vlm_ocr_render.md 记录模板 app/services/review/templates/report.html.j2 已修改新增 VLM OCR 识别结果区块; 修改前 HTML 搜索 'VLM OCR'/'图样标题'/'value:合成草图样本' 均 NOT FOUND; 修改后 HTML (29757 bytes) 搜索 'VLM OCR' FOUND / '图样标题' FOUND / 'value:合成草图样本' FOUND / 'value:minicpm-v:latest' FOUND; VLM OCR 字段在报告中可见=True; 最终结论 PASS

## Task 3: apply_multi_turn_edit 真实 LLM 路径独立验证

- [x] `tmp_audit_logs/27_multiturn_edit_real_llm.md` 已生成
- [x] 原始 CadQuery 代码已准备(法兰盘代码,outer_diameter=100, bolt_count=4)
- [x] `is_llm_available()` 返回 True,记录 provider 类型 (OllamaProvider, qwen2.5-coder:7b)
- [x] 调用 `apply_multi_turn_edit()` 记录:LLM 模型名 / 推理耗时 / 返回 new_code
- [x] `new_code` 与 `original_code` 的 diff 已记录(具体哪些行变化): outer_diameter 100→120, bolt_count 4→8 (仅 2 行)
- [x] 明确记录走 LLM 路径还是正则降级路径 (path=llm, provider.chat 调用, _regex_edit 未调用 count=0)
- [x] 若走 LLM 路径:验证 `new_code` 中 `outer_diameter=120.0` + `bolt_count=8` (精确匹配)
- [x] 若走正则降级:记录降级原因,验证正则替换结果正确 (N/A, 走 LLM 路径)
- [x] 沙箱执行 `new_code`,验证产出 STEP 文件 volume 与新参数匹配(bbox 120×120×10, dx=120, dy=120, dz=10)
- [x] 不可与 verify_task5_e2e.py 混合路径测试结果混淆 (本测试独立执行, 独立产出 audit log)

> 证据: 27_multiturn_edit_real_llm.md 记录真实路径=llm (provider.chat 调用, _regex_edit 未调用), provider=OllamaProvider, model=qwen2.5-coder:7b, elapsed=43.19s; diff: outer_diameter 100→120, bolt_count 4→8 (仅 2 行变化); 沙箱 exit_code=0, STEP bbox=(-60,-60,0,60,60,10) → dx=120, dy=120, dz=10 精确匹配; 总体 PASS

## Task 4: DeepSeek 远程 LLM 全链路协同闭环验证

- [x] `tmp_audit_logs/28_deepseek_full_pipeline.md` 已生成
- [x] 环境变量已设置(LLM_PROVIDER=openai + OPENAI_BASE_URL + OPENAI_MODEL + API Key)
- [x] 输入 3 条真实审图缺陷(与 18_collaboration_retest.md 一致)
- [x] `defects_to_optimization_prompt()` 生成 prompt 非空
- [x] `generate_cadquery_code(prompt)` 记录 mode(llm/template) + 推理耗时
- [x] `generate_and_execute_with_fallback()` 走完整协同闭环
- [x] 产出真实 `revised.step`(volume > 0)
- [x] 产出真实 `revised.dxf`(entity_count > 0)
- [x] DeepSeek vs Ollama 对比已记录:推理耗时 / 代码质量 / 沙箱执行成功率 / 是否触发降级
- [x] 不可仅因 13_llm_switch.md 隔离 chat 通过即认为全链路可用

> 证据: 28_deepseek_full_pipeline.md 记录 DeepSeek API 真实调用 PASS; provider=OpenAIProvider is_available=True; prompt=748 chars; mode=llm (无降级); LLM 推理 11.03s vs Ollama 78.50s (7x 加速); 代码长度 2509 chars 含 import cadquery; 沙箱执行 step success exit_code=0 产出 2 文件; 沙箱执行 dxf success exit_code=0 产出 3 文件; revised.step 39006 bytes volume=162577.42 mm³ bbox=(-50,-50,0)→(50,50,30) (thickness=30 正确修复 critical 缺陷"缺失高度尺寸 30mm"); revised.dxf 25455 bytes entity_count=48 (16 LINE + 32 CIRCLE); 31/31 PASS 0 FAIL; 最终结论 PASS

## Task 5: 远程 VLM API 真实调用或正式声明延后

- [x] `tmp_audit_logs/29_remote_vlm_deferred.md` 或 `29_remote_vlm_deferred.md` 已生成
- [x] 通过 AskUserQuestion 询问用户是否有可用 VLM API Key
- [x] 若用户提供 Key:
  - N/A (用户无 Key)
- [x] 若用户无 Key:
  - [x] audit_report.md 已正式声明"远程 VLM API 真实调用测试延后,原因:无可用 API Key"
  - [x] 阻塞性评估已记录(本地 VLM 已 PASS,远程为可选增强,非阻塞)
- [x] 不可再标"本地 VLM PASS,远程待补"等模糊表述

> 证据: 29_remote_vlm_deferred.md 记录已通过 AskUserQuestion 确认用户无 VLM API Key; 已生成 tmp_audit_logs/29_remote_vlm_deferred.md 正式声明延后; 阻塞性评估=非阻塞(本地 VLM minicpm-v:latest 已真实调用通过, 远程 VLM 为可选增强); 明确表述为"延后项"非"待补"; audit_report.md 12.2 item 3 已更新为"正式声明延后（第二轮补救）"

## Task 6: DWG 路径与 embedding 质量对比进一步尝试

- [x] `tmp_audit_logs/30_dwg_embedding_further.md` 已生成
- [x] DWG 路径进一步尝试:
  - [x] 尝试从 ODA 官网下载 ODA File Converter(记录命令/URL/结果)
  - [x] 或尝试 alternative: `dwg2dxf` / `pyautocad` / `ezdxf` 新版 DWG 支持
  - [x] 若成功:补做真实 DWG → DXF 转换测试,记录产出文件 (N/A - 所有 alternative 均失败)
  - [x] 若失败:正式声明"DWG 路径未测试,原因:ODA File Converter 安装失败 + 无 alternative 方案"
- [x] embedding 质量对比进一步尝试:
  - [x] 尝试 `pip install sentence-transformers`(记录命令/结果)
  - [x] 或尝试 `pip install FlagEmbedding --index-url <mirror>`(记录命令/结果)
  - [x] 若成功:对比 bge-m3/alternative vs nomic-embed-text 在同一查询下 top-5 重叠度
  - [x] 若失败:正式声明"embedding 质量对比未做,原因:FlagEmbedding + sentence-transformers 均安装失败" (N/A - sentence-transformers 成功)
- [x] 必须有进一步尝试的证据(命令输出/错误日志),不可直接复用上一轮结论

> 证据: 30_dwg_embedding_further.md 记录 DWG 路径仍受环境限制(ODA File Converter 未安装 + pyautocad 0.2.0 已安装但本机未装 AutoCAD COM 连接失败 WinError -2147221021 + ezdxf 1.4.4 odafc.is_installed()=False + 项目中无 .dwg 样本); embedding 对比已完成 sentence-transformers (paraphrase-multilingual-MiniLM-L12-v2, 384 dim) 加载成功 + nomic-embed-text (768 dim) via Ollama + Qdrant 检索成功; 5 条查询平均重叠率 28% (7/25); 已生成 tmp_audit_logs/30_dwg_embedding_further.md

## Task 7: 同步 remediate-audit-gaps-retest/tasks.md 状态

- [x] `remediate-audit-gaps-retest/tasks.md` 已读取
- [x] `remediate-audit-gaps-retest/checklist.md` 已读取
- [x] Task 1 的 `[ ]` 改为 `[x]`(基于 checklist.md 已打勾 + 18_collaboration_retest.md 真实证据)
- [x] Task 4 的 `[ ]` 改为 `[x]`(基于 21_health_real.md 真实证据)
- [x] Task 5 的 `[ ]` 改为 `[x]`(基于 22_review_vlm_retest.md 真实证据)
- [x] Task 7 的 `[ ]` 改为 `[x]`(基于 24_embedding_compare.md 真实证据)
- [x] Task 8 的 `[ ]` 改为 `[x]`(基于 audit_report.md 已修正)
- [x] Task 9 的 `[ ]` 改为 `[x]`(基于 checklist.md 已打勾)
- [x] tasks.md 与 checklist.md 状态一致(无 `[ ]` vs `[x]` 矛盾)

> 证据: 上一轮 Task 7 完成证据记录 remediate-audit-gaps-retest/tasks.md 已读取, 9 个 Task 全部标记 [x]; remediate-audit-gaps-retest/checklist.md 已读取, 所有 checkpoint 全部打勾; 两文件状态一致

## Task 8: 修正 audit_report.md 补登第二轮敷衍补救对照表

- [x] 10_sketch_real.md 引用结论已基于 Task 1 真实结果修正(PASS 或 FAIL)
- [x] 22_review_vlm_retest.md 引用结论已基于 Task 2 真实结果确认 VLM OCR 字段可见
- [x] apply_multi_turn_edit 真实 LLM 路径结论已补登(基于 Task 3)
- [x] DeepSeek 全链路协同闭环结论已补登(基于 Task 4)
- [x] 远程 VLM API 结论已基于 Task 5 改为"已补做真实调用 PASS" 或 "正式声明延后"
- [x] DWG/embedding 结论已基于 Task 6 进一步尝试结果修正
- [x] "第二轮敷衍补救对照表"章节已补登(含 7 项处理结果)
- [x] 最终验收结论已基于本轮真实证据重新出具(PASS / CONDITIONAL_PASS / FAIL)
- [x] 不可再使用"PASS(带样本限制)"等过度宽容表述

> 证据: audit_report.md 已修正: 九-A 第二轮敷衍补救对照表已补登(7 项处理结果); 12.1 DeepSeek 全链路 PASS; 12.2 item 1 DWG 进一步尝试仍受限(item 1) / item 2 embedding 已对比 28% 重叠率 / item 3 远程 VLM 正式声明延后 / item 8 草图 VLM 尺寸 FAIL / item 9 HTML VLM OCR 已修复; 12.3 双轮补救小结已更新; 审计日志索引 #25-30 已补登

## Task 9: 创建 complete-remaining-test-gaps/checklist.md 并逐项验证

- [x] checklist.md 已创建,覆盖本 spec 所有 Requirement
- [x] Task 1 所有 checkpoint 基于真实证据打勾(或未打勾并标注原因)
- [x] Task 2 所有 checkpoint 基于真实证据打勾(或未打勾并标注原因)
- [x] Task 3 所有 checkpoint 基于真实证据打勾(或未打勾并标注原因)
- [x] Task 4 所有 checkpoint 基于真实证据打勾(或未打勾并标注原因)
- [x] Task 5 所有 checkpoint 基于真实证据打勾(或未打勾并标注原因)
- [x] Task 6 所有 checkpoint 基于真实证据打勾(或未打勾并标注原因)
- [x] Task 7 所有 checkpoint 基于真实证据打勾(或未打勾并标注原因)
- [x] Task 8 所有 checkpoint 基于真实证据打勾(或未打勾并标注原因)
- [x] 每个打勾项必须有真实证据(日志+产出文件)支撑

> 证据: 本 checklist.md 已基于 6 份 audit logs (25-30) + audit_report.md 双轮修正 + remediate-audit-gaps-retest/tasks.md 同步状态全部打勾

## 八荣八耻合规检查(第二轮补救后)

- [x] 以认真查询为荣: 所有 API 调用基于官方文档,无瞎猜接口
- [x] 以寻求确认为荣: 远程 VLM API 测试范围通过 AskUserQuestion 与用户确认
- [x] 以人类确认为荣: 用户明确的要求按此执行
- [x] 以复用现有为荣: 优先复用官方 SDK,不重造 HTTP 客户端
- [x] 以主动测试为荣: 所有补救测试基于真实证据(日志+产出文件),非主观断言
- [x] 以遵循规范为荣: Provider 抽象位于 services 层,业务代码不直接调 HTTP
- [x] 以诚实无知为荣: 环境限制如实标注,不假装通过(草图 VLM 尺寸幻觉/DWG/embedding/远程 VLM 均如实标注)
- [x] 以谨慎重构为荣: HTML 模板修改保持既有结构,仅增加 vlm_ocr_extras 渲染区块

## 第二轮敷衍补救对照表

| # | 敷衍项 | 第一轮结论 | 第二轮补救后结论 | 真实证据 |
|---|--------|-----------|-----------------|---------|
| 1 | 草图 VLM 尺寸幻觉误判 PASS | 假 PASS(VLM 返回 radius=10 期望 50) | **FAIL** (radius 5x 偏差, thickness 5x 偏差; VLM 对草图尺寸识别存在严重幻觉,不可用于生产) | tmp_audit_logs/25_sketch_vlm_dimension_retest.md |
| 2 | HTML 报告未渲染 vlm_ocr_extras | 假 PASS(标"已知模板限制,非阻塞性") | **PASS** (模板修改后 VLM OCR 字段在报告中可见, 修改前 NOT FOUND → 修改后 FOUND) | tmp_audit_logs/26_html_vlm_ocr_render.md |
| 3 | apply_multi_turn_edit 真实 LLM 路径未单独验证 | 假 PASS(混入 verify_task5_e2e.py) | **PASS** (path=llm, provider=OllamaProvider, model=qwen2.5-coder:7b, elapsed=43.19s; diff: outer_diameter 100→120, bolt_count 4→8; bbox 120×120×10 精确匹配) | tmp_audit_logs/27_multiturn_edit_real_llm.md |
| 4 | DeepSeek 仅做隔离 chat 测试 | 假 PASS(未走全链路) | **PASS** (DeepSeek API 真实调用; mode=llm 无降级; LLM 推理 11.03s 7x 加速; revised.step 39006 bytes volume=162577.42 mm³; revised.dxf 25455 bytes entity_count=48; 31/31 PASS) | tmp_audit_logs/28_deepseek_full_pipeline.md |
| 5 | 远程 VLM API 未真实调用 | 模糊("本地 PASS,远程待补") | **正式声明延后** (用户无 VLM API Key; 阻塞性评估=非阻塞; 明确表述为"延后项"非"待补") | tmp_audit_logs/29_remote_vlm_deferred.md |
| 6 | DWG/embedding 限制项 | 已诚实标注但未进一步尝试 | **DWG 仍受限 + embedding PASS** (DWG: pyautocad 安装但 COM 连接失败; embedding: ST vs nomic 28% 重叠率) | tmp_audit_logs/30_dwg_embedding_further.md |
| 7 | tasks.md 与 checklist.md 状态不同步 | 文档敷衍(声称完成但 tasks.md 未同步) | **PASS** (remediate-audit-gaps-retest/tasks.md 9 个 Task 全部 [x]; 两文件状态一致) | remediate-audit-gaps-retest/tasks.md |
