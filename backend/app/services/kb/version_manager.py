"""规范版本管理与更新通知（SubTask 15.3）。

提供两个核心类：
- ``StandardVersionManager``：管理规范的多版本记录
    - ``register_version(standard_id, version, release_date, status)``：注册新版本
    - ``list_versions(standard_id)``：列出某规范的所有版本
    - ``get_latest_version(standard_id)``：获取最新 active 版本
    - ``deprecate_version(standard_id, version)``：废弃旧版本
    - ``compare_versions(standard_id, v1, v2)``：对比两版本条款差异
- ``UpdateNotifier``：基于版本变更生成"更新通知"
    - ``notify_subscribers(standard_id, new_version, old_version, message)``：
      创建通知（自动写入持久化后端）
    - ``list_notifications(only_unread=False)``：列出通知
    - ``mark_read(notification_id)``：标记已读

持久化策略（遵循"以复用现有为荣"+"以实事求是为荣"原则）：
1. 优先 PostgreSQL（``standard_versions`` / ``standard_notifications`` 表，运行时自动建表）
2. PostgreSQL 不可用时降级到 JSON 文件（默认 ``./tmp_state/standard_versions.json``
   与 ``./tmp_state/standard_notifications.json``）
3. ``backend_name`` 属性如实标注当前后端（``postgres`` / ``json``）

版本对比说明（实事求是原则）：
``compare_versions`` 仅基于"已注册到本管理器的版本元数据 + Qdrant 中已索引的条款"
做条款号集合差异对比（added / removed / modified）。
- ``added``：v2 中存在而 v1 中不存在的 clause_id
- ``removed``：v1 中存在而 v2 中不存在的 clause_id
- ``modified``：两版本同 clause_id 但 ``original_text`` 哈希不同（需 Qdrant 有索引数据）
当 Qdrant 不可用或某版本未索引时，对应字段返回空列表，并在 ``note`` 中如实标注。
"""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings
from app.logging import get_logger
from app.schemas.kb import (
    StandardNotification,
    StandardStatus,
    StandardVersion,
    VersionDiff,
)

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# 默认配置
# ---------------------------------------------------------------------------

DEFAULT_VERSIONS_JSON_PATH = "./tmp_state/standard_versions.json"
DEFAULT_NOTIFICATIONS_JSON_PATH = "./tmp_state/standard_notifications.json"


def _now_iso() -> str:
    """当前 UTC 时间 ISO 格式字符串。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_id(prefix: str = "n") -> str:
    """生成短 ID。"""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _strip_year(standard_id: str) -> str:
    """去除规范编号末尾年份，得到基线编号。

    示例：
        'GB/T 4458.4-2003' → 'GB/T 4458.4'
        'ISO 128-1:2003'   → 'ISO 128-1'
        'JB/T 8836-2023'   → 'JB/T 8836'
    """
    sid = standard_id.strip()
    # 兼容 'ISO 128-1:2003' 与 'GB/T 4458.4-2003' 两种年份分隔符
    for sep in (":", "-"):
        idx = sid.rfind(sep)
        if idx > 0:
            tail = sid[idx + 1 :].strip()
            if tail.isdigit() and len(tail) == 4:
                return sid[:idx].strip()
    return sid


# ---------------------------------------------------------------------------
# 版本管理后端：JSON
# ---------------------------------------------------------------------------


class _VersionsJsonBackend:
    """版本记录 JSON 文件持久化后端。"""

    def __init__(self, path: str | Path = DEFAULT_VERSIONS_JSON_PATH) -> None:
        self._path = Path(path)
        self._lock = threading.RLock()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.is_file():
            self._path.write_text("{}", encoding="utf-8")

    def _read(self) -> dict[str, list[dict[str, Any]]]:
        with self._lock:
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except Exception as e:  # noqa: BLE001
                log.warning("kb.version_manager.versions_json_read_failed", error=str(e))
                return {}

    def _write(self, data: dict[str, list[dict[str, Any]]]) -> None:
        with self._lock:
            self._path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    def list_versions(self, standard_id: str) -> list[StandardVersion]:
        sid = _strip_year(standard_id)
        data = self._read()
        items = data.get(sid, [])
        return [StandardVersion(**item) for item in items]

    def upsert_version(self, version: StandardVersion) -> None:
        sid = _strip_year(version.standard_id)
        data = self._read()
        items = data.setdefault(sid, [])
        # 同 version 年份覆盖
        for i, item in enumerate(items):
            if item.get("version") == version.version:
                items[i] = version.model_dump()
                break
        else:
            items.append(version.model_dump())
        self._write(data)

    def delete_version(self, standard_id: str, version: str) -> bool:
        sid = _strip_year(standard_id)
        data = self._read()
        items = data.get(sid, [])
        new_items = [it for it in items if it.get("version") != version]
        if len(new_items) == len(items):
            return False
        data[sid] = new_items
        self._write(data)
        return True


class _NotificationsJsonBackend:
    """更新通知 JSON 文件持久化后端。"""

    def __init__(
        self, path: str | Path = DEFAULT_NOTIFICATIONS_JSON_PATH
    ) -> None:
        self._path = Path(path)
        self._lock = threading.RLock()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.is_file():
            self._path.write_text("[]", encoding="utf-8")

    def _read(self) -> list[dict[str, Any]]:
        with self._lock:
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except Exception as e:  # noqa: BLE001
                log.warning("kb.version_manager.notif_json_read_failed", error=str(e))
                return []

    def _write(self, data: list[dict[str, Any]]) -> None:
        with self._lock:
            self._path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    def list_all(self) -> list[StandardNotification]:
        return [StandardNotification(**item) for item in self._read()]

    def add(self, notification: StandardNotification) -> None:
        items = self._read()
        items.append(notification.model_dump())
        self._write(items)

    def mark_read(self, notification_id: str) -> bool:
        items = self._read()
        for item in items:
            if item.get("notification_id") == notification_id:
                item["is_read"] = True
                self._write(items)
                return True
        return False


# ---------------------------------------------------------------------------
# 版本管理后端：PostgreSQL
# ---------------------------------------------------------------------------


class _VersionsPostgresBackend:
    """PostgreSQL 持久化后端（版本 + 通知共用一个连接）。

    连接失败时抛 RuntimeError，由上层降级到 JSON。
    """

    def __init__(self) -> None:
        try:
            import psycopg2  # type: ignore[import-not-found]
        except ImportError as e:
            raise RuntimeError("psycopg2 未安装") from e

        dsn = self._convert_dsn(settings.DATABASE_URL)
        try:
            self._conn = psycopg2.connect(dsn)
            self._conn.autocommit = True
            self._ensure_tables()
        except Exception as e:
            raise RuntimeError(f"PostgreSQL 连接失败：{e}") from e

    @staticmethod
    def _convert_dsn(asyncpg_url: str) -> str:
        from urllib.parse import urlparse

        u = urlparse(asyncpg_url)
        return (
            f"host={u.hostname or 'localhost'} "
            f"port={u.port or 5432} "
            f"user={u.username or 'postgres'} "
            f"password={u.password or ''} "
            f"dbname={u.path.lstrip('/') or 'postgres'}"
        )

    def _ensure_tables(self) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS standard_versions (
                    standard_id VARCHAR(128) NOT NULL,
                    version VARCHAR(32) NOT NULL,
                    release_date VARCHAR(64) DEFAULT '',
                    status VARCHAR(32) DEFAULT 'active',
                    notes TEXT DEFAULT '',
                    registered_at VARCHAR(64) DEFAULT '',
                    PRIMARY KEY (standard_id, version)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS standard_notifications (
                    notification_id VARCHAR(128) PRIMARY KEY,
                    standard_id VARCHAR(128) NOT NULL,
                    new_version VARCHAR(32) NOT NULL,
                    old_version VARCHAR(32) DEFAULT '',
                    message TEXT DEFAULT '',
                    created_at VARCHAR(64) DEFAULT '',
                    is_read BOOLEAN DEFAULT FALSE
                )
                """
            )

    # ===== 版本接口 =====

    def list_versions(self, standard_id: str) -> list[StandardVersion]:
        sid = _strip_year(standard_id)
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT standard_id, version, release_date, status, notes, registered_at "
                "FROM standard_versions WHERE standard_id = %s "
                "ORDER BY version DESC",
                (sid,),
            )
            rows = cur.fetchall()
        return [
            StandardVersion(
                standard_id=r[0],
                version=r[1],
                release_date=r[2] or "",
                status=r[3] or "active",
                notes=r[4] or "",
                registered_at=r[5] or "",
            )
            for r in rows
        ]

    def upsert_version(self, version: StandardVersion) -> None:
        sid = _strip_year(version.standard_id)
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO standard_versions
                    (standard_id, version, release_date, status, notes, registered_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (standard_id, version) DO UPDATE SET
                    release_date = EXCLUDED.release_date,
                    status = EXCLUDED.status,
                    notes = EXCLUDED.notes,
                    registered_at = EXCLUDED.registered_at
                """,
                (
                    sid,
                    version.version,
                    version.release_date,
                    version.status,
                    version.notes,
                    version.registered_at,
                ),
            )

    def delete_version(self, standard_id: str, version: str) -> bool:
        sid = _strip_year(standard_id)
        with self._conn.cursor() as cur:
            cur.execute(
                "DELETE FROM standard_versions "
                "WHERE standard_id = %s AND version = %s",
                (sid, version),
            )
            return cur.rowcount > 0

    # ===== 通知接口 =====

    def list_all_notifications(self) -> list[StandardNotification]:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT notification_id, standard_id, new_version, old_version, "
                "message, created_at, is_read FROM standard_notifications "
                "ORDER BY created_at DESC"
            )
            rows = cur.fetchall()
        return [
            StandardNotification(
                notification_id=r[0],
                standard_id=r[1],
                new_version=r[2],
                old_version=r[3] or "",
                message=r[4] or "",
                created_at=r[5] or "",
                is_read=bool(r[6]),
            )
            for r in rows
        ]

    def add_notification(self, notification: StandardNotification) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO standard_notifications
                    (notification_id, standard_id, new_version, old_version,
                     message, created_at, is_read)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (notification_id) DO UPDATE SET
                    is_read = EXCLUDED.is_read
                """,
                (
                    notification.notification_id,
                    notification.standard_id,
                    notification.new_version,
                    notification.old_version,
                    notification.message,
                    notification.created_at,
                    notification.is_read,
                ),
            )

    def mark_read(self, notification_id: str) -> bool:
        with self._conn.cursor() as cur:
            cur.execute(
                "UPDATE standard_notifications SET is_read = TRUE "
                "WHERE notification_id = %s",
                (notification_id,),
            )
            return cur.rowcount > 0

    # ===== 与 _NotificationsJsonBackend 对齐的别名方法 =====
    # UpdateNotifier 复用本类作为 Postgres 后端，但调用的是
    # _NotificationsJsonBackend 的方法名（add / list_all）。
    # 这里提供别名，避免 AttributeError 导致降级到 JSON。

    def add(self, notification: StandardNotification) -> None:
        self.add_notification(notification)

    def list_all(self) -> list[StandardNotification]:
        return self.list_all_notifications()


# ---------------------------------------------------------------------------
# StandardVersionManager
# ---------------------------------------------------------------------------


class StandardVersionManager:
    """规范版本管理器。

    用法：
        mgr = StandardVersionManager()
        mgr.register_version("GB/T 4458.4", "2003", release_date="2003-01-01")
        mgr.register_version("GB/T 4458.4", "2024", release_date="2024-06-01")
        latest = mgr.get_latest_version("GB/T 4458.4")
        mgr.deprecate_version("GB/T 4458.4", "2003")
        diff = mgr.compare_versions("GB/T 4458.4", "2003", "2024")
    """

    _instance: "StandardVersionManager | None" = None
    _lock = threading.Lock()

    def __new__(cls, *args: Any, **kwargs: Any) -> "StandardVersionManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False  # type: ignore[attr-defined]
        return cls._instance

    def __init__(
        self,
        json_path: str | Path | None = None,
    ) -> None:
        if getattr(self, "_initialized", False):
            if json_path is not None:
                self._json_path = Path(json_path)
                self._init_backend()
            return
        self._backend: Any = None
        self._backend_name: str = ""
        self._json_path = Path(json_path) if json_path else Path(
            DEFAULT_VERSIONS_JSON_PATH
        )
        self._init_backend()
        self._initialized = True

    def _init_backend(self) -> None:
        """初始化持久化后端：优先 PostgreSQL，失败降级 JSON。"""
        try:
            self._backend = _VersionsPostgresBackend()
            self._backend_name = "postgres"
            log.info("kb.version_manager.backend", backend="postgres")
            return
        except Exception as e:  # noqa: BLE001
            log.warning(
                "kb.version_manager.postgres_unavailable",
                error=str(e),
                fallback="json",
            )
        try:
            self._backend = _VersionsJsonBackend(self._json_path)
            self._backend_name = "json"
            log.info(
                "kb.version_manager.backend",
                backend="json",
                path=str(self._json_path),
            )
        except Exception as e:  # noqa: BLE001
            log.error("kb.version_manager.json_init_failed", error=str(e))
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

    def register_version(
        self,
        standard_id: str,
        version: str,
        release_date: str = "",
        status: StandardStatus = "active",
        notes: str = "",
    ) -> StandardVersion:
        """注册新版本。同 (standard_id, version) 覆盖。

        注册新 active 版本时，若该规范已有 active 版本，将旧版本自动标记为 superseded。
        """
        sid = _strip_year(standard_id)
        # 自动 supersede 旧 active 版本
        if status == "active":
            existing = self.list_versions(sid)
            for v in existing:
                if v.status == "active" and v.version != version:
                    self._backend.upsert_version(
                        StandardVersion(
                            standard_id=sid,
                            version=v.version,
                            release_date=v.release_date,
                            status="superseded",
                            notes=v.notes,
                            registered_at=v.registered_at,
                        )
                    )

        record = StandardVersion(
            standard_id=sid,
            version=version.strip(),
            release_date=release_date,
            status=status,
            notes=notes,
            registered_at=_now_iso(),
        )
        self._backend.upsert_version(record)
        log.info(
            "kb.version_manager.version_registered",
            standard_id=sid,
            version=version,
            status=status,
            backend=self._backend_name,
        )
        return record

    def list_versions(self, standard_id: str) -> list[StandardVersion]:
        """列出某规范的所有版本（按版本号降序）。"""
        sid = _strip_year(standard_id)
        items = self._backend.list_versions(sid)
        items.sort(key=lambda v: v.version, reverse=True)
        return items

    def get_latest_version(
        self, standard_id: str
    ) -> StandardVersion | None:
        """获取最新 active 版本。无 active 版本时返回 None。"""
        for v in self.list_versions(standard_id):
            if v.status == "active":
                return v
        return None

    def deprecate_version(
        self, standard_id: str, version: str
    ) -> StandardVersion | None:
        """废弃指定版本（status → deprecated）。"""
        sid = _strip_year(standard_id)
        existing = self.list_versions(sid)
        for v in existing:
            if v.version == version:
                if v.status == "deprecated":
                    return v
                deprecated = StandardVersion(
                    standard_id=sid,
                    version=v.version,
                    release_date=v.release_date,
                    status="deprecated",
                    notes=v.notes,
                    registered_at=v.registered_at,
                )
                self._backend.upsert_version(deprecated)
                log.info(
                    "kb.version_manager.version_deprecated",
                    standard_id=sid,
                    version=version,
                )
                return deprecated
        return None

    def compare_versions(
        self,
        standard_id: str,
        version_a: str,
        version_b: str,
    ) -> VersionDiff:
        """对比两版本条款差异。

        实事求是原则：本方法仅基于 Qdrant 已索引的条款做集合差异对比。
        - 若 Qdrant 不可用或某版本未索引，对应字段返回空列表，note 中如实标注。
        - ``modified`` 通过 ``original_text`` 的 SHA-256 哈希差异判断。
        """
        sid = _strip_year(standard_id)
        clauses_a = self._fetch_clauses_from_qdrant(sid, version_a)
        clauses_b = self._fetch_clauses_from_qdrant(sid, version_b)

        added: list[str] = []
        removed: list[str] = []
        modified: list[str] = []
        notes_parts: list[str] = []

        map_a: dict[str, str] = {c.clause_id: _hash_text(c.original_text) for c in clauses_a}
        map_b: dict[str, str] = {c.clause_id: _hash_text(c.original_text) for c in clauses_b}

        for cid in map_b:
            if cid not in map_a:
                added.append(cid)
            elif map_a[cid] != map_b[cid]:
                modified.append(cid)
        for cid in map_a:
            if cid not in map_b:
                removed.append(cid)

        if not clauses_a and not clauses_b:
            notes_parts.append(
                "Qdrant 中未检索到任一版本的条款数据，差异为空"
            )
        elif not clauses_a:
            notes_parts.append(f"版本 {version_a} 在 Qdrant 中无条款数据")
        elif not clauses_b:
            notes_parts.append(f"版本 {version_b} 在 Qdrant 中无条款数据")

        diff = VersionDiff(
            standard_id=sid,
            version_a=version_a,
            version_b=version_b,
            added=sorted(added),
            removed=sorted(removed),
            modified=sorted(modified),
            note="; ".join(notes_parts) if notes_parts else "",
        )
        log.info(
            "kb.version_manager.versions_compared",
            standard_id=sid,
            version_a=version_a,
            version_b=version_b,
            added=len(added),
            removed=len(removed),
            modified=len(modified),
        )
        return diff

    # ===== 内部 =====

    def _fetch_clauses_from_qdrant(
        self, standard_id: str, version: str
    ) -> list[Any]:
        """从 Qdrant 拉取指定 (standard_id, version) 的所有条款。

        Qdrant 不可用时返回空列表，不抛异常（让 compare_versions 如实降级）。
        """
        try:
            from app.services.kb.indexer import DEFAULT_COLLECTION
            from app.services.kb.qdrant_store import get_store
            from qdrant_client.http import models as qmodels

            store = get_store()
            seen_ids: set[str] = set()
            clauses: list[Any] = []
            offset = None
            # 注：standard 字段在 Qdrant 中存的是带年份的标准号（如 GB/T 4458.4-2003），
            # 这里需要既匹配带年份的、又匹配同基线编号但不同年份的。
            # 简化：先按 version 字段过滤（version 在 ClauseRecord 中是年份字符串）。
            while True:
                resp = store.client.scroll(
                    collection_name=DEFAULT_COLLECTION,
                    limit=256,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                    scroll_filter=qmodels.Filter(
                        must=[
                            qmodels.FieldCondition(
                                key="version",
                                match=qmodels.MatchValue(value=version),
                            )
                        ]
                    ),
                )
                points, next_offset = resp[0], resp[1]
                if not points:
                    break
                for p in points:
                    payload = p.payload or {}
                    std_in_payload = str(payload.get("standard", ""))
                    # 基线编号匹配（去掉年份后比较）
                    if _strip_year(std_in_payload) != standard_id:
                        continue
                    cid = str(payload.get("clause_id", ""))
                    key = f"{std_in_payload}|{cid}"
                    if key in seen_ids:
                        continue
                    seen_ids.add(key)
                    from app.schemas.kb import ClauseRecord

                    clauses.append(
                        ClauseRecord(
                            standard=std_in_payload,
                            clause_id=cid,
                            title=payload.get("title", ""),
                            category=payload.get("category", "general"),
                            keywords=payload.get("keywords", []),
                            references=payload.get("references", []),
                            version=payload.get("version", ""),
                            is_sample=payload.get("is_sample", False),
                            original_text=payload.get("original_text", ""),
                            source_file=payload.get("source_file", ""),
                        )
                    )
                offset = next_offset
                if offset is None:
                    break
            return clauses
        except Exception as e:  # noqa: BLE001
            log.warning(
                "kb.version_manager.qdrant_fetch_failed",
                standard_id=standard_id,
                version=version,
                error=str(e),
            )
            return []


def _hash_text(text: str) -> str:
    """对条款原文做 SHA-256 哈希，用于变更检测。"""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# UpdateNotifier
# ---------------------------------------------------------------------------


class UpdateNotifier:
    """规范更新通知器。

    用法：
        notifier = UpdateNotifier()
        notifier.notify_subscribers("GB/T 4458.4", new_version="2024", old_version="2003")
        for n in notifier.list_notifications(only_unread=True):
            print(n.message)
        notifier.mark_read(notification_id)
    """

    _instance: "UpdateNotifier | None" = None
    _lock = threading.Lock()

    def __new__(cls, *args: Any, **kwargs: Any) -> "UpdateNotifier":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False  # type: ignore[attr-defined]
        return cls._instance

    def __init__(
        self,
        json_path: str | Path | None = None,
        version_manager: StandardVersionManager | None = None,
    ) -> None:
        if getattr(self, "_initialized", False):
            if json_path is not None:
                self._json_path = Path(json_path)
                self._init_backend()
            return
        self._backend: Any = None
        self._backend_name: str = ""
        self._json_path = Path(json_path) if json_path else Path(
            DEFAULT_NOTIFICATIONS_JSON_PATH
        )
        self._version_manager = version_manager
        self._init_backend()
        self._initialized = True

    def _init_backend(self) -> None:
        """初始化持久化后端：优先 PostgreSQL，失败降级 JSON。

        复用与 StandardVersionManager 相同的连接策略，但不共享实例
        （两个类职责分离，避免单例互相污染）。
        """
        try:
            self._backend = _VersionsPostgresBackend()
            self._backend_name = "postgres"
            log.info("kb.update_notifier.backend", backend="postgres")
            return
        except Exception as e:  # noqa: BLE001
            log.warning(
                "kb.update_notifier.postgres_unavailable",
                error=str(e),
                fallback="json",
            )
        try:
            self._backend = _NotificationsJsonBackend(self._json_path)
            self._backend_name = "json"
            log.info(
                "kb.update_notifier.backend",
                backend="json",
                path=str(self._json_path),
            )
        except Exception as e:  # noqa: BLE001
            log.error("kb.update_notifier.json_init_failed", error=str(e))
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

    def notify_subscribers(
        self,
        standard_id: str,
        new_version: str,
        old_version: str = "",
        message: str = "",
    ) -> StandardNotification:
        """通知订阅者规范已发布新版本。

        若 ``message`` 留空，自动生成默认消息。
        通知写入持久化后端，后续可通过 ``list_notifications`` 查询。
        """
        sid = _strip_year(standard_id)
        if not message:
            if old_version:
                message = (
                    f"规范 {sid} 已发布新版本 {new_version}（替代 {old_version}）。"
                    f"请及时更新设计文档与图样引用。"
                )
            else:
                message = (
                    f"规范 {sid} 已纳入新版本 {new_version}。"
                    f"请关注其适用范围。"
                )

        notification = StandardNotification(
            notification_id=_new_id("n"),
            standard_id=sid,
            new_version=new_version,
            old_version=old_version,
            message=message,
            created_at=_now_iso(),
            is_read=False,
        )
        self._backend.add(notification)
        log.info(
            "kb.update_notifier.notification_created",
            notification_id=notification.notification_id,
            standard_id=sid,
            new_version=new_version,
            backend=self._backend_name,
        )
        return notification

    def list_notifications(
        self, only_unread: bool = False
    ) -> list[StandardNotification]:
        """列出通知。``only_unread=True`` 仅返回未读通知。按创建时间倒序。"""
        items = self._backend.list_all()
        if only_unread:
            items = [n for n in items if not n.is_read]
        items.sort(key=lambda n: n.created_at, reverse=True)
        return items

    def mark_read(self, notification_id: str) -> bool:
        """标记通知已读。返回是否找到该通知。"""
        ok = self._backend.mark_read(notification_id)
        if ok:
            log.info(
                "kb.update_notifier.marked_read",
                notification_id=notification_id,
            )
        else:
            log.warning(
                "kb.update_notifier.mark_read_not_found",
                notification_id=notification_id,
            )
        return ok


# ---------------------------------------------------------------------------
# 模块级便捷函数
# ---------------------------------------------------------------------------


def get_version_manager() -> StandardVersionManager:
    """获取全局 StandardVersionManager 单例。"""
    return StandardVersionManager()


def get_notifier() -> UpdateNotifier:
    """获取全局 UpdateNotifier 单例。"""
    return UpdateNotifier()
