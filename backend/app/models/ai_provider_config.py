"""AI Provider 配置 ORM 模型（Task 1.2 + split-llm-vlm-config）。

对应 ``ai_provider_configs`` 表：支持多 provider 配置共存 + 激活选择，
API key 经 Fernet 加密后存入 ``api_key_encrypted`` 列。

新增 ``role`` 字段（split-llm-vlm-config）：取值 ``"llm"`` / ``"vlm"``，
标识配置承担的文本模型或视觉模型角色。每个 role 内部独立维护激活状态
（LLM 与 VLM 各自最多一条 ``is_active=True``）。

遵循 SQLAlchemy 2.0 ``Mapped`` 注解风格，复用 ``app.database.Base``。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    """UTC 当前时间（SQLAlchemy default/onupdate 使用的 callable）。"""
    return datetime.now(timezone.utc)


class AIProviderConfig(Base):
    """统一的 AI Provider 配置记录。

    所有 provider（Ollama / OpenAI 兼容 / Anthropic）共用此表，通过
    ``provider_type`` 区分。``role`` 字段区分 ``"llm"``（文本模型）与
    ``"vlm"``（视觉模型），每个 role 内部由 ``config_store.activate_config``
    保证同一时刻最多一条 ``is_active=True``，LLM 与 VLM 互不影响。

    - ``role="llm"`` 的配置：``model`` 必填，``vlm_model`` 留空（不使用）。
    - ``role="vlm"`` 的配置：``vlm_model`` 必填，``model`` 留空（不使用），
      provider 实例化时 ``is_available()`` 检查 ``vlm_model``，``chat_with_image()``
      使用 ``vlm_model`` 作为模型名。
    """

    __tablename__ = "ai_provider_configs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    provider_type: Mapped[str] = mapped_column(String(50), nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    # Fernet 加密后的密文；本地模型（无 api_key）存空串
    api_key_encrypted: Mapped[str] = mapped_column(Text, nullable=False, default="")
    model: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    vlm_model: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # 角色字段：llm=文本模型 / vlm=视觉模型。每个 role 内独立激活。
    # 默认 "llm" 用于向后兼容现有配置（迁移逻辑会在 init_db 中补齐）。
    role: Mapped[str] = mapped_column(String(10), nullable=False, default="llm")
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return (
            f"<AIProviderConfig id={self.id} name={self.name!r} "
            f"provider_type={self.provider_type!r} role={self.role!r} "
            f"active={self.is_active}>"
        )
