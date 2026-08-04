"""LLM 推理模块（SubTask 4.4 主路径，Task 4 统一 provider 访问）。

管线：
1) retrieve_relevant_clauses()：从语义模型构造查询 → HybridClauseRetriever（Task 3）
2) llm_judge_defects()：构造 prompt（结构化 JSON + 规范条文）
   → ``get_llm_provider().chat()`` → DefectItem 列表

降级：LLM 不可用时调用 rule_engine_judge()。

注意：业务路径统一走 ``get_llm_provider()``，不再直接访问 Ollama HTTP API。
"""

from __future__ import annotations

import json
from typing import Any

from app.logging import get_logger
from app.schemas.kb import ClauseSearchResult
from app.schemas.review_detail import DefectItem, SemanticModel
from app.services.review.rule_engine import rule_engine_judge

log = get_logger(__name__)


def is_llm_available() -> bool:
    """检查 LLM 是否可用。

    自 SubTask 3.5 起转调 ``get_llm_provider().is_available()``，
    由 Provider 抽象屏蔽 ollama / openai / anthropic 差异。
    """
    try:
        from app.services.ai import get_llm_provider

        return get_llm_provider().is_available()
    except Exception as e:  # noqa: BLE001
        log.warning("review.llm.provider_unavailable", error=str(e))
        return False


def retrieve_relevant_clauses(
    semantic_model: SemanticModel,
    top_k: int = 5,
) -> list[ClauseSearchResult]:
    """根据语义模型构造查询，调用 HybridClauseRetriever 检索相关条款。

    构造查询关键词：图层名 + 标注类型 + 标题栏字段 + 几何统计。

    Args:
        semantic_model: 三层语义模型
        top_k: 每条查询返回的条数

    Returns:
        去重后的条款列表（按 score 降序）
    """
    queries = _build_queries(semantic_model)
    if not queries:
        log.warning("review.llm.retrieve.no_queries")
        return []

    try:
        from app.services.kb.retriever import HybridClauseRetriever

        retriever = HybridClauseRetriever()
    except Exception as e:  # noqa: BLE001
        log.warning("review.llm.retriever_unavailable", error=str(e))
        return []

    seen_ids: set[str] = set()
    all_results: list[ClauseSearchResult] = []
    for q in queries:
        try:
            results = retriever.retrieve(query=q, top_k=top_k)
        except Exception as e:  # noqa: BLE001
            log.warning("review.llm.retrieve.failed", query=q[:40], error=str(e))
            continue
        for r in results:
            key = f"{r.standard}|{r.clause_id}"
            if key in seen_ids:
                continue
            seen_ids.add(key)
            all_results.append(r)

    # 按 score 降序
    all_results.sort(key=lambda r: r.score, reverse=True)
    log.info(
        "review.llm.retrieve.done",
        queries=len(queries),
        results=len(all_results),
    )
    return all_results


def _build_queries(model: SemanticModel) -> list[str]:
    """从语义模型构造多条检索查询。"""
    queries: list[str] = []

    # 1) 标题栏相关
    sem = model.semantic
    if sem.has_title_block:
        missing = [
            f for f in ("drawing_number", "scale", "material", "date")
            if not sem.title_block_fields.get(f)
        ]
        if missing:
            queries.append("工程图标题栏必填字段 图号 比例 材料 日期")
    else:
        queries.append("工程图标题栏内容要求")

    # 2) 图层命名
    if sem.layer_names:
        queries.append("技术制图 图层命名规范 GB/T 17450")

    # 3) 尺寸标注
    if sem.dimension_count == 0:
        queries.append("机械制图 尺寸标注完整性要求")
    else:
        queries.append("尺寸标注类型 线性 对齐 半径 直径")

    # 4) 形位公差
    if not sem.has_tolerance:
        queries.append("几何公差 形位公差标注 GB/T 1182")

    # 5) 表面粗糙度
    if not sem.has_surface_roughness:
        queries.append("表面粗糙度符号标注 GB/T 131")

    return queries[:8]  # 限制查询数避免过多检索


def llm_judge_defects(
    semantic_model: SemanticModel,
    clauses: list[ClauseSearchResult],
) -> tuple[list[DefectItem], str]:
    """构造 prompt，调用 LLM 输出缺陷列表。

    自 SubTask 3.5 起走 ``get_llm_provider().chat()``，
    由 Provider 抽象屏蔽 ollama / openai / anthropic 差异。

    Args:
        semantic_model: 三层语义模型
        clauses: 检索到的相关条款

    Returns:
        (defects, llm_model_name)
        LLM 不可用时返回 ([], "")，由调用方降级到 rule_engine。
    """
    if not is_llm_available():
        log.warning("review.llm.judge.skipped", reason="llm_unavailable")
        return [], ""

    prompt = _build_judge_prompt(semantic_model, clauses)
    try:
        from app.services.ai import ChatMessage, get_llm_provider

        provider = get_llm_provider()
        resp = provider.chat(
            [ChatMessage(role="user", content=prompt)],
            temperature=0.2,
            max_tokens=2048,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("review.llm.judge.failed", error=str(e))
        return [], ""

    if not resp.content:
        log.warning("review.llm.judge.empty", model=resp.model)
        return [], ""

    defects = _parse_defects_from_llm_output(resp.content)
    log.info("review.llm.judge.done", model=resp.model, defects=len(defects))
    return defects, resp.model


def _build_judge_prompt(
    model: SemanticModel, clauses: list[ClauseSearchResult]
) -> str:
    """构造 LLM 推理 prompt。"""
    # 语义模型摘要（避免过长）
    sem = model.semantic
    summary = {
        "geometry_stats": model.stats,
        "dimension_count": sem.dimension_count,
        "dimension_types": sem.dimension_types,
        "has_title_block": sem.has_title_block,
        "title_block_fields": sem.title_block_fields,
        "has_tolerance": sem.has_tolerance,
        "has_surface_roughness": sem.has_surface_roughness,
        "layer_names": sem.layer_names,
        "vlm_ocr_extras": sem.vlm_ocr_extras,
    }

    # 规范条文（最多 5 条）
    clause_texts = []
    for c in clauses[:5]:
        clause_texts.append(
            f"[{c.standard} §{c.clause_id}] {c.title}\n原文：{c.original_text[:300]}"
        )

    prompt = (
        "你是工程图审图专家，依据中国国家标准（GB/T）审查工程图的合规性。\n\n"
        f"【图纸语义模型】\n{json.dumps(summary, ensure_ascii=False, indent=2)}\n\n"
        f"【相关规范条文】\n" + "\n\n".join(clause_texts) + "\n\n"
        "【任务】请基于上述信息，找出图纸中存在的合规性缺陷。\n"
        "仅输出 JSON 数组（不要包含任何其他文字、不要使用 markdown 代码块）：\n"
        "[\n"
        "  {\n"
        '    "category": "title_block|layer_naming|dimensioning|tolerance|surface_roughness|line_type|view_layout|text_annotation|other",\n'
        '    "severity": "critical|major|minor|warning",\n'
        '    "coordinate": {"x": 0.0, "y": 0.0} 或 null,\n'
        '    "standard_ref": "GB/T xxxx-yyyy §x.x",\n'
        '    "standard_clause_id": "x.x",\n'
        '    "suggestion": "具体修改建议",\n'
        '    "evidence": "缺陷证据描述"\n'
        "  }\n"
        "]\n"
        "要求：\n"
        "1. 每条缺陷必须引用具体 GB/T 条款\n"
        "2. severity 严格分级：critical=致命（缺失标题栏/尺寸）/major=严重（必填字段空）/minor=一般/警告\n"
        "3. 仅报告真实存在的缺陷，不要虚构\n"
        "4. 若图纸完全合规，返回空数组 []"
    )
    return prompt


def _parse_defects_from_llm_output(text: str) -> list[DefectItem]:
    """解析 LLM 输出为 list[DefectItem]。

    容错：尝试直接解析 JSON，失败则截取 [...] 子串。
    """
    if not text:
        return []

    obj: Any = None
    # 尝试直接解析
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        # 兜底：截取 [...] 子串
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1 and end > start:
            try:
                obj = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass

    if not isinstance(obj, list):
        log.warning("review.llm.parse_failed", text_preview=text[:300])
        return []

    defects: list[DefectItem] = []
    for item in obj:
        if not isinstance(item, dict):
            continue
        try:
            # 标准化字段
            category = str(item.get("category", "other"))
            severity = str(item.get("severity", "warning"))
            # 校验枚举值
            if category not in (
                "title_block", "layer_naming", "dimensioning", "tolerance",
                "surface_roughness", "line_type", "view_layout",
                "text_annotation", "other",
            ):
                category = "other"
            if severity not in ("critical", "major", "minor", "warning"):
                severity = "warning"

            coord = item.get("coordinate")
            if coord is not None and isinstance(coord, dict):
                coord = {
                    k: float(v)
                    for k, v in coord.items()
                    if isinstance(v, (int, float))
                }
                if not coord:
                    coord = None
            elif coord is not None and not isinstance(coord, dict):
                coord = None

            defects.append(
                DefectItem(
                    category=category,  # type: ignore[arg-type]
                    severity=severity,  # type: ignore[arg-type]
                    coordinate=coord,
                    standard_ref=str(item.get("standard_ref", "GB/T 未指定")),
                    standard_clause_id=str(item.get("standard_clause_id")) if item.get("standard_clause_id") else None,
                    suggestion=str(item.get("suggestion", "")),
                    evidence=str(item.get("evidence", "")),
                )
            )
        except Exception as e:  # noqa: BLE001
            log.warning("review.llm.parse_item_failed", item=item, error=str(e))
            continue

    return defects


def judge_with_fallback(
    semantic_model: SemanticModel,
    use_llm: bool = True,
    top_k: int = 5,
) -> tuple[list[DefectItem], str, str]:
    """主入口：先尝试 LLM，失败降级到规则引擎。

    Returns:
        (defects, mode, model_name)
        mode ∈ {"llm", "rule_engine"}
        model_name 为 LLM 模型名（rule_engine 模式为空字符串）
    """
    if use_llm and is_llm_available():
        try:
            clauses = retrieve_relevant_clauses(semantic_model, top_k=top_k)
        except Exception as e:  # noqa: BLE001
            log.warning("review.judge.retrieve_failed", error=str(e))
            clauses = []

        defects, model_name = llm_judge_defects(semantic_model, clauses)
        if defects or model_name:
            return defects, "llm", model_name
        # LLM 调用失败 → 降级

    log.info("review.judge.fallback_to_rule_engine")
    defects = rule_engine_judge(semantic_model)
    return defects, "rule_engine", ""
