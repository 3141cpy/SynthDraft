"""Task 5 端到端验证脚本。

验证流程：
1. 检查 cadquery 可用性 + Ollama LLM 可用性
2. CadQuery 基础验证：最小立方体脚本 → STEP 导出
3. 静态扫描验证：构造恶意代码，断言被拒绝
4. 沙箱执行验证：合法 CadQuery 代码（法兰盘）→ STEP 文件
5. 几何校验验证：对生成的 STEP 调用 validate_step_file，断言 volume > 0
6. 端到端测试：完整管线（generate → execute → validate）
7. 多轮对话测试：apply_multi_turn_edit 修改外径与孔数
8. 输出 GenerationResult JSON

运行：
    d:\\SynthDraft\\backend\\.venv\\Scripts\\python.exe tests/verify_task5_e2e.py
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

# 将 backend 目录加入 sys.path
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def section(title: str) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'-' * 70}")


def _cadquery_available() -> bool:
    try:
        import cadquery  # noqa: F401

        return True
    except ImportError:
        return False


def _occ_available() -> bool:
    from app.services.cad.occ_engine import is_occ_available

    return is_occ_available()


def main() -> int:
    print("=" * 70)
    print("Task 5 端到端验证")
    print("=" * 70)

    failures: list[str] = []

    # ===== 1. 依赖与可用性检查 =====
    section("步骤 1：依赖与可用性检查")
    cq_ok = _cadquery_available()
    occ_ok = _occ_available()
    print(f"cadquery 可用: {cq_ok}")
    print(f"OCC (OCP) 可用: {occ_ok}")
    if cq_ok:
        import cadquery

        print(f"cadquery 版本: {cadquery.__version__}")

    from app.services.generation import is_llm_available

    llm_ok = is_llm_available()
    print(f"LLM (qwen2.5-coder:7b) 可用: {llm_ok}")
    if not llm_ok:
        print("[warn] LLM 不可用，将走模板匹配降级路径")

    if not cq_ok:
        print("[FAIL] cadquery 未安装，无法继续后续验证")
        failures.append("cadquery 未安装")
        _print_summary(failures)
        return 1

    # ===== 2. CadQuery 基础验证：最小立方体 =====
    section("步骤 2：CadQuery 基础验证（最小立方体 → STEP）")
    try:
        import cadquery as cq

        t0 = time.time()
        cube = cq.Workplane("XY").box(10, 10, 10)
        vol = cube.val().Volume()
        with tempfile.TemporaryDirectory() as td:
            step_path = Path(td) / "cube.step"
            cq.exporters.export(cube, str(step_path))
            size = step_path.stat().st_size
        elapsed = (time.time() - t0) * 1000
        print(f"立方体体积: {vol:.2f} mm³ (期望 1000)")
        print(f"STEP 文件大小: {size} bytes")
        print(f"耗时: {elapsed:.1f} ms")
        assert abs(vol - 1000.0) < 1.0, f"体积异常: {vol}"
        assert size > 0
        print("[OK] CadQuery 基础验证通过")
    except Exception as e:  # noqa: BLE001
        print(f"[FAIL] CadQuery 基础验证失败: {type(e).__name__}: {e}")
        failures.append(f"CadQuery 基础: {e}")

    # ===== 3. 静态扫描验证 =====
    section("步骤 3：静态扫描验证（拒绝 import os）")
    from app.services.generation import static_scan_code

    malicious = (
        "import cadquery as cq\n"
        "import os\n"
        "os.system('rm -rf /')\n"
        "result = cq.Workplane('XY').box(1,1,1)\n"
    )
    violations = static_scan_code(malicious)
    print(f"恶意代码违规列表: {violations}")
    assert len(violations) > 0, "静态扫描未拒绝 import os"
    print("[OK] 静态扫描拒绝危险代码")

    safe_code = (
        "import cadquery as cq\n"
        "result = cq.Workplane('XY').box(10,10,10)\n"
    )
    safe_violations = static_scan_code(safe_code)
    print(f"安全代码违规列表: {safe_violations}")
    assert safe_violations == []
    print("[OK] 静态扫描放行纯 cadquery 代码")

    # ===== 4. 沙箱执行验证：法兰盘 =====
    section("步骤 4：沙箱执行验证（法兰盘模板）")
    from app.services.generation import execute_cadquery_code, template_match_generate

    flange_prompt = "设计一个法兰盘，外径100mm，内径50mm，6个均布孔直径10mm，厚度10mm，孔分度圆直径80mm"
    flange_code = template_match_generate(flange_prompt)
    print("-- 生成的 CadQuery 代码 --")
    print(flange_code)

    sandbox_dir = Path(tempfile.mkdtemp(prefix="task5_sandbox_"))
    exec_result = None
    try:
        exec_result = execute_cadquery_code(
            code=flange_code,
            output_dir=sandbox_dir,
            timeout=30,
            output_format="step",
        )
        print(f"\n执行结果 success: {exec_result.success}")
        print(f"exit_code: {exec_result.exit_code}")
        print(f"elapsed_ms: {exec_result.elapsed_ms}")
        print(f"output_files: {exec_result.output_files}")
        if exec_result.stderr:
            print(f"stderr (前500字符): {exec_result.stderr[:500]}")
        if exec_result.stdout:
            print(f"stdout (前500字符): {exec_result.stdout[:500]}")
        assert exec_result.success, f"沙箱执行失败: {exec_result.stderr}"
        assert any(p.endswith(".step") for p in exec_result.output_files)
        print("[OK] 沙箱执行生成 STEP 文件")
    except Exception as e:  # noqa: BLE001
        print(f"[FAIL] 沙箱执行异常: {type(e).__name__}: {e}")
        failures.append(f"沙箱执行: {e}")

    # ===== 5. 几何校验验证 =====
    section("步骤 5：几何校验验证（对 STEP 文件）")
    from app.services.generation import validate_step_file

    if exec_result is None:
        print("[FAIL] 沙箱执行未产出结果，跳过几何校验")
        failures.append("几何校验: 沙箱执行失败")
    else:
        step_files = [p for p in exec_result.output_files if p.endswith(".step")]
        if step_files:
            step_path = Path(step_files[0])
            geo = validate_step_file(step_path)
            print(f"is_valid: {geo.is_valid}")
            print(f"volume: {geo.volume:.2f} mm³")
            print(f"surface_area: {geo.surface_area:.2f} mm²")
            print(f"bounding_box: {geo.bounding_box}")
            print(f"errors: {geo.errors}")
            print(f"backend: {geo.backend}")
            assert geo.volume > 0, f"体积应 > 0, 实际 {geo.volume}"
            print("[OK] 几何校验通过，volume > 0")
        else:
            print("[FAIL] 无 STEP 文件可供校验")
            failures.append("几何校验: 无 STEP 文件")

    # ===== 6. 端到端：完整生成管线 =====
    section("步骤 6：端到端生成管线（自然语言 → CadQuery → STEP）")
    from app.services.generation import generate_cadquery_code

    e2e_prompt = "设计一个法兰盘，外径100mm，内径50mm，6个均布孔直径10mm，厚度10mm，孔分度圆直径80mm"
    t0 = time.time()
    e2e_code, mode = generate_cadquery_code(e2e_prompt)
    gen_elapsed = (time.time() - t0) * 1000
    print(f"生成模式 mode: {mode}")
    print(f"代码生成耗时: {gen_elapsed:.1f} ms")
    print("-- 生成的 CadQuery 代码（前 30 行）--")
    for i, line in enumerate(e2e_code.splitlines()[:30], 1):
        print(f"  {i:3d}: {line}")

    e2e_dir = Path(tempfile.mkdtemp(prefix="task5_e2e_"))
    e2e_exec = execute_cadquery_code(
        code=e2e_code, output_dir=e2e_dir, timeout=30, output_format="step"
    )
    print(f"\n执行 success: {e2e_exec.success}")
    print(f"output_files: {e2e_exec.output_files}")

    e2e_geo = None
    e2e_step_files = [p for p in e2e_exec.output_files if p.endswith(".step")]
    if e2e_step_files:
        e2e_geo = validate_step_file(Path(e2e_step_files[0]))
        print(f"几何校验: is_valid={e2e_geo.is_valid}, volume={e2e_geo.volume:.2f}")

    # 组装 GenerationResult
    from app.schemas.generation_detail import (
        ExecutionResult,
        GenerationResult as GR,
    )

    result = GR(
        task_id="verify-task5-e2e",
        input_prompt=e2e_prompt,
        generated_code=e2e_code,
        execution=e2e_exec,
        geometry_validation=e2e_geo,
        output_files=e2e_exec.output_files,
        mode=mode,  # type: ignore[arg-type]
        metadata={
            "llm_available": llm_ok,
            "codegen_elapsed_ms": int(gen_elapsed),
        },
    )
    print("\n-- GenerationResult JSON --")
    print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2)[:3000])

    if e2e_exec.success and e2e_geo and e2e_geo.volume > 0:
        print("\n[OK] 端到端管线通过")
    else:
        print("\n[FAIL] 端到端管线异常")
        failures.append("端到端: 执行或几何校验失败")

    # ===== 7. 多轮对话测试 =====
    section("步骤 7：多轮对话修改（把外径改为120，孔数改为8）")
    from app.services.generation import apply_multi_turn_edit

    edit_instruction = "把外径改为120mm，孔数改为8"
    t0 = time.time()
    new_code = apply_multi_turn_edit(
        original_code=e2e_code,
        edit_instruction=edit_instruction,
        history=[{"role": "user", "content": e2e_prompt}],
    )
    edit_elapsed = (time.time() - t0) * 1000
    print(f"多轮修改耗时: {edit_elapsed:.1f} ms")
    print("-- 修改后代码（前 20 行）--")
    for i, line in enumerate(new_code.splitlines()[:20], 1):
        print(f"  {i:3d}: {line}")

    if new_code != e2e_code:
        print("[OK] 新代码与原代码不同")
    else:
        print("[FAIL] 新代码与原代码相同")
        failures.append("多轮对话: 代码未变更")

    # 检查参数是否真的被改了
    # 正则降级路径会替换；LLM 路径可能整体重写
    has_120 = "120" in new_code
    has_8 = "hole_count = 8" in new_code or "8" in new_code
    print(f"新代码含 '120': {has_120}")
    print(f"新代码含 hole_count=8 或 8: {has_8}")

    # 重新执行新代码验证
    new_dir = Path(tempfile.mkdtemp(prefix="task5_multiturn_"))
    new_exec = execute_cadquery_code(
        code=new_code, output_dir=new_dir, timeout=30, output_format="step"
    )
    print(f"\n修改后代码执行 success: {new_exec.success}")
    if new_exec.success:
        new_step_files = [p for p in new_exec.output_files if p.endswith(".step")]
        if new_step_files:
            new_geo = validate_step_file(Path(new_step_files[0]))
            print(f"修改后几何: is_valid={new_geo.is_valid}, volume={new_geo.volume:.2f}")
            print(f"修改后包围盒: {new_geo.bounding_box}")
            # 外径从 100 → 120，体积应变化
            if e2e_geo and new_geo:
                print(
                    f"体积变化: {e2e_geo.volume:.2f} → {new_geo.volume:.2f} "
                    f"(delta={new_geo.volume - e2e_geo.volume:.2f})"
                )
                if abs(new_geo.volume - e2e_geo.volume) > 1.0:
                    print("[OK] 修改后体积确实变化（多轮生效）")
                else:
                    print("[warn] 修改后体积未变化，可能 LLM 路径未按预期修改")
    else:
        print(f"[FAIL] 修改后代码执行失败: {new_exec.stderr[:500]}")
        failures.append("多轮对话: 修改后代码执行失败")

    # ===== 8. 单元测试运行 =====
    section("步骤 8：单元测试（test_generation.py）")
    import subprocess

    t0 = time.time()
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(BACKEND_ROOT / "tests" / "test_generation.py"),
            "-v",
            "--tb=short",
        ],
        capture_output=True,
        text=True,
        cwd=str(BACKEND_ROOT),
        timeout=180,
    )
    print(f"pytest 退出码: {proc.returncode}")
    print(f"pytest 耗时: {time.time() - t0:.1f}s")
    print("-- pytest stdout (最后 80 行) --")
    for line in proc.stdout.splitlines()[-80:]:
        print(f"  {line}")
    if proc.returncode != 0:
        failures.append(f"单元测试失败 (exit={proc.returncode})")
        print("-- pytest stderr (最后 30 行) --")
        for line in proc.stderr.splitlines()[-30:]:
            print(f"  {line}")

    # ===== 汇总 =====
    _print_summary(failures)
    return 0 if not failures else 1


def _print_summary(failures: list[str]) -> None:
    print("\n" + "=" * 70)
    print("验证汇总")
    print("=" * 70)
    if not failures:
        print("全部验证通过 ✓")
    else:
        print(f"共 {len(failures)} 项失败:")
        for i, f in enumerate(failures, 1):
            print(f"  {i}. {f}")


if __name__ == "__main__":
    sys.exit(main())
