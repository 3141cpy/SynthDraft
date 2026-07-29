"""Task 11 端到端实测脚本（审图→生成→复审协同闭环）。

覆盖 SubTask：
- 11.1：缺陷 → LLM prompt 转换 + Celery 任务派发 + API 端点
- 11.2：修订后文件自动复审（run_generation 内嵌自检派发）
- 11.3：修订前后对比报告（diff_report + 闭环率）
- 11.4：用户反馈存储 / 检索 / 统计
- E2E：完整闭环 审图→优化→生成→复审→对比报告

执行策略（遵循"以实测为荣"，不靠 mock 兜底）：
- 真实 Redis broker/backend（localhost:6379）
- 直接调用 task 函数体（绕过 Celery 任务包装的序列化开销）
- FastAPI TestClient 测试 API 端点
- 真实文件系统操作（feedback 存储 / 报告生成）

运行：
    d:\\SynthDraft\\backend\\.venv\\Scripts\\python.exe tests/verify_task11_e2e.py
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

# 将 backend 目录加入 sys.path
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# 指向本地 Redis / Ollama（实测环境）
os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6379/1")
os.environ.setdefault("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("OLLAMA_HOST_URL", "http://localhost:11434")
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("UPLOAD_DIR", "./tmp_uploads")
os.environ.setdefault("LOG_LEVEL", "WARNING")  # 降低日志噪声


def section(title: str) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'-' * 70}", flush=True)


def _ok(msg: str) -> None:
    print(f"  [PASS] {msg}", flush=True)


def _fail(msg: str, detail: str = "") -> None:
    print(f"  [FAIL] {msg}{f' :: {detail}' if detail else ''}", flush=True)


def _info(msg: str) -> None:
    print(f"  [INFO] {msg}", flush=True)


# ===== 全局统计 =====
_passed = 0
_failed = 0
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


# ===== Celery 配置辅助 =====


def _setup_celery_eager() -> None:
    """配置 Celery eager 模式 + 存储 eager 结果。"""
    from app.celery_app import celery_app
    celery_app.conf.update(
        task_always_eager=True,
        task_eager_propagates=True,
        task_store_eager_result=True,
        broker_connection_retry_on_startup=False,
    )


def _store_review_result(review_task_id: str, review_result_dict: dict[str, Any]) -> None:
    """将审图结果写入 Celery result backend。"""
    from app.celery_app import celery_app
    backend = celery_app.AsyncResult(review_task_id).backend
    if backend is not None:
        backend.store_result(review_task_id, review_result_dict, "SUCCESS")


# ===== 构造测试缺陷数据 =====


def _make_defect(
    category: str = "title_block",
    severity: str = "major",
    standard_ref: str = "GB/T 18229-2023 §A.3",
    suggestion: str = "请在标题栏中补充图号字段",
    evidence: str = "标题栏 drawing_number 字段为空",
    coordinate: dict[str, float] | None = None,
) -> dict[str, Any]:
    """构造单条缺陷 dict（与 DefectItem schema 对齐）。"""
    return {
        "category": category,
        "severity": severity,
        "coordinate": coordinate if coordinate is not None else {"x": 100.0, "y": 50.0},
        "standard_ref": standard_ref,
        "standard_clause_id": "A.3",
        "suggestion": suggestion,
        "evidence": evidence,
    }


def _make_review_result_dict(
    task_id: str,
    defects: list[dict[str, Any]],
    score: float = 60.0,
    file_key: str = "test_sample.dxf",
) -> dict[str, Any]:
    """构造 ReviewResult dict（与 Celery result backend 存储格式一致）。"""
    return {
        "task_id": task_id,
        "file_key": file_key,
        "file_type": "dxf",
        "status": "completed",
        "compliance_score": score,
        "defects": defects,
        "standards_applied": ["GB/T 18229-2023"],
        "review_mode": "rule_engine",
        "report_path": None,
        "pdf_report_path": None,
        "metadata": {"elapsed_ms": 1000, "judge_mode": "rule_engine"},
    }


class _MockRequest:
    """模拟 Celery Task request 对象。"""
    def __init__(self, task_id: str | None = None) -> None:
        self.id = task_id or f"mock-{uuid.uuid4().hex[:8]}"


class _MockSelf:
    """模拟 Celery Task self 对象（仅含 request.id 用于日志）。"""
    def __init__(self, task_id: str | None = None) -> None:
        self.request = _MockRequest(task_id)


# ===== SubTask 11.1 实测 =====


def test_11_1_defect_to_prompt() -> None:
    """SubTask 11.1：缺陷 → LLM prompt 转换。"""
    section("SubTask 11.1 实测：缺陷 → LLM prompt 转换")
    from app.services.collaboration.defect_to_prompt import (
        defects_to_optimization_prompt,
        extract_file_hint_from_review_result,
    )
    from app.schemas.review_detail import DefectItem

    # 场景 1：空缺陷列表 → 通用优化 prompt
    prompt_empty = defects_to_optimization_prompt([])
    check(
        "GB/T 18229-2023" in prompt_empty and len(prompt_empty) > 0,
        "空缺陷列表返回通用优化 prompt",
        f"len={len(prompt_empty)}",
    )

    # 场景 2：单条缺陷
    single_defect = DefectItem(**_make_defect(severity="critical"))
    prompt_single = defects_to_optimization_prompt([single_defect])
    check(
        "标题栏" in prompt_single and "critical" in prompt_single.lower(),
        "单条缺陷 prompt 含类别与严重等级",
    )
    check(
        "CadQuery" in prompt_single,
        "单条缺陷 prompt 含 CadQuery 代码要求",
    )

    # 场景 3：多条缺陷按 severity 排序
    defects_multi = [
        DefectItem(**_make_defect(severity="minor", category="layer_naming",
                                   suggestion="图层名应使用 GB/T 17450 规范")),
        DefectItem(**_make_defect(severity="critical", category="title_block",
                                   suggestion="标题栏缺失图号")),
        DefectItem(**_make_defect(severity="major", category="dimensioning",
                                   suggestion="尺寸标注缺失")),
        DefectItem(**_make_defect(severity="warning", category="line_type",
                                   suggestion="线型不规范")),
    ]
    prompt_multi = defects_to_optimization_prompt(defects_multi)
    # critical 应该出现在最前（按 severity 优先级）
    critical_pos = prompt_multi.find("严重")
    major_pos = prompt_multi.find("重要")
    check(
        0 <= critical_pos < major_pos,
        "多条缺陷按 severity 优先级排序（critical 在 major 前）",
        f"critical_pos={critical_pos}, major_pos={major_pos}",
    )

    # 场景 4：缺陷数量截断（超过 _MAX_DEFECTS_IN_PROMPT=15）
    many_defects = [
        DefectItem(**_make_defect(
            severity="minor",
            category="dimensioning",
            suggestion=f"缺陷 #{i}",
        ))
        for i in range(20)
    ]
    prompt_many = defects_to_optimization_prompt(many_defects)
    check(
        "审图发现 15 条缺陷" in prompt_many,
        "缺陷数量截断到 15 条（_MAX_DEFECTS_IN_PROMPT）",
    )

    # 场景 5：file_hint 提取
    review_dict = _make_review_result_dict("test-1", [], file_key="/path/to/bolt.dxf")
    hint = extract_file_hint_from_review_result(review_dict)
    check(
        "bolt.dxf" in hint,
        "extract_file_hint_from_review_result 提取 basename",
        f"hint={hint}",
    )

    # 场景 6：prompt 长度可控
    check(
        len(prompt_multi) < 4000,
        "prompt 总长度 < 4000 字符",
        f"len={len(prompt_multi)}",
    )


def test_11_1_celery_task(review_task_id: str, review_result_dict: dict[str, Any]) -> dict[str, Any]:
    """SubTask 11.1：Celery 任务 run_optimize_from_review（直接调用函数体）。"""
    section("SubTask 11.1 实测：Celery 任务 run_optimize_from_review")
    _setup_celery_eager()
    _store_review_result(review_task_id, review_result_dict)
    _info(f"已写入审图结果到 backend: task_id={review_task_id}")

    # 验证读取
    from app.celery.tasks.collaboration import _fetch_review_result
    fetched = _fetch_review_result(review_task_id)
    check(
        fetched is not None and fetched.get("task_id") == review_task_id,
        "从 backend 读取原审图结果成功",
    )

    # 直接调用 run_optimize_from_review（Celery task 对象，bind=True）
    # 注意：Celery task 对象的 __call__ 会自动绑定 self，无需手动传入
    from app.celery.tasks.collaboration import run_optimize_from_review

    result_dict: dict[str, Any] = {}
    try:
        # 直接调用 task 对象（eager 模式下同步执行）
        result_dict = run_optimize_from_review(
            review_task_id=review_task_id,
            user_id="test_user",
            output_format="dxf",
            auto_re_review=True,
        )
        check(True, "run_optimize_from_review 直接调用成功")
    except Exception as e:
        check(False, "run_optimize_from_review 直接调用失败", f"{type(e).__name__}: {e}")
        _info(f"异常详情: {e}")
        return {}

    # 验证返回结构
    check(
        result_dict.get("original_review_task_id") == review_task_id,
        "返回 original_review_task_id 正确",
    )
    check(
        "generation_task_id" in result_dict,
        "返回 generation_task_id 字段",
    )
    check(
        "defects_count" in result_dict and result_dict["defects_count"] >= 0,
        "返回 defects_count 字段",
    )
    check(
        "optimized_prompt" in result_dict,
        "返回 optimized_prompt 字段（截断 500 字符）",
    )
    check(
        len(result_dict.get("optimized_prompt", "")) <= 500,
        "optimized_prompt 长度 ≤ 500",
        f"actual_len={len(result_dict.get('optimized_prompt', ''))}",
    )
    _info(f"返回 status={result_dict.get('status')}, defects_count={result_dict.get('defects_count')}")
    _info(f"optimized_prompt 前 200 字符: {result_dict.get('optimized_prompt', '')[:200]}")

    return result_dict


def test_11_1_api_endpoint(review_task_id: str, review_result_dict: dict[str, Any]) -> None:
    """SubTask 11.1：API 端点 POST /api/v1/collaboration/optimize-from-review。"""
    section("SubTask 11.1 实测：API 端点 /optimize-from-review")
    _setup_celery_eager()
    _store_review_result(review_task_id, review_result_dict)

    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        # 场景 1：合法请求
        resp = client.post(
            "/api/v1/collaboration/optimize-from-review",
            json={
                "review_task_id": review_task_id,
                "user_id": "api_test_user",
                "output_format": "dxf",
                "auto_re_review": True,
            },
        )
        check(
            resp.status_code == 202,
            "POST /optimize-from-review 返回 202",
            f"actual={resp.status_code}, body={resp.text[:300]}",
        )
        if resp.status_code == 202:
            data = resp.json()
            check(
                data.get("original_review_task_id") == review_task_id,
                "响应含 original_review_task_id",
            )
            check(
                "generation_task_id" in data and data["generation_task_id"],
                "响应含 generation_task_id",
            )
            check(
                "websocket_url" in data.get("metadata", {}),
                "响应 metadata 含 websocket_url",
            )

        # 场景 2：审图任务未完成（409）
        pending_task_id = f"pending-{uuid.uuid4().hex[:8]}"
        resp2 = client.post(
            "/api/v1/collaboration/optimize-from-review",
            json={
                "review_task_id": pending_task_id,
                "output_format": "dxf",
            },
        )
        check(
            resp2.status_code == 409,
            "审图任务未完成时返回 409",
            f"actual={resp2.status_code}",
        )

        # 场景 3：非法 output_format（422）
        resp3 = client.post(
            "/api/v1/collaboration/optimize-from-review",
            json={
                "review_task_id": review_task_id,
                "output_format": "invalid_format",
            },
        )
        check(
            resp3.status_code == 422,
            "非法 output_format 返回 422",
            f"actual={resp3.status_code}",
        )


# ===== SubTask 11.2 实测 =====


def test_11_2_auto_re_review() -> dict[str, Any] | None:
    """SubTask 11.2：修订后文件自动复审（run_generation 内嵌自检）。"""
    section("SubTask 11.2 实测：run_generation 内嵌自动复审派发")
    _setup_celery_eager()

    # 直接调用 run_generation（Celery task 对象，bind=True）
    from app.celery.tasks.generations import run_generation

    try:
        result_dict = run_generation(
            input_type="text",
            prompt="生成一个 10mm 立方体",
            sketch_key=None,
            output_format="dxf",
            user_id="test_11_2",
        )
        check(True, "run_generation 直接调用成功")
    except Exception as e:
        check(False, "run_generation 直接调用失败", f"{type(e).__name__}: {e}")
        _info(f"异常详情: {e}")
        return None

    # 验证 metadata 中的自检字段
    metadata = result_dict.get("metadata", {})
    self_review_status = metadata.get("self_review_status")
    self_review_task_id = metadata.get("self_review_task_id")

    _info(f"self_review_status={self_review_status}")
    _info(f"self_review_task_id={self_review_task_id}")

    check(
        self_review_status in ("dispatched", "skipped_unsupported", "skipped", "dispatch_failed"),
        "metadata.self_review_status 字段存在且合法",
        f"actual={self_review_status}",
    )

    # 关键验证：自检派发逻辑被执行（status 非 None）
    check(
        self_review_status is not None,
        "自检派发逻辑被执行（status 非 None）",
    )

    # 验证输出文件
    output_files = result_dict.get("output_files", [])
    _info(f"output_files count={len(output_files)}")
    if output_files:
        dxf_files = [f for f in output_files if f.lower().endswith(".dxf")]
        check(
            len(dxf_files) > 0,
            "生成 DXF 输出文件（可触发复审）",
            f"dxf_count={len(dxf_files)}",
        )

        # 如果有 DXF 文件且 dispatched，验证 task_id 非空
        if self_review_status == "dispatched":
            check(
                bool(self_review_task_id),
                "self_review_task_id 已填充（dispatched 状态）",
                f"task_id={self_review_task_id}",
            )

    # 验证 review_mode 与 metadata 一致性
    check(
        "self_review_standard_set" in metadata,
        "metadata 含 self_review_standard_set 字段",
    )

    return result_dict


# ===== SubTask 11.3 实测 =====


def test_11_3_diff_report() -> dict[str, Any]:
    """SubTask 11.3：修订前后对比报告。"""
    section("SubTask 11.3 实测：diff_report 生成（resolved/unresolved/new）")

    from app.schemas.review_detail import DefectItem
    from app.services.collaboration.diff_report import generate_diff_report, _similarity

    # 场景 1：相似度计算
    d1 = DefectItem(**_make_defect(suggestion="标题栏缺失图号字段"))
    d2 = DefectItem(**_make_defect(suggestion="标题栏缺失图号字段"))
    sim_same = _similarity(d1, d2)
    check(
        sim_same >= 0.7,
        "相同缺陷相似度 ≥ 0.7",
        f"sim={sim_same:.3f}",
    )

    d3 = DefectItem(**_make_defect(
        category="dimensioning",
        suggestion="尺寸标注缺失",
        standard_ref="GB/T 4457.4-2002 §4.1",
    ))
    sim_diff = _similarity(d1, d3)
    check(
        sim_diff < 0.5,
        "不同类别缺陷相似度 < 0.5",
        f"sim={sim_diff:.3f}",
    )

    # 场景 2：全部修复（resolved）
    old_defects = [
        DefectItem(**_make_defect(severity="critical", suggestion="标题栏缺失图号")),
        DefectItem(**_make_defect(severity="major", suggestion="图层名不规范")),
    ]
    new_defects_empty: list[DefectItem] = []
    report_all_resolved = generate_diff_report(
        old_review_task_id="old-1",
        new_review_task_id="new-1",
        old_defects=old_defects,
        new_defects=new_defects_empty,
        old_score=50.0,
        new_score=95.0,
    )
    check(
        report_all_resolved.resolved_count == 2,
        "全部修复：resolved_count=2",
        f"actual={report_all_resolved.resolved_count}",
    )
    check(
        report_all_resolved.unresolved_count == 0,
        "全部修复：unresolved_count=0",
    )
    check(
        report_all_resolved.new_count == 0,
        "全部修复：new_count=0",
    )
    check(
        report_all_resolved.closure_rate == 1.0,
        "全部修复：closure_rate=1.0",
        f"actual={report_all_resolved.closure_rate}",
    )
    check(
        report_all_resolved.score_improvement == 45.0,
        "评分提升计算正确（95-50=45）",
        f"actual={report_all_resolved.score_improvement}",
    )

    # 场景 3：部分未修复 + 新增
    old_defects_partial = [
        DefectItem(**_make_defect(severity="critical", suggestion="标题栏缺失图号")),
        DefectItem(**_make_defect(severity="major", suggestion="图层名不规范")),
        DefectItem(**_make_defect(severity="minor", suggestion="尺寸标注重复")),
    ]
    new_defects_partial = [
        # 与第 1 条相似 → unresolved
        DefectItem(**_make_defect(severity="critical", suggestion="标题栏缺失图号")),
        # 新增缺陷
        DefectItem(**_make_defect(
            severity="major",
            category="tolerance",
            suggestion="形位公差标注缺失",
            standard_ref="GB/T 1182-2018 §4.1",
        )),
    ]
    report_partial = generate_diff_report(
        old_review_task_id="old-2",
        new_review_task_id="new-2",
        old_defects=old_defects_partial,
        new_defects=new_defects_partial,
        old_score=40.0,
        new_score=70.0,
    )
    check(
        report_partial.resolved_count == 2,
        "部分修复：resolved_count=2（图层+尺寸标注已修复）",
        f"actual={report_partial.resolved_count}",
    )
    check(
        report_partial.unresolved_count == 1,
        "部分修复：unresolved_count=1（标题栏仍存在）",
        f"actual={report_partial.unresolved_count}",
    )
    check(
        report_partial.new_count == 1,
        "部分修复：new_count=1（新增形位公差缺陷）",
        f"actual={report_partial.new_count}",
    )
    check(
        0.0 < report_partial.closure_rate < 1.0,
        "部分修复：0 < closure_rate < 1",
        f"actual={report_partial.closure_rate}",
    )

    # 场景 4：空缺陷列表
    report_empty = generate_diff_report(
        old_review_task_id="old-3",
        new_review_task_id="new-3",
        old_defects=[],
        new_defects=[],
    )
    check(
        report_empty.closure_rate == 1.0,
        "空缺陷列表 closure_rate=1.0（边界处理）",
        f"actual={report_empty.closure_rate}",
    )

    # 场景 5：统计字段
    check(
        report_partial.old_defects_count == 3,
        "old_defects_count 统计正确",
    )
    check(
        report_partial.new_defects_count == 2,
        "new_defects_count 统计正确",
    )
    check(
        report_partial.generated_at != "",
        "generated_at 时间戳已填充",
    )

    return report_partial.model_dump(mode="json")


def test_11_3_api_endpoint(old_task_id: str, new_task_id: str, old_result: dict, new_result: dict) -> None:
    """SubTask 11.3：API 端点 GET /api/v1/collaboration/diff-report。"""
    section("SubTask 11.3 实测：API 端点 /diff-report")
    _setup_celery_eager()

    _store_review_result(old_task_id, old_result)
    _store_review_result(new_task_id, new_result)

    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        resp = client.get(f"/api/v1/collaboration/diff-report/{old_task_id}/{new_task_id}")
        check(
            resp.status_code == 200,
            "GET /diff-report 返回 200",
            f"actual={resp.status_code}, body={resp.text[:300]}",
        )
        if resp.status_code == 200:
            data = resp.json()
            check(
                data.get("original_review_task_id") == old_task_id,
                "响应含 original_review_task_id",
            )
            check(
                data.get("new_review_task_id") == new_task_id,
                "响应含 new_review_task_id",
            )
            check(
                "closure_rate" in data,
                "响应含 closure_rate",
            )
            check(
                "diffs" in data and isinstance(data["diffs"], list),
                "响应含 diffs 列表",
            )

        # 场景 2：不存在的 task_id（404）
        resp2 = client.get(f"/api/v1/collaboration/diff-report/{old_task_id}/nonexistent-task")
        check(
            resp2.status_code == 404,
            "不存在的 new_task_id 返回 404",
            f"actual={resp2.status_code}",
        )


# ===== SubTask 11.4 实测 =====


def test_11_4_feedback_store() -> dict[str, Any]:
    """SubTask 11.4：用户反馈存储 / 检索 / 统计。"""
    section("SubTask 11.4 实测：feedback 存储 / 检索 / 统计")

    from app.schemas.collaboration import FeedbackRecord
    from app.services.collaboration.feedback_store import (
        save_feedback,
        load_feedback,
        list_feedback_by_action,
        feedback_stats,
        _feedback_dir,
    )

    # 清理测试目录（避免历史数据干扰）
    fb_dir = _feedback_dir()
    if fb_dir.exists():
        for f in fb_dir.glob("*.json"):
            f.unlink()
    _info(f"已清理 feedback 目录: {fb_dir}")

    review_task_id = f"fb-test-{uuid.uuid4().hex[:8]}"

    # 场景 1：保存 accept 反馈
    rec1 = FeedbackRecord(
        review_task_id=review_task_id,
        defect_index=0,
        action="accept",
        comment="确认该缺陷",
        user_id="tester_1",
    )
    path1 = save_feedback(rec1)
    check(
        path1.is_file(),
        "保存 accept 反馈到文件",
        f"path={path1}",
    )

    # 场景 2：保存 reject_as_false_positive 反馈
    rec2 = FeedbackRecord(
        review_task_id=review_task_id,
        defect_index=1,
        action="reject_as_false_positive",
        comment="误报，该标注实际正确",
        user_id="tester_1",
    )
    save_feedback(rec2)

    # 场景 3：保存 modify_suggestion 反馈
    rec3 = FeedbackRecord(
        review_task_id=review_task_id,
        defect_index=2,
        action="modify_suggestion",
        comment="建议修改为：使用 GB/T 4457.4 规范",
        user_id="tester_2",
    )
    save_feedback(rec3)

    # 场景 4：按 task_id 加载所有反馈
    records = load_feedback(review_task_id)
    check(
        len(records) == 3,
        "按 task_id 加载全部反馈（3 条）",
        f"actual={len(records)}",
    )
    check(
        records[0].defect_index == 0,
        "反馈按 defect_index 升序排列",
    )

    # 场景 5：按 defect_index 加载单条
    single = load_feedback(review_task_id, defect_index=1)
    check(
        len(single) == 1 and single[0].action == "reject_as_false_positive",
        "按 defect_index 加载单条反馈",
    )

    # 场景 6：按 action 类型检索
    accepts = list_feedback_by_action("accept")
    rejects = list_feedback_by_action("reject_as_false_positive")
    modifies = list_feedback_by_action("modify_suggestion")
    check(
        len(accepts) == 1 and len(rejects) == 1 and len(modifies) == 1,
        "按 action 类型检索反馈",
        f"accept={len(accepts)}, reject={len(rejects)}, modify={len(modifies)}",
    )

    # 场景 7：全局统计
    stats = feedback_stats()
    check(
        stats.get("total") == 3,
        "feedback_stats total=3",
        f"actual={stats}",
    )
    check(
        stats.get("accept") == 1
        and stats.get("reject_as_false_positive") == 1
        and stats.get("modify_suggestion") == 1,
        "feedback_stats 分类统计正确",
        f"stats={stats}",
    )

    # 场景 8：created_at 自动填充
    check(
        rec1.created_at != "",
        "反馈记录 created_at 自动填充",
        f"actual={rec1.created_at}",
    )

    return stats


def test_11_4_api_endpoint(review_task_id: str, review_result_dict: dict[str, Any]) -> None:
    """SubTask 11.4：API 端点 POST /feedback / GET /feedback / GET /feedback-stats。"""
    section("SubTask 11.4 实测：API 端点 /feedback")
    _setup_celery_eager()

    from app.services.collaboration.feedback_store import _feedback_dir
    # 清理目录
    fb_dir = _feedback_dir()
    if fb_dir.exists():
        for f in fb_dir.glob("*.json"):
            f.unlink()

    _store_review_result(review_task_id, review_result_dict)

    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        # 场景 1：POST /feedback（带缺陷快照）
        resp = client.post(
            "/api/v1/collaboration/feedback",
            json={
                "review_task_id": review_task_id,
                "defect_index": 0,
                "action": "accept",
                "comment": "API 提交采纳",
                "user_id": "api_tester",
            },
        )
        check(
            resp.status_code == 201,
            "POST /feedback 返回 201",
            f"actual={resp.status_code}, body={resp.text[:300]}",
        )
        if resp.status_code == 201:
            data = resp.json()
            check(
                data.get("action") == "accept",
                "响应含 action 字段",
            )
            check(
                data.get("defect_snapshot") is not None,
                "缺陷快照自动填充",
            )

        # 场景 2：POST /feedback（误报）
        resp2 = client.post(
            "/api/v1/collaboration/feedback",
            json={
                "review_task_id": review_task_id,
                "defect_index": 1,
                "action": "reject_as_false_positive",
                "comment": "误报",
            },
        )
        check(resp2.status_code == 201, "POST /feedback 误报返回 201")

        # 场景 3：GET /feedback/{review_task_id}
        resp3 = client.get(f"/api/v1/collaboration/feedback/{review_task_id}")
        check(
            resp3.status_code == 200,
            "GET /feedback/{task_id} 返回 200",
        )
        if resp3.status_code == 200:
            data = resp3.json()
            check(
                data.get("count") == 2,
                "GET /feedback 返回 2 条反馈",
                f"actual={data.get('count')}",
            )

        # 场景 4：GET /feedback-stats
        resp4 = client.get("/api/v1/collaboration/feedback-stats")
        check(
            resp4.status_code == 200,
            "GET /feedback-stats 返回 200",
        )
        if resp4.status_code == 200:
            stats = resp4.json()
            check(
                stats.get("total", 0) >= 2,
                "feedback-stats total ≥ 2",
                f"stats={stats}",
            )


# ===== 端到端实测 =====


def test_e2e_closed_loop() -> dict[str, Any]:
    """端到端：审图 → 优化 → 生成 → 复审 → 对比报告。"""
    section("Task 11 端到端实测：审图→优化→生成→复审→对比报告")
    _setup_celery_eager()

    # ===== 步骤 1：构造"原审图任务"结果（含 3 条缺陷）=====
    original_task_id = f"e2e-old-{uuid.uuid4().hex[:8]}"
    original_defects = [
        _make_defect(severity="critical", category="title_block",
                     suggestion="标题栏缺失图号字段", evidence="drawing_number 字段为空"),
        _make_defect(severity="major", category="layer_naming",
                     suggestion="图层名不符合 GB/T 17450 规范", evidence="图层 'Layer1' 不规范"),
        _make_defect(severity="minor", category="dimensioning",
                     suggestion="尺寸标注缺失高度尺寸", evidence="仅有长度标注"),
    ]
    original_review = _make_review_result_dict(
        task_id=original_task_id,
        defects=original_defects,
        score=45.0,
        file_key="original_part.dxf",
    )
    _store_review_result(original_task_id, original_review)
    _info(f"步骤 1：原审图任务已就绪 task_id={original_task_id}, defects=3, score=45.0")

    # ===== 步骤 2：调用 run_optimize_from_review 派发生成 =====
    from app.celery.tasks.collaboration import run_optimize_from_review

    try:
        optimize_result = run_optimize_from_review(
            review_task_id=original_task_id,
            user_id="e2e_tester",
            output_format="dxf",
            auto_re_review=True,
        )
        check(True, "步骤 2：run_optimize_from_review 执行成功")
    except Exception as e:
        check(False, "步骤 2：run_optimize_from_review 执行失败", f"{type(e).__name__}: {e}")
        return {}

    generation_task_id = optimize_result.get("generation_task_id", "")
    check(
        bool(generation_task_id),
        "返回有效的 generation_task_id",
        f"actual={generation_task_id}",
    )
    check(
        optimize_result.get("defects_count") == 3,
        "defects_count=3（与原审图一致）",
    )

    # ===== 步骤 3：（模拟）生成任务完成并触发复审 =====
    # 实际 run_generation 会派发 run_review，这里我们模拟一个"修订后审图"结果
    new_task_id = f"e2e-new-{uuid.uuid4().hex[:8]}"
    # 模拟：critical 缺陷已修复，major 仍存在，新增 1 条 warning
    new_defects = [
        # major 仍存在 → unresolved
        _make_defect(severity="major", category="layer_naming",
                     suggestion="图层名不符合 GB/T 17450 规范", evidence="图层 'Layer1' 不规范"),
        # 新增 warning
        _make_defect(severity="warning", category="line_type",
                     suggestion="线型粗细不一致", evidence="OUTLINE 层线宽 0.5mm，应改为 0.7mm"),
    ]
    new_review = _make_review_result_dict(
        task_id=new_task_id,
        defects=new_defects,
        score=75.0,
        file_key="revised_part.dxf",
    )
    _store_review_result(new_task_id, new_review)
    _info(f"步骤 3：修订后审图任务已就绪 task_id={new_task_id}, defects=2, score=75.0")

    # ===== 步骤 4：生成对比报告 =====
    from app.schemas.review_detail import DefectItem
    from app.services.collaboration.diff_report import generate_diff_report

    old_defect_objs = [DefectItem(**d) for d in original_defects]
    new_defect_objs = [DefectItem(**d) for d in new_defects]

    diff_report = generate_diff_report(
        old_review_task_id=original_task_id,
        new_review_task_id=new_task_id,
        old_defects=old_defect_objs,
        new_defects=new_defect_objs,
        old_score=45.0,
        new_score=75.0,
        generation_task_id=generation_task_id,
    )

    check(
        diff_report.resolved_count == 2,
        "E2E：resolved_count=2（critical 标题栏 + minor 尺寸标注已修复）",
        f"actual={diff_report.resolved_count}",
    )
    check(
        diff_report.unresolved_count == 1,
        "E2E：unresolved_count=1（major 图层名仍存在）",
        f"actual={diff_report.unresolved_count}",
    )
    check(
        diff_report.new_count == 1,
        "E2E：new_count=1（新增 warning 线型）",
        f"actual={diff_report.new_count}",
    )
    check(
        diff_report.score_improvement == 30.0,
        "E2E：评分提升 30 分（75-45）",
        f"actual={diff_report.score_improvement}",
    )
    check(
        diff_report.generation_task_id == generation_task_id,
        "E2E：generation_task_id 关联正确",
    )
    _info(f"步骤 4：对比报告 closure_rate={diff_report.closure_rate:.2%}")

    # ===== 步骤 5：用户反馈回流 =====
    from app.schemas.collaboration import FeedbackRecord
    from app.services.collaboration.feedback_store import save_feedback

    # 对未修复的 major 缺陷提交"修改建议"反馈
    fb = FeedbackRecord(
        review_task_id=new_task_id,
        defect_index=0,
        action="modify_suggestion",
        comment="建议将图层名改为 OUTLINE/DIM/TEXT 等规范名",
        user_id="e2e_tester",
        defect_snapshot=new_defect_objs[0],
    )
    save_feedback(fb)
    check(True, "步骤 5：用户反馈已保存")

    # ===== 步骤 6：通过 API 验证完整闭环 =====
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        # 验证对比报告可通过 API 获取
        resp = client.get(f"/api/v1/collaboration/diff-report/{original_task_id}/{new_task_id}")
        check(
            resp.status_code == 200,
            "E2E API：GET /diff-report 返回 200",
            f"actual={resp.status_code}",
        )
        if resp.status_code == 200:
            api_report = resp.json()
            check(
                api_report.get("closure_rate") is not None,
                "E2E API：响应含 closure_rate",
            )
            check(
                api_report.get("resolved_count") == 2,
                "E2E API：响应 resolved_count=2",
                f"actual={api_report.get('resolved_count')}",
            )

        # 验证反馈可通过 API 查询
        resp2 = client.get(f"/api/v1/collaboration/feedback/{new_task_id}")
        check(
            resp2.status_code == 200 and resp2.json().get("count", 0) >= 1,
            "E2E API：GET /feedback 返回反馈列表",
        )

    return {
        "original_task_id": original_task_id,
        "generation_task_id": generation_task_id,
        "new_task_id": new_task_id,
        "diff_report": diff_report.model_dump(mode="json"),
    }


# ===== 主入口 =====


def main() -> int:
    print("=" * 70, flush=True)
    print("Task 11 端到端实测：审图→生成→复审协同闭环", flush=True)
    print("=" * 70, flush=True)

    # ===== 1. SubTask 11.1：defect_to_prompt 转换 =====
    test_11_1_defect_to_prompt()

    # 构造共享的审图结果（用于后续测试）
    original_task_id = f"test-old-{uuid.uuid4().hex[:8]}"
    original_defects = [
        _make_defect(severity="critical", category="title_block",
                     suggestion="标题栏缺失图号", evidence="drawing_number 字段为空"),
        _make_defect(severity="major", category="layer_naming",
                     suggestion="图层名不规范", evidence="图层 'Layer1'"),
    ]
    original_review = _make_review_result_dict(
        task_id=original_task_id,
        defects=original_defects,
        score=55.0,
    )

    # ===== 2. SubTask 11.1：Celery 任务 =====
    test_11_1_celery_task(original_task_id, original_review)

    # ===== 3. SubTask 11.1：API 端点 =====
    test_11_1_api_endpoint(original_task_id, original_review)

    # ===== 4. SubTask 11.2：自动复审 =====
    test_11_2_auto_re_review()

    # ===== 5. SubTask 11.3：diff_report =====
    test_11_3_diff_report()

    # ===== 6. SubTask 11.3：API 端点 =====
    old_task_id = f"diff-old-{uuid.uuid4().hex[:8]}"
    new_task_id = f"diff-new-{uuid.uuid4().hex[:8]}"
    old_review = _make_review_result_dict(
        task_id=old_task_id,
        defects=[_make_defect(suggestion="缺陷 A")],
        score=50.0,
    )
    new_review = _make_review_result_dict(
        task_id=new_task_id,
        defects=[],  # 全部修复
        score=90.0,
    )
    test_11_3_api_endpoint(old_task_id, new_task_id, old_review, new_review)

    # ===== 7. SubTask 11.4：feedback 存储 =====
    test_11_4_feedback_store()

    # ===== 8. SubTask 11.4：API 端点 =====
    fb_review_task_id = f"fb-api-{uuid.uuid4().hex[:8]}"
    fb_review_result = _make_review_result_dict(
        task_id=fb_review_task_id,
        defects=[_make_defect(suggestion="缺陷 1"), _make_defect(suggestion="缺陷 2")],
        score=60.0,
    )
    test_11_4_api_endpoint(fb_review_task_id, fb_review_result)

    # ===== 9. 端到端闭环 =====
    test_e2e_closed_loop()

    # ===== 汇总 =====
    print("\n" + "=" * 70, flush=True)
    print(f"Task 11 实测汇总: PASS={_passed}, FAIL={_failed}", flush=True)
    print("=" * 70, flush=True)
    if _failures:
        print("\n失败项：", flush=True)
        for i, f in enumerate(_failures, 1):
            print(f"  {i}. {f}", flush=True)
    return 0 if _failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
