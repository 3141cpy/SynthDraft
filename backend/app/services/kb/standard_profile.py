"""多套规范配置切换（SubTask 14.3）。

提供 ``StandardProfileManager`` 管理"国标集 / 企业标准集 / 行业标准集"等多套规范配置。

遵循"八荣八耻"原则：
- 以复用现有为荣：优先使用已有 PostgreSQL（``app.database``）；连接失败时降级到 JSON 文件持久化。
- 以实事求是为荣：降级路径如实标注，``backend`` 属性区分 ``"postgres"`` 与 ``"json"``。
- 以最小修改为荣：不修改已有数据库模型，仅新增本模块。

持久化策略：
1. 优先 PostgreSQL（``standard_profiles`` 表，运行时按需自动建表）
2. PostgreSQL 不可用时降级为 JSON 文件（默认 ``./tmp_state/standard_profiles.json``）
3. 活跃配置也可通过环境变量 ``STANDARD_PROFILE`` 覆盖

接口：
- ``list_profiles()``：列出所有配置
- ``get_active_profile()``：返回当前活跃配置
- ``set_active_profile(name)``：切换活跃配置
- ``create_profile(name, standards, ...)``：创建新配置
- ``delete_profile(name)``：删除配置
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings
from app.logging import get_logger
from app.schemas.kb import StandardProfile

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# 默认配置
# ---------------------------------------------------------------------------

DEFAULT_JSON_PATH = "./tmp_state/standard_profiles.json"
"""JSON 降级持久化路径（相对 backend cwd）。"""

ENV_ACTIVE_PROFILE = "STANDARD_PROFILE"
"""环境变量名：覆盖当前活跃配置。"""

DEFAULT_PROFILE_NAME = "default"
"""默认配置名（国标集）。"""

# 默认国标集（与 kb/standards/ 下已有样本对齐）
_DEFAULT_NATIONAL_STANDARDS = [
    "GB/T 1182-2018",
    "GB/T 131-2006",
    "GB/T 17450-1998",
    "GB/T 1804-2000",
    "GB/T 18229-2023",
    "GB/T 4457.4-2002",
]


# ---------------------------------------------------------------------------
# JSON 文件后端
# ---------------------------------------------------------------------------


class _JsonBackend:
    """JSON 文件持久化后端。"""

    def __init__(self, path: str | Path = DEFAULT_JSON_PATH) -> None:
        self._path = Path(path)
        self._lock = threading.RLock()
        self._ensure_dir()
        self._ensure_seed()

    def _ensure_dir(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def _ensure_seed(self) -> None:
        """首次初始化时种子默认配置。"""
        if self._path.is_file():
            return
        seed_profiles = [
            StandardProfile(
                name=DEFAULT_PROFILE_NAME,
                description="默认国标集（与 kb/standards/ 对齐）",
                standards=list(_DEFAULT_NATIONAL_STANDARDS),
                priority=10,
                created_at=_now_iso(),
                is_active=True,
            )
        ]
        self._write_all(seed_profiles, active=DEFAULT_PROFILE_NAME)

    def _read_all(self) -> tuple[list[StandardProfile], str]:
        """读取全部配置 + 活跃名。返回 (profiles, active_name)。"""
        with self._lock:
            if not self._path.is_file():
                return [], ""
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
            except Exception as e:  # noqa: BLE001
                log.warning("kb.standard_profile.json_read_failed", error=str(e))
                return [], ""
            profiles = [
                StandardProfile(**p) for p in data.get("profiles", [])
            ]
            active = data.get("active_profile", "")
            return profiles, active

    def _write_all(self, profiles: list[StandardProfile], active: str) -> None:
        with self._lock:
            data = {
                "profiles": [p.model_dump() for p in profiles],
                "active_profile": active,
                "updated_at": _now_iso(),
            }
            self._path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    # ===== 公共接口 =====

    def list_profiles(self) -> list[StandardProfile]:
        profiles, active = self._read_all()
        for p in profiles:
            p.is_active = (p.name == active)
        return profiles

    def get_active_name(self) -> str:
        _, active = self._read_all()
        return active

    def upsert_profile(self, profile: StandardProfile) -> None:
        profiles, active = self._read_all()
        # 替换或追加
        for i, p in enumerate(profiles):
            if p.name == profile.name:
                profiles[i] = profile
                break
        else:
            profiles.append(profile)
        self._write_all(profiles, active)

    def delete_profile(self, name: str) -> bool:
        profiles, active = self._read_all()
        new_profiles = [p for p in profiles if p.name != name]
        if len(new_profiles) == len(profiles):
            return False
        # 若删除的是活跃配置，回退到 default
        new_active = active if active != name else (
            DEFAULT_PROFILE_NAME if any(p.name == DEFAULT_PROFILE_NAME for p in new_profiles)
            else (new_profiles[0].name if new_profiles else "")
        )
        self._write_all(new_profiles, new_active)
        return True

    def set_active(self, name: str) -> bool:
        profiles, _ = self._read_all()
        if not any(p.name == name for p in profiles):
            return False
        self._write_all(profiles, name)
        return True


# ---------------------------------------------------------------------------
# PostgreSQL 后端（轻量同步封装，避免引入 async 调用复杂度）
# ---------------------------------------------------------------------------


class _PostgresBackend:
    """PostgreSQL 持久化后端。

    使用同步 psycopg2 风格的连接（从 settings.DATABASE_URL 派生 DSN）。
    若 asyncpg 不可用或表不存在且无法建表，构造时抛异常，由上层降级。
    """

    def __init__(self) -> None:
        try:
            import psycopg2  # type: ignore[import-not-found]
        except ImportError as e:
            raise RuntimeError("psycopg2 未安装") from e
        # 从 asyncpg URL 转换为 psycopg2 DSN
        dsn = self._convert_dsn(settings.DATABASE_URL)
        try:
            self._conn = psycopg2.connect(dsn)
            self._conn.autocommit = True
            self._ensure_table()
        except Exception as e:
            raise RuntimeError(f"PostgreSQL 连接失败：{e}") from e

    @staticmethod
    def _convert_dsn(asyncpg_url: str) -> str:
        """postgresql+asyncpg://user:pwd@host:port/db → host=... port=... user=... password=... dbname=..."""
        # 简化解析
        from urllib.parse import urlparse

        u = urlparse(asyncpg_url)
        return (
            f"host={u.hostname or 'localhost'} "
            f"port={u.port or 5432} "
            f"user={u.username or 'postgres'} "
            f"password={u.password or ''} "
            f"dbname={u.path.lstrip('/') or 'postgres'}"
        )

    def _ensure_table(self) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS standard_profiles (
                    name VARCHAR(128) PRIMARY KEY,
                    description TEXT DEFAULT '',
                    standards JSONB DEFAULT '[]'::jsonb,
                    priority INTEGER DEFAULT 0,
                    created_at VARCHAR(64) DEFAULT '',
                    is_active BOOLEAN DEFAULT FALSE
                )
                """
            )

    def list_profiles(self) -> list[StandardProfile]:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT name, description, standards, priority, created_at, is_active "
                "FROM standard_profiles ORDER BY priority DESC, name"
            )
            rows = cur.fetchall()
        return [
            StandardProfile(
                name=r[0],
                description=r[1] or "",
                standards=r[2] if isinstance(r[2], list) else json.loads(r[2] or "[]"),
                priority=r[3] or 0,
                created_at=r[4] or "",
                is_active=bool(r[5]),
            )
            for r in rows
        ]

    def get_active_name(self) -> str:
        with self._conn.cursor() as cur:
            cur.execute("SELECT name FROM standard_profiles WHERE is_active = TRUE LIMIT 1")
            row = cur.fetchone()
        return row[0] if row else ""

    def upsert_profile(self, profile: StandardProfile) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO standard_profiles (name, description, standards, priority, created_at, is_active)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (name) DO UPDATE SET
                    description = EXCLUDED.description,
                    standards = EXCLUDED.standards,
                    priority = EXCLUDED.priority,
                    created_at = EXCLUDED.created_at,
                    is_active = EXCLUDED.is_active
                """,
                (
                    profile.name,
                    profile.description,
                    json.dumps(profile.standards, ensure_ascii=False),
                    profile.priority,
                    profile.created_at,
                    profile.is_active,
                ),
            )

    def delete_profile(self, name: str) -> bool:
        with self._conn.cursor() as cur:
            cur.execute("DELETE FROM standard_profiles WHERE name = %s", (name,))
            return cur.rowcount > 0

    def set_active(self, name: str) -> bool:
        with self._conn.cursor() as cur:
            cur.execute("SELECT 1 FROM standard_profiles WHERE name = %s", (name,))
            if cur.fetchone() is None:
                return False
            cur.execute("UPDATE standard_profiles SET is_active = FALSE")
            cur.execute("UPDATE standard_profiles SET is_active = TRUE WHERE name = %s", (name,))
        return True


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


class StandardProfileManager:
    """多套规范配置管理器。

    用法：
        mgr = StandardProfileManager()
        mgr.create_profile(name="enterprise_a", standards=["Q/XX 001-2024", "GB/T 1182-2018"])
        mgr.set_active_profile("enterprise_a")
        active = mgr.get_active_profile()
    """

    _instance: "StandardProfileManager | None" = None
    _lock = threading.Lock()

    def __new__(cls, *args: Any, **kwargs: Any) -> "StandardProfileManager":
        # 接受并忽略 *args/**kwargs（如 json_path），由 __init__ 处理；
        # 这样允许测试代码 StandardProfileManager(json_path=...) 首次构造时不报错。
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False  # type: ignore[attr-defined]
        return cls._instance

    def __init__(self, json_path: str | Path | None = None) -> None:
        if getattr(self, "_initialized", False):
            # 已初始化的单例：若传入新 json_path，则重置后端以尊重调用方意图
            # （主要服务于测试场景，生产环境通常不传 json_path）。
            if json_path is not None:
                self._json_path = Path(json_path)
                self._init_backend()
            return
        self._backend: Any = None
        self._backend_name: str = ""
        self._json_path = Path(json_path) if json_path else Path(DEFAULT_JSON_PATH)
        self._init_backend()
        self._initialized = True

    def _init_backend(self) -> None:
        """初始化持久化后端：优先 PostgreSQL，失败降级 JSON 文件。"""
        # 尝试 PostgreSQL
        try:
            self._backend = _PostgresBackend()
            self._backend_name = "postgres"
            log.info("kb.standard_profile.backend", backend="postgres")
            return
        except Exception as e:  # noqa: BLE001
            log.warning(
                "kb.standard_profile.postgres_unavailable",
                error=str(e),
                fallback="json",
            )
        # 降级 JSON
        try:
            self._backend = _JsonBackend(self._json_path)
            self._backend_name = "json"
            log.info("kb.standard_profile.backend", backend="json", path=str(self._json_path))
        except Exception as e:  # noqa: BLE001
            log.error("kb.standard_profile.json_init_failed", error=str(e))
            raise RuntimeError(f"无法初始化任何后端：{e}") from e

    @property
    def backend_name(self) -> str:
        """当前后端名称（postgres / json）。"""
        return self._backend_name

    def reset(self, json_path: str | Path | None = None) -> None:
        """重置后端（测试用）。"""
        self._json_path = Path(json_path) if json_path else self._json_path
        self._init_backend()

    # ===== 公共接口 =====

    def list_profiles(self) -> list[StandardProfile]:
        """列出所有配置。"""
        profiles = self._backend.list_profiles()
        active_name = self._resolve_active_name()
        for p in profiles:
            p.is_active = (p.name == active_name)
        # 按 priority 降序、name 升序
        profiles.sort(key=lambda x: (-x.priority, x.name))
        return profiles

    def get_active_profile(self) -> StandardProfile | None:
        """返回当前活跃配置。优先环境变量 ``STANDARD_PROFILE`` 覆盖。"""
        active_name = self._resolve_active_name()
        if not active_name:
            return None
        for p in self._backend.list_profiles():
            if p.name == active_name:
                p.is_active = True
                return p
        # 环境变量指向不存在的配置 → 返回 None
        return None

    def set_active_profile(self, name: str) -> bool:
        """切换当前活跃配置。

        Args:
            name: 配置名

        Returns:
            True 切换成功；False 配置不存在
        """
        ok = self._backend.set_active(name)
        if ok:
            log.info("kb.standard_profile.active_set", name=name, backend=self._backend_name)
        else:
            log.warning("kb.standard_profile.set_active_failed", name=name)
        return ok

    def create_profile(
        self,
        name: str,
        standards: list[str] | None = None,
        description: str = "",
        priority: int = 0,
    ) -> StandardProfile:
        """创建或更新配置（同名覆盖）。"""
        profile = StandardProfile(
            name=name,
            description=description,
            standards=standards or [],
            priority=priority,
            created_at=_now_iso(),
            is_active=False,
        )
        self._backend.upsert_profile(profile)
        log.info(
            "kb.standard_profile.created",
            name=name,
            standards_count=len(profile.standards),
            backend=self._backend_name,
        )
        return profile

    def delete_profile(self, name: str) -> bool:
        """删除配置。活跃配置被删除时自动回退到 default。"""
        if name == DEFAULT_PROFILE_NAME:
            log.warning("kb.standard_profile.delete_default_skipped", name=name)
            return False
        ok = self._backend.delete_profile(name)
        if ok:
            log.info("kb.standard_profile.deleted", name=name, backend=self._backend_name)
        return ok

    # ===== 内部 =====

    def _resolve_active_name(self) -> str:
        """解析当前活跃配置名：环境变量优先，其次后端持久化值。"""
        env_name = os.environ.get(ENV_ACTIVE_PROFILE, "").strip()
        if env_name:
            return env_name
        return self._backend.get_active_name()


def _now_iso() -> str:
    """当前 UTC 时间 ISO 格式字符串。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# 模块级便捷函数
# ---------------------------------------------------------------------------


def get_manager() -> StandardProfileManager:
    """获取全局 StandardProfileManager 单例。"""
    return StandardProfileManager()


def list_profiles() -> list[StandardProfile]:
    """便捷函数：列出所有配置。"""
    return get_manager().list_profiles()


def get_active_profile() -> StandardProfile | None:
    """便捷函数：获取当前活跃配置。"""
    return get_manager().get_active_profile()


def set_active_profile(name: str) -> bool:
    """便捷函数：切换活跃配置。"""
    return get_manager().set_active_profile(name)


def create_profile(
    name: str,
    standards: list[str] | None = None,
    description: str = "",
    priority: int = 0,
) -> StandardProfile:
    """便捷函数：创建配置。"""
    return get_manager().create_profile(
        name=name, standards=standards, description=description, priority=priority
    )
