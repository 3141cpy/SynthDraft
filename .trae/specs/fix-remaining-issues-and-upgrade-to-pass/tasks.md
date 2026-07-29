# Tasks

本任务清单对照 spec.md 拆解 SynthDraft 剩余 8 项非阻塞问题的修复工作。任务按"先修复 → 再重新测试 → 最后更新报告"的串行依赖链组织。

## 阶段一:依赖项与服务状态确认(前置门控)

- [x] Task 1: 依赖项与服务状态确认
  - [x] SubTask 1.1: 验证 Docker 服务运行中(postgres/redis/qdrant/ollama healthy),若未运行主动启动
  - [x] SubTask 1.2: 验证 FastAPI 服务运行中(http://localhost:8000/healthz 返回 200),若未运行主动启动
  - [x] SubTask 1.3: 验证 Celery worker 运行中(`celery -A app.celery_app inspect ping` 返回 pong),若未运行主动启动(监听全部 7 队列)
  - [x] SubTask 1.4: 验证 SolidWorks 2025 可达(D:\Program Files\SolidWorks Corp\SOLIDWORKS\ 存在)
  - [x] SubTask 1.5: 验证 Python venv 与关键包(cadquery / pywin32 / pydantic / httpx / Pillow)已安装,缺失立即 `pip install`

## 阶段二:SolidWorks Worker 剩余问题修复(SW-04/SW-05/SW-06)

- [x] Task 2: SW-04 CadQuery STEP 导入兼容性修复
  - [x] SubTask 2.1: 阅读现有 `writer.py:generate_sldprt_from_cadquery` 与 `_run_cadquery_to_step` 实现,确认失败根因
  - [x] SubTask 2.2: 在 `generate_sldprt_from_cadquery` 中增加 STEP 导入失败降级逻辑:OpenDoc6 失败时,先尝试 `swOpenDocOptions_Silent | swOpenDocOptions_OverrideDefaultTemplate` 标志组合
  - [x] SubTask 2.3: 若仍失败,尝试调用 `ISldWorks::RepairDocument` API(SolidWorks 2024+,通过 Dispatch 探测可用性)
  - [x] SubTask 2.4: 若所有 STEP 导入尝试均失败,降级到特征重建路径(从 CadQuery 代码提取基础特征或返回 fallback 信号),在 warnings 中标注 `path_type=FALLBACK-PATH`
  - [x] SubTask 2.5: 编写 `_test_sw_step_import_fix.py` 测试脚本,验证修复后 CadQuery→STEP→SLDPRT 路径要么成功,要么明确降级(无 EXCEPTION 中断)
  - [x] SubTask 2.6: 记录测试结果到 `backend/tmp_audit_logs/sw04_step_import_fix.md`

- [x] Task 3: SW-05 装配体生成测试样本与用例补充
  - [x] SubTask 3.1: 阅读 `writer.py:generate_sldasm_from_components` 实现,确认 SWComponent/SWMate schema
  - [x] SubTask 3.2: 通过 `generate_sldprt_from_features` 生成 2 个测试组件文件(cube.SLDPRT 与 shaft.SLDPRT),验证文件存在且 size > 10KB
  - [x] SubTask 3.3: 构造 SWComponent 列表(2 个组件,含 path/position/orientation)与 SWMate 列表(2 个配合:coincident + concentric)
  - [x] SubTask 3.4: 调用 `generate_sldasm_from_components(session, components, mates, output_path)`,验证生成的 SLDASM 文件存在且 size > 0
  - [x] SubTask 3.5: 编写 `_test_sw_writer_assembly.py` 测试脚本,覆盖组件插入与配合添加
  - [x] SubTask 3.6: 记录测试结果到 `backend/tmp_audit_logs/sw05_assembly_generation.md`

- [x] Task 4: SW-06 含真实配合的装配体样本与读取验证
  - [x] SubTask 4.1: 复用 Task 3 生成的 SLDASM 样本(含 2 个组件 + 2 个配合)
  - [x] SubTask 4.2: 调用 `read_sldasm(session, sample_path)`,验证返回结果中 `mates` 数组非空
  - [x] SubTask 4.3: 验证每个 mate 含 `name` / `mate_type` / `component_a` / `component_b` 字段
  - [x] SubTask 4.4: 验证路径 1(GetMates)或路径 2(特征树遍历)至少一条生效,标注路径类型
  - [x] SubTask 4.5: 编写 `_test_sw_reader_mates.py` 测试脚本
  - [x] SubTask 4.6: 记录测试结果到 `backend/tmp_audit_logs/sw06_mates_extraction.md`

## 阶段三:VLM 模块改进(VLM-02/VLM-03/VLM-04)

- [x] Task 5: VLM-02 图像大小限制检查
  - [x] SubTask 5.1: 在 `vlm_ocr.py:_encode_image` 中增加图像尺寸检查(Pillow `Image.open().size`),阈值 4096×4096
  - [x] SubTask 5.2: 增加文件大小检查(Path.stat().st_size),阈值 10MB
  - [x] SubTask 5.3: 超阈值时调用 Pillow `Image.thumbnail((4096, 4096))` 降采样,保存到 BytesIO 后 base64 编码
  - [x] SubTask 5.4: log.warning `review.vlm.image_too_large_resized` 记录原始尺寸与降采样后尺寸
  - [x] SubTask 5.5: 编写 `_test_vlm_image_size.py` 测试脚本,验证大图降采样与小图直通
  - [x] SubTask 5.6: 记录测试结果到 `backend/tmp_audit_logs/vlm02_image_size_check.md`

- [x] Task 6: VLM-03 VLM 调用重试机制
  - [x] SubTask 6.1: 定义 `_vlm_call_with_retry(provider, messages, image_b64, **kwargs)` 辅助函数,实现指数退避重试(1s/2s/4s,最多 3 次)
  - [x] SubTask 6.2: 仅对可重试异常重试(httpx.ConnectError / httpx.ReadTimeout / HTTPStatusError 5xx),4xx 错误不重试
  - [x] SubTask 6.3: 将 `vlm_detect_regions` / `vlm_ocr_extract` / `sketch_parser.parse_sketch` 中的 `provider.chat_with_image` 调用替换为 `_vlm_call_with_retry`
  - [x] SubTask 6.4: 每次重试 log.warning `review.vlm.retry` 记录 attempt / error / backoff_sec
  - [x] SubTask 6.5: 编写 `_test_vlm_retry.py` 测试脚本,模拟 VLM 失败场景验证重试逻辑
  - [x] SubTask 6.6: 记录测试结果到 `backend/tmp_audit_logs/vlm03_retry_mechanism.md`

- [x] Task 7: VLM-04 Pydantic 类型校验结构化输出
  - [x] SubTask 7.1: 在 `app/schemas/vlm.py`(若不存在则创建)中定义 `VLMRegionItem` / `VLMRegionList` / `VLMOCRResult` Pydantic 模型
  - [x] SubTask 7.2: 在 `vlm_ocr.py:vlm_detect_regions` 中,对 `_parse_json_array_from_text` 返回的列表逐项 `VLMRegionItem.model_validate`,无效项 log.warning 后丢弃
  - [x] SubTask 7.3: 在 `vlm_ocr.py:vlm_ocr_extract` 中,对 `_parse_json_object_from_text` 返回的 dict `VLMOCRResult.model_validate`,无效字段 log.warning 后丢弃或返回空 dict
  - [x] SubTask 7.4: 编写 `_test_vlm_schema.py` 测试脚本,验证符合 schema 的输出通过、不符合的字段丢弃
  - [x] SubTask 7.5: 记录测试结果到 `backend/tmp_audit_logs/vlm04_schema_validation.md`

## 阶段四:后端 API 剩余问题修复(P-03/P-05)

- [x] Task 8: P-03 LLM 流式终止标记统一为 [DONE]
  - [x] SubTask 8.1: 修改 `llm.py:event_gen` 函数,在 `{"done": true}` / `{"cancelled": true}` / `{"error": ...}` 事件后追加 `yield "data: [DONE]\n\n"` 行
  - [x] SubTask 8.2: 更新端点 docstring,说明终止标记为 `[DONE]`(OpenAI 风格)+ `{"done": true}`(JSON 对象,向后兼容)
  - [x] SubTask 8.3: 编写 `_test_llm_stream_done.py` 测试脚本,curl 调用 `/api/v1/llm/stream` 验证末尾含 `data: [DONE]`
  - [x] SubTask 8.4: 记录测试结果到 `backend/tmp_audit_logs/p03_llm_done_marker.md`

- [x] Task 9: P-05 可观测性告警规则补充
  - [x] SubTask 9.1: 在 `alerts.py:evaluate_queue_alerts` 中新增 `task_stale_reserved` 告警规则:某队列 `reserved > 0` 且 `active == 0` 且 `worker_count > 0` 时触发,level=critical
  - [x] SubTask 9.2: 更新 `alerts.py:self_test`,新增 `task_stale_reserved` 测试场景
  - [x] SubTask 9.3: 编写 `_test_alert_stale_reserved.py` 测试脚本,验证规则触发与不触发场景
  - [x] SubTask 9.4: 记录测试结果到 `backend/tmp_audit_logs/p05_stale_reserved_alert.md`

## 阶段五:修复后端到端重新验证

- [x] Task 10: 修复后端到端重新验证
  - [x] SubTask 10.1: 重启 FastAPI 与 Celery worker 加载修复后的代码
  - [x] SubTask 10.2: 重测 `/api/v1/llm/stream`,验证末尾含 `data: [DONE]`
  - [x] SubTask 10.3: 重测 `/api/v1/observability/queue-status`,验证 `task_stale_reserved` 告警规则可触发(模拟场景)
  - [x] SubTask 10.4: 重测 SolidWorks Worker 路径 A(CadQuery→STEP→SLDPRT),验证降级逻辑生效
  - [x] SubTask 10.5: 重测装配体生成与读取,验证 SW-05/SW-06 修复
  - [x] SubTask 10.6: 重测 VLM 调用路径(草图解析),验证 VLM-02/03/04 不影响正常路径
  - [x] SubTask 10.7: 汇总重测结果到 `backend/tmp_audit_logs/remaining_issues_fix_report.md`

## 阶段六:更新最终交付报告与原 spec checklist

- [x] Task 11: 更新最终交付报告
  - [x] SubTask 11.1: 更新 `final_acceptance_report.md` 第六章问题清单,将已修复项移到 6.1 已修复节,附修复方案与重测证据
  - [x] SubTask 11.2: 更新第七章环境限制清单(若有变化)
  - [x] SubTask 11.3: 更新第九章结论:若所有可修复项已修复,升级为 PASS;否则保持 CONDITIONAL_PASS 并说明剩余项
  - [x] SubTask 11.4: 更新"特别提醒用户"章节,移除已修复项的提醒

- [x] Task 12: 更新 complete-final-acceptance-and-fix spec 的 checklist 与 tasks
  - [x] SubTask 12.1: 勾选 `complete-final-acceptance-and-fix/checklist.md` 中已通过项(阶段一至阶段八全部 `[x]`)
  - [x] SubTask 12.2: 勾选 `complete-final-acceptance-and-fix/tasks.md` 中已完成 Task(SubTask 全部 `[x]`)
  - [x] SubTask 12.3: 在 `complete-final-acceptance-and-fix/spec.md` 末尾追加"后续修复"链接,指向本 spec

# Task Dependencies

- Task 1(服务确认)→ 所有后续 Task(需服务运行)
- Task 2/3/4(SolidWorks 修复)可并行,但 Task 4 依赖 Task 3 生成的样本
- Task 5/6/7(VLM 改进)可并行
- Task 8/9(后端 API 修复)可并行
- Task 10(端到端重测)依赖 Task 2-9 全部完成
- Task 11(报告更新)依赖 Task 10 完成
- Task 12(spec checklist 更新)依赖 Task 11 完成

# 并行化建议

- 第一波(并行):Task 1(服务确认)
- 第二波(并行):Task 2(SW-04) || Task 3(SW-05) || Task 5(VLM-02) || Task 6(VLM-03) || Task 7(VLM-04) || Task 8(P-03) || Task 9(P-05)
- 第三波(串行):Task 4(SW-06,依赖 Task 3 样本)
- 第四波(串行):Task 10(端到端重测)→ Task 11(报告更新)→ Task 12(spec 更新)

# 阶段门控

1. Task 1 服务确认必须实测,不得仅理论分析
2. Task 2-9 修复必须遵循"谨慎重构"原则,最小改动,不破坏架构
3. Task 10 端到端重测必须真实 HTTP/COM 调用,不得仅单元测试
4. Task 11 报告更新必须实事求是,不可将未修复项标为已修复
5. Task 12 checklist 勾选必须基于真实测试证据,不得敷衍
