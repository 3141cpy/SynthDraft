"""Task 4 智能审图模块单元测试。

覆盖：
1. test_render_dxf_to_image —— 渲染 sample.dxf 为 PNG，断言文件存在且 > 0 字节
2. test_prepare_review_context —— 解析 sample.dxf，断言 cad_model.entities 非空
3. test_rule_engine_judge —— 构造缺失标题栏的 SemanticModel，断言 ≥1 条缺陷
4. test_compute_compliance_score —— 构造 1 critical + 2 major，断言 score == 69
5. test_generate_html_report —— 生成 HTML 报告，断言含"合规性评分"文字
6. test_fuse_to_semantic_model —— 融合语义模型，断言几何层非空
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.schemas.cad_intermediate import CADIntermediateModel
from app.schemas.review_detail import (
    DefectItem,
    ReviewResult,
    SemanticModel,
    SemanticLayer,
    GeometryLayer,
)
from app.services.review.pipeline import (
    fuse_to_semantic_model,
    prepare_review_context,
    render_dxf_to_image,
)
from app.services.review.report import generate_html_report
from app.services.review.rule_engine import rule_engine_judge
from app.services.review.scoring import compute_compliance_score

FIXTURE_DIR = Path(__file__).parent / "fixtures"
SAMPLE_DXF = FIXTURE_DIR / "sample.dxf"


# ===== Fixtures =====


@pytest.fixture(scope="module")
def _ensure_sample_dxf() -> Path:
    """确保 sample.dxf 存在，不存在则生成。"""
    if not SAMPLE_DXF.is_file():
        from tests.fixtures.generate_sample_dxf import generate

        generate(SAMPLE_DXF)
    assert SAMPLE_DXF.is_file(), f"sample.dxf 仍不存在: {SAMPLE_DXF}"
    return SAMPLE_DXF


# ===== SubTask 4.1 测试 =====


def test_render_dxf_to_image(_ensure_sample_dxf: Path, tmp_path: Path) -> None:
    """渲染 sample.dxf 为 PNG，断言文件存在且 > 0 字节。"""
    out = tmp_path / "sample.png"
    result = render_dxf_to_image(_ensure_sample_dxf, output_path=out, dpi=100)
    assert result == out
    assert out.is_file(), f"PNG 文件未生成: {out}"
    assert out.stat().st_size > 0, "PNG 文件为空"
    # PNG 文件头魔数：\x89PNG\r\n\x1a\n
    with open(out, "rb") as f:
        header = f.read(8)
    assert header.startswith(b"\x89PNG\r\n\x1a\n"), f"PNG 文件头异常: {header!r}"


def test_prepare_review_context(_ensure_sample_dxf: Path) -> None:
    """解析 sample.dxf，断言 ReviewContext.cad_model.entities 非空。"""
    ctx = prepare_review_context(_ensure_sample_dxf)
    assert ctx.source_file.endswith("sample.dxf")
    assert ctx.source_format == "dxf"
    assert ctx.cad_model is not None
    assert len(ctx.cad_model.entities) > 0, "entities 不应为空"
    # sample.dxf 含 LINE/CIRCLE/TEXT/DIMENSION/INSERT
    types = {e.type for e in ctx.cad_model.entities}
    assert "LINE" in types, f"应含 LINE，实际 types={types}"
    # 标题栏应被识别
    assert ctx.cad_model.title_block is not None, "标题栏未被识别"
    assert ctx.cad_model.title_block.drawing_number == "SD-2026-001"
    # image_path 可能为 None（若 matplotlib 不可用），但若有则文件应存在
    if ctx.image_path:
        assert Path(ctx.image_path).is_file(), f"图片文件不存在: {ctx.image_path}"
    # parse_metadata 应含关键字段
    assert "entity_count" in ctx.parse_metadata
    assert ctx.parse_metadata["entity_count"] > 0


# ===== SubTask 4.3 测试 =====


def test_fuse_to_semantic_model(_ensure_sample_dxf: Path) -> None:
    """融合语义模型，断言几何层非空、统计字段正确。"""
    ctx = prepare_review_context(_ensure_sample_dxf)
    sm = fuse_to_semantic_model(ctx.cad_model, vlm_result=None)
    assert sm.geometry is not None
    assert len(sm.geometry.lines) > 0, "几何层 lines 不应为空"
    assert len(sm.geometry.circles) > 0, "几何层 circles 不应为空"
    assert len(sm.geometry.texts) > 0, "几何层 texts 不应为空"
    # 语义层
    assert sm.semantic.has_title_block is True
    assert sm.semantic.dimension_count >= 1
    assert "OUTLINE" in sm.semantic.layer_names or "DIM" in sm.semantic.layer_names
    # 统计
    assert sm.stats["geometry_line_count"] == len(sm.geometry.lines)
    assert sm.stats["entity_total"] == len(ctx.cad_model.entities)


# ===== SubTask 4.4/4.5 测试 =====


def test_rule_engine_judge_missing_title_block() -> None:
    """构造缺失标题栏的 SemanticModel，断言 rule_engine 输出 ≥1 条 critical 缺陷。"""
    sm = _build_minimal_semantic_model(has_title_block=False, has_dims=False)
    defects = rule_engine_judge(sm)
    assert len(defects) >= 1, "缺失标题栏应至少报 1 条缺陷"
    # 应含 critical 标题栏缺失
    title_defects = [d for d in defects if d.category == "title_block"]
    assert len(title_defects) >= 1
    assert any(d.severity == "critical" for d in title_defects)
    # 每条缺陷必含 SubTask 4.5 强制字段
    for d in defects:
        assert d.category is not None
        assert d.severity in ("critical", "major", "minor", "warning")
        assert d.standard_ref  # 非空
        assert d.suggestion  # 非空
        assert d.evidence  # 非空


def test_rule_engine_judge_complete_model(_ensure_sample_dxf: Path) -> None:
    """用完整的 sample.dxf 跑规则引擎，断言缺陷数 ≥ 0 且评分在 0-100。"""
    ctx = prepare_review_context(_ensure_sample_dxf)
    sm = fuse_to_semantic_model(ctx.cad_model)
    defects = rule_engine_judge(sm)
    score = compute_compliance_score(defects)
    assert 0.0 <= score <= 100.0
    # sample.dxf 缺表面粗糙度与形位公差，应有 warning/minor 缺陷
    categories = {d.category for d in defects}
    assert "surface_roughness" in categories or "tolerance" in categories, (
        f"完整模型应报粗糙度/形位公差缺陷，实际 categories={categories}"
    )


# ===== SubTask 4.6 测试 =====


def test_compute_compliance_score() -> None:
    """构造 1 critical + 2 major + 0 minor + 0 warning，断言 score = 100 - 15 - 16 = 69。"""
    defects = [
        DefectItem(
            category="title_block",
            severity="critical",
            standard_ref="GB/T 18229-2023 §A.3",
            suggestion="补标题栏",
            evidence="无标题栏",
        ),
        DefectItem(
            category="dimensioning",
            severity="major",
            standard_ref="GB/T 4457.4-2002 §4.1",
            suggestion="补尺寸",
            evidence="无尺寸",
        ),
        DefectItem(
            category="layer_naming",
            severity="major",
            standard_ref="GB/T 17450-1998 §5",
            suggestion="改图层名",
            evidence="图层名不规范",
        ),
    ]
    score = compute_compliance_score(defects)
    # 100 - 15 (1 critical) - 16 (2 major × 8) = 69
    assert score == 69.0, f"期望 69.0，实际 {score}"


def test_compute_compliance_score_zero_cap() -> None:
    """构造大量 critical，断言 score 不为负。"""
    defects = [
        DefectItem(
            category="other",
            severity="critical",
            standard_ref="test",
            suggestion="test",
            evidence="test",
        )
        for _ in range(20)
    ]
    score = compute_compliance_score(defects)
    assert score == 0.0, f"期望 0.0，实际 {score}"


def test_compute_compliance_score_perfect() -> None:
    """无缺陷应得满分。"""
    score = compute_compliance_score([])
    assert score == 100.0


# ===== SubTask 4.7 测试 =====


def test_generate_html_report(_ensure_sample_dxf: Path, tmp_path: Path) -> None:
    """生成 HTML 报告，断言文件存在且含"合规性评分"文字。"""
    ctx = prepare_review_context(_ensure_sample_dxf)
    sm = fuse_to_semantic_model(ctx.cad_model)
    defects = rule_engine_judge(sm)
    score = compute_compliance_score(defects)

    result = ReviewResult(
        task_id="test-task-001",
        file_key="sample.dxf",
        file_type="dxf",
        compliance_score=score,
        defects=defects,
        standards_applied=["GB/T 1182", "GB/T 4457.4"],
        review_mode="rule_engine",
        report_path=None,
        metadata={"image_path": ctx.image_path},
    )

    out = tmp_path / "report.html"
    html_path = generate_html_report(result, output_path=out)
    assert html_path == out
    assert out.is_file(), f"HTML 报告未生成: {out}"
    assert out.stat().st_size > 0

    content = out.read_text(encoding="utf-8")
    assert "合规性评分" in content, "HTML 报告应含'合规性评分'文字"
    assert "SynthDraft" in content, "HTML 报告应含 'SynthDraft' 标题"
    assert "review_mode" in content or "rule_engine" in content, (
        "HTML 报告应标注审图模式"
    )
    # 若有图片且成功嵌入，应含 base64 图片
    if ctx.image_path:
        assert "data:image/png;base64," in content, "HTML 报告应内嵌 PNG 图片"


# ===== 内部辅助 =====


def _build_minimal_semantic_model(
    has_title_block: bool = False,
    has_dims: bool = False,
) -> SemanticModel:
    """构造最小语义模型（用于规则引擎测试）。"""
    geometry = GeometryLayer(
        lines=[
            {"start": [0.0, 0.0, 0.0], "end": [10.0, 0.0, 0.0], "length": 10.0, "layer": "OUTLINE"},
        ],
        circles=[
            {"center": [5.0, 5.0, 0.0], "radius": 2.0, "layer": "OUTLINE"},
        ],
    )
    semantic = SemanticLayer(
        dimension_count=1 if has_dims else 0,
        dimension_types={"linear": 1} if has_dims else {},
        has_title_block=has_title_block,
        title_block_fields={"drawing_number": "X-001"} if has_title_block else {},
        has_tolerance=False,
        has_surface_roughness=False,
        layer_names=["OUTLINE", "DIM", "TEXT"],
    )
    return SemanticModel(
        geometry=geometry,
        semantic=semantic,
        source_file="test.dxf",
        stats={"entity_total": 2},
    )
