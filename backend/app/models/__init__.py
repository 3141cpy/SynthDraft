"""SQLAlchemy ORM 模型包。

导入本包即触发各模型模块加载，使其映射类注册到 ``app.database.Base.metadata``。
``app.database.init_db()`` 依赖此注册完成 ``create_all`` 建表。
"""

from __future__ import annotations

from app.models.ai_provider_config import AIProviderConfig

__all__ = ["AIProviderConfig"]
