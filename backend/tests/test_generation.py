"""Task 5 生成模块单元测试。

覆盖：
1. test_static_scan_rejects_dangerous_imports —— 静态扫描拒绝 ``import os``
2. test_static_scan_allows_cadquery_only —— 静态扫描放行纯 cadquery 代码
3. test_template_match_flange —— 模板匹配法兰盘并提取参数
4. test_template_match_shaft —— 模板匹配阶梯轴
5. test_regex_edit_outer_diameter —— 多轮正则降级修改外径
6. test_extract_python_code_from_llm_output —— LLM 输出代码块提取
7. test_execution_result_schema —— ExecutionResult/GecometryValidation schema 序列化
8. test_sandbox_executes_simple_cube —— 沙箱执行最小 CadQuery 立方体（依赖 cadquery 安装）
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 确保 backend/ 在 sys.path
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.schemas.generation_detail import (
    ExecutionResult,
    GeometryValidation,
    GenerationResult,
)
from app.services.generation import (
    STATIC_VIOLATIONS,
    execute_cadquery_code,
    static_scan_code,
)
from app.services.generation.code_generator import (
    _extract_python_code,
    _regex_edit,
)
from app.services.generation.templates import (
    detect_template,
    template_match_generate,
)


# ---------------------------------------------------------------------------
# 1. 静态扫描：危险 import
# ---------------------------------------------------------------------------


def test_static_scan_rejects_dangerous_imports() -> None:
    """含 ``import os`` / ``import subprocess`` 的代码必须被拒绝。"""
    malicious_samples = [
        "import cadquery as cq\nimport os\nos.system('rm -rf /')\nresult = cq.Workplane('XY').box(1,1,1)",
        "import cadquery as cq\nimport subprocess\nresult = cq.Workplane('XY').box(1,1,1)",
        "import cadquery as cq\nresult = cq.Workplane('XY').box(1,1,1)\n__import__('os').system('echo pwned')",
        "import cadquery as cq\neval('1+1')\nresult = cq.Workplane('XY').box(1,1,1)",
        "import cadquery as cq\nopen('/etc/passwd')\nresult = cq.Workplane('XY').box(1,1,1)",
        "import socket\nimport cadquery as cq\nresult = cq.Workplane('XY').box(1,1,1)",
        "from pathlib import Path\nimport cadquery as cq\nresult = cq.Workplane('XY').box(1,1,1)",
        "import cadquery as cq\nimport ctypes\nresult = cq.Workplane('XY').box(1,1,1)",
    ]
    for code in malicious_samples:
        violations = static_scan_code(code)
        assert len(violations) > 0, f"应拒绝危险代码，但未检出违规: {code!r}"


def test_static_scan_rejects_non_cadquery_import() -> None:
    """非 cadquery 的 import 必须被拒绝（即便不是黑名单模块）。"""
    code = "import numpy as np\nimport cadquery as cq\nresult = cq.Workplane('XY').box(1,1,1)"
    violations = static_scan_code(code)
    assert any("numpy" in v for v in violations), violations


def test_static_scan_allows_cadquery_only() -> None:
    """纯 cadquery 代码应通过静态扫描。"""
    safe_code = (
        "import cadquery as cq\n"
        "outer = 100\n"
        "result = cq.Workplane('XY').circle(outer/2).extrude(10)\n"
    )
    violations = static_scan_code(safe_code)
    assert violations == [], f"安全代码不应有违规: {violations}"


def test_static_violations_constant_present() -> None:
    """STATIC_VIOLATIONS 常量非空且含关键模式。"""
    assert "import os" in STATIC_VIOLATIONS
    assert "import subprocess" in STATIC_VIOLATIONS
    assert "__import__" in STATIC_VIOLATIONS
    assert "eval(" in STATIC_VIOLATIONS


# ---------------------------------------------------------------------------
# 2. 模板匹配
# ---------------------------------------------------------------------------


def test_template_match_flange() -> None:
    """法兰盘模板匹配 + 参数提取。"""
    prompt = "设计一个法兰盘，外径100mm，内径50mm，6个均布孔直径10mm，厚度10mm，孔分度圆直径80mm"
    code = template_match_generate(prompt)
    assert "import cadquery as cq" in code
    assert "outer_diameter = 100.0" in code
    assert "inner_diameter = 50.0" in code
    assert "hole_count = 6" in code
    assert "hole_diameter = 10.0" in code
    assert "bolt_circle_diameter = 80.0" in code
    assert "thickness = 10.0" in code
    assert "result =" in code
    assert detect_template(prompt) == "flange"


def test_template_match_flange_alt_phrasing() -> None:
    """法兰盘变体表达：'外径为120'。"""
    prompt = "做一个法兰盘，外径为120，内径为60，孔数8，孔径12，分度圆90，厚度15"
    code = template_match_generate(prompt)
    assert "outer_diameter = 120.0" in code
    assert "inner_diameter = 60.0" in code
    assert "hole_count = 8" in code
    assert "hole_diameter = 12.0" in code
    assert "thickness = 15.0" in code


def test_template_match_shaft() -> None:
    """阶梯轴模板匹配。"""
    prompt = "设计一根阶梯轴，左段直径20mm长40mm，右段直径30mm长60mm"
    code = template_match_generate(prompt)
    assert "import cadquery as cq" in code
    assert "seg1_diameter = 20.0" in code
    assert "seg1_length = 40.0" in code
    assert "seg2_diameter = 30.0" in code
    assert "seg2_length = 60.0" in code
    assert detect_template(prompt) == "shaft"


def test_template_match_plate() -> None:
    """矩形板模板匹配。"""
    prompt = "设计一块矩形板，长100mm宽60mm厚5mm，四角各有一个直径8mm的安装孔"
    code = template_match_generate(prompt)
    assert "import cadquery as cq" in code
    assert "length = 100.0" in code
    assert "width = 60.0" in code
    assert "thickness = 5.0" in code
    assert "hole_diameter = 8.0" in code
    assert detect_template(prompt) == "plate"


def test_template_match_default_cube() -> None:
    """无法识别时降级到 cube。"""
    code = template_match_generate("随便生成一个东西")
    assert "import cadquery as cq" in code
    assert "result = cq.Workplane(\"XY\").box" in code


def test_template_match_empty_prompt_raises() -> None:
    """空 prompt 应抛 ValueError。"""
    with pytest.raises(ValueError):
        template_match_generate("")


# ---------------------------------------------------------------------------
# 3. 多轮正则降级
# ---------------------------------------------------------------------------


def test_regex_edit_outer_diameter() -> None:
    """正则降级：'把外径改为120' 应替换 outer_diameter。"""
    original = (
        "import cadquery as cq\n"
        "outer_diameter = 100.0\n"
        "inner_diameter = 50.0\n"
        "result = cq.Workplane('XY').circle(outer_diameter/2).extrude(10)\n"
    )
    new_code = _regex_edit(original, "把外径改为120mm")
    # 接受 120 或 120.0（正则保留用户输入的数字格式）
    import re as _re

    assert _re.search(r"outer_diameter\s*=\s*120(?:\.0)?\b", new_code), new_code
    # 旧值不应再出现
    assert "outer_diameter = 100.0" not in new_code
    # 内径不应被改动
    assert "inner_diameter = 50.0" in new_code


def test_regex_edit_hole_count() -> None:
    """正则降级：'孔数改为8' 应替换 hole_count（整数）。"""
    original = (
        "import cadquery as cq\n"
        "hole_count = 6\n"
        "hole_diameter = 10.0\n"
        "result = cq.Workplane('XY')\n"
    )
    new_code = _regex_edit(original, "孔数改为8")
    assert "hole_count = 8" in new_code
    assert "hole_count = 6" not in new_code


def test_regex_edit_multi_param() -> None:
    """正则降级：多条修改意图同时存在。"""
    original = (
        "import cadquery as cq\n"
        "outer_diameter = 100.0\n"
        "hole_count = 6\n"
        "result = cq.Workplane('XY')\n"
    )
    new_code = _regex_edit(original, "把外径改为120，孔数改为8")
    import re as _re

    assert _re.search(r"outer_diameter\s*=\s*120(?:\.0)?\b", new_code), new_code
    assert "hole_count = 8" in new_code


def test_regex_edit_no_match_returns_original() -> None:
    """无匹配时返回原代码（不抛错）。"""
    original = "import cadquery as cq\nresult = cq.Workplane('XY').box(1,1,1)\n"
    new_code = _regex_edit(original, "改成红色")
    assert new_code == original


# ---------------------------------------------------------------------------
# 4. LLM 输出代码块提取
# ---------------------------------------------------------------------------


def test_extract_python_code_from_fenced_block() -> None:
    """从 ```python ... ``` 围栏中提取代码。"""
    llm_output = (
        "好的，这是代码：\n"
        "```python\n"
        "import cadquery as cq\n"
        "result = cq.Workplane('XY').box(10, 10, 10)\n"
        "```\n"
    )
    code = _extract_python_code(llm_output)
    assert "import cadquery as cq" in code
    assert "result = cq.Workplane('XY').box(10, 10, 10)" in code
    assert "```" not in code


def test_extract_python_code_last_block_wins() -> None:
    """多个代码块时取最后一个。"""
    llm_output = (
        "```python\nimport cadquery as cq\nresult = cq.Workplane('XY').box(1,1,1)\n```\n"
        "再修改：\n"
        "```python\nimport cadquery as cq\nresult = cq.Workplane('XY').box(2,2,2)\n```\n"
    )
    code = _extract_python_code(llm_output)
    assert "box(2,2,2)" in code
    assert "box(1,1,1)" not in code


def test_extract_python_code_no_fence() -> None:
    """无围栏时整段返回（去掉 ``` 标记行）。"""
    llm_output = "import cadquery as cq\nresult = cq.Workplane('XY').box(5,5,5)\n"
    code = _extract_python_code(llm_output)
    assert "import cadquery as cq" in code


def test_extract_python_code_empty() -> None:
    """空输入返回空字符串。"""
    assert _extract_python_code("") == ""


# ---------------------------------------------------------------------------
# 5. Schema 序列化
# ---------------------------------------------------------------------------


def test_execution_result_schema() -> None:
    """ExecutionResult 序列化/反序列化往返。"""
    er = ExecutionResult(
        success=True,
        stdout="EXPORT_OK step /tmp/x.step\n",
        stderr="",
        output_files=["/tmp/x.step"],
        elapsed_ms=123,
        exit_code=0,
        violations=[],
    )
    j = er.model_dump_json()
    restored = ExecutionResult.model_validate_json(j)
    assert restored.success is True
    assert restored.elapsed_ms == 123
    assert restored.output_files == ["/tmp/x.step"]


def test_geometry_validation_schema() -> None:
    """GeometryValidation 含 errors 时 is_valid 可以为 False。"""
    gv = GeometryValidation(
        is_valid=False,
        volume=0.0,
        bounding_box=None,
        surface_area=0.0,
        errors=["体积非正: 0.0"],
        backend="OCP",
    )
    j = gv.model_dump_json()
    restored = GeometryValidation.model_validate_json(j)
    assert restored.is_valid is False
    assert restored.backend == "OCP"
    assert "体积非正" in restored.errors[0]


def test_generation_result_schema() -> None:
    """GenerationResult 默认 mode=template。"""
    gr = GenerationResult(
        task_id="t-1",
        input_prompt="测试",
        generated_code="import cadquery as cq\n",
        mode="template",
    )
    assert gr.mode == "template"
    assert gr.execution.success is False  # default_factory
    assert gr.geometry_validation is None


# ---------------------------------------------------------------------------
# 6. 沙箱执行（依赖 cadquery 安装）
# ---------------------------------------------------------------------------


def _cadquery_available() -> bool:
    try:
        import cadquery  # noqa: F401

        return True
    except ImportError:
        return False


@pytest.mark.skipif(
    not _cadquery_available(),
    reason="cadquery 未安装，跳过沙箱执行测试",
)
def test_sandbox_executes_simple_cube(tmp_path: Path) -> None:
    """沙箱执行最小 CadQuery 立方体，断言 STEP 文件生成。"""
    code = (
        "import cadquery as cq\n"
        "size = 10.0\n"
        "result = cq.Workplane('XY').box(size, size, size)\n"
    )
    result = execute_cadquery_code(
        code=code,
        output_dir=tmp_path,
        timeout=30,
        output_format="step",
    )
    assert result.success, f"执行失败: stderr={result.stderr}"
    assert any(p.endswith(".step") for p in result.output_files), result.output_files
    assert result.exit_code == 0


@pytest.mark.skipif(
    not _cadquery_available(),
    reason="cadquery 未安装，跳过沙箱执行测试",
)
def test_sandbox_rejects_dangerous_code(tmp_path: Path) -> None:
    """沙箱应拒绝危险代码并返回 violations。"""
    code = (
        "import cadquery as cq\n"
        "import os\n"
        "os.system('echo pwned')\n"
        "result = cq.Workplane('XY').box(1,1,1)\n"
    )
    result = execute_cadquery_code(
        code=code,
        output_dir=tmp_path,
        timeout=10,
        output_format="step",
    )
    assert result.success is False
    assert len(result.violations) > 0
    assert result.exit_code is None  # 未执行子进程
