"""Task 4 端到端验证脚本。

用 sample.dxf 跑完整审图管线，输出 ReviewResult JSON：
1) prepare_review_context(dxf) → ReviewContext
2) VLM OCR（可选，本次环境无 VLM，应降级为 vector_only）
3) fuse_to_semantic_model() → SemanticModel
4) judge_with_fallback()（先试 LLM qwen2.5:7b，失败降级 rule_engine）
5) compute_compliance_score()
6) generate_html_report() + generate_pdf_report()
7) 打印 ReviewResult JSON（含 score / defects / review_mode / report_path）

断言：
- defects 数 ≥ 0（允许无缺陷）
- score 在 0-100 之间
- report_path 文件存在
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# 将 backend 目录加入 sys.path
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

FIXTURE_DXF = BACKEND_ROOT / "tests" / "fixtures" / "sample.dxf"


def main() -> int:
    # 注入环境变量（指向本地 Ollama/Qdrant）
    os.environ.setdefault("OLLAMA_HOST_URL", "http://localhost:11434")
    os.environ.setdefault("QDRANT_URL", "http://localhost:6333")

    print("=" * 70)
    print("Task 4 端到端验证（sample.dxf）")
    print("=" * 70)
    print(f"DXF: {FIXTURE_DXF}")
    assert FIXTURE_DXF.is_file(), f"sample.dxf 不存在: {FIXTURE_DXF}"

    # ===== 步骤 1：prepare_review_context =====
    print("\n--- 步骤 1：prepare_review_context ---")
    from app.services.review.pipeline import prepare_review_context

    t0 = time.perf_counter()
    ctx = prepare_review_context(FIXTURE_DXF)
    t1 = time.perf_counter()
    print(f"  source_format: {ctx.source_format}")
    print(f"  entities: {len(ctx.cad_model.entities)}")
    print(f"  dimensions: {len(ctx.cad_model.dimensions)}")
    print(f"  layers: {len(ctx.cad_model.layers)}")
    print(f"  title_block: {ctx.cad_model.title_block is not None}")
    print(f"  image_path: {ctx.image_path}")
    print(f"  耗时: {(t1 - t0) * 1000:.0f}ms")

    # ===== 步骤 2：VLM OCR =====
    print("\n--- 步骤 2：VLM OCR ---")
    from app.services.review.vlm_ocr import is_vlm_available, vlm_detect_regions, vlm_ocr_extract

    vlm_available = is_vlm_available()
    print(f"  VLM 可用: {vlm_available}")
    vlm_result: dict = {}
    if vlm_available and ctx.image_path:
        regions = vlm_detect_regions(Path(ctx.image_path))
        print(f"  regions: {len(regions)}")
        vlm_result = vlm_ocr_extract(Path(ctx.image_path), regions)
        print(f"  OCR keys: {list(vlm_result.keys())}")
    else:
        print("  跳过 VLM OCR（无视觉模型或无图片）")

    # ===== 步骤 3：fuse_to_semantic_model =====
    print("\n--- 步骤 3：fuse_to_semantic_model ---")
    from app.services.review.pipeline import fuse_to_semantic_model

    sm = fuse_to_semantic_model(ctx.cad_model, vlm_result)
    print(f"  geometry.lines: {len(sm.geometry.lines)}")
    print(f"  geometry.circles: {len(sm.geometry.circles)}")
    print(f"  geometry.arcs: {len(sm.geometry.arcs)}")
    print(f"  geometry.texts: {len(sm.geometry.texts)}")
    print(f"  topology.shared_endpoints: {len(sm.topology.shared_endpoints)}")
    print(f"  topology.concentric_pairs: {len(sm.topology.concentric_pairs)}")
    print(f"  semantic.dimension_count: {sm.semantic.dimension_count}")
    print(f"  semantic.has_title_block: {sm.semantic.has_title_block}")
    print(f"  semantic.has_tolerance: {sm.semantic.has_tolerance}")
    print(f"  semantic.has_surface_roughness: {sm.semantic.has_surface_roughness}")
    print(f"  semantic.layer_names: {sm.semantic.layer_names}")

    # ===== 步骤 4：judge_with_fallback =====
    print("\n--- 步骤 4：judge_with_fallback（LLM 优先，失败降级 rule_engine）---")
    from app.services.review.llm_judge import is_llm_available, judge_with_fallback

    llm_available = is_llm_available()
    print(f"  LLM 可用: {llm_available}")
    t0 = time.perf_counter()
    defects, judge_mode, llm_model = judge_with_fallback(sm, use_llm=True, top_k=5)
    t1 = time.perf_counter()
    print(f"  judge_mode: {judge_mode}")
    print(f"  llm_model: {llm_model or '(none)'}")
    print(f"  defects: {len(defects)} 条")
    print(f"  耗时: {(t1 - t0) * 1000:.0f}ms")
    print("\n  缺陷列表:")
    for i, d in enumerate(defects, 1):
        print(f"    [{i}] {d.severity:8s} | {d.category:18s} | {d.standard_ref}")
        print(f"         evidence: {d.evidence[:80]}")
        print(f"         suggestion: {d.suggestion[:80]}")

    # 综合审图模式
    if judge_mode == "llm":
        review_mode = "vlm" if vlm_available and vlm_result else "vector_only"
    else:
        review_mode = "rule_engine"
    print(f"\n  review_mode: {review_mode}")

    # ===== 步骤 5：compute_compliance_score =====
    print("\n--- 步骤 5：compute_compliance_score ---")
    from app.services.review.scoring import compute_compliance_score, severity_counts

    score = compute_compliance_score(defects)
    counts = severity_counts(defects)
    print(f"  score: {score}")
    print(f"  severity_counts: {counts}")

    # ===== 步骤 6：generate_html_report + generate_pdf_report =====
    print("\n--- 步骤 6：generate_html_report + generate_pdf_report ---")
    from app.schemas.review_detail import ReviewResult
    from app.services.review.report import generate_html_report, generate_pdf_report

    result = ReviewResult(
        task_id="e2e-verify-001",
        file_key="sample.dxf",
        file_type="dxf",
        compliance_score=score,
        defects=defects,
        standards_applied=["GB/T 1182", "GB/T 4457.4", "GB/T 17450", "GB/T 131", "GB/T 18229"],
        review_mode=review_mode,  # type: ignore[arg-type]
        report_path=None,
        metadata={
            "image_path": ctx.image_path,
            "judge_mode": judge_mode,
            "llm_model": llm_model,
            "vlm_available": vlm_available,
        },
    )
    html_path = generate_html_report(result)
    result.report_path = str(html_path)
    print(f"  HTML 报告: {html_path} ({html_path.stat().st_size} bytes)")
    pdf_path = generate_pdf_report(html_path)
    if pdf_path:
        result.pdf_report_path = str(pdf_path)
        print(f"  PDF 报告: {pdf_path} ({pdf_path.stat().st_size} bytes)")
    else:
        print("  PDF 报告: 跳过（weasyprint 不可用，Windows 缺 GTK 库）")

    # ===== 步骤 7：断言 + 输出 ReviewResult JSON =====
    print("\n--- 步骤 7：断言校验 ---")
    assert len(defects) >= 0, "defects 应为非负"
    assert 0.0 <= score <= 100.0, f"score 越界: {score}"
    assert Path(result.report_path).is_file(), f"HTML 报告文件不存在: {result.report_path}"
    print(f"  ✓ defects 数 ≥ 0: PASS (n={len(defects)})")
    print(f"  ✓ score 在 0-100: PASS (score={score})")
    print(f"  ✓ HTML 报告文件存在: PASS ({result.report_path})")

    print("\n--- ReviewResult JSON ---")
    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))

    print("\n" + "=" * 70)
    print(f"验证完成。mode={review_mode}, score={score}, defects={len(defects)}")
    print(f"报告路径: {result.report_path}")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
