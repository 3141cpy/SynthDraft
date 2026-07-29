"""CadQuery 代码沙箱执行（SubTask 5.2 / 5.4）。

P0 阶段策略（参考降级策略）：
- 静态扫描禁止危险 import / 内建
- 临时目录隔离
- subprocess + timeout 限时执行
- 末尾自动追加导出逻辑（STEP/STL/DXF）

不要求完整 Docker 沙箱，但必须做静态扫描与子进程隔离。

CadQuery 导出 API（已查询确认）：
- ``cq.exporters.export(result, path)`` 按扩展名自动选择导出器
  支持 .step / .stp / .stl / .dxf / .svg / .amf
- ``cq.Workplane.val()`` 取出底层 Shape
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from app.logging import get_logger
from app.schemas.generation_detail import ExecutionResult

__all__ = ["STATIC_VIOLATIONS", "static_scan_code", "execute_cadquery_code"]

log = get_logger(__name__)


# ===== 静态扫描 =====

# 危险 import / 内建黑名单（参考降级策略要求）
# 命中任一即拒绝执行
STATIC_VIOLATIONS: tuple[str, ...] = (
    "import os",
    "from os",
    "import subprocess",
    "from subprocess",
    "import socket",
    "from socket",
    "import ctypes",
    "from ctypes",
    "import sys",
    "from sys",
    "import shutil",
    "from shutil",
    "import pathlib",
    "from pathlib",
    "import glob",
    "from glob",
    "import importlib",
    "from importlib",
    "import pickle",
    "from pickle",
    "import marshal",
    "from marshal",
    "import builtins",
    "from builtins",
    "__import__",
    "eval(",
    "exec(",
    "compile(",
    "open(",
    "globals(",
    "locals(",
    "getattr(",
    "setattr(",
    "delattr(",
)

# 允许的 import 白名单（首行 import 语句仅允许 cadquery）
_ALLOWED_IMPORT_RE = re.compile(r"^\s*import\s+(\S+)|^\s*from\s+(\S+)\s+import")


def static_scan_code(code: str) -> list[str]:
    """静态扫描代码，返回违规列表。

    Args:
        code: 待执行的 CadQuery Python 代码

    Returns:
        违规描述列表（空列表表示通过）
    """
    violations: list[str] = []

    # 1. 黑名单子串匹配（保守策略，宁可误拒不可漏放）
    for bad in STATIC_VIOLATIONS:
        if bad in code:
            violations.append(f"forbidden pattern: {bad!r}")

    # 2. 检查所有 import 语句，只允许 cadquery
    for line in code.splitlines():
        stripped = line.strip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            m = _ALLOWED_IMPORT_RE.match(stripped)
            if m:
                mod = (m.group(1) or m.group(2) or "").strip()
                # 仅允许 cadquery（含子模块形式 from cadquery import xxx）
                top = mod.split(".")[0]
                if top != "cadquery":
                    violations.append(
                        f"forbidden import: {mod!r} (only cadquery allowed)"
                    )

    return violations


# ===== 代码末尾导出追加 =====

# 导出脚本模板：在用户代码末尾追加，将 result 变量导出为多种格式
# 使用 cq.exporters.export 按扩展名自动分发
_EXPORT_SUFFIX = """

# === 沙箱自动追加的导出逻辑（请勿手动修改）===
import cadquery as cq

_export_result = globals().get("result")
if _export_result is None:
    raise RuntimeError("CadQuery 代码未定义变量 'result'")
if not isinstance(_export_result, cq.Workplane):
    _export_result = cq.Workplane(obj=_export_result)

_export_dir = r"{output_dir}"
_exports = {export_map}

for _ext, _path in _exports.items():
    try:
        cq.exporters.export(_export_result, _path)
        print("EXPORT_OK", _ext, _path)
    except Exception as _e:
        print("EXPORT_FAIL", _ext, repr(_e))
# === 导出逻辑结束 ===
"""


def _build_export_suffix(output_dir: Path, output_format: str) -> str:
    """构造导出后缀代码。

    Args:
        output_dir: 输出目录（绝对路径）
        output_format: 用户期望输出格式（step/stl/dxf/iges）

    Returns:
        追加到用户代码末尾的 Python 字符串
    """
    fmt = output_format.lower()
    export_map: dict[str, str] = {}

    # 主格式必出
    if fmt == "step":
        export_map["step"] = str(output_dir / "output.step")
    elif fmt == "stl":
        export_map["stl"] = str(output_dir / "output.stl")
    elif fmt == "dxf":
        export_map["dxf"] = str(output_dir / "output.dxf")
    elif fmt == "iges":
        export_map["iges"] = str(output_dir / "output.iges")
    else:
        export_map["step"] = str(output_dir / "output.step")

    # P0 阶段：主格式 + STEP（便于几何校验）
    if "step" not in export_map:
        export_map["step"] = str(output_dir / "output.step")
    # 同时输出 STL（CadQuery exporters 支持，便于 3D 预览）
    if "stl" not in export_map:
        export_map["stl"] = str(output_dir / "output.stl")

    # 用 repr 安全转义路径
    return _EXPORT_SUFFIX.format(
        output_dir=str(output_dir),
        export_map=repr(export_map),
    )


# ===== 主执行入口 =====


def execute_cadquery_code(
    code: str,
    output_dir: Path,
    timeout: int = 30,
    output_format: str = "step",
) -> ExecutionResult:
    """在隔离子进程中执行 CadQuery 代码并导出几何文件。

    Args:
        code: 用户/LLM 生成的 CadQuery Python 代码
        output_dir: 输出目录（不存在则创建）
        timeout: 子进程超时秒数
        output_format: 期望主输出格式

    Returns:
        ExecutionResult 结构化结果
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. 静态扫描
    violations = static_scan_code(code)
    if violations:
        log.warning("sandbox.static_scan.rejected", violations=violations)
        return ExecutionResult(
            success=False,
            stdout="",
            stderr="static scan rejected",
            output_files=[],
            elapsed_ms=0,
            exit_code=None,
            violations=violations,
        )

    # 2. 拼接完整脚本
    full_code = code.rstrip() + "\n" + _build_export_suffix(output_dir, output_format)

    # 3. 写入临时 .py
    script_path = output_dir / "generated_script.py"
    script_path.write_text(full_code, encoding="utf-8")

    log.info(
        "sandbox.execute.start",
        script=str(script_path),
        timeout=timeout,
        output_format=output_format,
    )

    # 4. 子进程执行
    t0 = time.time()
    try:
        proc = subprocess.run(
            [sys.executable, str(script_path)],
            timeout=timeout,
            capture_output=True,
            text=True,
            cwd=str(output_dir),
            encoding="utf-8",
            errors="replace",
        )
        elapsed_ms = int((time.time() - t0) * 1000)
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        exit_code = proc.returncode
    except subprocess.TimeoutExpired as e:
        elapsed_ms = int((time.time() - t0) * 1000)
        log.warning("sandbox.execute.timeout", elapsed_ms=elapsed_ms)
        return ExecutionResult(
            success=False,
            stdout=(e.stdout or "") if isinstance(e.stdout, str) else "",
            stderr=f"timeout after {timeout}s",
            output_files=[],
            elapsed_ms=elapsed_ms,
            exit_code=None,
            violations=[],
        )
    except Exception as e:  # noqa: BLE001
        elapsed_ms = int((time.time() - t0) * 1000)
        log.error("sandbox.execute.error", error=str(e), error_type=type(e).__name__)
        return ExecutionResult(
            success=False,
            stdout="",
            stderr=f"{type(e).__name__}: {e}",
            output_files=[],
            elapsed_ms=elapsed_ms,
            exit_code=None,
            violations=[],
        )

    # 5. 收集产出文件
    output_files: list[str] = []
    for ext in ("step", "stp", "stl", "dxf", "iges"):
        for p in output_dir.glob(f"*.{ext}"):
            output_files.append(str(p.resolve()))

    success = exit_code == 0 and len(output_files) > 0

    # 截断超长输出
    if len(stdout) > 8000:
        stdout = stdout[:4000] + "\n...[truncated]...\n" + stdout[-2000:]
    if len(stderr) > 8000:
        stderr = stderr[:4000] + "\n...[truncated]...\n" + stderr[-2000:]

    log.info(
        "sandbox.execute.done",
        success=success,
        exit_code=exit_code,
        elapsed_ms=elapsed_ms,
        output_count=len(output_files),
    )

    return ExecutionResult(
        success=success,
        stdout=stdout,
        stderr=stderr,
        output_files=output_files,
        elapsed_ms=elapsed_ms,
        exit_code=exit_code,
        violations=[],
    )
