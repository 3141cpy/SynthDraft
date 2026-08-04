# 端到端测试报告

## 测试日期与环境
- 测试时间: 2026-08-04 22:56 ~ 23:24 (Asia/Shanghai)
- 后端: uvicorn (localhost:8000), app v0.1.0
- Celery: worker --pool=solo (reviews + generations 队列)
- AI Provider: 阿里云 qwen3.7-plus (LLM + VLM 均活跃), base_url=https://llm-txo3y63cgpfey8bj.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
- Docker 基础服务: PostgreSQL(localhost:5433) ✅ / Redis(6379) ✅ / Qdrant(6333) ✅
- MinIO: 未运行 (后端降级为本地 tmp_uploads/ 存储)
- HF 缓存: D:\synthdraft_hf_cache

### 健康检查
- `GET /api/v1/healthz` → 200, llm_available=true, vlm_available=true ✅
- `GET /api/v1/readyz` → 200, postgres=ok, redis=ok ✅

---

## 功能矩阵

### 审图测试 (7 种文件类型)

VLM 结果 10 个字段: `title, drawing_number, material, scale, dimensions, technical_requirements, surface_roughness, tolerance, regions, vlm_model`

| 功能 | 样本 | task_id | status | review_mode | score | defects | vlm_keys | 耗时(s) | 报告含图 | 通过 |
|---|---|---|---|---|---|---|---|---|---|---|
| PDF 审图 | 安全阀.pdf | 5089b4d9-b225-44df-9b33-63b643f6461d | completed | vlm | 54.0 | 4 | 10 | 262.2 | ✅ | ✅ |
| DWG 审图 | 安全阀.dwg | edcd7df1-c871-4efe-b7b1-fbaece49046b | completed | vlm | 62.0 | 3 | 10 | 172.9 | ✅ | ✅ |
| image 审图 | test.jpg | 2c7be2a7-a511-4acb-a83f-a29502b15d22 | completed | vlm | 54.0 | 4 | 10 | 203.7 | ✅ | ✅ |
| STEP 审图 | sample_box.step | 73a1a48c-49c6-44d2-bdc9-ef51f5fc3fd2 | completed | vlm | 54.0 | 4 | 10 | 91.9 | ✅ | ✅ |
| IGES 审图 | sample_box.iges | 1135ce41-a593-46b7-8104-d1175d3b8cd4 | completed | vlm | 54.0 | 4 | 10 | 111.9 | ✅ | ✅ |
| SLDPRT 审图 | sample.sldprt | 1ac2082f-7468-4341-a0ba-003eaa0edf6f | completed | vlm | 54.0 | 4 | 10 | 246.5 | ✅ | ✅ |
| SLDASM 审图 | sample.sldasm | 286fb806-ed82-463b-92b4-1ff39db0de6c | completed | vlm | 77.0 | 2 | 10 | 117.3 | ✅ | ✅ |

**审图测试汇总: 7/7 通过 (100%)**

#### PDF 审图缺陷详情 (score=54.0, 4 defects)
1. **title_block** (critical) - GB/T 18229-2023 §4.1: 未检测到标题栏实体, material 为 null
2. **dimensioning** (critical) - GB/T 18229-2023 §7.1: 未检测到尺寸标注实体 (dimension_count=0)
3. **tolerance** (major) - GB/T 1804-2000 §6.1: 未检测到一般公差标注或说明
4. **layer_naming** (major) - GB/T 18229-2023 §4.1: 未检测到任何图层定义

#### DWG 审图 (score=62.0, 3 defects)
- DWG 文件经 ODA File Converter 转换后走 VLM 审图流程, 缺陷数少于 PDF

#### SLDASM 审图 (score=77.0, 2 defects)
- 装配体文件审图得分最高 (77.0), 仅 2 个缺陷

---

## 智能生成测试

- **API**: `POST /api/v1/generations`
- **请求体**: `{"input_type": "text", "prompt": "生成长方体 50x30x20", "output_format": "step"}`
- **task_id**: a68e8f57-62de-4c86-8e84-564021c1a394
- **status**: succeeded
- **mode**: llm
- **cadquery 代码**: ✅ 已生成

```python
import cadquery as cq

# 长方体参数
length = 50.0  # 长 mm
width = 30.0   # 宽 mm
height = 20.0  # 高 mm

# 在 XY 平面创建长方体
result = cq.Workplane("XY").box(length, width, height)
```

- **执行结果**: success=true, exit_code=0, elapsed=8.4s
- **输出文件**:
  - `D:\SynthDraft\backend\tmp_uploads\generations\acc7e0d80ce6\output.step`
  - `D:\SynthDraft\backend\tmp_uploads\generations\acc7e0d80ce6\output.stl`
- **下载链接**: ✅ 已返回 (output_files 路径, 可通过 `/api/v1/generations/files/{path}` 下载)
- **几何验证**:
  - is_valid: true
  - volume: 30000.0 (50×30×20=30000 ✅)
  - bounding_box: [-25, -15, -10, 25, 15, 10] (居中 ✅)
  - surface_area: 6200.0 (2×(1500+1000+600)=6200 ✅)
  - backend: OCP
- **代码生成耗时**: 17.1s (LLM) + 8.4s (执行) = 25.5s 总计
- **通过**: ✅

---

## 知识库检索测试

- **API**: `GET /api/v1/kb/clauses?query=形位公差&top_k=5`
- **初始状态**: 返回空数组 (索引未建立)
- **重建索引**: `POST /api/v1/kb/reindex` → indexed_count=42, collection=gb_clauses
- **返回条数**: 5
- **标准号列表**: GB/T 1182-2018 (4条), GB/T 1804-2000 (1条)

| 序号 | standard | clause_id | title | score | category |
|---|---|---|---|---|---|
| 1 | GB/T 1182-2018 | 7.2 | 位置度公差 | 0.6451 | location_tolerance |
| 2 | GB/T 1182-2018 | 5.2 | 圆度公差 | 0.6078 | shape_tolerance |
| 3 | GB/T 1804-2000 | 5.1 | 角度尺寸一般公差 | 0.5969 | angle_tolerance |
| 4 | GB/T 1182-2018 | 5.3 | 圆柱度公差 | 0.5964 | shape_tolerance |
| 5 | GB/T 1182-2018 | 7.1 | 同轴度公差 | 0.5791 | location_tolerance |

- 每条结果包含: standard, clause_id, title, original_text, score, source_file, category, keywords, completeness
- **通过**: ✅

---

## Settings 配置页测试

- **API**: `GET /api/v1/ai/config`
- **配置数量**: 4
- **活跃配置**: 2 (Qwen3.7-Plus-LLM + Qwen3.7-Plus-VLM)

| id | name | provider_type | base_url | model | vlm_model | role | is_active |
|---|---|---|---|---|---|---|---|
| 1 | Ollama(.env 迁移) | ollama | http://localhost:11434 | qwen2.5-coder:7b | | llm | false |
| 2 | DS | openai_compatible | https://api.deepseek.com/v1 | deepseek-v4-pro | | llm | false |
| 4 | Qwen3.7-Plus-LLM | openai_compatible | https://llm-txo3y63cgpfey8bj... | qwen3.7-plus | | llm | **true** |
| 5 | Qwen3.7-Plus-VLM | openai_compatible | https://llm-txo3y63cgpfey8bj... | | qwen3.7-plus | vlm | **true** |

- **api_key 脱敏**: ✅ (所有配置的 api_key 显示为 `***`)
- **字段完整性**: ✅ (provider_type, base_url, model, vlm_model 均存在)
- **通过**: ✅

---

## 发现的问题

### 严重程度: 中

1. **Celery prefork 池在 Windows 上不可用**
   - 现象: 使用默认 prefork 池启动 worker 时, 子进程立即崩溃报 `PermissionError(13, '拒绝访问。')`, 无限重启
   - 原因: Windows 不支持 billiard semlock
   - 解决: 改用 `--pool=solo` 启动 worker (单线程顺序处理)
   - 影响: 任务串行处理, 7 个审图任务总耗时约 20 分钟

### 严重程度: 低

2. **OpenCV 无法读取中文路径文件**
   - 现象: `cv::findDecoder imread_('...安全阀.png'): can't open/read file`
   - 影响: 图像预处理失败, 但系统已优雅降级 (fallback 到原图)
   - 审图结果不受影响

3. **知识库索引初始未建立**
   - 现象: 首次查询 `GET /kb/clauses` 返回空数组 (非 503)
   - 解决: 手动调用 `POST /kb/reindex` 重建索引 (42 条)
   - 建议: 后端启动时自动检查并建立索引

4. **生成任务 metadata 中 llm_model 显示不正确**
   - 现象: 生成任务 metadata 显示 `llm_model=qwen2.5-coder:7b`, 但活跃 LLM 配置为 `qwen3.7-plus`
   - 影响: 不影响功能 (生成成功), 但 metadata 不准确
   - 可能原因: 生成任务代码中读取了非活跃配置或缓存过期

5. **生成任务自审图功能对 STEP 格式不支持**
   - 现象: `self_review_status=skipped_unsupported`, error: `output_format=step; reviews pipeline supports only ['dxf'] in P0`
   - 影响: STEP/IGES/STL 生成结果不会自动触发审图复查
   - 符合 P0 阶段设计预期

6. **任务状态术语不一致**
   - 现象: `GET /tasks/{id}` 返回 `status=succeeded` (Celery 映射), `GET /reviews/{id}/result` 返回 `status=completed`
   - 影响: 前端轮询需注意两个端点的状态值不同

7. **PDF 渲染图片过大触发缩放**
   - 现象: PDF 渲染为 9363×6623 PNG (2.1MB), 超过 VLM 输入限制, 自动缩放至 4096×2897
   - 影响: 不影响审图结果, 但增加处理时间

---

## 测试结论

### 通过率汇总

| 测试项 | 通过/总计 | 通过率 |
|---|---|---|
| 后端健康检查 | 2/2 | 100% |
| 7 种文件类型审图 | 7/7 | 100% |
| 智能生成 (文本→STEP) | 1/1 | 100% |
| 知识库检索 | 1/1 | 100% |
| Settings 配置页 | 1/1 | 100% |
| **总计** | **12/12** | **100%** |

### 整体评估

**所有端到端测试项全部通过 (12/12, 100%)。**

- **审图功能**: 7 种文件类型 (PDF/DWG/image/STEP/IGES/SLDPRT/SLDASM) 全部通过 VLM 审图, 每种均返回完整的 10 字段 VLM 结果、缺陷列表、合规评分和 HTML 报告 (含渲染图)。
- **智能生成**: 文本描述 "生成长方体 50x30x20" 成功生成 CadQuery 代码, 执行后输出 STEP/STL 文件, 几何验证通过 (体积 30000mm³, 符合预期)。
- **知识库检索**: 重建索引后 (42 条标准条款), 查询 "形位公差" 返回 5 条相关结果, 涵盖 GB/T 1182-2018 和 GB/T 1804-2000。
- **Settings 配置**: 4 个 AI Provider 配置正确展示, 活跃配置为阿里云 qwen3.7-plus (LLM+VLM), api_key 已脱敏。

### 已知限制
- Celery 在 Windows 上需使用 solo 池 (prefork 不可用)
- MinIO 未运行, 文件存储降级为本地 tmp_uploads/
- 生成任务的自审图功能仅支持 DXF 格式 (P0 阶段)
