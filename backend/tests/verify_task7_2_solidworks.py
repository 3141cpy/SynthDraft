"""Task 8 / SubTask 7.2 离线 self-test：验证 SolidWorks 模块 import 与降级。

设计目标（spec.md §"SubTask 7.2 自检报告"）：
1. 模块导入安全：Linux/无 pywin32 下 `import app.services.solidworks` 不抛异常
2. `is_solidworks_available()` 返回 bool（True/False 由运行环境决定）
3. 公共 API 完整：read_sldprt / read_sldasm / Session / WorkerPool / 异常类等
4. schema 可构造与序列化（SolidWorksModel 及子类型）
5. 降级行为：模拟无 pywin32 时 `_require_backend` 抛 SolidWorksNotAvailableError
6. 复用 reader._self_test() 的离线检查

运行：
    python tests/verify_task7_2_solidworks.py

退出码：0=PASS，1=FAIL
"""

from __future__ import annotations

import json
import platform
import sys
from pathlib import Path

# 将 backend/ 加入 sys.path，便于 `import app...`
BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def section(title: str) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'-' * 70}")


def main() -> int:
    checks: dict[str, bool] = {}
    errors: list[str] = []

    # ===== 验证 1：包导入安全 =====
    section("验证 1：app.services.solidworks 包导入安全")
    try:
        import app.services.solidworks as sw_pkg

        print(f"包路径            : {sw_pkg.__file__}")
        print(f"__all__ 条目数     : {len(sw_pkg.__all__)}")
        print(f"平台              : {platform.system()}")
        checks["pkg_import"] = True
    except Exception as e:  # noqa: BLE001
        checks["pkg_import"] = False
        errors.append(f"包导入失败: {e}")
        return _print_summary(checks, errors)

    # ===== 验证 2：is_solidworks_available() 返回 bool =====
    section("验证 2：is_solidworks_available() 返回 bool")
    try:
        from app.services.solidworks import is_solidworks_available

        available = is_solidworks_available()
        print(f"is_solidworks_available() = {available}")
        print(f"返回类型                   : {type(available).__name__}")
        checks["available_returns_bool"] = isinstance(available, bool)

        # 平台相关性断言（不强制 True/False，只验证类型与平台一致性）
        if platform.system() == "Windows":
            # Windows + pywin32 已安装时应为 True；未装 pywin32 时为 False
            # 本脚本目标是不依赖 SolidWorks 实例，所以只验证类型
            print("(Windows 平台：pywin32 已装则 True，未装则 False)")
        else:
            # Linux/无 pywin32 必为 False
            checks["linux_unavailable"] = available is False
            print("(非 Windows 平台：期望 False)")
    except Exception as e:  # noqa: BLE001
        checks["available_returns_bool"] = False
        errors.append(f"is_solidworks_available 异常: {e}")

    # ===== 验证 3：公共 API 完整性 =====
    section("验证 3：公共 API 完整性")
    expected_exports = [
        # 读取入口（SubTask 7.2）
        "read_sldprt",
        "read_sldasm",
        # 会话与 Worker 池（SubTask 7.1）
        "SolidWorksSession",
        "SolidWorksWorkerPool",
        "solidworks_task",
        "get_session",
        "get_worker_pool",
        "SW_DOC_PART",
        "SW_DOC_ASSEMBLY",
        "SW_DOC_DRAWING",
        # 异常类
        "SolidWorksNotAvailableError",
        "SolidWorksSessionError",
        "SolidWorksTaskError",
        "SolidWorksTaskTimeout",
        "SolidWorksLicenseError",
    ]
    missing = [name for name in expected_exports if not hasattr(sw_pkg, name)]
    print(f"期望导出数 : {len(expected_exports)}")
    print(f"缺失导出   : {missing or '无'}")
    checks["all_exports_present"] = len(missing) == 0
    checks["read_sldprt_callable"] = callable(getattr(sw_pkg, "read_sldprt", None))
    checks["read_sldasm_callable"] = callable(getattr(sw_pkg, "read_sldasm", None))
    print(f"read_sldprt callable : {checks['read_sldprt_callable']}")
    print(f"read_sldasm callable : {checks['read_sldasm_callable']}")

    # ===== 验证 4：schema 可构造与序列化 =====
    section("验证 4：SolidWorksModel schema 可构造与序列化")
    try:
        from app.schemas.solidworks_model import (
            SWBOMItem,
            SWComponent,
            SWCustomProperty,
            SWDimension,
            SWFeature,
            SWGeometricTolerance,
            SWMassProperty,
            SWMate,
            SWSurfaceFinish,
            SWTechnicalNote,
            SolidWorksModel,
        )

        # 空模型构造（仅 source_file 必填）
        model = SolidWorksModel(source_file="test.sldprt", doc_type="part")
        print(f"空模型构造 : source_file={model.source_file}, doc_type={model.doc_type}")
        print(f"             units={model.units}, features={len(model.features)}")

        # 序列化 / 反序列化往返
        json_str = model.model_dump_json()
        model2 = SolidWorksModel.model_validate_json(json_str)
        print(f"JSON 往返   : source_file={model2.source_file} (len={len(json_str)})")
        checks["schema_construct_serialize"] = model2.source_file == "test.sldprt"

        # 子 schema 类可导入（验证类型系统完整）
        sub_classes = [
            SWFeature, SWDimension, SWGeometricTolerance, SWSurfaceFinish,
            SWTechnicalNote, SWComponent, SWMate, SWBOMItem,
            SWCustomProperty, SWMassProperty,
        ]
        print(f"子 schema 类可导入 : {len(sub_classes)}/10")
        checks["sub_schema_importable"] = len(sub_classes) == 10
    except Exception as e:  # noqa: BLE001
        checks["schema_construct_serialize"] = False
        checks["sub_schema_importable"] = False
        errors.append(f"schema 验证失败: {e}")

    # ===== 验证 5：降级行为（模拟无 pywin32）=====
    section("验证 5：降级行为（模拟无 pywin32 环境）")
    original_backend = None
    try:
        from app.services.solidworks import sw_session
        from app.services.solidworks.exceptions import SolidWorksNotAvailableError

        original_backend = sw_session._WIN32_BACKEND
        print(f"原始 backend       : {original_backend}")

        # 模拟无 pywin32
        sw_session._WIN32_BACKEND = None
        try:
            # 5.1 is_solidworks_available 应返回 False
            avail = sw_session.is_solidworks_available()
            print(f"模拟后 available   : {avail}")
            checks["degraded_available_false"] = avail is False

            # 5.2 _require_backend 应抛 SolidWorksNotAvailableError
            try:
                sw_session._require_backend()
                checks["degraded_require_raises"] = False
                errors.append(
                    "_require_backend 未抛异常（期望 SolidWorksNotAvailableError）"
                )
            except SolidWorksNotAvailableError:
                checks["degraded_require_raises"] = True
                print("_require_backend 抛 SolidWorksNotAvailableError ✓")
            except Exception as e:  # noqa: BLE001
                checks["degraded_require_raises"] = False
                errors.append(
                    f"_require_backend 抛错类型异常: {type(e).__name__}: {e}"
                )
        finally:
            # 恢复 backend，避免污染后续测试
            sw_session._WIN32_BACKEND = original_backend
            print(f"已恢复 backend     : {sw_session._WIN32_BACKEND}")
    except Exception as e:  # noqa: BLE001
        checks["degraded_available_false"] = False
        checks["degraded_require_raises"] = False
        errors.append(f"降级测试异常: {e}")
        # 兜底恢复
        try:
            if original_backend is not None:
                from app.services.solidworks import sw_session

                sw_session._WIN32_BACKEND = original_backend
        except Exception:  # noqa: BLE001
            pass

    # ===== 验证 6：复用 reader._self_test() =====
    section("验证 6：reader._self_test() 离线自检")
    try:
        from app.services.solidworks.reader import _self_test

        result = _self_test()
        print(f"ok     : {result['ok']}")
        print(f"checks : {json.dumps(result['checks'], ensure_ascii=False)}")
        if result["errors"]:
            print(f"errors : {result['errors']}")
        checks["reader_self_test"] = result["ok"]
        if not result["ok"]:
            errors.extend(result["errors"])
    except Exception as e:  # noqa: BLE001
        checks["reader_self_test"] = False
        errors.append(f"reader._self_test 异常: {e}")

    return _print_summary(checks, errors)


def _print_summary(checks: dict[str, bool], errors: list[str]) -> int:
    section("汇总")
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    print(f"通过: {passed}/{total}")
    for name, ok in checks.items():
        mark = "[PASS]" if ok else "[FAIL]"
        print(f"  {mark} {name}")
    if errors:
        print(f"\n错误 ({len(errors)}):")
        for e in errors:
            print(f"  - {e}")
    ok = all(checks.values()) and not errors
    print(f"\n结果: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
