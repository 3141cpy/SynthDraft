# Tasks

本任务清单按"先修复 VLM 尺寸误判 → 后 DeepSeek 全链路协同闭环"的顺序推进。所有任务必须保留可追溯证据（日志 + 产出文件 + 原始 VLM 输出）。

## Task 1: 草图 VLM 尺寸幻觉误判 PASS 修复（重测）

目标：重跑 `parse_sketch()` 真实 VLM 推理，校验 VLM 返回尺寸与草图标注期望值的偏差，基于真实证据重新出具 PASS/WARN/FAIL 结论。

- [ ] SubTask 1.1: 准备合成草图 PNG
  - 生成带孔圆盘草图：外圆 φ100（半径 50）+ 中心孔 φ20（半径 10）+ 厚度 10mm
  - 用 PIL 绘制线稿 + 文字标注（与上一轮 `10_sketch_real.md` 保持一致以便复现历史问题）
  - 落盘到 `tmp_audit_outputs/sketch_vlm_retest/sketch.png`
  - 记录期望值：`EXPECTED_OUTER_RADIUS=50.0` / `EXPECTED_INNER_RADIUS=10.0` / `EXPECTED_THICKNESS=10.0`

- [ ] SubTask 1.2: 验证 VLM 可用性
  - 调用 `is_vlm_available()` + `_pick_vlm_model()`
  - 确认 minicpm-v:latest 已拉取且 Ollama 服务可达
  - 若 VLM 不可用则明确标 FAIL 并退出（不可假装通过）

- [ ] SubTask 1.3: 安装 monkey-patch 捕获原始 VLM 输出
  - monkey-patch `OllamaProvider.chat_with_image` 捕获原始响应
  - 记录 `captured.content` / `captured.model` / `captured.raw`
  - 保存原始 VLM 输出到 `raw_vlm_output.txt`

- [ ] SubTask 1.4: 调用 parse_sketch 真实推理
  - 调用 `parse_sketch(sketch_png)`
  - 记录耗时（预期 30-120s）
  - 记录 `vlm_model` / `features` 数 / `overall_shape` / `dimensions_hint`
  - 落盘 `parse_result.json`

- [ ] SubTask 1.5: 校验尺寸偏差
  - 提取 feature[0] 的 `parameters`（radius/thickness）
  - 计算偏差比例：`max(actual/expected, expected/actual)` 倍数
  - 分类：< 10% PASS / 10%~2倍 WARN / > 2倍 FAIL
  - 记录每个尺寸的实际值、期望值、偏差比例、倍数、分类

- [ ] SubTask 1.6: bbox 格式分析
  - 调用 `_analyze_bbox_format(bbox)` 判别 `[x1,y1,x2,y2]` vs `[x,y,w,h]`
  - 调用 `_normalize_bbox(bbox)` 记录处理结果
  - 验证 `_normalize_bbox` 是否对该 bbox 误判（如将 `[x1,y1,x2,y2]` 误当 `[x,y,w,h]` 截断）

- [ ] SubTask 1.7: 输出 audit log
  - 输出 `tmp_audit_logs/27_sketch_vlm_dimension_retest.md`
  - 包含：环境信息、草图样本信息、VLM 原始输出、parse_result.json、尺寸偏差表、bbox 格式分析、最终结论
  - 最终结论必须基于真实尺寸偏差（PASS / WARN / FAIL），不可仅因"返回非空"标 PASS

## Task 4: DeepSeek 远程 LLM 全链路协同闭环验证

目标：在 DeepSeek 远程 LLM 配置下走完整协同闭环，验证端到端流程真实可用且产出真实文件。

- [ ] SubTask 4.1: 读取 .env 并设置 DeepSeek 环境变量
  - 读取 `backend/.env` 中的 DeepSeek API Key（sk-7fc861488a2742ec9e139bdfea894be1）
  - 设置 `LLM_PROVIDER=openai`
  - 设置 `OPENAI_BASE_URL=https://api.deepseek.com`
  - 设置 `OPENAI_MODEL=deepseek-chat`
  - 设置 `OPENAI_API_KEY=sk-...`
  - 设置 `OPENAI_VLM_MODEL=`（空，DeepSeek 不支持视觉模型）

- [ ] SubTask 4.2: 重置 provider cache 并验证切换
  - 调用 `get_settings.cache_clear()` 重置 settings 缓存
  - 重新赋值 `app.config.settings = get_settings()`
  - 调用 `reset_provider_cache()` 重置 provider 单例
  - 调用 `get_llm_provider()` 验证返回类为 `OpenAIProvider`
  - 调用 `provider.is_available()` 验证为 True（实测 ping）

- [ ] SubTask 4.3: 准备缺陷输入
  - 构造 3 条真实审图缺陷（与 18_collaboration_retest.md 保持一致）：
    - 缺陷 1: 尺寸标注缺失（critical, GB/T 4458.4-2003 §4.1）
    - 缺陷 2: 表面粗糙度不符合 GB/T 131（major）
    - 缺陷 3: 标题栏信息不完整（major, GB/T 18229-2023 §A.3）
  - 落盘到 `tmp_audit_outputs/deepseek_pipeline/defects.json`

- [ ] SubTask 4.4: 调用 defects_to_optimization_prompt
  - 调用 `defects_to_optimization_prompt(defects, file_hint)`
  - 验证 prompt 非空 + 含 "CadQuery" + 含规范引用 + 长度 < 4000
  - 落盘 `optimization_prompt.txt`

- [ ] SubTask 4.5: 调用 generate_cadquery_code 记录 mode + 耗时
  - 调用 `generate_cadquery_code(prompt)`
  - 验证 mode=llm（非 template 降级）
  - 验证代码含 `import cadquery`
  - 验证代码通过 `_is_valid_llm_code` 校验
  - 记录推理耗时（用于对比 Ollama）
  - 落盘 `deepseek_code.py`

- [ ] SubTask 4.6: 调用 generate_and_execute_with_fallback 走完整闭环
  - 调用 `generate_and_execute_with_fallback(prompt, out_dir, fmt="step", task_id, timeout=60)`
  - 验证沙箱执行 `exit_code=0`
  - 验证产出文件非空
  - 复制产出文件到 `revised.step`

- [ ] SubTask 4.7: 验证 revised.step volume + revised.dxf entity_count
  - 用最终代码再执行 `execute_cadquery_code(code, output_format="dxf")` 产出 revised.dxf
  - 用 pythonOCC 读取 revised.step，验证 volume > 0
  - 用 ezdxf 读取 revised.dxf，验证 entity_count > 0
  - 复制产出文件到 `revised.dxf`

- [ ] SubTask 4.8: 对比 DeepSeek vs Ollama
  - 读取 `tmp_audit_logs/13_llm_switch.md` 中 Ollama 的推理耗时与代码质量
  - 对比 DeepSeek 推理耗时 vs Ollama 推理耗时
  - 对比代码质量（是否含幻觉 API / 是否通过沙箱执行）
  - 记录对比表

- [ ] SubTask 4.9: 恢复环境
  - 清空 DeepSeek 相关环境变量（OPENAI_BASE_URL / OPENAI_MODEL / OPENAI_API_KEY / OPENAI_VLM_MODEL）
  - 设置 `LLM_PROVIDER=ollama`（恢复默认）
  - 调用 `get_settings.cache_clear()` + `reset_provider_cache()`
  - 验证 `get_llm_provider()` 返回 OllamaProvider
  - 验证 `provider.is_available()` 为 True

- [ ] SubTask 4.10: 输出 audit log
  - 输出 `tmp_audit_logs/28_deepseek_full_pipeline.md`
  - 包含：环境信息、DeepSeek 配置、缺陷输入、prompt、生成代码、沙箱执行结果、STEP/DXF 文件校验、对比表、环境恢复验证、最终结论
  - 最终结论必须基于真实文件产出（PASS / FAIL），不可仅因"单步代码生成通过"标 PASS

# Task Dependencies

- Task 1（VLM 尺寸重测）独立，可并行执行
- Task 4（DeepSeek 全链路）独立，可并行执行
- Task 1 与 Task 4 无依赖关系，可同时启动两个 sub-agent 并行处理

# 并行执行建议

- Sub-Agent A: 执行 Task 1（VLM 尺寸重测，使用本地 Ollama minicpm-v）
- Sub-Agent B: 执行 Task 4（DeepSeek 全链路，使用远程 DeepSeek API）
- 两个 Sub-Agent 互不干扰（不同 provider / 不同测试目标）
- 完成后由父 agent 汇总两个 audit log 并向用户报告

# 验证标准

- 所有 audit log 必须包含真实证据（日志 + 产出文件 + 原始 VLM/LLM 输出）
- 不可仅因"返回非空"标 PASS
- 不可仅因"单步通过"标 PASS（DeepSeek 必须走全链路）
- 环境恢复必须验证（DeepSeek 测试后回到 Ollama）
- 所有偏差/耗时/文件大小必须记录真实数值
