# P2 问题即时修复记录

## 修复时间
2026-08-05

## 修复人
子 agent F

## 环境
- 项目路径: d:\SynthDraft
- 后端: uvicorn (port 8000) + Celery worker (--pool=solo, -Q reviews,generations)
- 数据库活跃 LLM 配置: id=4, name="Qwen3.7-Plus-LLM", model="qwen3.7-plus", provider_type="openai_compatible"
- .env 旧值: LLM_MODEL="qwen2.5-coder:7b" (Ollama, is_active=false)

---

## P2-1：生成任务 metadata.llm_model 显示不正确

### 问题描述
生成任务返回的 `metadata.llm_model="qwen2.5-coder:7b"`（来自 .env 的 `settings.LLM_MODEL`），
与数据库活跃 Provider（`qwen3.7-plus`）不一致。

### 根因
`backend/app/celery/tasks/generations.py` 第 295 行直接读 `settings.LLM_MODEL`（.env 配置），
而非数据库活跃 LLM provider 的 `model` 字段。

### 修复前
- 文件: `backend/app/celery/tasks/generations.py`
- 行号: 295
- 代码:
```python
"llm_model": settings.LLM_MODEL if is_llm_available() else None,
```

### 修复后
- 文件: `backend/app/celery/tasks/generations.py`
- 新增辅助函数 `_get_active_llm_model()`（第 47-67 行），优先从数据库活跃配置读取 `model` 字段，
  DB 无配置或不可达时回退 `settings.LLM_MODEL`（兼容纯 .env 部署）。
- 修改 metadata 行（第 318 行）:
```python
def _get_active_llm_model() -> str | None:
    """获取当前激活 LLM provider 的 model 字段（反映数据库活跃配置）。

    P2-1 修复：原代码直接读 ``settings.LLM_MODEL``（.env），与数据库活跃
    provider 不一致。本函数优先从数据库活跃配置（``role="llm" AND is_active=True``）
    读取 ``model`` 字段；DB 无配置或不可达时回退 ``settings.LLM_MODEL``
    （兼容纯 .env 部署与 legacy 路径）。

    Returns:
        激活配置的 model 字段；无任何配置时返回 None。
    """
    try:
        from app.services.ai.base import _load_active_config_sync

        config = _load_active_config_sync("llm")
        if config is not None:
            return getattr(config, "model", "") or None
    except Exception as e:  # noqa: BLE001
        log.warning("generation.llm_model.lookup_failed", error=str(e))
    # DB 无配置或不可达时回退到 settings（legacy/.env 部署）
    return settings.LLM_MODEL or None


# ... 在 run_generation 的 metadata 中:
"llm_model": _get_active_llm_model() if is_llm_available() else None,
```

### 回归测试
- 测试步骤: 重启 Celery worker → 执行生成任务（POST /api/v1/generations, prompt="生成一个 10mm 立方体"）→ 等待完成 → 查看 metadata.llm_model
- 测试结果: **通过**
- 实际值: `llm_model="qwen3.7-plus"`（与数据库活跃配置一致，不再是 .env 的 `qwen2.5-coder:7b`）
- task_id: 84334ad2-9fe9-43a7-bece-c1645d9c7580

---

## P2-2：任务状态术语不一致

### 问题描述
1. `_map_celery_state` / `_map_state` 未处理 PROGRESS 状态 → 执行中任务误报为 "queued"
2. SUCCESS 状态术语不一致：tasks.py/ws.py 用 "succeeded"，reviews.py 用 "completed"
3. progress 字段硬编码为 0

### 涉及文件
1. `backend/app/api/v1/endpoints/tasks.py` — `_map_celery_state` 缺 PROGRESS，progress 硬编码 0
2. `backend/app/api/v1/endpoints/ws.py` — `_map_state` 缺 PROGRESS，progress 硬编码 0
3. `backend/app/api/v1/endpoints/reviews.py` — SUCCESS 返回 "completed"（与 "succeeded" 不一致）
4. `backend/app/api/v1/endpoints/generations.py` — 缺 PROGRESS 状态处理（PROGRESS 会误入 SUCCESS 分支）

### 修复前

**tasks.py `_map_celery_state`（第 14-25 行）:**
```python
def _map_celery_state(state: str) -> str:
    """将 Celery 原生状态映射为业务状态。"""
    mapping = {
        "PENDING": "queued",
        "RECEIVED": "queued",
        "STARTED": "running",
        "RETRY": "running",
        "SUCCESS": "succeeded",
        "FAILURE": "failed",
        "REVOKED": "canceled",
    }
    return mapping.get(state, "queued")
```

**tasks.py `get_task_status`（第 47-53 行）progress 硬编码:**
```python
    return TaskStatusResponse(
        task_id=task_id,
        status=state,
        progress=0,  # 硬编码
        result=output,
        error=error,
    )
```

**ws.py `_map_state`（第 20-30 行）:**
```python
def _map_state(state: str) -> str:
    mapping = {
        "PENDING": "queued",
        "RECEIVED": "queued",
        "STARTED": "running",
        "RETRY": "running",
        "SUCCESS": "succeeded",
        "FAILURE": "failed",
        "REVOKED": "canceled",
    }
    return mapping.get(state, "queued")
```

**ws.py payload（第 42 行）progress 硬编码:**
```python
            payload: dict = {"task_id": task_id, "status": state, "progress": 0}
```

**reviews.py SUCCESS（第 125-132 行）:**
```python
    if state == "SUCCESS":
        data = result.result
        if isinstance(data, dict):
            data = {**data, "status": "completed"}
        return JSONResponse(...)
```

**generations.py（第 142 行）缺 PROGRESS:**
```python
    if state == "STARTED" or state == "RETRY":
        ...
```

### 修复后

**tasks.py `_map_celery_state` — 添加 PROGRESS → "running":**
```python
def _map_celery_state(state: str) -> str:
    """将 Celery 原生状态映射为业务状态。

    P2-2 修复：补充 PROGRESS → "running"（原缺失导致执行中任务误报 "queued"）。
    SUCCESS 统一为 "succeeded"（与 ws.py / reviews.py 保持一致）。
    """
    mapping = {
        "PENDING": "queued",
        "RECEIVED": "queued",
        "STARTED": "running",
        "PROGRESS": "running",
        "RETRY": "running",
        "SUCCESS": "succeeded",
        "FAILURE": "failed",
        "REVOKED": "canceled",
    }
    return mapping.get(state, "queued")
```

**tasks.py — progress 从 result.info 读取真实值:**
```python
    # P2-2 修复：progress 从 Celery task info 中读取真实值（PROGRESS 状态下
    # task.info 为 dict，含 progress 字段）；其他状态默认 0。
    progress = 0
    if state == "succeeded":
        output = result.result if isinstance(result.result, dict) else {"value": str(result.result)}
    elif state == "failed":
        error = str(result.result) if result.result else "unknown error"
    elif state == "running":
        if isinstance(result.info, dict):
            progress = result.info.get("progress", 0)
    return TaskStatusResponse(
        task_id=task_id,
        status=state,
        progress=progress,
        result=output,
        error=error,
    )
```

**ws.py `_map_state` — 添加 PROGRESS → "running":**
```python
def _map_state(state: str) -> str:
    """将 Celery 原生状态映射为业务状态。

    P2-2 修复：补充 PROGRESS → "running"（与 tasks.py _map_celery_state 对齐）。
    """
    mapping = {
        "PENDING": "queued",
        "RECEIVED": "queued",
        "STARTED": "running",
        "PROGRESS": "running",
        "RETRY": "running",
        "SUCCESS": "succeeded",
        "FAILURE": "failed",
        "REVOKED": "canceled",
    }
    return mapping.get(state, "queued")
```

**ws.py — progress 从 result.info 读取真实值:**
```python
            # P2-2 修复：progress 从 task.info 读取真实值（PROGRESS 状态下
            # task.info 为 dict 含 progress 字段）；其他状态默认 0。
            progress = 0
            if state == "running" and isinstance(result.info, dict):
                progress = result.info.get("progress", 0)
            payload: dict = {"task_id": task_id, "status": state, "progress": progress}
```

**reviews.py — "completed" → "succeeded":**
```python
    if state == "SUCCESS":
        data = result.result
        if isinstance(data, dict):
            # P2-2 修复：SUCCESS 状态术语统一为 "succeeded"
            # （原 "completed" 与 tasks.py / ws.py 的 "succeeded" 不一致）
            data = {**data, "status": "succeeded"}
        return JSONResponse(...)
```

**generations.py — 添加 PROGRESS 到 running 分支:**
```python
    # P2-2 修复：补充 PROGRESS 状态处理（原缺失会导致 PROGRESS 误入 SUCCESS 分支）
    if state in ("STARTED", "RETRY", "PROGRESS"):
        return JSONResponse(...)
```

### 回归测试
- 测试步骤:
  1. 查询运行中生成任务状态（GET /api/v1/tasks/{task_id}）→ 验证 status="running"
  2. 查询运行中审图任务结果（GET /api/v1/reviews/{task_id}/result）→ 验证 status="running"、progress=真实值
  3. 查询已完成审图任务结果 → 验证 status="succeeded"（非 "completed"）
- 测试结果: **通过**
- 生成任务运行中: status="running"（原会误报 "queued"）
- 审图任务运行中: status="running", progress=25/40/80（真实进度值，非硬编码 0）
- 审图任务完成: status="succeeded"（原为 "completed"）
- task_id: 生成=84334ad2-9fe9-43a7-bece-c1645d9c7580, 审图=095975ce-80ad-4a92-9231-292b0fe2f44e

---

## P2-3：OpenCV 无法读取中文路径

### 问题描述
上传"安全阀.pdf"等中文文件名后，图像预处理失败（cv2.imread 不支持中文路径）。

### 根因
`backend/app/services/review/image_preprocess.py` 的 `load_image()` 函数使用 `cv2.imread()` 读取图片。
`cv2.imread` 在 Windows 上不支持中文路径（静默返回 None 或抛异常）。原代码虽有 try/except
兜底（先 imread 再 fallback 到 np.fromfile），但在部分 cv2 版本下 imread 可能返回非 None 的
损坏数据，导致 fallback 不触发。

### 修复前
- 文件: `backend/app/services/review/image_preprocess.py`
- 行号: 75-88
- 代码:
```python
    # cv2.imread 不支持中文路径，用 np.fromfile + cv2.imdecode 兜底
    try:
        img = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("cv2.imread 返回 None")
    except Exception:
        log.debug("preprocess.imread_fallback", path=str(image_path))
        import numpy as _np
        data = _np.fromfile(str(image_path), dtype=_np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError(f"cv2.imdecode 失败：{image_path}")

    return img
```

### 修复后
- 文件: `backend/app/services/review/image_preprocess.py`
- 行号: 75-86
- 代码:
```python
    # P2-3 修复：cv2.imread 不支持中文路径（如"安全阀.pdf"渲染的 PNG），
    # 在 Windows 上会静默返回 None 或抛异常。原 try/except 兜底在部分
    # cv2 版本下仍可能漏掉（如 imread 返回非 None 的损坏数据）。
    # 直接使用 np.fromfile + cv2.imdecode 是中文路径的可靠方案：
    # np.fromfile 按 Unicode 路径读取原始字节，cv2.imdecode 解码为 ndarray。
    import numpy as _np
    data = _np.fromfile(str(image_path), dtype=_np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"cv2.imdecode 失败（文件可能不是有效图片）：{image_path}")

    return img
```

### 回归测试
- 测试步骤:
  1. 直接调用 `load_image()` 加载中文路径 PNG 文件 `安全阀.png`
  2. 通过审图 API 提交中文文件名 PDF（安全阀.pdf）端到端验证
- 测试结果: **通过**
- 直接测试: `load_image(Path("...安全阀.png"))` 返回 ndarray, shape=(6623, 9363, 3), dtype=uint8
- 端到端测试: 审图任务处理 `安全阀.pdf` 全流程成功（PDF→PNG 渲染→图像预处理→VLM 检测→VLM OCR→LLM 判定→报告生成），compliance_score=54.0
- task_id: 095975ce-80ad-4a92-9231-292b0fe2f44e

---

## P-001：collaboration 队列无 worker（联动测试发现）

### 问题描述
`POST /api/v1/collaboration/optimize-from-review` 派发的生成任务使用 `queue="default"`，
而 Celery worker 仅监听 `reviews,generations` 队列，导致任务永远 PENDING，审图→协同→生成闭环断裂。

### 根因
`backend/app/api/v1/endpoints/collaboration.py` 第 86 行 `apply_async(..., queue="default")`，
但系统中不存在 default 队列 worker（celery_app 只路由到 reviews/generations/solidworks/sketch/assembly/collaboration 6 个队列）。

### 修复前
- 文件: `backend/app/api/v1/endpoints/collaboration.py`
- 代码:
```python
task = run_generation.apply_async(
    kwargs={...},
    queue="default",  # 无 worker 监听此队列
)
```

### 修复后
- 代码:
```python
task = run_generation.apply_async(
    kwargs={...},
    queue="generations",  # 复用已有 worker 的 generations 队列
)
```

### 回归测试
- 测试步骤: 重启后端 → 提交审图（安全阀.pdf）→ 调用 optimize-from-review → 轮询任务状态
- 测试结果: **通过**
- 实际值: optimize 任务在 generations 队列被立即消费，status="succeeded"，defects_count=5，optimized_prompt 生成成功
- 修复后 P-001 与 P2-2 联动验证：审图任务状态依次 running(progress 10→25→40) → succeeded

---

## P-002：Embedding 模型 HF_HOME 未配置（联动测试发现）

### 问题描述
`POST /api/v1/kb/reindex` 与 `GET /api/v1/kb/clauses` 返回 503：
`"无法加载任何 embedding 模型：bge-m3 / sentence-transformers / Ollama 均失败"`。
但 bge-m3 模型实际已完整下载至 `D:\synthdraft_hf_cache\hub\models--BAAI--bge-m3\`（pytorch_model.bin 等文件齐全）。

### 根因
`HF_HOME` 环境变量未设置。huggingface_hub 的 `snapshot_download` 默认使用
`~/.cache/huggingface`（C 盘）查找模型缓存，找不到本地模型后尝试经 hf-mirror 联网下载失败
（沙箱网络受限），导致模型加载链全失败。

### 修复前
- 文件: `backend/app/services/kb/embedder.py`
- 代码:
```python
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "60")
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
# 未设置 HF_HOME → snapshot_download 去 C 盘查找 → 找不到 → 联网下载 → 失败
```

### 修复后
- 代码:
```python
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "60")
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
# HF_HOME：指向本地 HuggingFace 缓存目录（bge-m3 模型已预下载至此）。
# 未设置时 huggingface_hub 默认使用 ~/.cache/huggingface（C 盘），找不到模型会尝试联网下载。
# 优先尊重环境变量；其次尝试 D:\synthdraft_hf_cache（当前环境模型实际存放位置）。
_HF_HOME_CANDIDATES = [
    os.environ.get("HF_HOME"),
    r"D:\synthdraft_hf_cache",
]
for _cand in _HF_HOME_CANDIDATES:
    if _cand and os.path.isdir(_cand):
        os.environ.setdefault("HF_HOME", _cand)
        os.environ.setdefault("HF_HUB_CACHE", os.path.join(_cand, "hub"))
        break
```
- 同时 `_BGE_M3_ALLOW_PATTERNS` 添加 `"pytorch_model.bin"`（本地缓存为 .bin 格式而非 .safetensors，
  缺失该模式会导致 snapshot_download 校验时认为文件不完整而触发重新下载）

### 回归测试
- 测试步骤: 重启后端 → POST /api/v1/kb/reindex → GET /api/v1/kb/clauses（形位公差 / 尺寸标注）
- 测试结果: **通过**
- reindex: 200，indexed_count=42，耗时 33.2s（bge-m3 从 D:\synthdraft_hf_cache 成功加载）
- clauses"形位公差": 200，5 条结果（位置度 0.645 / 圆度 0.608 / 角度一般公差 0.597 / 圆柱度 0.596 / 同轴度 0.579）
- clauses"尺寸标注": 200，3 条结果（基本规则 0.731 / CAD 关联标注 0.706 / 尺寸数字 0.696）
- standards 列表: 200，6 个规范

---

## 总结

- **修复完成: 5/5**
- **回归测试通过: 5/5**
- **遗留问题: 无（P2-1/P2-2/P2-3/P-001/P-002 全部修复）**

### 修改文件清单
1. `backend/app/celery/tasks/generations.py` — 新增 `_get_active_llm_model()` 函数，metadata.llm_model 改读数据库活跃配置
2. `backend/app/api/v1/endpoints/tasks.py` — `_map_celery_state` 添加 PROGRESS→"running"；progress 从 result.info 读取
3. `backend/app/api/v1/endpoints/ws.py` — `_map_state` 添加 PROGRESS→"running"；progress 从 result.info 读取
4. `backend/app/api/v1/endpoints/reviews.py` — SUCCESS 状态术语 "completed"→"succeeded"
5. `backend/app/api/v1/endpoints/generations.py` — 添加 PROGRESS 状态到 running 分支
6. `backend/app/services/review/image_preprocess.py` — `load_image` 改用 np.fromfile + cv2.imdecode（中文路径可靠方案）
7. `backend/app/api/v1/endpoints/collaboration.py` — P-001：队列路由 default→generations
8. `backend/app/services/kb/embedder.py` — P-002：HF_HOME 自动检测（D:\synthdraft_hf_cache）+ allow_patterns 添加 pytorch_model.bin

### 后端重启记录
- Celery worker: 已重启（P2-1、P2-3 代码在 Celery 进程执行）
- Uvicorn: 已重启（P2-2/P-001/P-002 代码在 API 进程执行，原 --reload 未生效因存在孤儿进程占用端口）
