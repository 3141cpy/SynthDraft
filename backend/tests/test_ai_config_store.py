"""Task 7.1: AI Provider 配置存取服务（config_store）单元测试。

覆盖 config_store.py 的 CRUD、加解密、激活切换、连接测试、.env 迁移逻辑，
含 split-llm-vlm-config 的 role 过滤、role 内互斥激活、独立激活等场景。
使用内存 SQLite（aiosqlite）隔离测试，每个用例独立 engine/session。

测试用例（17 个）：
1. test_create_config — 新增配置，验证字段正确存储
2. test_create_config_auto_activate_first — 首条配置自动激活
3. test_list_configs — 列表按 id 升序
4. test_get_config — 按 id 获取，不存在返回 None
5. test_get_active_config — 获取激活配置
6. test_update_config — 更新字段，api_key=None 不修改密钥
7. test_update_config_api_key_empty — 更新 api_key 为空串（清空密钥）
8. test_update_config_not_found — 更新不存在配置返回 None
9. test_delete_config — 删除配置
10. test_activate_config — 激活指定配置，其他配置自动取消激活
11. test_api_key_encryption — 存入密文，读出明文
12. test_migrate_from_env_ollama — .env 迁移（ollama provider）
13. test_migrate_from_env_skip_when_db_not_empty — 数据库非空时不迁移
14. test_test_config_not_found — 测试不存在配置返回 available=False
15. test_list_configs_role_filter — 按 role 过滤列表
16. test_create_config_vlm_role — 创建 VLM role 配置
17. test_activate_config_role_isolation — LLM/VLM 激活互不影响
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import pytest_asyncio

# 确保 backend/ 在 sys.path
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.ai_provider_config import AIProviderConfig  # noqa: F401 — 注册模型到 metadata
from app.schemas.ai_config import AIProviderConfigCreate, AIProviderConfigUpdate
from app.security import decrypt_value
from app.services.ai import config_store


# ===== Fixtures =====


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    """内存 SQLite 异步 session（每用例独立 engine，完全隔离）。

    使用 StaticPool 确保所有连接共享同一内存数据库（默认 pool 每个 connection
    一个独立内存库，会导致 create_all 建的表在 session 中不可见）。
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture(autouse=True)
def _mock_refresh_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """防止 activate_config 触发真实 PostgreSQL 连接。

    activate_config 内部调用 base.refresh_active_config_cache()，该函数通过
    app.database.async_session_factory 连接 PostgreSQL。测试环境下 PostgreSQL
    不可达，虽被 try/except 兜底但会拖慢测试。此处替换为 no-op。
    """

    async def _noop() -> None:
        pass

    monkeypatch.setattr(
        "app.services.ai.base.refresh_active_config_cache", _noop
    )


def _make_create(
    name: str = "test-ollama",
    provider_type: str = "ollama",
    base_url: str = "http://localhost:11434",
    api_key: str = "",
    model: str = "qwen2.5-coder:7b",
    vlm_model: str = "",
    role: str = "llm",
) -> AIProviderConfigCreate:
    """构造 AIProviderConfigCreate 测试数据。

    split-llm-vlm-config：``role="llm"`` 时填 ``model``；``role="vlm"`` 时
    调用方应传 ``model=""`` + ``vlm_model="<视觉模型>"`` + ``role="vlm"``。
    """
    return AIProviderConfigCreate(
        name=name,
        provider_type=provider_type,
        base_url=base_url,
        api_key=api_key,
        model=model,
        vlm_model=vlm_model,
        role=role,  # type: ignore[arg-type]
    )


# ===== CRUD =====


@pytest.mark.asyncio
async def test_create_config(db_session: AsyncSession) -> None:
    """新增配置，验证字段正确存储。"""
    data = _make_create(api_key="secret-key")
    config = await config_store.create_config(db_session, data)
    assert config.id is not None
    assert config.name == "test-ollama"
    assert config.provider_type == "ollama"
    assert config.base_url == "http://localhost:11434"
    assert config.model == "qwen2.5-coder:7b"
    assert config.vlm_model == ""
    # api_key 加密存储（密文非明文、非空）
    assert config.api_key_encrypted != "secret-key"
    assert config.api_key_encrypted != ""
    # 首条配置自动激活
    assert config.is_active is True


@pytest.mark.asyncio
async def test_create_config_auto_activate_first(db_session: AsyncSession) -> None:
    """首条配置自动激活，第二条不自动激活。"""
    first = await config_store.create_config(db_session, _make_create(name="first"))
    assert first.is_active is True

    second = await config_store.create_config(db_session, _make_create(name="second"))
    assert second.is_active is False
    # 首条仍激活
    refetched = await config_store.get_config(db_session, first.id)
    assert refetched is not None
    assert refetched.is_active is True


@pytest.mark.asyncio
async def test_list_configs(db_session: AsyncSession) -> None:
    """列表按 id 升序。"""
    c1 = await config_store.create_config(db_session, _make_create(name="c1"))
    c2 = await config_store.create_config(db_session, _make_create(name="c2"))
    c3 = await config_store.create_config(db_session, _make_create(name="c3"))
    configs = await config_store.list_configs(db_session)
    assert len(configs) == 3
    assert [c.id for c in configs] == [c1.id, c2.id, c3.id]


@pytest.mark.asyncio
async def test_get_config(db_session: AsyncSession) -> None:
    """按 id 获取，不存在返回 None。"""
    created = await config_store.create_config(db_session, _make_create())
    found = await config_store.get_config(db_session, created.id)
    assert found is not None
    assert found.id == created.id
    assert found.name == "test-ollama"

    missing = await config_store.get_config(db_session, 99999)
    assert missing is None


@pytest.mark.asyncio
async def test_get_active_config(db_session: AsyncSession) -> None:
    """获取激活配置。"""
    c1 = await config_store.create_config(db_session, _make_create(name="c1"))
    c2 = await config_store.create_config(db_session, _make_create(name="c2"))

    # 首条自动激活
    active = await config_store.get_active_config(db_session)
    assert active is not None
    assert active.id == c1.id

    # 切换激活到 c2
    await config_store.activate_config(db_session, c2.id)
    active = await config_store.get_active_config(db_session)
    assert active is not None
    assert active.id == c2.id


@pytest.mark.asyncio
async def test_update_config(db_session: AsyncSession) -> None:
    """更新字段，api_key=None 不修改密钥。"""
    config = await config_store.create_config(
        db_session, _make_create(api_key="original-key")
    )
    original_encrypted = config.api_key_encrypted

    update = AIProviderConfigUpdate(
        name="updated-name",
        model="new-model",
        api_key=None,  # None 表示不修改密钥
    )
    updated = await config_store.update_config(db_session, config.id, update)
    assert updated is not None
    assert updated.name == "updated-name"
    assert updated.model == "new-model"
    # 密钥未变
    assert updated.api_key_encrypted == original_encrypted
    assert decrypt_value(updated.api_key_encrypted) == "original-key"


@pytest.mark.asyncio
async def test_update_config_api_key_empty(db_session: AsyncSession) -> None:
    """更新 api_key 为空串（清空密钥）。"""
    config = await config_store.create_config(
        db_session, _make_create(api_key="original-key")
    )
    assert config.api_key_encrypted != ""

    update = AIProviderConfigUpdate(api_key="")  # 显式空串清空密钥
    updated = await config_store.update_config(db_session, config.id, update)
    assert updated is not None
    assert updated.api_key_encrypted == ""
    assert decrypt_value(updated.api_key_encrypted) == ""


@pytest.mark.asyncio
async def test_update_config_not_found(db_session: AsyncSession) -> None:
    """更新不存在的配置返回 None。"""
    update = AIProviderConfigUpdate(name="x")
    result = await config_store.update_config(db_session, 99999, update)
    assert result is None


@pytest.mark.asyncio
async def test_delete_config(db_session: AsyncSession) -> None:
    """删除配置。"""
    config = await config_store.create_config(db_session, _make_create())
    ok = await config_store.delete_config(db_session, config.id)
    assert ok is True

    # 删除后查不到
    missing = await config_store.get_config(db_session, config.id)
    assert missing is None

    # 再删一次返回 False
    ok2 = await config_store.delete_config(db_session, config.id)
    assert ok2 is False


@pytest.mark.asyncio
async def test_activate_config(db_session: AsyncSession) -> None:
    """激活指定配置，其他配置自动取消激活。"""
    c1 = await config_store.create_config(db_session, _make_create(name="c1"))
    c2 = await config_store.create_config(db_session, _make_create(name="c2"))
    c3 = await config_store.create_config(db_session, _make_create(name="c3"))

    # 初始 c1 激活
    assert c1.is_active is True

    # 激活 c2
    activated = await config_store.activate_config(db_session, c2.id)
    assert activated is not None
    assert activated.id == c2.id
    assert activated.is_active is True

    # c1 不再激活
    refetched_c1 = await config_store.get_config(db_session, c1.id)
    assert refetched_c1 is not None
    assert refetched_c1.is_active is False

    # 激活 c3，c2 取消
    await config_store.activate_config(db_session, c3.id)
    active = await config_store.get_active_config(db_session)
    assert active is not None
    assert active.id == c3.id


@pytest.mark.asyncio
async def test_activate_config_not_found(db_session: AsyncSession) -> None:
    """激活不存在的配置返回 None。"""
    result = await config_store.activate_config(db_session, 99999)
    assert result is None


# ===== 加解密 =====


@pytest.mark.asyncio
async def test_api_key_encryption(db_session: AsyncSession) -> None:
    """存入密文，读出明文（通过 decrypt_value 验证）。"""
    config = await config_store.create_config(
        db_session, _make_create(api_key="sk-test-12345")
    )
    # 数据库中存的是密文，不是明文
    assert config.api_key_encrypted != "sk-test-12345"
    assert config.api_key_encrypted != ""
    # decrypt_value 能还原明文
    assert decrypt_value(config.api_key_encrypted) == "sk-test-12345"

    # 无 api_key 的配置（本地模型）存空串
    local = await config_store.create_config(
        db_session, _make_create(name="local", api_key="")
    )
    assert local.api_key_encrypted == ""
    assert decrypt_value(local.api_key_encrypted) == ""


# ===== .env 迁移 =====


@pytest.mark.asyncio
async def test_migrate_from_env_ollama(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ .env 迁移（ollama provider）。"""
    from app.config import settings

    monkeypatch.setattr(settings, "LLM_PROVIDER", "ollama")
    monkeypatch.setattr(settings, "OLLAMA_HOST_URL", "http://localhost:11434")
    monkeypatch.setattr(settings, "LLM_MODEL", "qwen2.5-coder:7b")

    count = await config_store.migrate_from_env(db_session)
    assert count == 1

    configs = await config_store.list_configs(db_session)
    assert len(configs) == 1
    migrated = configs[0]
    assert migrated.provider_type == "ollama"
    assert migrated.base_url == "http://localhost:11434"
    assert migrated.model == "qwen2.5-coder:7b"
    assert migrated.is_active is True  # 迁移配置自动激活


@pytest.mark.asyncio
async def test_migrate_from_env_skip_when_db_not_empty(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """数据库非空时不迁移。"""
    # 先建一条配置
    await config_store.create_config(db_session, _make_create())

    from app.config import settings

    monkeypatch.setattr(settings, "LLM_PROVIDER", "ollama")

    count = await config_store.migrate_from_env(db_session)
    assert count == 0

    # 仍是原来那条
    configs = await config_store.list_configs(db_session)
    assert len(configs) == 1


# ===== 连接测试 =====


@pytest.mark.asyncio
async def test_test_config_not_found(db_session: AsyncSession) -> None:
    """测试不存在配置返回 available=False。"""
    result = await config_store.test_config(db_session, 99999)
    assert result.available is False
    assert result.vlm_available is False
    assert result.error  # 非空错误信息
    assert "不存在" in result.error


# ===== split-llm-vlm-config：role 过滤 / 隔离激活 =====


@pytest.mark.asyncio
async def test_list_configs_role_filter(db_session: AsyncSession) -> None:
    """按 role 过滤列表：``role="llm"`` 只返回 LLM 配置，``role="vlm"`` 同理。"""
    # 2 条 LLM + 1 条 VLM
    llm1 = await config_store.create_config(db_session, _make_create(name="llm1"))
    llm2 = await config_store.create_config(db_session, _make_create(name="llm2"))
    vlm1 = await config_store.create_config(
        db_session,
        _make_create(
            name="vlm1",
            model="",
            vlm_model="qwen2.5-vl:7b",
            role="vlm",
        ),
    )

    # 不传 role 返回全部
    all_configs = await config_store.list_configs(db_session)
    assert len(all_configs) == 3

    # role="llm" 只返回 2 条 LLM
    llm_configs = await config_store.list_configs(db_session, role="llm")
    assert len(llm_configs) == 2
    assert {c.id for c in llm_configs} == {llm1.id, llm2.id}
    assert all(c.role == "llm" for c in llm_configs)

    # role="vlm" 只返回 1 条 VLM
    vlm_configs = await config_store.list_configs(db_session, role="vlm")
    assert len(vlm_configs) == 1
    assert vlm_configs[0].id == vlm1.id
    assert vlm_configs[0].role == "vlm"
    assert vlm_configs[0].vlm_model == "qwen2.5-vl:7b"


@pytest.mark.asyncio
async def test_create_config_vlm_role(db_session: AsyncSession) -> None:
    """创建 VLM role 配置：role 字段正确持久化，首条 VLM 自动激活。"""
    vlm = await config_store.create_config(
        db_session,
        _make_create(
            name="my-vlm",
            model="",
            vlm_model="llama3.2-vision:11b",
            role="vlm",
        ),
    )
    assert vlm.role == "vlm"
    assert vlm.vlm_model == "llama3.2-vision:11b"
    assert vlm.model == ""
    # 首条 VLM 自动激活
    assert vlm.is_active is True

    # 通过 get_active_config(role="vlm") 可取到
    active_vlm = await config_store.get_active_config(db_session, role="vlm")
    assert active_vlm is not None
    assert active_vlm.id == vlm.id

    # get_active_config(role="llm") 此时为 None（无 LLM 配置）
    active_llm = await config_store.get_active_config(db_session, role="llm")
    assert active_llm is None


@pytest.mark.asyncio
async def test_activate_config_role_isolation(db_session: AsyncSession) -> None:
    """LLM 与 VLM 激活互不影响：切换 LLM 激活不影响 VLM，反之亦然。"""
    # 2 条 LLM + 2 条 VLM
    llm1 = await config_store.create_config(db_session, _make_create(name="llm1"))
    llm2 = await config_store.create_config(db_session, _make_create(name="llm2"))
    vlm1 = await config_store.create_config(
        db_session,
        _make_create(
            name="vlm1", model="", vlm_model="vlm-a", role="vlm"
        ),
    )
    vlm2 = await config_store.create_config(
        db_session,
        _make_create(
            name="vlm2", model="", vlm_model="vlm-b", role="vlm"
        ),
    )

    # 初始：每个 role 首条自动激活
    assert llm1.is_active is True
    assert vlm1.is_active is True
    assert llm2.is_active is False
    assert vlm2.is_active is False

    # 切换 LLM 激活到 llm2 —— VLM 激活状态应不变
    await config_store.activate_config(db_session, llm2.id)
    active_llm = await config_store.get_active_config(db_session, role="llm")
    active_vlm = await config_store.get_active_config(db_session, role="vlm")
    assert active_llm is not None and active_llm.id == llm2.id
    assert active_vlm is not None and active_vlm.id == vlm1.id  # VLM 未受影响

    # 切换 VLM 激活到 vlm2 —— LLM 激活状态应不变
    await config_store.activate_config(db_session, vlm2.id)
    active_llm = await config_store.get_active_config(db_session, role="llm")
    active_vlm = await config_store.get_active_config(db_session, role="vlm")
    assert active_llm is not None and active_llm.id == llm2.id  # LLM 未受影响
    assert active_vlm is not None and active_vlm.id == vlm2.id
