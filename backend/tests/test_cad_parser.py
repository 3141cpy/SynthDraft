"""Task 2 CAD 解析底座单元测试。

覆盖：
1. test_parse_minimal_dxf —— 解析最小 DXF，断言 entities ≥ 3
2. test_parse_nonexistent_file_raises —— 传入不存在的路径，断言抛 CADParseError
3. test_odafc_unavailable_raises_or_returns_false —— ODA 不可用时行为正确
4. test_occ_availability_check —— is_occ_available 不崩溃
5. test_freecad_availability_check —— is_freecad_available 返回 False
6. test_schema_roundtrip —— 解析结果可 JSON 序列化/反序列化
7. test_title_block_extraction —— 标题栏字段正确提取
8. test_dxf_layers_and_dimensions —— 图层与尺寸标注结构正确
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.schemas.cad_intermediate import CADIntermediateModel
from app.services.cad import (
    CADParseError,
    ODANotAvailableError,
    is_freecad_available,
    is_occ_available,
    is_odafc_available,
    parse_dxf_to_intermediate,
)
from app.services.cad.dwg_converter import dwg_to_dxf

FIXTURE_DIR = Path(__file__).parent / "fixtures"
SAMPLE_DXF = FIXTURE_DIR / "sample.dxf"


@pytest.fixture(scope="module")
def sample_model() -> CADIntermediateModel:
    """模块级 fixture：解析 sample.dxf 一次，多个测试复用。"""
    if not SAMPLE_DXF.is_file():
        # 兜底：若 fixture 不存在则现场生成
        from tests.fixtures.generate_sample_dxf import generate
        generate(SAMPLE_DXF)
    return parse_dxf_to_intermediate(SAMPLE_DXF)


# ===== 必需测试 1：解析最小 DXF =====
def test_parse_minimal_dxf(sample_model: CADIntermediateModel) -> None:
    """解析最小 DXF，断言 entities 数 ≥ 3。"""
    assert sample_model.source_format == "dxf"
    assert sample_model.source_file.endswith("sample.dxf")
    # fixture 含 LINE/CIRCLE/TEXT/DIMENSION/INSERT 共 5 个实体
    assert len(sample_model.entities) >= 3, (
        f"期望 entities >= 3，实际 {len(sample_model.entities)}"
    )
    types = {e.type for e in sample_model.entities}
    assert {"LINE", "CIRCLE", "TEXT"}.issubset(types), (
        f"期望实体类型包含 LINE/CIRCLE/TEXT，实际 {types}"
    )
    # metadata 必须包含解析耗时与版本信息
    assert sample_model.metadata.get("parser") == "ezdxf"
    assert "ezdxf_version" in sample_model.metadata
    assert "parse_elapsed_ms" in sample_model.metadata
    assert sample_model.metadata["parse_elapsed_ms"] >= 0


# ===== 必需测试 2：文件不存在抛 CADParseError =====
def test_parse_nonexistent_file_raises() -> None:
    """传入不存在的路径，断言抛出 CADParseError。"""
    nonexistent = Path("nonexistent_file.dxf")
    with pytest.raises(CADParseError, match="不存在"):
        parse_dxf_to_intermediate(nonexistent)


# ===== 必需测试 3：ODA 不可用 =====
def test_odafc_unavailable_raises_or_returns_false(tmp_path: Path) -> None:
    """断言 is_odafc_available() 返回 False 且 dwg_to_dxf 抛 ODANotAvailableError。

    测试环境未安装 ODA File Converter。若实际安装了 ODA，本测试应被跳过
    （通过 pytest.skip）以免误报。
    """
    if is_odafc_available():
        pytest.skip("ODA File Converter 已安装，跳过不可用场景测试")

    assert is_odafc_available() is False

    # 造一个假的 .dwg 文件以触发 ODANotAvailableError（而非 FileNotFoundError）
    fake_dwg = tmp_path / "fake.dwg"
    fake_dwg.write_bytes(b"not a real dwg, only for testing")

    with pytest.raises(ODANotAvailableError):
        dwg_to_dxf(fake_dwg)


# ===== 必需测试 4：OCC 可用性检测 =====
def test_occ_availability_check() -> None:
    """is_occ_available() 不应崩溃；返回 bool。"""
    result = is_occ_available()
    assert isinstance(result, bool)
    # 测试环境实际已安装 cadquery-ocp，期望 True
    # 若未安装则期望 False（两种情况均通过）


# ===== 必需测试 5：FreeCAD 可用性检测 =====
def test_freecad_availability_check() -> None:
    """is_freecad_available() 应返回 False（测试环境未装 FreeCAD）。"""
    result = is_freecad_available()
    assert isinstance(result, bool)
    assert result is False, "测试环境未安装 FreeCAD，期望返回 False"


# ===== 必需测试 6：Schema 序列化/反序列化往返 =====
def test_schema_roundtrip(sample_model: CADIntermediateModel) -> None:
    """解析结果可序列化为 JSON 再反序列化为 CADIntermediateModel，类型校验通过。"""
    # 序列化为 JSON 字符串
    json_str = sample_model.model_dump_json()
    assert isinstance(json_str, str)

    # 解析 JSON 并校验为 dict
    data = json.loads(json_str)
    assert data["source_format"] == "dxf"
    assert isinstance(data["entities"], list)
    assert len(data["entities"]) >= 3

    # 反序列化回 CADIntermediateModel
    restored = CADIntermediateModel.model_validate_json(json_str)
    assert restored.source_file == sample_model.source_file
    assert restored.source_format == sample_model.source_format
    assert len(restored.entities) == len(sample_model.entities)
    assert len(restored.layers) == len(sample_model.layers)
    # 关键字段逐一比对
    for orig, rest in zip(sample_model.entities, restored.entities):
        assert orig.type == rest.type
        assert orig.layer == rest.layer
        assert orig.coordinates == rest.coordinates


# ===== 必需测试 7：标题栏字段提取 =====
def test_title_block_extraction(sample_model: CADIntermediateModel) -> None:
    """标题栏字段应从带属性的 INSERT 中正确提取。"""
    tb = sample_model.title_block
    assert tb is not None, "标题栏未提取到（期望非空）"
    assert tb.drawing_number == "SD-2026-001", f"drawing_number={tb.drawing_number}"
    assert tb.title == "Test Bracket", f"title={tb.title}"
    assert tb.scale == "1:2", f"scale={tb.scale}"
    assert tb.material == "Q235", f"material={tb.material}"
    assert tb.drawn_by == "alice", f"drawn_by={tb.drawn_by}"
    assert tb.checked_by == "bob", f"checked_by={tb.checked_by}"


# ===== 必需测试 8：图层与标注结构 =====
def test_dxf_layers_and_dimensions(sample_model: CADIntermediateModel) -> None:
    """图层与尺寸标注结构正确。"""
    layer_names = {l.name for l in sample_model.layers}
    # fixture 创建了 OUTLINE/DIM/TEXT/TITLE 四个图层，外加默认 0 与 Defpoints
    assert {"OUTLINE", "DIM", "TEXT", "TITLE"}.issubset(layer_names), (
        f"期望包含 OUTLINE/DIM/TEXT/TITLE，实际 {layer_names}"
    )

    # 单位：fixture 设置 $INSUNITS=4 (mm)；ezdxf.units.unit_name(4) 返回 "Millimeters"
    assert sample_model.units is not None
    units_lower = sample_model.units.lower()
    # "Millimeters" 拼写为 m-i-l-l-i-m-e-t-e-r-s，故匹配 "illi" 或 "meter"
    assert "illi" in units_lower or units_lower == "mm", (
        f"期望单位为 Millimeters 或 mm，实际 {sample_model.units!r}"
    )

    # 应至少有 1 个 DIMENSION 实体被识别为标注
    assert len(sample_model.dimensions) >= 1, (
        f"期望 dimensions >= 1，实际 {len(sample_model.dimensions)}"
    )
    dim = sample_model.dimensions[0]
    assert dim.type == "linear", f"dim.type={dim.type}"
    # linear dim 应有定义点
    assert len(dim.definition_points) >= 2, (
        f"definition_points 数量不足: {dim.definition_points}"
    )

    # blocks 中应包含 TITLE_BLOCK
    block_names = {b.name for b in sample_model.blocks}
    assert "TITLE_BLOCK" in block_names, f"TITLE_BLOCK 不在 blocks 中: {block_names}"

    # layouts 应至少包含 Model layout
    layout_names = {l.name for l in sample_model.layouts}
    assert "Model" in layout_names, f"Model layout 缺失: {layout_names}"
