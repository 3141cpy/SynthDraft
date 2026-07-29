# Checklist

本清单用于系统性验证 `retest-vlm-dimension-and-deepseek-collaboration` spec 中所有 Requirement 是否落实。每项必须基于实际证据（日志/产出文件/原始输出）打勾，不可主观断言。

## Task 1: 草图 VLM 尺寸幻觉误判 PASS 修复（重测）

- [ ] `tmp_audit_logs/27_sketch_vlm_dimension_retest.md` 已生成
- [ ] 合成草图 PNG 已落盘（外圆 φ100 + 中心孔 φ20 + 厚度 10mm）
- [ ] 期望值已记录（EXPECTED_OUTER_RADIUS=50 / EXPECTED_INNER_RADIUS=10 / EXPECTED_THICKNESS=10）
- [ ] VLM 可用性已验证（is_vlm_available()=True, _pick_vlm_model()=minicpm-v:latest）
- [ ] monkey-patch 已安装捕获原始 VLM 输出
- [ ] `parse_sketch()` 真实推理已执行（记录耗时）
- [ ] `parse_result.json` 已落盘
- [ ] 原始 VLM 输出 `raw_vlm_output.txt` 已落盘
- [ ] feature[0].parameters 已提取（radius / thickness 实际值）
- [ ] 尺寸偏差已计算（max(actual/expected, expected/actual) 倍数）
- [ ] 偏差分类已记录（PASS < 10% / WARN 10%~2倍 / FAIL > 2倍）
- [ ] bbox 格式已分析（[x1,y1,x2,y2] vs [x,y,w,h]）
- [ ] `_normalize_bbox` 处理结果已记录
- [ ] 最终结论基于真实尺寸偏差（不可仅因"返回非空"标 PASS）
- [ ] 旧 `10_sketch_real.md` 的 PASS 判据不充分已在 27 号文档中标注

## Task 4: DeepSeek 远程 LLM 全链路协同闭环验证

- [ ] `tmp_audit_logs/28_deepseek_full_pipeline.md` 已生成
- [ ] DeepSeek API Key 已从 .env 读取（sk-7fc861488a2742ec9e139bdfea894be1）
- [ ] 环境变量已设置（LLM_PROVIDER=openai / OPENAI_BASE_URL / OPENAI_MODEL / OPENAI_API_KEY）
- [ ] OPENAI_VLM_MODEL 设置为空（DeepSeek 不支持视觉模型）
- [ ] `get_settings.cache_clear()` 已调用
- [ ] `app.config.settings` 已重新赋值
- [ ] `reset_provider_cache()` 已调用
- [ ] `get_llm_provider()` 返回类为 `OpenAIProvider`
- [ ] `provider.is_available()` 为 True
- [ ] 3 条真实审图缺陷已构造（尺寸/粗糙度/标题栏）
- [ ] `defects.json` 已落盘
- [ ] `defects_to_optimization_prompt()` 返回非空 prompt
- [ ] prompt 含 "CadQuery"
- [ ] prompt 含至少 1 条规范引用
- [ ] prompt 长度 < 4000 字符
- [ ] `optimization_prompt.txt` 已落盘
- [ ] `generate_cadquery_code(prompt)` 返回 mode=llm（非 template 降级）
- [ ] 代码含 `import cadquery`
- [ ] 代码通过 `_is_valid_llm_code` 校验
- [ ] 推理耗时已记录
- [ ] `deepseek_code.py` 已落盘
- [ ] `generate_and_execute_with_fallback(fmt="step")` 已调用
- [ ] 沙箱执行 exit_code=0
- [ ] 产出文件非空
- [ ] `revised.step` 已复制到产出目录
- [ ] 用最终代码再执行 `execute_cadquery_code(output_format="dxf")` 产出 revised.dxf
- [ ] DXF 沙箱执行 exit_code=0
- [ ] DXF 产出文件非空
- [ ] `revised.dxf` 已复制到产出目录
- [ ] 用 pythonOCC 读取 revised.step 验证 volume > 0
- [ ] 用 ezdxf 读取 revised.dxf 验证 entity_count > 0
- [ ] DeepSeek vs Ollama 对比表已记录（推理耗时 + 代码质量）
- [ ] 环境变量已清空（OPENAI_BASE_URL / OPENAI_MODEL / OPENAI_API_KEY / OPENAI_VLM_MODEL）
- [ ] LLM_PROVIDER 已恢复为 ollama
- [ ] `reset_provider_cache()` 已再次调用
- [ ] `get_llm_provider()` 返回 OllamaProvider
- [ ] `provider.is_available()` 为 True（恢复后）
- [ ] 最终结论基于真实文件产出（不可仅因"单步代码生成通过"标 PASS）

## 八荣八耻合规检查

- [ ] 以认真查询为荣：DeepSeek API 调用基于官方 OpenAI 兼容接口，无瞎猜参数
- [ ] 以寻求确认为荣：所有 spec/tasks 决策点通过 spec 文档明确
- [ ] 以人类确认为荣：用户明确的要求（DeepSeek Key / Ollama host）按此执行
- [ ] 以复用现有为荣：复用 provider 抽象 + generate_and_execute_with_fallback，不重造
- [ ] 以主动测试为荣：VLM 尺寸重测 + DeepSeek 全链路均基于真实证据
- [ ] 以遵循规范为荣：provider 切换走 services/ai 抽象层，业务代码不直接调 HTTP
- [ ] 以诚实无知为荣：偏差/失败如实标注，不假装通过
- [ ] 以谨慎重构为荣：无源码修改，仅做测试与验证

## 敷衍项检查（防止再次出现）

- [ ] 不可仅因"VLM 返回非空"标 PASS（必须校验尺寸语义）
- [ ] 不可仅因"单步代码生成通过"标 PASS（必须走全链路协同闭环）
- [ ] 不可跳过沙箱执行（必须验证 exit_code=0 + 文件产出）
- [ ] 不可跳过文件校验（必须验证 STEP volume > 0 + DXF entity_count > 0）
- [ ] 不可跳过环境恢复（必须验证恢复后回到 Ollama）
- [ ] 不可使用模拟数据替代真实文件产出
- [ ] 不可跳过对比分析（DeepSeek vs Ollama 必须对比）
