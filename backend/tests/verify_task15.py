"""Task 15 规范知识库扩展 端到端实测脚本。

覆盖 SubTask：
- 15.1: 预置规范库 - GB/T 4458 系列 / GB/T 14665 / ISO 128 / ISO 1101
- 15.2: 预置规范库 - 行业标准（JB/T 8836 等）
- 15.3: 规范版本管理与更新通知
- 降级路径：PostgreSQL 不可用时 JSON 持久化；Qdrant 不可用时 compare_versions 如实降级

运行：
    cd d:\\SynthDraft\\backend
    .venv\\Scripts\\python.exe tests\\verify_task15.py

设计原则（八荣八耻）：
- 复用现有：通过 sys.path 注入 backend 目录，复用现有 settings 与 KB 模块
- 实事求是：环境限制项（无 Qdrant / 无 PostgreSQL）如实标注，仅验证降级路径
- 覆盖测试：每个 SubTask 必须有可执行的断言
- 最小修改：不污染既有 tmp_state 持久化文件，使用独立临时目录
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

# 将 backend 目录加入 sys.path
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# 测试环境变量（避免污染真实配置）
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault("OFFLINE_MODE", "false")


def section(title: str) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'-' * 70}", flush=True)


def _ok(msg: str) -> None:
    print(f"  [PASS] {msg}", flush=True)


def _fail(msg: str, detail: str = "") -> None:
    print(f"  [FAIL] {msg}{f' :: {detail}' if detail else ''}", flush=True)


def _info(msg: str) -> None:
    print(f"  [INFO] {msg}", flush=True)


def _env_limit(msg: str) -> None:
    print(f"  [ENV-LIMIT] {msg}", flush=True)


def _pg_dsn() -> str:
    """构造 psycopg2 连接 DSN（与 version_manager._convert_dsn 一致）。"""
    from urllib.parse import urlparse
    from app.config import settings

    u = urlparse(settings.DATABASE_URL)
    return (
        f"host={u.hostname or 'localhost'} "
        f"port={u.port or 5432} "
        f"user={u.username or 'postgres'} "
        f"password={u.password or ''} "
        f"dbname={u.path.lstrip('/') or 'postgres'}"
    )


def _check_pg_available() -> bool:
    """检测 PostgreSQL 是否可用（与 version_manager 同款检测逻辑）。"""
    try:
        import psycopg2  # type: ignore[import-not-found]

        conn = psycopg2.connect(_pg_dsn())
        conn.close()
        return True
    except Exception:
        return False


def _cleanup_pg_test_state() -> None:
    """清理 PG 中本测试触及的版本/通知残留数据。

    PG 持久化跨运行累积，而 JSON tempfile 每次运行均为 fresh。
    为对齐两种后端的"每次 fresh"语义，PG 可用时清理本测试使用的
    standard_id（GB/T 4458.4、JB/T 8836），使计数类断言不受历史残留影响。
    """
    try:
        import psycopg2  # type: ignore[import-not-found]

        conn = psycopg2.connect(_pg_dsn())
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM standard_versions WHERE standard_id = %s",
                ("GB/T 4458.4",),
            )
            cur.execute(
                "DELETE FROM standard_notifications "
                "WHERE standard_id IN (%s, %s)",
                ("GB/T 4458.4", "JB/T 8836"),
            )
        conn.close()
        _info("已清理 PG 中本测试的版本/通知残留数据")
    except Exception as e:
        _info(f"清理 PG 测试数据失败（忽略）：{e}")


# 模块级缓存：首次检测后不再重复检测
_PG_AVAILABLE: bool | None = None


def pg_available() -> bool:
    """获取 PG 可用性（带缓存）。"""
    global _PG_AVAILABLE
    if _PG_AVAILABLE is None:
        _PG_AVAILABLE = _check_pg_available()
        if _PG_AVAILABLE:
            _info("PostgreSQL 可用 → 断言 postgres 后端")
        else:
            _info("PostgreSQL 不可用 → 断言 json 降级")
    return _PG_AVAILABLE


# ===== 全局统计 =====
_passed = 0
_failed = 0
_env_limits = 0
_failures: list[str] = []


def check(condition: bool, msg: str, detail: str = "") -> None:
    global _passed, _failed
    if condition:
        _passed += 1
        _ok(msg)
    else:
        _failed += 1
        _failures.append(f"{msg}{f' :: {detail}' if detail else ''}")
        _fail(msg, detail)


def env_limit(msg: str) -> None:
    global _env_limits
    _env_limits += 1
    _env_limit(msg)


# ---------------------------------------------------------------------------
# SubTask 15.1：预置规范库（国标 / 国际标准）
# ---------------------------------------------------------------------------


def test_preset_library_national_international() -> None:
    section("SubTask 15.1: 预置规范库（国标 + 国际标准）")

    # 1. 模块导入
    try:
        from app.services.kb.standard_library import (
            StandardLibrary,
            get_library,
            list_preset_standards,
            get_preset_standard,
            create_seed_metadata,
        )

        check(True, "standard_library 模块导入成功")
    except Exception as e:
        check(False, "standard_library 模块导入失败", str(e))
        return

    # 2. 实例化
    try:
        lib = StandardLibrary()
        check(True, "StandardLibrary 实例化成功")
    except Exception as e:
        check(False, "StandardLibrary 实例化失败", str(e))
        return

    # 3. 总数应 >= 7（国标）+ 3（国际）+ 5（行业）= 15
    total = lib.count()
    check(
        total >= 15,
        f"预置规范总数 >= 15（实际 {total}）",
    )

    # 4. GB/T 4458 系列至少 6 条
    all_presets = lib.list_preset_standards()
    gbt_4458 = [
        s for s in all_presets if s.standard_id.startswith("GB/T 4458")
    ]
    check(
        len(gbt_4458) >= 6,
        f"GB/T 4458 系列 >= 6 条（实际 {len(gbt_4458)}）",
        f"ids={[s.standard_id for s in gbt_4458]}",
    )

    # 5. GB/T 14665 必须存在
    gbt_14665 = next(
        (s for s in all_presets if "14665" in s.standard_id), None
    )
    check(gbt_14665 is not None, "包含 GB/T 14665-2012")
    if gbt_14665:
        check(
            gbt_14665.category == "national",
            f"GB/T 14665 类别为 national（实际 {gbt_14665.category}）",
        )
        check(
            "CAD" in gbt_14665.title or "CAD" in gbt_14665.scope,
            "GB/T 14665 标题或范围提及 CAD",
        )

    # 6. ISO 128 / ISO 1101 必须存在
    iso_128 = next(
        (s for s in all_presets if s.standard_id.startswith("ISO 128")), None
    )
    iso_1101 = next(
        (s for s in all_presets if s.standard_id.startswith("ISO 1101")), None
    )
    check(iso_128 is not None, "包含 ISO 128 系列")
    check(iso_1101 is not None, "包含 ISO 1101:2017")
    if iso_128:
        check(
            iso_128.category == "international",
            f"ISO 128 类别为 international（实际 {iso_128.category}）",
        )
    if iso_1101:
        check(
            iso_1101.category == "international",
            f"ISO 1101 类别为 international（实际 {iso_1101.category}）",
        )

    # 7. GB/T 4458.4 与 GB/T 4457.4 区分（关键校验）
    std_4458_4 = lib.get_preset_standard("GB/T 4458.4-2003")
    check(std_4458_4 is not None, "能按编号查到 GB/T 4458.4-2003")
    if std_4458_4:
        check(
            "尺寸注法" in std_4458_4.title,
            f"GB/T 4458.4 标题含'尺寸注法'（实际 {std_4458_4.title}）",
        )
        check(
            "GB/T 4457.4-2002" in std_4458_4.references
            or "4457.4" in std_4458_4.scope
            or "4457.4" in std_4458_4.references,
            "GB/T 4458.4 引用或说明中提及 GB/T 4457.4",
        )

    # 8. 未找到的规范返回 None
    unknown = lib.get_preset_standard("GB/T NONEXIST-9999")
    check(unknown is None, "查询不存在的规范返回 None")

    # 9. 种子元数据生成（实事求是原则验证）
    seeds = lib.create_seed_metadata("GB/T 4458.4-2003")
    check(len(seeds) == 1, f"种子元数据生成 1 条（实际 {len(seeds)}）")
    if seeds:
        seed = seeds[0]
        check(
            seed.is_sample is True,
            "种子条款 is_sample=True（如实标注非原文）",
        )
        check(
            "占位元数据" in seed.original_text,
            "种子条款 original_text 含'占位元数据'标识",
        )
        check(
            seed.source_file.startswith("preset_library:"),
            f"种子条款 source_file 标识来源（实际 {seed.source_file}）",
        )
        check(
            seed.standard == "GB/T 4458.4-2003",
            f"种子条款 standard 字段正确（实际 {seed.standard}）",
        )

    # 10. 不存在规范的种子返回空列表
    empty_seeds = lib.create_seed_metadata("UNKNOWN-9999")
    check(
        len(empty_seeds) == 0,
        "不存在规范的种子元数据返回空列表",
    )

    # 11. 模块级便捷函数
    check(
        len(list_preset_standards()) == total,
        "list_preset_standards() 便捷函数返回一致",
    )
    check(
        get_preset_standard("ISO 1101:2017") is not None,
        "get_preset_standard() 便捷函数工作",
    )
    check(
        len(create_seed_metadata("JB/T 8836-2023")) == 1,
        "create_seed_metadata() 便捷函数工作",
    )


# ---------------------------------------------------------------------------
# SubTask 15.2：预置规范库（行业标准）
# ---------------------------------------------------------------------------


def test_preset_library_industry() -> None:
    section("SubTask 15.2: 预置规范库（行业标准）")

    try:
        from app.services.kb.standard_library import StandardLibrary
    except Exception as e:
        check(False, "standard_library 模块导入失败", str(e))
        return

    lib = StandardLibrary()

    # 1. 类别筛选：national
    national = lib.list_standards_by_category("national")
    check(
        len(national) >= 7,
        f"national 类别 >= 7 条（实际 {len(national)}）",
        f"ids={[s.standard_id for s in national]}",
    )
    check(
        all(s.category == "national" for s in national),
        "national 类别下所有规范 category=national",
    )

    # 2. 类别筛选：international
    international = lib.list_standards_by_category("international")
    check(
        len(international) >= 3,
        f"international 类别 >= 3 条（实际 {len(international)}）",
        f"ids={[s.standard_id for s in international]}",
    )
    check(
        all(s.category == "international" for s in international),
        "international 类别下所有规范 category=international",
    )

    # 3. 类别筛选：industry
    industry = lib.list_standards_by_category("industry")
    check(
        len(industry) >= 5,
        f"industry 类别 >= 5 条（实际 {len(industry)}）",
        f"ids={[s.standard_id for s in industry]}",
    )
    check(
        all(s.category == "industry" for s in industry),
        "industry 类别下所有规范 category=industry",
    )

    # 4. JB/T 8836 必须存在
    jb_8836 = next(
        (s for s in industry if "8836" in s.standard_id), None
    )
    check(jb_8836 is not None, "行业标准中包含 JB/T 8836-2023")
    if jb_8836:
        check(
            "工艺文件" in jb_8836.title or "编号方法" in jb_8836.title,
            f"JB/T 8836 标题正确（实际 {jb_8836.title}）",
        )
        check(
            jb_8836.publisher != "",
            f"JB/T 8836 发布机构非空（实际 {jb_8836.publisher}）",
        )

    # 5. JB/T 5996 / JB/T 5054 / HG/T 20668 / QC/T 265 均应存在
    expected_ids = [
        "JB/T 5996-2023",
        "JB/T 5054-2023",
        "HG/T 20668-2000",
        "QC/T 265-2023",
    ]
    all_presets = lib.list_preset_standards()
    for sid in expected_ids:
        found = next(
            (s for s in all_presets if s.standard_id == sid), None
        )
        check(found is not None, f"预置规范库包含 {sid}")

    # 6. 非法类别抛 ValueError
    try:
        lib.list_standards_by_category("invalid")  # type: ignore[arg-type]
        check(False, "非法类别应抛 ValueError")
    except ValueError as e:
        check(True, "非法类别抛 ValueError", str(e)[:80])

    # 7. enterprise 类别为空（预置不含企业标准，企业标准由 Task 14 导入）
    enterprise = lib.list_standards_by_category("enterprise")
    check(
        len(enterprise) == 0,
        f"enterprise 类别预置为空（实际 {len(enterprise)}）",
    )


# ---------------------------------------------------------------------------
# SubTask 15.3：规范版本管理与更新通知
# ---------------------------------------------------------------------------


def test_version_management() -> None:
    section("SubTask 15.3: 规范版本管理 + 更新通知")

    # 使用独立临时目录，避免污染既有持久化文件
    tmpdir = tempfile.mkdtemp(prefix="task15_versions_")
    versions_json = Path(tmpdir) / "versions.json"
    notifications_json = Path(tmpdir) / "notifications.json"

    try:
        # 测试环境通常无 PostgreSQL/psycopg2，StandardVersionManager 会自动降级到 JSON。
        # 即使有 psycopg2，连接失败也会降级。
        from app.services.kb.version_manager import (
            StandardVersionManager,
            UpdateNotifier,
        )

        # 重置单例（避免上次测试残留）
        StandardVersionManager._instance = None  # type: ignore[attr-defined]
        UpdateNotifier._instance = None  # type: ignore[attr-defined]

        mgr = StandardVersionManager(json_path=versions_json)
        notifier = UpdateNotifier(json_path=notifications_json)

        if pg_available():
            check(
                mgr.backend_name == "postgres",
                f"PostgreSQL 可用 → postgres 后端（实际 {mgr.backend_name}）",
            )
            check(
                notifier.backend_name == "postgres",
                f"Notifier 同样使用 postgres 后端（实际 {notifier.backend_name}）",
            )
        else:
            check(
                mgr.backend_name == "json",
                f"PostgreSQL 不可用 → 降级到 json 后端（实际 {mgr.backend_name}）",
            )
            check(
                notifier.backend_name == "json",
                f"Notifier 同样降级到 json 后端（实际 {notifier.backend_name}）",
            )

        # PG 可用时清理本测试触及的残留数据，对齐 JSON tempfile 的 fresh 语义
        if pg_available():
            _cleanup_pg_test_state()

        # ===== 版本注册 / 列表 / 最新 / 废弃 =====

        # 1. 初始状态：无版本
        versions = mgr.list_versions("GB/T 4458.4")
        check(len(versions) == 0, "初始状态：GB/T 4458.4 无版本记录")

        # 2. 注册 2003 版本
        v2003 = mgr.register_version(
            "GB/T 4458.4-2003",
            version="2003",
            release_date="2003-01-13",
            notes="首次注册",
        )
        check(
            v2003.version == "2003" and v2003.status == "active",
            f"注册 2003 版本成功（version={v2003.version}, status={v2003.status}）",
        )

        # 3. 注册 2024 版本（应自动 supersede 2003）
        v2024 = mgr.register_version(
            "GB/T 4458.4",
            version="2024",
            release_date="2024-06-01",
            notes="修订版",
        )
        check(
            v2024.status == "active",
            f"注册 2024 active 版本（status={v2024.status}）",
        )

        # 4. list_versions 应返回 2 条
        versions = mgr.list_versions("GB/T 4458.4")
        check(
            len(versions) == 2,
            f"列出 2 个版本（实际 {len(versions)}）",
        )

        # 5. 2003 应被自动 superseded
        v2003_after = next(
            (v for v in versions if v.version == "2003"), None
        )
        check(
            v2003_after is not None and v2003_after.status == "superseded",
            f"2003 版本自动标记为 superseded（实际 status={v2003_after.status if v2003_after else 'N/A'}）",
        )

        # 6. get_latest_version 应返回 2024
        latest = mgr.get_latest_version("GB/T 4458.4")
        check(
            latest is not None and latest.version == "2024",
            f"最新 active 版本为 2024（实际 {latest.version if latest else 'N/A'}）",
        )

        # 7. 废弃 2003 版本
        deprecated = mgr.deprecate_version("GB/T 4458.4", "2003")
        check(
            deprecated is not None and deprecated.status == "deprecated",
            "废弃 2003 版本成功",
        )

        # 8. 重复废弃不报错
        deprecated_again = mgr.deprecate_version("GB/T 4458.4", "2003")
        check(
            deprecated_again is not None
            and deprecated_again.status == "deprecated",
            "重复废弃 2003 版本幂等",
        )

        # 9. 废弃不存在的版本返回 None
        nonexistent = mgr.deprecate_version("GB/T 4458.4", "1999")
        check(nonexistent is None, "废弃不存在版本返回 None")

        # 10. 废弃后 latest 仍是 2024
        latest_after = mgr.get_latest_version("GB/T 4458.4")
        check(
            latest_after is not None and latest_after.version == "2024",
            "废弃 2003 后最新版本仍为 2024",
        )

        # ===== 版本对比（实事求是：Qdrant 不可用时降级）=====

        # 11. compare_versions：Qdrant 不可用 → 返回空差异 + note 说明
        try:
            from app.services.kb.qdrant_store import get_store  # noqa: F401

            qdrant_available = True
        except Exception:
            qdrant_available = False

        diff = mgr.compare_versions("GB/T 4458.4", "2003", "2024")
        check(
            diff.standard_id == "GB/T 4458.4"
            and diff.version_a == "2003"
            and diff.version_b == "2024",
            f"compare_versions 返回正确元数据（sid={diff.standard_id}）",
        )
        # Qdrant 不可用时 added/removed/modified 应为空
        if not qdrant_available:
            check(
                len(diff.added) == 0
                and len(diff.removed) == 0
                and len(diff.modified) == 0,
                "Qdrant 不可用时差异字段为空",
            )
            check(
                "Qdrant" in diff.note or "无条款数据" in diff.note,
                f"note 如实说明 Qdrant 不可用（note={diff.note!r}）",
            )
        else:
            _info(f"Qdrant 可用：diff={diff.added}/{diff.removed}/{diff.modified}")

        # ===== 更新通知 =====

        # 12. 创建通知
        n1 = notifier.notify_subscribers(
            "GB/T 4458.4",
            new_version="2024",
            old_version="2003",
        )
        check(
            n1.new_version == "2024"
            and n1.old_version == "2003"
            and not n1.is_read,
            f"创建通知（id={n1.notification_id}, unread={not n1.is_read}）",
        )
        check(
            "GB/T 4458.4" in n1.message and "2024" in n1.message,
            f"通知默认消息包含规范号与新版本（message={n1.message[:60]}...）",
        )

        # 13. 创建第二条通知（无 old_version）
        n2 = notifier.notify_subscribers(
            "JB/T 8836",
            new_version="2023",
        )
        check(
            "JB/T 8836" in n2.message and "新版本" in n2.message,
            f"无 old_version 时通知消息正确（message={n2.message[:60]}...）",
        )

        # 14. list_notifications 返回 2 条
        all_notifs = notifier.list_notifications()
        check(
            len(all_notifs) == 2,
            f"列出 2 条通知（实际 {len(all_notifs)}）",
        )

        # 15. only_unread=True 也返回 2 条
        unread = notifier.list_notifications(only_unread=True)
        check(
            len(unread) == 2,
            f"未读通知 2 条（实际 {len(unread)}）",
        )

        # 16. mark_read 第一条
        ok = notifier.mark_read(n1.notification_id)
        check(ok, "标记 n1 已读成功")

        # 17. mark_read 后未读应为 1 条
        unread_after = notifier.list_notifications(only_unread=True)
        check(
            len(unread_after) == 1,
            f"标记后未读通知 1 条（实际 {len(unread_after)}）",
        )

        # 18. 标记不存在的通知返回 False
        ok_unknown = notifier.mark_read("nonexistent_id_xxx")
        check(not ok_unknown, "标记不存在的通知返回 False")

        # 19. 重复标记已读通知仍返回 True（幂等）
        ok_again = notifier.mark_read(n1.notification_id)
        check(ok_again, "重复标记已读通知幂等返回 True")

        # 20. 持久化验证：JSON 后端写文件；PG 后端不写 JSON 文件（数据在 PG）
        if pg_available():
            env_limit("PG 后端不写 JSON 文件，跳过 JSON 文件存在性检查")
        else:
            check(
                versions_json.is_file() and versions_json.stat().st_size > 0,
                f"版本 JSON 文件已写入（{versions_json}）",
            )
            check(
                notifications_json.is_file()
                and notifications_json.stat().st_size > 0,
                f"通知 JSON 文件已写入（{notifications_json}）",
            )

        # 21. reload 后端从 JSON 恢复（验证持久化可读）
        StandardVersionManager._instance = None  # type: ignore[attr-defined]
        UpdateNotifier._instance = None  # type: ignore[attr-defined]
        mgr2 = StandardVersionManager(json_path=versions_json)
        notifier2 = UpdateNotifier(json_path=notifications_json)
        restored_versions = mgr2.list_versions("GB/T 4458.4")
        check(
            len(restored_versions) == 2,
            f"reload 后从 JSON 恢复 2 个版本（实际 {len(restored_versions)}）",
        )
        restored_notifs = notifier2.list_notifications()
        check(
            len(restored_notifs) == 2,
            f"reload 后从 JSON 恢复 2 条通知（实际 {len(restored_notifs)}）",
        )

    except Exception as e:
        check(False, "版本管理测试异常", str(e))
        import traceback

        traceback.print_exc()
    finally:
        # 清理临时目录
        try:
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# API 端点导入测试
# ---------------------------------------------------------------------------


def test_api_endpoints_import() -> None:
    section("API 端点定义导入测试")

    try:
        from app.api.v1.endpoints import kb as kb_endpoint

        # 收集 router 中所有注册的路由 path
        paths: list[str] = []
        for route in kb_endpoint.router.routes:
            paths.append(route.path)  # type: ignore[attr-defined]

        # Task 15 新增端点路径校验
        expected_paths = [
            "/standards/library",
            "/standards/library/{category}",
            "/standards/versions",
            "/standards/notifications",
        ]
        for p in expected_paths:
            check(p in paths, f"API 路由注册：{p}")

        # 验证方法（GET / POST）
        method_map: dict[str, set[str]] = {}
        for route in kb_endpoint.router.routes:
            path = route.path  # type: ignore[attr-defined]
            methods = set(route.methods or [])  # type: ignore[attr-defined]
            method_map.setdefault(path, set()).update(methods)

        check(
            "GET" in method_map.get("/standards/library", set()),
            "GET /standards/library 已注册",
        )
        check(
            "GET" in method_map.get("/standards/library/{category}", set()),
            "GET /standards/library/{category} 已注册",
        )
        check(
            "GET" in method_map.get("/standards/versions", set()),
            "GET /standards/versions 已注册",
        )
        check(
            "POST" in method_map.get("/standards/versions", set()),
            "POST /standards/versions 已注册",
        )
        check(
            "GET" in method_map.get("/standards/notifications", set()),
            "GET /standards/notifications 已注册",
        )

    except Exception as e:
        check(False, "API 端点导入或路由校验失败", str(e))
        import traceback

        traceback.print_exc()


# ---------------------------------------------------------------------------
# Schema 模型测试
# ---------------------------------------------------------------------------


def test_schemas() -> None:
    section("Schema 模型测试")

    try:
        from app.schemas.kb import (
            PresetStandard,
            StandardNotification,
            StandardVersion,
            VersionDiff,
            VersionRegisterRequest,
        )

        # 1. PresetStandard
        ps = PresetStandard(
            standard_id="GB/T 4458.4-2003",
            title="机械制图 尺寸注法",
            publisher="国标委",
            year="2003",
            category="national",
            status="active",
        )
        check(
            ps.category == "national" and ps.status == "active",
            "PresetStandard 默认字段正确",
        )

        # 2. StandardVersion
        sv = StandardVersion(
            standard_id="GB/T 4458.4",
            version="2024",
            release_date="2024-06-01",
            status="active",
        )
        check(
            sv.status == "active" and sv.version == "2024",
            "StandardVersion 字段正确",
        )

        # 3. VersionDiff
        vd = VersionDiff(
            standard_id="GB/T 4458.4",
            version_a="2003",
            version_b="2024",
            added=["5.3"],
            removed=["4.2"],
            modified=["5.1"],
        )
        check(
            vd.added == ["5.3"] and vd.removed == ["4.2"] and vd.modified == ["5.1"],
            "VersionDiff 字段正确",
        )

        # 4. StandardNotification
        n = StandardNotification(
            notification_id="n_test",
            standard_id="GB/T 4458.4",
            new_version="2024",
            old_version="2003",
            message="test",
        )
        check(
            n.is_read is False and n.new_version == "2024",
            "StandardNotification 默认 is_read=False",
        )

        # 5. VersionRegisterRequest 校验
        req = VersionRegisterRequest(version="2024", status="active")
        check(req.version == "2024", "VersionRegisterRequest 构造成功")

        # 6. VersionRegisterRequest 必填字段缺失应抛 ValidationError
        try:
            VersionRegisterRequest()  # type: ignore[call-arg]
            check(False, "VersionRegisterRequest 缺少 version 应抛 ValidationError")
        except Exception:
            check(True, "VersionRegisterRequest 缺少 version 抛 ValidationError")

    except Exception as e:
        check(False, "Schema 模型测试异常", str(e))
        import traceback

        traceback.print_exc()


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def main() -> int:
    section("Task 15: 规范知识库扩展 - 端到端实测")

    test_schemas()
    test_preset_library_national_international()
    test_preset_library_industry()
    test_version_management()
    test_api_endpoints_import()

    section("汇总")
    print(f"  PASS:       {_passed}", flush=True)
    print(f"  FAIL:       {_failed}", flush=True)
    print(f"  ENV-LIMIT:  {_env_limits}", flush=True)
    if _failures:
        print("\n  失败项明细：", flush=True)
        for f in _failures:
            print(f"    - {f}", flush=True)

    return 0 if _failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
