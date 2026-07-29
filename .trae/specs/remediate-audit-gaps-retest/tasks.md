# Tasks

## 阶段一: 真实证据补救测试

- [x] Task 1: 协同闭环沙箱执行真实文件产出验证(最高优先级)
  - 依赖: 修复后的 `code_generator._is_valid_llm_code` 已合入(已确认)
  - SubTask 1.1: 准备真实审图缺陷输入(3 条缺陷: 尺寸/粗糙度/标题栏)
  - SubTask 1.2: 调用 `defects_to_optimization_prompt()` 生成 prompt
  - SubTask 1.3: 调用 `generate_cadquery_code(prompt)` 触发 LLM 路径,记录 mode(llm/template)
    - 若 mode=llm: 验证 LLM 输出代码通过 `_is_valid_llm_code` 校验
    - 若 mode=template: 验证 LLM 幻觉被拦截并降级
  - SubTask 1.4: 调用 `execute_cadquery_code()` 沙箱执行,验证 exit_code=0, files 非空
  - SubTask 1.5: 验证产出 `revised.step` + `revised.dxf` 真实文件,STEP 体积非零,DXF 实体数 > 0
  - SubTask 1.6: 调用 `generate_diff_report()` 基于真实修订后文件(非模拟数据)生成对比报告
  - SubTask 1.7: 输出 `tmp_audit_logs/18_collaboration_retest.md`,记录 mode/exit_code/file_size/volume/diff_report
  - 验证标准: 必须产出真实 revised.step / revised.dxf,不可用模拟数据替代

- [x] Task 2: VLM 区域检测真实工程图样本重测
  - SubTask 2.1: 寻找或生成真实工程图 PNG 样本(必须含标题栏/标注区/视图区/明细栏四类区域)
    - 优先从 `tests/samples/` 或 `tmp_audit_outputs/cad/` 渲染真实 DXF 为 PNG
    - 备选: 用 ezdxf 渲染 `sample.dxf` 为 PNG(dpi=150)
  - SubTask 2.2: 调用 `vlm_detect_regions(real_png)` 真实推理,记录耗时与返回区域列表
  - SubTask 2.3: 验证返回区域名包含至少 2 个语义正确类别(如 title_block / dimension_area / view_area / parts_list)
  - SubTask 2.4: 调用 `vlm_ocr_extract(real_png, regions)` 真实 OCR,验证返回字段
  - SubTask 2.5: 验证 OCR 字段包含至少 1 个语义正确工程图字段(图号 / 比例 / 材料 / 日期)
  - SubTask 2.6: 输出 `tmp_audit_logs/19_vlm_region_retest.md` + 真实样本 PNG + raw_detect_regions.txt + raw_ocr_extract.txt
  - 验证标准: 不可用登机牌等非工程图样本;区域名与 OCR 字段必须语义正确

- [x] Task 3: 装配体 interference 修复验证
  - SubTask 3.1: 重跑 `verify_task11_e2e.py` 中装配体相关阶段,记录 `validate_assembly.is_valid` 与 interference 维度状态
  - SubTask 3.2: 构造 concentric mate 场景(bolt M8 + flange_plate φ100),验证 `_has_concentric_axis_hole_exception` 触发豁免
  - SubTask 3.3: 验证 `validate_assembly.is_valid=True`(或 interference 维度 PASS)
  - SubTask 3.4: 构造非共线 Port 场景(如 port_a.axis_dir=[0,1,0] / port_b.axis_dir=[0,0,1])验证非平凡旋转变换分支(可选,若构造困难可标注)
  - SubTask 3.5: 输出 `tmp_audit_logs/20_assembly_retest.md`
  - 验证标准: concentric mate 不再被误报为干涉;若构造非共线场景困难需明确标注

- [x] Task 4: 真实 FastAPI 服务健康检查验证
  - SubTask 4.1: 用 uvicorn 启动 FastAPI 服务(`uvicorn app.main:app --host 127.0.0.1 --port 18080`),后台运行
  - SubTask 4.2: 用 curl 或 requests 调用 `GET http://127.0.0.1:18080/api/v1/healthz`,记录 status_code 与响应 JSON
  - SubTask 4.3: 验证响应包含 `llm_provider="ollama"` / `llm_available=True` / `vlm_available=True` 字段
  - SubTask 4.4: 验证 asyncio.to_thread 在真实 ASGI 环境下正常调度(响应时间 < 6s,无超时)
  - SubTask 4.5: 切换 LLM_PROVIDER=openai 重启服务,验证字段值变化
  - SubTask 4.6: 关闭服务,输出 `tmp_audit_logs/21_health_real.md`
  - 验证标准: 必须用真实 uvicorn 服务,不可用 TestClient 替代

- [x] Task 5: 审图 E2E 真实 VLM 路径补测
  - 依赖: Task 2 完成(真实工程图样本可用)
  - SubTask 5.1: 用 Task 2 的真实工程图样本,调用 `prepare_review_context(real_dxf_or_png)`
  - SubTask 5.2: 调用 `fuse_to_semantic_model()` 构建三层语义模型,验证 VLM OCR 字段真实填充(非空)
  - SubTask 5.3: 调用 `judge_with_fallback(use_llm=True)` 触发 LLM 路径,验证 `judge_mode=llm`
  - SubTask 5.4: 调用 `generate_review_report()` 产出真实 HTML 报告,验证 VLM OCR 字段在报告中可见
  - SubTask 5.5: 输出 `tmp_audit_logs/22_review_vlm_retest.md`
  - 验证标准: VLM OCR 字段必须真实填充到语义模型,不可为空

- [x] Task 6: CAD DWG 路径测试或明确标注
  - SubTask 6.1: 检测 ODA File Converter 是否可安装(Windows 安装包)
  - SubTask 6.2: 若可安装,安装后调用 `dwg_converter.convert_dwg_to_dxf()` 测试真实 DWG 文件
  - SubTask 6.3: 若不可得,在 audit_report.md 中明确标注"DWG 路径未测试(ODA File Converter 未安装)"而非 CONDITIONAL_PASS
  - SubTask 6.4: 输出 `tmp_audit_logs/23_dwg_path.md`
  - 验证标准: 不可跳过 DWG 路径或用"CONDITIONAL_PASS"模糊处理

- [x] Task 7: KB RAG embedding 质量对比(可选,优先级低)
  - SubTask 7.1: 尝试 `pip install FlagEmbedding`(若失败则标注)
  - SubTask 7.2: 若安装成功,对比 bge-m3 vs nomic-embed-text 在同一查询下的 top-5 结果重叠度
  - SubTask 7.3: 输出 `tmp_audit_logs/24_embedding_compare.md`
  - 验证标准: 若安装失败需明确标注降级路径未对比质量

## 阶段二: audit_report 真实证据修正

- [x] Task 8: 修正 audit_report.md 所有"假 PASS"
  - 依赖: Task 1-7 完成
  - SubTask 8.1: 修正 SubTask 4.4 协同闭环结论: 基于 Task 1 真实结果改为 PASS / CONDITIONAL_PASS / FAIL
  - SubTask 8.2: 修正 SubTask 4.1 VLM 区域检测结论: 基于 Task 2 真实结果改为 PASS / CONDITIONAL_PASS / FAIL
  - SubTask 8.3: 修正 SubTask 4.3 装配体结论: 基于 Task 3 真实结果确认 interference 修复生效
  - SubTask 8.4: 修正 SubTask 5.3 健康检查结论: 基于 Task 4 真实结果确认 uvicorn 路径通过
  - SubTask 8.5: 修正 SubTask 2.3 审图 E2E 结论: 基于 Task 5 真实结果改为 PASS(若 VLM 路径通过)
  - SubTask 8.6: 修正 Task 5.2 VLM 切换验证结论: 把"远程视觉 VLM 切换验证 PASS"改为"本地 VLM 验证 PASS,远程 VLM API 测试待补(无 Key)"
  - SubTask 8.7: 修正 SubTask 2.1 CAD 解析结论: 基于 Task 6 明确标注 DWG 路径未测试
  - SubTask 8.8: 补登"敷衍问题清单与补救结果对照表"章节
  - SubTask 8.9: 修正最终验收结论: 基于真实证据重新出具 PASS / CONDITIONAL_PASS / FAIL
  - 验证标准: 不可再使用"PASS(带样本限制)"等过度宽容表述

- [x] Task 9: 修正 checklist.md 所有打勾项
  - 依赖: Task 8 完成
  - SubTask 9.1: 重新核对所有 checkpoint,基于真实证据重新打勾
  - SubTask 9.2: 未真正通过的 checkpoint 必须改为未打勾并标注原因
  - SubTask 9.3: 补登新 checkpoint 覆盖敷衍项补救
  - 验证标准: 每个打勾项必须有真实证据(日志+产出文件)支撑

## Task Dependencies

- Task 1 独立(可并行)
- Task 2 独立(可并行)
- Task 3 独立(可并行)
- Task 4 独立(可并行)
- Task 5 依赖 Task 2(需真实工程图样本)
- Task 6 独立(可并行)
- Task 7 独立(可并行,优先级低)
- Task 8 依赖 Task 1-7 全部完成
- Task 9 依赖 Task 8 完成

## 并行执行建议

阶段一(Task 1-7)可并行启动 3 个 sub-agent:
- Sub-Agent A: Task 1(协同闭环) + Task 5(审图 VLM,依赖 Task 2 样本)
- Sub-Agent B: Task 2(VLM 区域检测) + Task 3(装配体) + Task 6(DWG)
- Sub-Agent C: Task 4(健康检查) + Task 7(embedding 对比)

阶段二(Task 8-9)必须在阶段一全部完成后串行执行。
