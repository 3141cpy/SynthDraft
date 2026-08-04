# 知识库配置监控测试报告

## 测试时间
2026-08-04 23:56 ~ 23:59 (Asia/Shanghai)

## 测试环境
- 后端: http://localhost:8000 (uvicorn)
- Celery worker: 运行中
- AI Provider: 4 个配置（阿里云 qwen3.7-plus 活跃，id=4 LLM / id=5 VLM）
- 知识库: 42 条国标条款已索引（collection=gb_clauses）
- Docker: PostgreSQL(5433) / Redis(6379) / Qdrant(6333) healthy
- 测试样本: d:\SynthDraft\test\安全阀.pdf（已验证存在）
- 测试工具: PowerShell Invoke-RestMethod / curl.exe（multipart 上传）

## 端点签名确认

### kb.py 端点签名
| # | 方法 | 路径 | 参数 | 说明 |
|---|---|---|---|---|
| 1 | GET | /api/v1/kb/clauses | query*, top_k, standard, category, clause_id | 规范条款检索 |
| 2 | GET | /api/v1/kb/standards | — | 已索引规范列表 |
| 3 | POST | /api/v1/kb/reindex | (user_id Dep) | 重建索引（recreate=True） |
| 4 | POST | /api/v1/kb/enterprise-standards/import | standard*, version, file*(UploadFile) | 上传并导入企业规范 |
| 5 | GET | /api/v1/kb/standards/conflicts | standard_a*, standard_b*, use_llm | 规范集冲突检测 |
| 6 | GET | /api/v1/kb/profiles | — | 列出所有规范配置 |
| 7 | POST | /api/v1/kb/profiles | body: name*, description, standards, priority | 创建规范配置（同名覆盖） |
| 8 | POST | /api/v1/kb/profiles/active | body: name* | 切换当前活跃配置 |
| 9 | GET | /api/v1/kb/standards/library | category(query, 可选) | 预置规范库列表 |
| 10 | GET | /api/v1/kb/standards/library/{category} | category(path) | 按类别列出预置规范 |
| 11 | GET | /api/v1/kb/standards/versions | standard_id*(query) | 列出某规范所有版本 |
| 12 | POST | /api/v1/kb/standards/versions | standard_id*(query), body: version*, release_date, status, notes | 注册规范新版本 |
| 13 | GET | /api/v1/kb/standards/notifications | only_unread(query) | 列出规范更新通知 |

### ai_config.py 端点签名
| # | 方法 | 路径 | 参数 | 说明 |
|---|---|---|---|---|
| 1 | GET | /api/v1/ai/config | role(query: llm/vlm) | 列出所有 provider 配置（api_key 脱敏） |
| 2 | POST | /api/v1/ai/config | body: name*, provider_type*, base_url*, api_key, model, vlm_model, role | 新增 provider 配置（201） |
| 3 | PUT | /api/v1/ai/config/{config_id} | config_id(path), body: name, provider_type, base_url, api_key, model, vlm_model, role | 更新指定配置 |
| 4 | POST | /api/v1/ai/config/{config_id}/test | config_id(path) | 测试连接（文本+视觉模型探测） |
| 5 | POST | /api/v1/ai/config/{config_id}/activate | config_id(path) | 激活配置（role 内互斥热切换） |
| 6 | DELETE | /api/v1/ai/config/{config_id} | config_id(path) | 删除指定配置（204） |

### observability.py 端点签名
| # | 方法 | 路径 | 参数 | 说明 |
|---|---|---|---|---|
| 1 | GET | /api/v1/observability/queue-status | — | Celery 队列状态 |
| 2 | GET | /api/v1/observability/feedback-summary | — | 反馈总体统计 |
| 3 | GET | /api/v1/observability/feedback-by-category | — | 按缺陷类别分组统计 |
| 4 | GET | /api/v1/observability/feedback-trend | granularity(query: day/week/month) | 反馈时间趋势 |
| 5 | GET | /api/v1/observability/llm-cost-summary | — | LLM 推理成本汇总（按模型） |
| 6 | GET | /api/v1/observability/llm-latency | — | LLM 推理延迟分布 |

## 端点测试结果

| # | 方法 | 路径 | 状态码 | 关键字段/响应 | 通过 | 备注 |
|---|---|---|---|---|---|---|
| 1 | GET | /api/v1/kb/clauses | 200 | total=5, 5 条 results 全 complete | ✅ | 涵盖 GB/T 1182-2018/GB/T 1804-2000 |
| 2 | GET | /api/v1/kb/standards | 200 | count=6 | ✅ | 6 个已索引规范 |
| 3 | POST | /api/v1/kb/reindex | 200 | indexed_count=42, collection=gb_clauses | ✅ | 重建索引成功 |
| 4 | POST | /api/v1/kb/enterprise-standards/import | 200 | clauses_count=33, format=pdf | ✅ | 安全阀.pdf 解析 33 条条款 |
| 5 | GET | /api/v1/kb/standards/conflicts | 200 | total=8, by_type={missing:8}, llm_used=false | ✅ | 8 个 missing 冲突 |
| 6 | GET | /api/v1/kb/profiles | 200 | total=1, active=v3-e2e-profile-e7a74127 | ✅ | 初始 1 个配置 |
| 7 | POST | /api/v1/kb/profiles | 200 | name=test-profile, is_active=false | ✅ | 创建成功 |
| 8 | POST | /api/v1/kb/profiles/active | 200 | active_profile=test-profile, total=2 | ✅ | 切换成功，已恢复原配置 |
| 9 | GET | /api/v1/kb/standards/library | 200 | count=15 | ✅ | 15 个预置规范 |
| 10 | GET | /api/v1/kb/standards/library/national | 200 | count=7 | ✅ | 7 个国家标准 |
| 11 | GET | /api/v1/kb/standards/versions | 200 | count=0 | ✅ | 注册前为空（合法） |
| 12 | POST | /api/v1/kb/standards/versions | 200 | standard_id=GB/T 1182, version=2024, status=active | ✅ | 注册成功 |
| 13 | GET | /api/v1/kb/standards/notifications | 200 | count=2 | ✅ | 2 条通知 |
| 14 | GET | /api/v1/ai/config | 200 | count=4, api_key=***/空（脱敏正常） | ✅ | 有 key 显示***，本地模型空串 |
| 15 | POST | /api/v1/ai/config | 201 | id=6, name=test-temp, api_key=*** | ✅ | 新增成功，api_key 脱敏 |
| 16 | PUT | /api/v1/ai/config/6 | 200 | name=test-temp-updated, api_key=*** | ✅ | 更新成功 |
| 17 | POST | /api/v1/ai/config/6/test | 200 | available=false, vlm_available=false, latency_ms=5207 | ✅ | 假 key 导致 403，符合预期 |
| 18 | POST | /api/v1/ai/config/6/activate | 200 | id=6, is_active=true, role=llm | ✅ | 激活成功，已恢复 id=4 |
| 19 | DELETE | /api/v1/ai/config/6 | 204 | 无响应体 | ✅ | 删除成功 |
| 20 | GET | /api/v1/observability/queue-status | 200 | worker_count=0, alert_count=1 | ✅ | 见问题 1 |
| 21 | GET | /api/v1/observability/feedback-summary | 200 | total=6 | ✅ | 6 条反馈统计 |
| 22 | GET | /api/v1/observability/feedback-by-category | 200 | category_count=4 | ✅ | 4 个类别 |
| 23 | GET | /api/v1/observability/feedback-trend | 200 | bucket_count=1, granularity=day | ✅ | 1 个时间桶 |
| 24 | GET | /api/v1/observability/llm-cost-summary | 200 | total_calls=1, total_cost_usd=0.0 | ✅ | 1 次调用 |
| 25 | GET | /api/v1/observability/llm-latency | 200 | overall.count=1, p95_ms=4497.922 | ✅ | 延迟分布正常 |

## 详细测试记录

### Task 11: 知识库端点
- **clauses 检索结果**: 5 条，涵盖标准: GB/T 1182-2018（4 条: 7.2/5.2/5.3/7.1）、GB/T 1804-2000（1 条: 5.1）；score 范围 0.579~0.645；全部 completeness=complete，含 source_file
- **standards 已索引列表**: 6 个规范 — GB/T 1182-2018, GB/T 131-2006, GB/T 17450-1998, GB/T 1804-2000, GB/T 18229-2023, GB/T 4457.4-2002
- **reindex 结果**: indexed_count=42, collection=gb_clauses, 重建成功
- **enterprise-standards/import**: 上传 安全阀.pdf（standard=Q/Test-001, version=2024），format=pdf，成功提取 33 条条款，返回 clauses 数组 33 条
- **conflicts 冲突检测**: GB/T 1182-2018 vs GB/T 1804-2000（use_llm=false），total=8，全部为 missing 类型（GB/T 1182 有而 GB/T 1804 无），severity 均为 minor，llm_used=false；涉及条款 5.1/5.2/5.3/5.4/6.1/6.2/7.1/7.2
- **profiles 初始**: 1 个配置 v3-e2e-profile-e7a74127（active=true，priority=10）
- **profiles 创建**: 成功创建 test-profile（standards=[GB/T 1182-2018, GB/T 1804-2000], priority=5）
- **profiles/active 切换**: 成功切换到 test-profile（total=2），测试后已恢复为 v3-e2e-profile-e7a74127
- **standards/library**: 15 个预置规范
- **standards/library/national**: 7 个国家标准（含 GB/T 14665-2012, GB/T 4458.1~4458.4 等）
- **standards/versions（GET）**: 注册前 count=0（合法空列表）
- **standards/versions（POST）**: 注册 GB/T 1182-2018 的 v2024 版本成功，返回 standard_id=GB/T 1182（自动去除年份后缀）、version=2024、status=active
- **standards/notifications**: 2 条通知 — JB/T 8836 新版本 2023（未读）、GB/T 4458.4 新版本 2024 替代 2003（已读）

### Task 12: AI 配置端点
- **初始配置数**: 4
  - id=1: Ollama（.env 迁移）, role=llm, provider=ollama, model=qwen2.5-coder:7b, api_key=""（本地模型）, is_active=false
  - id=2: DS, role=llm, provider=openai_compatible, model=deepseek-v4-pro, api_key=***, is_active=false
  - id=4: Qwen3.7-Plus-LLM, role=llm, provider=openai_compatible, model=qwen3.7-plus, api_key=***, is_active=true
  - id=5: Qwen3.7-Plus-VLM, role=vlm, provider=openai_compatible, vlm_model=qwen3.7-plus, api_key=***, is_active=true
- **新增配置 id**: 6（name=test-temp, role=llm, model=gpt-4o-mini）
- **api_key 脱敏**: ✅ POST 返回 api_key="***"，GET 中有 key 的配置显示 "***"，Ollama 本地模型显示空串
- **更新后 name**: test-temp-updated（updated_at 时间戳已刷新）
- **测试连接结果**: available=false, vlm_available=false, latency_ms=5207, error="Client error '403 Forbidden' for url 'https://api.openai.com/v1/models'" — 假 key 被拒，端点返回 200 + 结果对象（符合设计：不抛 HTTP 错误）
- **激活后状态**: id=6 is_active=true（role=llm 内互斥，原 id=4 自动去激活）
- **清理**: 已激活恢复 id=4（Qwen3.7-Plus-LLM）→ DELETE id=6 返回 204
- **删除后配置数**: 4（恢复初始），id=4/id=5 保持 active
- **清理完成**: ✅

### Task 13: 可观测性端点
- **queue-status**: 返回 active_workers, alerts, collected_at, errors, queues, total_failed, worker_count；worker_count=0，alert_count=1
- **feedback-summary**: 返回 accept_count, accept_rate, false_positive_rate, modify_rate, modify_suggestion_count, reject_as_false_positive_count, total；total=6
- **feedback-by-category**: 返回 categories, category_count；category_count=4
- **feedback-trend**: 返回 bucket_count, granularity, skipped_records, trend；bucket_count=1, granularity=day
- **llm-cost-summary**: 返回 by_model, total_calls, total_cost_usd, total_input_tokens, total_output_tokens；total_calls=1, total_cost_usd=0.0
- **llm-latency**: 返回 by_model, overall；overall.count=1, p95_ms=4497.922

## 发现的问题

1. **queue-status 报告 worker_count=0**（观察项，非端点故障）
   - 前置条件确认 Celery worker 运行中，但 `/observability/queue-status` 返回 worker_count=0，并产生 1 条告警。
   - 端点本身返回 200 与有效数据结构（功能正常），但 worker 探测为 0 可能反映 queue_monitor 通过 Celery inspect 获取 worker 列表超时或 worker 未正确响应 inspect ping。
   - 建议：检查 queue_monitor 采集逻辑的 inspect 超时设置，或确认 worker 的 `--hostname` 与 broker 可达性。

2. **PowerShell 控制台中文乱码**（环境问题，非 API 问题）
   - PowerShell CLIXML 输出流中中文出现 mojibake（如 "形位公差" 显示为乱码），但 API 实际返回的 JSON 体为合法 UTF-8 中文。属 PowerShell 控制台编码问题，不影响 API 正确性。文件上传改用 curl.exe 是因为当前 PowerShell 版本（5.1）不支持 `Invoke-WebRequest -Form` 参数。

## 通过率汇总
- 通过: 25/25
- 失败: 0/25
- 通过率: 100%
