"""Task 7.2: AI Provider 配置管理 API 端点测试。

覆盖 ai_config.py 的 6 个端点，使用 httpx AsyncClient + ASGITransport
配合内存 SQLite 数据库。依赖注入通过 dependency_overrides 替换为测试 session。
含 split-llm-vlm-config 的 role 过滤、VLM 配置创建等场景。

测试用例（13 个）：
1. test_list_configs_empty — 空列表
2. test_create_config — 新增，返回 201 + 脱敏 api_key
3. test_create_config_validation_error — 缺少必填字段返回 422
4. test_update_config — 更新，返回脱敏 api_key
5. test_update_config_not_found — 不存在返回 404
6. test_delete_config — 删除返回 204
7. test_delete_config_not_found — 不存在返回 404
8. test_activate_config — 激活，返回更新后的配置
9. test_activate_config_not_found — 不存在返回 404
10. test_test_config — 测试连接（mock _probe_ollama 成功 + 不存在返回 404）
11. test_api_key_desensitization — 创建带 api_key 的配置，GET 返回 ***
12. test_list_configs_role_filter — GET ?role=vlm 按 role 过滤
13. test_create_vlm_config — POST 创建 VLM role 配置，返回 role 字段
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import AsyncGenerator

import pytest
import pytest_asyncio

# 确保 backend/ 在 sys.path
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user_id, get_db
from app.api.v1.endpoints import ai_config as ai_config_endpoint
from app.database import Base
from app.models.ai_provider_config import AIProviderConfig  # noqa: F401 — 注册模型到 metadata


# ===== Fixtures =====


@pytest_asyncio.fixture
async def app_client() -> AsyncGenerator[AsyncClient, None]:
    """创建带 ai_config 路由的测试 FastAPI app + httpx AsyncClient。

    - 内存 SQLite 数据库（StaticPool 共享内存库）
    - 覆盖 get_db 依赖为测试 session factory
    - 覆盖 get_current_user_id 为固定 "test-user"
    - 覆盖 refresh_active_config_cache 为 no-op（防止 activate 端点连 PostgreSQL）
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    app = FastAPI()
    app.include_router(ai_config_endpoint.router, prefix="/api/v1/ai/config")

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    def override_get_user() -> str:
        return "test-user"

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user_id] = override_get_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.fixture(autouse=True)
def _mock_refresh_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """防止 activate_config 触发真实 PostgreSQL 连接。"""

    async def _noop() -> None:
        pass

    monkeypatch.setattr(
        "app.services.ai.base.refresh_active_config_cache", _noop
    )


def _create_payload(
    name: str = "test-ollama",
    provider_type: str = "ollama",
    base_url: str = "http://localhost:11434",
    api_key: str = "",
    model: str = "qwen2.5-coder:7b",
    vlm_model: str = "",
    role: str = "llm",
) -> dict:
    """构造 POST 创建请求体。

    split-llm-vlm-config：``role="vlm"`` 时调用方应传 ``model=""`` +
    ``vlm_model="<视觉模型>"`` + ``role="vlm"``。
    """
    return {
        "name": name,
        "provider_type": provider_type,
        "base_url": base_url,
        "api_key": api_key,
        "model": model,
        "vlm_model": vlm_model,
        "role": role,
    }


# ===== 测试用例 =====


@pytest.mark.asyncio
async def test_list_configs_empty(app_client: AsyncClient) -> None:
    """空列表。"""
    resp = await app_client.get("/api/v1/ai/config")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_create_config(app_client: AsyncClient) -> None:
    """新增，返回 201 + 脱敏 api_key。"""
    payload = _create_payload(api_key="sk-secret-12345")
    resp = await app_client.post("/api/v1/ai/config", json=payload)
    assert resp.status_code == 201
    body = resp.json()
    assert body["id"] is not None
    assert body["name"] == "test-ollama"
    assert body["provider_type"] == "ollama"
    assert body["base_url"] == "http://localhost:11434"
    assert body["model"] == "qwen2.5-coder:7b"
    # api_key 脱敏
    assert body["api_key"] == "***"
    # 首条配置自动激活
    assert body["is_active"] is True


@pytest.mark.asyncio
async def test_create_config_validation_error(app_client: AsyncClient) -> None:
    """缺少必填字段返回 422。"""
    # 缺少 name 和 model（必填字段）
    payload = {
        "provider_type": "ollama",
        "base_url": "http://localhost:11434",
    }
    resp = await app_client.post("/api/v1/ai/config", json=payload)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_update_config(app_client: AsyncClient) -> None:
    """更新，返回脱敏 api_key。"""
    # 先创建
    create_resp = await app_client.post(
        "/api/v1/ai/config", json=_create_payload(api_key="sk-original")
    )
    assert create_resp.status_code == 201
    config_id = create_resp.json()["id"]

    # 更新
    update_resp = await app_client.put(
        f"/api/v1/ai/config/{config_id}",
        json={"name": "updated-name", "model": "new-model"},
    )
    assert update_resp.status_code == 200
    body = update_resp.json()
    assert body["name"] == "updated-name"
    assert body["model"] == "new-model"
    # api_key 仍脱敏（未修改密钥）
    assert body["api_key"] == "***"


@pytest.mark.asyncio
async def test_update_config_not_found(app_client: AsyncClient) -> None:
    """不存在返回 404。"""
    resp = await app_client.put(
        "/api/v1/ai/config/99999",
        json={"name": "x"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_config(app_client: AsyncClient) -> None:
    """删除返回 204。"""
    create_resp = await app_client.post(
        "/api/v1/ai/config", json=_create_payload()
    )
    config_id = create_resp.json()["id"]

    del_resp = await app_client.delete(f"/api/v1/ai/config/{config_id}")
    assert del_resp.status_code == 204

    # 删除后列表为空
    list_resp = await app_client.get("/api/v1/ai/config")
    assert list_resp.status_code == 200
    assert list_resp.json() == []


@pytest.mark.asyncio
async def test_delete_config_not_found(app_client: AsyncClient) -> None:
    """不存在返回 404。"""
    resp = await app_client.delete("/api/v1/ai/config/99999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_activate_config(app_client: AsyncClient) -> None:
    """激活，返回更新后的配置。"""
    # 创建两条配置
    c1_resp = await app_client.post(
        "/api/v1/ai/config", json=_create_payload(name="c1")
    )
    c2_resp = await app_client.post(
        "/api/v1/ai/config", json=_create_payload(name="c2")
    )
    c1_id = c1_resp.json()["id"]
    c2_id = c2_resp.json()["id"]

    # c1 首条自动激活
    assert c1_resp.json()["is_active"] is True
    assert c2_resp.json()["is_active"] is False

    # 激活 c2
    resp = await app_client.post(f"/api/v1/ai/config/{c2_id}/activate")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == c2_id
    assert body["is_active"] is True

    # 列表中 c1 不再激活
    list_resp = await app_client.get("/api/v1/ai/config")
    configs = {c["id"]: c for c in list_resp.json()}
    assert configs[c2_id]["is_active"] is True
    assert configs[c1_id]["is_active"] is False


@pytest.mark.asyncio
async def test_activate_config_not_found(app_client: AsyncClient) -> None:
    """不存在返回 404。"""
    resp = await app_client.post("/api/v1/ai/config/99999/activate")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_test_config_not_found(app_client: AsyncClient) -> None:
    """测试不存在的配置返回 404。"""
    resp = await app_client.post("/api/v1/ai/config/99999/test")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_test_config_success(
    app_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """测试连接成功（mock _probe_ollama 返回可用）。"""
    # 先创建 ollama 配置
    create_resp = await app_client.post(
        "/api/v1/ai/config", json=_create_payload()
    )
    config_id = create_resp.json()["id"]

    # mock 探测函数返回成功（签名需兼容 role kwarg）
    async def _mock_probe(base_url: str, model: str, vlm_model: str, role: str = "llm") -> dict:
        return {"available": True, "vlm_available": False}

    monkeypatch.setattr(
        "app.services.ai.config_store._probe_ollama", _mock_probe
    )

    resp = await app_client.post(f"/api/v1/ai/config/{config_id}/test")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True
    assert body["vlm_available"] is False
    assert body["error"] == ""


@pytest.mark.asyncio
async def test_api_key_desensitization(app_client: AsyncClient) -> None:
    """创建带 api_key 的配置，GET 返回 ***。"""
    create_resp = await app_client.post(
        "/api/v1/ai/config",
        json=_create_payload(name="with-key", api_key="sk-super-secret"),
    )
    assert create_resp.status_code == 201
    # POST 响应已脱敏
    assert create_resp.json()["api_key"] == "***"

    # GET 列表也脱敏
    list_resp = await app_client.get("/api/v1/ai/config")
    assert list_resp.status_code == 200
    configs = list_resp.json()
    assert len(configs) == 1
    assert configs[0]["api_key"] == "***"
    # 不泄露实际密钥
    assert "sk-super-secret" not in list_resp.text


# ===== split-llm-vlm-config：role 过滤 / VLM 创建 =====


@pytest.mark.asyncio
async def test_list_configs_role_filter(app_client: AsyncClient) -> None:
    """GET ?role=vlm 按 role 过滤；响应体含 role 字段。"""
    # 2 条 LLM（默认 role=llm）+ 1 条 VLM
    await app_client.post("/api/v1/ai/config", json=_create_payload(name="llm1"))
    await app_client.post("/api/v1/ai/config", json=_create_payload(name="llm2"))
    vlm_resp = await app_client.post(
        "/api/v1/ai/config",
        json=_create_payload(
            name="vlm1", model="", vlm_model="qwen2.5-vl:7b", role="vlm"
        ),
    )
    assert vlm_resp.status_code == 201

    # 不传 role 返回全部 3 条
    all_resp = await app_client.get("/api/v1/ai/config")
    assert all_resp.status_code == 200
    assert len(all_resp.json()) == 3

    # ?role=llm 只返回 2 条 LLM
    llm_resp = await app_client.get("/api/v1/ai/config?role=llm")
    assert llm_resp.status_code == 200
    llm_configs = llm_resp.json()
    assert len(llm_configs) == 2
    assert all(c["role"] == "llm" for c in llm_configs)

    # ?role=vlm 只返回 1 条 VLM，且 vlm_model 字段正确
    vlm_resp2 = await app_client.get("/api/v1/ai/config?role=vlm")
    assert vlm_resp2.status_code == 200
    vlm_configs = vlm_resp2.json()
    assert len(vlm_configs) == 1
    assert vlm_configs[0]["role"] == "vlm"
    assert vlm_configs[0]["vlm_model"] == "qwen2.5-vl:7b"
    assert vlm_configs[0]["model"] == ""


@pytest.mark.asyncio
async def test_create_vlm_config(app_client: AsyncClient) -> None:
    """POST 创建 VLM role 配置，返回 201 + role="vlm" + 首条 VLM 自动激活。"""
    payload = _create_payload(
        name="my-vlm",
        model="",
        vlm_model="llama3.2-vision:11b",
        role="vlm",
    )
    resp = await app_client.post("/api/v1/ai/config", json=payload)
    assert resp.status_code == 201
    body = resp.json()
    assert body["role"] == "vlm"
    assert body["vlm_model"] == "llama3.2-vision:11b"
    assert body["model"] == ""
    # 首条 VLM 自动激活
    assert body["is_active"] is True


@pytest.mark.asyncio
async def test_create_vlm_config_validation_error(app_client: AsyncClient) -> None:
    """role=vlm 但 vlm_model 为空时返回 422（schema 层校验）。"""
    payload = _create_payload(
        name="bad-vlm",
        model="",
        vlm_model="",
        role="vlm",
    )
    resp = await app_client.post("/api/v1/ai/config", json=payload)
    assert resp.status_code == 422
