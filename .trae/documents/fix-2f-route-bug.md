# 修复 %2F 路由 Bug

## Summary

将 KB 模块中两个使用 `{standard_id}` 路径参数的端点改为使用 query 参数，从根本上解决 Starlette/uvicorn 将 `%2F` 解码为 `/` 导致的路由不匹配（404）问题。

**影响范围**：所有含 `/` 的 standard_id（如 `GB/T 4458.4`、`JB/T 8836` 等）的版本管理端点当前完全不可用。预置规范库 15 条中有 12 条含 `/`（所有 GB/T、JB/T、HG/T、QC/T），均受影响。

---

## Current State Analysis

### Bug 根因

- **受影响端点**（[kb.py:524](file:///d:/SynthDraft/backend/app/api/v1/endpoints/kb.py#L524) 与 [kb.py:546](file:///d:/SynthDraft/backend/app/api/v1/endpoints/kb.py#L546)）：
  - `GET  /api/v1/kb/standards/{standard_id}/versions`
  - `POST /api/v1/kb/standards/{standard_id}/versions`
- **触发条件**：当 `standard_id` 含 `/`（如 `GB/T 4458.4`），客户端按规范 URL 编码为 `GB%2FT%204458.4`。
- **失效原因**：Starlette/uvicorn 在路由匹配前将 `%2F` 解码为 `/`，导致 `/standards/GB%2FT%204458.4/versions` 被解析为 7 段路径（`standards` / `GB` / `T 4458.4` / `versions`）而非预期的 4 段，路由不匹配返回 404。
- **实测结果**（见 [version_manager_pg_realpath_test.md:98-103](file:///d:/SynthDraft/backend/tmp_audit_logs/version_manager_pg_realpath_test.md#L98)）：
  - `ISO 128-1`（无 `/`）→ 200 ✓
  - `GB/T 4458.4`（含 `/`，`%2F` 编码）→ **404 ✗**
  - `GB-T 4458.4`（用 `-` 代替）→ 200，但破坏 `_strip_year` 逻辑
  - `test123`（无特殊字符）→ 200 ✓

### 为什么选择 query 参数方案

审计日志（[version_manager_pg_realpath_test.md:190-193](file:///d:/SynthDraft/backend/tmp_audit_logs/version_manager_pg_realpath_test.md#L190)）列出了三种修复方案：

| 方案 | 评价 |
|------|------|
| **A. query 参数**（本方案） | 标准做法，query 参数中的 `%2F` 不影响路由匹配；API 契约清晰；无服务端配置依赖 |
| B. `__` 分隔符替换 | 需要客户端与服务端双向编解码，易出错，非标准 |
| C. uvicorn `--proxy-headers` + `raw_path` | `--proxy-headers` 实际不影响 `%2F` 解码；需自定义 ASGI 中间件读 `scope["raw_path"]`，复杂且脆弱 |

方案 A 是 RESTful API 中处理含特殊字符资源标识符的标准做法，且当前端点对 12/15 预置规范已完全不可用，无生产调用方，可安全变更。

### 受影响的调用方

- `d:\SynthDraft\backend\tests\verify_task15.py`（[L595](file:///d:/SynthDraft/backend/tests/verify_task15.py#L595), [L617](file:///d:/SynthDraft/backend/tests/verify_task15.py#L617), [L621](file:///d:/SynthDraft/backend/tests/verify_task15.py#L621)）：硬编码了旧路由路径做注册校验
- `d:\SynthDraft\backend\tmp_test_kb_api_v2.py`：临时测试脚本，使用旧路径
- `d:\SynthDraft\backend\tmp_test_kb_api_v3.py`：临时测试脚本，使用旧路径（`TEST-VERIFY2` 无 `/`，技术上仍能工作但路径需更新）
- `d:\SynthDraft\backend\tmp_test_kb_api.py`：临时测试脚本，使用旧路径
- 无前端、无其他后端服务调用这些端点（已搜索确认）

---

## Proposed Changes

### 1. 修改 `d:\SynthDraft\backend\app\api\v1\endpoints\kb.py`

**变更内容**：将 `GET` 与 `POST` `/standards/{standard_id}/versions` 改为 `/standards/versions`，`standard_id` 改为 query 参数。

**为什么**：query 参数中的 `%2F` 在路由匹配之后才解码，不会破坏路径分段。

**怎么做**：

#### 1a. 更新模块 docstring（[L16-17](file:///d:/SynthDraft/backend/app/api/v1/endpoints/kb.py#L16)）

```
- GET  /standards/{standard_id}/versions：列出某规范所有版本
- POST /standards/{standard_id}/versions：注册新版本
```
改为：
```
- GET  /standards/versions?standard_id=...：列出某规范所有版本
- POST /standards/versions?standard_id=...：注册新版本
```

#### 1b. 改造 GET 端点（[L523-542](file:///d:/SynthDraft/backend/app/api/v1/endpoints/kb.py#L523)）

- 路由路径：`/standards/{standard_id}/versions` → `/standards/versions`
- 函数签名：`standard_id: str` → `standard_id: str = Query(..., description="规范编号，如 GB/T 4458.4 或 GB/T 4458.4-2003")`
- description 末尾追加说明：`standard_id 作为 query 参数传递，避免 URL 编码的 '/' 导致路由不匹配。`
- 函数体不变（`mgr.list_versions(standard_id)` 调用不变）

#### 1c. 改造 POST 端点（[L545-577](file:///d:/SynthDraft/backend/app/api/v1/endpoints/kb.py#L545)）

- 路由路径：`/standards/{standard_id}/versions` → `/standards/versions`
- 函数签名：
  ```python
  async def register_standard_version(
      req: VersionRegisterRequest,
      standard_id: str = Query(..., description="规范编号，如 GB/T 4458.4 或 GB/T 4458.4-2003"),
  ) -> StandardVersion:
  ```
- description 末尾追加说明：`standard_id 作为 query 参数传递，避免 URL 编码的 '/' 导致路由不匹配。`
- 函数体不变

#### 1d. 路由冲突检查（已确认无冲突）

变更后 `/standards` 下的路由：
- `GET    /standards`（list_standards）
- `GET    /standards/conflicts`
- `GET    /standards/library`
- `GET    /standards/library/{category}`
- `GET    /standards/versions`（新）
- `POST   /standards/versions`（新）
- `GET    /standards/notifications`

无路径冲突。Starlette 优先匹配静态路径，`/standards/versions` 不会被 `/standards/{standard_id}/versions`（已删除）捕获。

### 2. 更新 `d:\SynthDraft\backend\tests\verify_task15.py`

**变更内容**：更新路由注册校验，匹配新的端点路径。

**为什么**：[L595](file:///d:/SynthDraft/backend/tests/verify_task15.py#L595) 硬编码了 `"/standards/{standard_id}/versions"`，变更后会断言失败。

**怎么做**：

- [L595](file:///d:/SynthDraft/backend/tests/verify_task15.py#L595)：`"/standards/{standard_id}/versions"` → `"/standards/versions"`
- [L617-618](file:///d:/SynthDraft/backend/tests/verify_task15.py#L617)：`method_map.get("/standards/{standard_id}/versions", ...)` → `method_map.get("/standards/versions", ...)`，提示文案同步更新
- [L621-622](file:///d:/SynthDraft/backend/tests/verify_task15.py#L621)：同上

### 3. 更新 `d:\SynthDraft\backend\tmp_test_kb_api_v2.py`

**变更内容**：更新临时测试脚本，验证修复后的端点能正确处理含 `/` 的 standard_id。

**为什么**：原脚本使用旧路径且用于诊断此 bug，需更新为验证修复。

**怎么做**：将所有 `/standards/{sid_encoded}/versions` 调用改为 `/standards/versions?standard_id={sid_encoded}` 形式。具体：

- A1（`ISO 128-1`）：`GET /standards/versions?standard_id=ISO%20128-1` → 预期 200 `[]`
- A2（`GB/T 4458.4`，`%2F` 编码）：`GET /standards/versions?standard_id=GB%2FT%204458.4` → **预期 200（核心验证项）**
- A3（不编码直接用 `/`）：删除或改为说明性注释（query 参数中 `/` 不需要编码，但 `%2F` 也会正确解码）
- A4（`GB-T 4458.4`）：保留作为对照
- A5（`test123`）：`GET /standards/versions?standard_id=test123` → 预期 200 `[]`
- B2（POST 注册）：`POST /standards/versions?standard_id=TEST-VERIFY` → 预期 200

### 4. 更新 `d:\SynthDraft\backend\tmp_test_kb_api_v3.py`（轻量更新）

**变更内容**：将 `/standards/TEST-VERIFY2/versions` 改为 `/standards/versions?standard_id=TEST-VERIFY2`。

**为什么**：保持临时脚本与新 API 契约一致，避免后续运行时混淆。

---

## Assumptions & Decisions

1. **API 契约变更是破坏性的**：旧路径 `/standards/{standard_id}/versions` 将不再存在。鉴于该端点对 12/15 预置规范已完全不可用，且无生产调用方，此变更可接受。
2. **不保留向后兼容**：遵循用户偏好"避免向后兼容 hack"，不添加旧路径的兼容重定向。旧端点本身已损坏，无实际用户。
3. **`standard_id` 作为 query 参数而非 body 字段**：POST 端点保留 `VersionRegisterRequest` body 不变，`standard_id` 作为 query 参数。这是为了（a）保持 schema 不变，（b）GET 与 POST 一致，（c）资源标识符与可变字段分离的常见模式。
4. **不修改 `version_manager.py`**：服务层逻辑（`_strip_year` 等）与路由 bug 无关，无需变更。
5. **不修改 `standard_library.py`**：预置规范数据中的 `/` 是规范编号的固有部分，不应篡改。
6. **不创建新文件**：遵循"NEVER create files unless absolutely necessary"，仅编辑现有文件。

---

## Verification Steps

### V1. 静态验证（代码检查）

- [x] 确认 `kb.py` 中两个端点的路由路径已改为 `/standards/versions`（[kb.py:527,554](file:///d:/SynthDraft/backend/app/api/v1/endpoints/kb.py#L527)）
- [x] 确认 `standard_id` 参数类型为 `Query(..., ...)`（[kb.py:538,565](file:///d:/SynthDraft/backend/app/api/v1/endpoints/kb.py#L538)）
- [x] 确认模块 docstring 已同步更新（[kb.py:16-21](file:///d:/SynthDraft/backend/app/api/v1/endpoints/kb.py#L16)）
- [x] 确认 `verify_task15.py` 中 `expected_paths` 与 `method_map` 校验已更新（[verify_task15.py:592-627](file:///d:/SynthDraft/backend/tests/verify_task15.py#L592)）

### V2. 单元测试

- [x] 执行 `python tests\verify_task15.py`，确认 `test_api_endpoints_import` 通过（80 PASS / 0 FAIL / 0 ENV-LIMIT）
- [x] 确认路由注册校验：`/standards/versions` 同时注册了 GET 和 POST

### V3. 端到端验证（需 FastAPI 服务运行）

- [x] 重启 FastAPI 服务：`uvicorn app.main:app --host 0.0.0.0 --port 8000`
- [x] 执行更新后的 `tmp_test_kb_api_v2.py`：所有断言通过
- [x] **核心断言**：`GET /api/v1/kb/standards/versions?standard_id=GB%2FT%204458.4` 返回 **HTTP 200**（修复前为 404）+ 返回 PG 中已有版本记录
- [x] 对照断言：
  - `ISO 128-1`（无 `/`）→ 200 `[]`
  - `GB/T 4458.4`（含 `/`，`%2F` 编码）→ **200**（核心修复验证）+ 返回 1 条版本
  - `test123` → 200 `[]`
- [x] POST 验证：`POST /api/v1/kb/standards/versions?standard_id=TEST-VERIFY` → 200，PG 中能查到写入记录
- [x] 回归验证：`/standards/notifications` 端点仍正常工作（返回 1 条通知）

### V4. PG 数据一致性验证

- [x] POST 后查 PG：`SELECT * FROM standard_versions WHERE standard_id = 'TEST-VERIFY'` → 1 行
- [x] 确认 `standard_id` 字段值为 `TEST-VERIFY`（不含 `%2F`，证明 query 参数正确解码）
- [x] PG 后端可用：`standard_versions` 表 3 行，`standard_notifications` 表 1 行（uvicorn 进程走 postgres 后端）

---

## Verification Summary

**所有验证通过（2026-07-28 18:17）：**

| 阶段 | 结果 | 关键证据 |
|------|------|---------|
| V1 静态验证 | ✓ | 代码已按计划改造，路由路径与签名正确 |
| V2 单元测试 | ✓ | 80 PASS / 0 FAIL，路由注册校验通过 |
| V3 端到端 | ✓ | A2 核心断言通过：`?standard_id=GB%2FT%204458.4` 返回 200（修复前 404） |
| V4 PG 一致性 | ✓ | `TEST-VERIFY` 正确写入 PG，`standard_id` 字段不含 `%2F` |

**%2F 路由 bug 已彻底修复并验证。**
