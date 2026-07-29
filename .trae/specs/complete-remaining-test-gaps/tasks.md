# Tasks

## 阶段一: 误判 PASS 项补救(最高优先级)

- [x] Task 1: 草图 VLM 尺寸幻觉误判 PASS 修复
  - 依赖: 无(独立可并行)
  - SubTask 1.1: 重新准备草图样本(已知尺寸: 外圆 φ100 + 中心孔 φ20 + 厚度 10mm),记录期望值
  - SubTask 1.2: 调用 `sketch_parser.parse_sketch(sketch_png)` 真实推理,记录 VLM 返回的 `parameters`
  - SubTask 1.3: 校验 VLM 返回尺寸与期望值偏差:
    - 期望 `radius=50`(外圆 φ100/2),实际若返回 `radius=10` 则偏差 5 倍 → 标 FAIL
    - 期望 `thickness=10`,实际若返回 `thickness=2` 则偏差 5 倍 → 标 FAIL
  - SubTask 1.4: 校验 bbox 格式:`[0.35, 0.4, 0.85, 0.7]` 疑似 `[x1,y1,x2,y2]` 而非 `[x,y,w,h]`
    - 验证 `_normalize_bbox` 是否正确处理该格式
    - 若 `_normalize_bbox` 未钳制越界值(0.85+0.4>1.0),定位根因
  - SubTask 1.5: 基于 1.2-1.4 真实结果,在 audit log 中明确标 PASS 或 FAIL
    - 若 VLM 尺寸偏差超 2 倍:标 FAIL,记录"VLM 对草图尺寸识别存在严重幻觉,不可用于生产"
    - 若 VLM 尺寸偏差 < 10%:标 PASS
  - SubTask 1.6: 输出 `tmp_audit_logs/25_sketch_vlm_dimension_retest.md`,含期望值/实际值/偏差比例/最终结论
  - 验证标准: 不可仅因"VLM 返回非空"即标 PASS;尺寸偏差超阈值必须标 FAIL
  - 完成证据: 真实测试标 FAIL; VLM=minicpm-v:latest, elapsed=12.43s; radius 期望 50.0 实际 10 偏差 5.00x FAIL; thickness 期望 10.0 实际 2 偏差 5.00x FAIL; bbox=[0.5,0.49,0.78,0.6] 格式判为 [x1,y1,x2,y2] 但 _normalize_bbox 按 [x,y,w,h] 处理导致语义错误; 最终结论 FAIL "VLM 对草图尺寸识别存在严重幻觉,不可用于生产"

- [x] Task 2: HTML 报告模板渲染 vlm_ocr_extras 修复
  - 依赖: 无(独立可并行)
  - SubTask 2.1: 定位 HTML 报告模板文件(可能在 `app/services/review/` 或 `app/templates/`)
  - SubTask 2.2: 读取模板源码,确认 `vlm_ocr_extras` 字段未渲染的原因
  - SubTask 2.3: 在模板中增加 "VLM OCR 识别结果" 区块,渲染所有非空的 `vlm_ocr_extras` 字段:
    - `title`(图样标题)
    - `drawing_number`(图号)
    - `material`(材料)
    - `scale`(比例)
    - `dimensions`(尺寸标注)
    - `technical_requirements`(技术要求)
    - `surface_roughness`(表面粗糙度)
    - `tolerance`(公差)
    - `vlm_model`(VLM 模型名)
  - SubTask 2.4: 重新调用 `generate_review_report()` 生成 HTML,验证 VLM OCR 字段在报告中可见
  - SubTask 2.5: 用 `grep` 或字符串搜索验证 `title="SynthDraft Sample"` 等字段值在 HTML 中出现
  - SubTask 2.6: 输出 `tmp_audit_logs/26_html_vlm_ocr_render.md`,含修改前后 HTML 截图/搜索结果对比
  - 验证标准: VLM OCR 字段必须对最终用户可见,不可标"已知模板限制,非阻塞性"即视为 PASS
  - 完成证据: 模板 app/services/review/templates/report.html.j2 已修改新增 VLM OCR 识别结果区块; 修改前 HTML 搜索 'VLM OCR'/'图样标题'/'value:合成草图样本' 均 NOT FOUND; 修改后 HTML (29757 bytes) 搜索 'VLM OCR' FOUND / '图样标题' FOUND / 'value:合成草图样本' FOUND / 'value:minicpm-v:latest' FOUND; VLM OCR 字段在报告中可见=True; 最终结论 PASS

- [x] Task 3: apply_multi_turn_edit 真实 LLM 路径独立验证
  - 依赖: 无(独立可并行)
  - SubTask 3.1: 准备原始 CadQuery 代码(从 08_generation_e2e.md 的法兰盘代码复用)
  - SubTask 3.2: 调用 `is_llm_available()` 确认 LLM 可用(记录 provider 类型)
  - SubTask 3.3: 调用 `apply_multi_turn_edit(original_code, "把外径改为120mm, 孔数改为8", history)`
  - SubTask 3.4: 记录:
    - LLM 模型名 + provider 类型
    - 推理耗时
    - 返回的 `new_code` 是否与 `original_code` 不同
    - 修改前后代码 diff(具体哪些行变化)
    - 是否走 LLM 路径(非正则降级)
  - SubTask 3.5: 若 LLM 路径生效:验证 `new_code` 中 `outer_diameter=120.0` + `bolt_count=8`
  - SubTask 3.6: 若 LLM 路径未生效(走正则降级):记录降级原因,验证正则替换结果正确
  - SubTask 3.7: 沙箱执行 `new_code`,验证产出 STEP 文件 volume 与新参数匹配(外径 120 → bbox 120×120×10)
  - SubTask 3.8: 输出 `tmp_audit_logs/27_multiturn_edit_real_llm.md`
  - 验证标准: 必须明确记录走 LLM 还是正则路径,不可混淆;若走 LLM 需验证代码实际变更
  - 完成证据: 真实路径=llm (provider.chat 调用, _regex_edit 未调用), provider=OllamaProvider, model=qwen2.5-coder:7b, elapsed=43.19s; diff: outer_diameter 100→120, bolt_count 4→8 (仅 2 行变化); 沙箱 exit_code=0, STEP bbox=(-60,-60,0,60,60,10) → dx=120, dy=120, dz=10 精确匹配; 总体 PASS

- [x] Task 4: DeepSeek 远程 LLM 全链路协同闭环验证
  - 依赖: 无(独立可并行)
  - SubTask 4.1: 设置环境变量 `LLM_PROVIDER=openai` + `OPENAI_BASE_URL=https://api.deepseek.com` + `OPENAI_MODEL=deepseek-chat` + `OPENAI_API_KEY=sk-7fc...`(从 .env 读取)
  - SubTask 4.2: 输入 3 条真实审图缺陷(尺寸/粗糙度/标题栏,与 18_collaboration_retest.md 一致)
  - SubTask 4.3: 调用 `defects_to_optimization_prompt()` 生成 prompt
  - SubTask 4.4: 调用 `generate_cadquery_code(prompt)` 记录 mode(llm/template) + LLM 推理耗时
  - SubTask 4.5: 调用 `generate_and_execute_with_fallback()` 走完整协同闭环(含沙箱失败降级)
  - SubTask 4.6: 验证产出真实 `revised.step`(volume > 0) + `revised.dxf`(entity_count > 0)
  - SubTask 4.7: 对比 DeepSeek vs Ollama 在同一 prompt 下的:
    - LLM 推理耗时(DeepSeek 应 < 5s, Ollama 105s)
    - 生成代码质量(参数解析正确性)
    - 沙箱执行成功率
    - 是否触发降级
  - SubTask 4.8: 输出 `tmp_audit_logs/28_deepseek_full_pipeline.md`
  - 验证标准: DeepSeek 必须走完整协同闭环并产出真实文件,不可仅因 13_llm_switch.md 隔离 chat 通过即认为全链路可用
  - 完成证据: DeepSeek API 真实调用 PASS; provider=OpenAIProvider is_available=True; prompt=748 chars; mode=llm (无降级); LLM 推理 11.03s vs Ollama 78.50s (7x 加速); 代码长度 2509 chars 含 import cadquery; 沙箱执行 step success exit_code=0 产出 2 文件; 沙箱执行 dxf success exit_code=0 产出 3 文件; revised.step 39006 bytes volume=162577.42 mm³ bbox=(-50,-50,0)→(50,50,30) (thickness=30 正确修复 critical 缺陷"缺失高度尺寸 30mm"); revised.dxf 25455 bytes entity_count=48 (16 LINE + 32 CIRCLE); 31/31 PASS 0 FAIL; 最终结论 PASS

## 阶段二: 已诚实标注项进一步处理

- [x] Task 5: 远程 VLM API 真实调用或正式声明延后
  - 依赖: 无(独立可并行)
  - SubTask 5.1: 通过 AskUserQuestion 询问用户是否有可用 VLM API Key(OpenAI gpt-4o / 通义千问 VL / 其他)
  - SubTask 5.2: 若用户提供 Key:
    - 设置 `LLM_PROVIDER` + `OPENAI_VLM_MODEL` 或对应配置
    - 调用 `provider.chat_with_image()` 真实远程调用,记录响应内容 + 耗时
    - 调用 `vlm_detect_regions()` 验证返回语义正确区域
    - 输出 `tmp_audit_logs/29_remote_vlm_real.md`
  - SubTask 5.3: 若用户无 Key:
    - 在 audit_report.md 中正式声明"远程 VLM API 真实调用测试延后,原因:无可用 API Key"
    - 评估阻塞性:本地 VLM 已 PASS,远程 VLM 为可选增强,非阻塞
    - 输出 `tmp_audit_logs/29_remote_vlm_deferred.md`
  - 验证标准: 不可再标"本地 VLM PASS,远程待补"等模糊表述——需明确为延后项 + 阻塞性评估
  - 完成证据: 已通过 AskUserQuestion 确认用户无 VLM API Key; 已生成 tmp_audit_logs/29_remote_vlm_deferred.md 正式声明延后; 阻塞性评估=非阻塞(本地 VLM minicpm-v:latest 已真实调用通过, 远程 VLM 为可选增强); 明确表述为"延后项"非"待补"

- [x] Task 6: DWG 路径与 embedding 质量对比进一步尝试
  - 依赖: 无(独立可并行)
  - SubTask 6.1: DWG 路径进一步尝试:
    - 尝试从 ODA 官网下载 ODA File Converter 安装包(若网络可达)
    - 或尝试 alternative: `dwg2dxf` 命令(LibreCAD)/ `pyautocad` / `ezdxf` 新版 DWG 支持
    - 若成功:补做真实 DWG → DXF 转换测试
    - 若失败:正式声明"DWG 路径未测试,原因:ODA File Converter 安装失败 + 无 alternative 方案"
  - SubTask 6.2: embedding 质量对比进一步尝试:
    - 尝试 `pip install sentence-transformers`(若成功则用 `paraphrase-multilingual-MiniLM-L12-v2` 对比)
    - 或尝试 `pip install FlagEmbedding --index-url <mirror>`(若 HF mirror 可达)
    - 若成功:对比 bge-m3/alternative vs nomic-embed-text 在同一查询下 top-5 重叠度
    - 若失败:正式声明"embedding 质量对比未做,原因:FlagEmbedding + sentence-transformers 均安装失败"
  - SubTask 6.3: 输出 `tmp_audit_logs/30_dwg_embedding_further.md`
  - 验证标准: 必须有进一步尝试的证据(命令输出/错误日志),不可直接复用上一轮结论
  - 完成证据: DWG 路径仍受环境限制(ODA File Converter 未安装 + pyautocad 需 AutoCAD + ezdxf 不支持 DWG); embedding 对比已完成 sentence-transformers (paraphrase-multilingual-MiniLM-L12-v2, 384 dim) 加载成功 + nomic-embed-text (768 dim) via Ollama + Qdrant 检索成功; 5 条查询平均重叠率 28% (7/25); 已生成 tmp_audit_logs/30_dwg_embedding_further.md

## 阶段三: 文档同步与最终修正

- [x] Task 7: 同步 remediate-audit-gaps-retest/tasks.md 状态
  - 依赖: 无(独立可并行)
  - SubTask 7.1: 读取 `remediate-audit-gaps-retest/tasks.md` 与 `checklist.md`
  - SubTask 7.2: 把 Task 1/4/5/7/8/9 的 `[ ]` 改为 `[x]`(基于 checklist.md 已打勾且有真实证据)
  - SubTask 7.3: 验证两个文件状态一致
  - 验证标准: tasks.md 与 checklist.md 不可出现状态不一致
  - 完成证据: remediate-audit-gaps-retest/tasks.md 已读取, 9 个 Task 全部标记 [x]; remediate-audit-gaps-retest/checklist.md 已读取, 所有 checkpoint 全部打勾; 两文件状态一致

- [x] Task 8: 修正 audit_report.md 补登第二轮敷衍补救对照表
  - 依赖: Task 1-6 全部完成
  - SubTask 8.1: 修正 10_sketch_real.md 引用结论:基于 Task 1 真实结果改为 PASS 或 FAIL
  - SubTask 8.2: 修正 22_review_vlm_retest.md 引用结论:基于 Task 2 真实结果确认 VLM OCR 字段可见
  - SubTask 8.3: 补登 apply_multi_turn_edit 真实 LLM 路径结论(基于 Task 3)
  - SubTask 8.4: 补登 DeepSeek 全链路协同闭环结论(基于 Task 4)
  - SubTask 8.5: 修正远程 VLM API 结论:基于 Task 5 改为"已补做真实调用 PASS" 或 "正式声明延后"
  - SubTask 8.6: 修正 DWG/embedding 结论:基于 Task 6 进一步尝试结果
  - SubTask 8.7: 补登"第二轮敷衍补救对照表"章节(含 7 项处理结果)
  - SubTask 8.8: 修正最终验收结论:基于本轮真实证据重新出具 PASS / CONDITIONAL_PASS / FAIL
  - 验证标准: 不可再使用"PASS(带样本限制)"等过度宽容表述
  - 完成证据: audit_report.md 已修正: 九-A 第二轮敷衍补救对照表已补登(7 项处理结果); 12.1 DeepSeek 全链路 PASS; 12.2 item 1 DWG 进一步尝试仍受限(pyautocad COM 失败) / item 2 embedding 已对比 28% 重叠率 / item 3 远程 VLM 正式声明延后 / item 8 草图 VLM 尺寸 FAIL / item 9 HTML VLM OCR 已修复; 12.3 双轮补救小结已更新; 审计日志索引 #25-30 已补登

- [x] Task 9: 创建 complete-remaining-test-gaps/checklist.md 并逐项验证
  - 依赖: Task 8 完成
  - SubTask 9.1: 创建 checklist.md 覆盖本 spec 所有 Requirement
  - SubTask 9.2: 逐项验证 checkpoint,基于真实证据打勾
  - SubTask 9.3: 未真正通过的 checkpoint 必须改为未打勾并标注原因
  - 验证标准: 每个打勾项必须有真实证据(日志+产出文件)支撑
  - 完成证据: checklist.md 已重写为全部 [x] 状态; 每个 checkpoint 附真实证据引用(25-30 audit logs); 八荣八耻合规检查 8 项全打勾; 第二轮敷衍补救对照表 7 项全部填实

## Task Dependencies

- Task 1 独立(可并行)
- Task 2 独立(可并行)
- Task 3 独立(可并行)
- Task 4 独立(可并行)
- Task 5 独立(可并行)
- Task 6 独立(可并行)
- Task 7 独立(可并行)
- Task 8 依赖 Task 1-6 全部完成
- Task 9 依赖 Task 8 完成

## 并行执行建议

阶段一(Task 1-4)可并行启动 3 个 sub-agent:
- Sub-Agent A: Task 1(草图 VLM 尺寸) + Task 4(DeepSeek 全链路)
- Sub-Agent B: Task 2(HTML 报告渲染) + Task 3(多轮修改 LLM)
- Sub-Agent C: Task 5(远程 VLM) + Task 6(DWG/embedding) + Task 7(tasks.md 同步)

阶段二(Task 8-9)必须在阶段一全部完成后串行执行。
