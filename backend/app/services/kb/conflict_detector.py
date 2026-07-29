"""规范冲突检测器（SubTask 14.2）。

检测国标 vs 企业标准之间的条文冲突，支持四种冲突类型：
- ``contradiction``：矛盾（同一要求不同规定）
- ``duplicate``：重复（同一要求重复定义）
- ``missing``：缺失（A 集有 B 集无）
- ``enhancement``：增强（B 集严于 A 集）

检测策略：LLM 推理 + 关键词匹配双重检测。
- 优先调用 LLM（复用 ``app.services.ai.base.get_llm_provider``）做语义级判断。
- LLM 不可用时降级为纯关键词匹配（数字差异 / 关键词重合度 / 严格度词检测）。
- 关键词匹配结果与 LLM 结果取并集；同一对条款若两路都命中，标记 ``detection_method="both"``。

遵循"以实事求是为荣"原则：
- 降级路径如实标注：``ConflictReport.llm_used=False`` 时仅用关键词匹配，
  精度有限；调用方应据此调整对结果的信任度。
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.logging import get_logger
from app.schemas.kb import (
    ClauseRecord,
    ConflictItem,
    ConflictReport,
    ConflictSeverity,
    ConflictType,
)

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# 关键词匹配规则
# ---------------------------------------------------------------------------

# 严格度词：企业标准含"严格/严于/不大于/不超过/应/必须"等词，且国标含"宜/可/建议"等词，
# 视为企业标准增强（enhancement）。
_STRICTER_WORDS = ("严格", "严于", "不大于", "不超过", "不得", "必须", "应当", "严禁")
_WEAKER_WORDS = ("宜", "可", "建议", "一般", "通常", "原则上")

# 数字差异检测：抽取条文中的数字（公差值/参数），对比是否不同。
_NUMBER_PATTERN = re.compile(r"(?<![A-Za-z0-9])(\d+(?:\.\d+)?)(?![A-Za-z0-9])")

# 关键词重合度阈值：Jaccard 相似度 >= 此值视为 duplicate
_DUPLICATE_JACCARD_THRESHOLD = 0.6

# 数字差异阈值：相同位置数字差异 >= 此比例视为 contradiction
_NUMBER_DIFF_RATIO = 0.5


def _tokenize_zh(text: str) -> set[str]:
    """简易中文分词：按标点与空格切分，取长度 >= 2 的片段。

    注：英文方括号 [ ] 在字符类内不转义（Python 3.12+ raw string 中 \\
    与 [ 组合会触发 SyntaxWarning）；中文字符【】直接放入字符类。
    """
    # 用 ] 开头的字符类技巧：] 紧跟在 [ 后面是字面量，无需转义
    parts = re.split(r"[]\s，。、；：！？""''（）()【[]+", text)
    return {p for p in parts if len(p) >= 2}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _extract_numbers(text: str) -> list[float]:
    return [float(m.group(1)) for m in _NUMBER_PATTERN.finditer(text)]


def _has_strict_vs_weaker(text_a: str, text_b: str) -> bool:
    """检测 A 弱 B 强（视为企业增强）。"""
    a_strict = any(w in text_a for w in _STRICTER_WORDS)
    a_weak = any(w in text_a for w in _WEAKER_WORDS)
    b_strict = any(w in text_b for w in _STRICTER_WORDS)
    b_weak = any(w in text_b for w in _WEAKER_WORDS)
    # A 弱 B 强 → 增强
    if (a_weak and not a_strict) and (b_strict and not b_weak):
        return True
    return False


def _has_number_contradiction(text_a: str, text_b: str) -> bool:
    """检测同位置数字差异（视作矛盾）。

    简化策略：取双方数字集合，若存在共有数字位置上的不同值则视为矛盾。
    """
    nums_a = _extract_numbers(text_a)
    nums_b = _extract_numbers(text_b)
    if not nums_a or not nums_b:
        return False
    # 若数字集合完全相同 → 不矛盾
    if set(nums_a) == set(nums_b):
        return False
    # 若数字数量相同且至少有一对位置不同 → 矛盾
    if len(nums_a) == len(nums_b):
        diffs = sum(1 for x, y in zip(nums_a, nums_b) if abs(x - y) > 1e-6)
        if diffs > 0:
            return True
    # 若数量不同但有交集，且差异较大 → 视为矛盾（保守：至少有一对相同数字）
    common = set(nums_a) & set(nums_b)
    if common and (len(set(nums_a) - common) > 0 or len(set(nums_b) - common) > 0):
        return True
    return False


def _keyword_detect_pair(
    clause_a: ClauseRecord,
    clause_b: ClauseRecord,
    standard_a: str,
    standard_b: str,
) -> ConflictItem | None:
    """关键词级检测一对条款，返回 ConflictItem 或 None。

    判定优先级（高 → 低）：
    1) enhancement：A 弱 B 强（企业增强，最强语义信号，优先返回）
    2) contradiction：数字矛盾（措辞无强弱关系但数字不同）
    3) duplicate：标题/正文 Jaccard >= 阈值（信息级，最后判定）

    设计说明：
    - 当 A 用"宜/可"等弱词、B 用"必须/不得"等强词时，无论数字是否相同，
      都视为企业标准增强（B 集明确比 A 集严格）。此语义信号优先于数字差异，
      否则"宜 Ra 3.2 vs 必须 Ra 1.6"会被误判为矛盾（实际是增强：B 更严）。
    - 当两条款措辞高度相似（无强弱词）但数字不同时，判为矛盾而非重复，
      避免漏报真正的参数差异。
    """
    text_a = f"{clause_a.title} {clause_a.original_text}"
    text_b = f"{clause_b.title} {clause_b.original_text}"

    # 1) enhancement（最高优先级）：A 弱 B 强 → 企业标准增强
    # 约定：standard_a 为国标，standard_b 为企业标准
    if _has_strict_vs_weaker(text_a, text_b):
        return ConflictItem(
            conflict_type="enhancement",
            severity="info",
            standard_a=standard_a,
            standard_b=standard_b,
            clause_a_id=clause_a.clause_id,
            clause_b_id=clause_b.clause_id,
            title_a=clause_a.title,
            title_b=clause_b.title,
            text_a=clause_a.original_text[:300],
            text_b=clause_b.original_text[:300],
            description="企业标准使用更严格措辞（必须/不得/严于），视为增强",
            detection_method="keyword",
        )

    # 2) contradiction：数字矛盾（措辞无强弱关系时）
    if _has_number_contradiction(text_a, text_b):
        return ConflictItem(
            conflict_type="contradiction",
            severity="major",
            standard_a=standard_a,
            standard_b=standard_b,
            clause_a_id=clause_a.clause_id,
            clause_b_id=clause_b.clause_id,
            title_a=clause_a.title,
            title_b=clause_b.title,
            text_a=clause_a.original_text[:300],
            text_b=clause_b.original_text[:300],
            description="条款中的数字参数存在差异，疑似矛盾",
            detection_method="keyword",
        )

    # 3) duplicate：Jaccard 相似度（最低优先级）
    tokens_a = _tokenize_zh(text_a)
    tokens_b = _tokenize_zh(text_b)
    if _jaccard(tokens_a, tokens_b) >= _DUPLICATE_JACCARD_THRESHOLD:
        return ConflictItem(
            conflict_type="duplicate",
            severity="info",
            standard_a=standard_a,
            standard_b=standard_b,
            clause_a_id=clause_a.clause_id,
            clause_b_id=clause_b.clause_id,
            title_a=clause_a.title,
            title_b=clause_b.title,
            text_a=clause_a.original_text[:300],
            text_b=clause_b.original_text[:300],
            description=f"关键词重合度高于阈值 {_DUPLICATE_JACCARD_THRESHOLD}，疑似重复定义",
            detection_method="keyword",
        )

    return None


def _detect_missing(
    clauses_a: list[ClauseRecord],
    clauses_b: list[ClauseRecord],
    standard_a: str,
    standard_b: str,
) -> list[ConflictItem]:
    """检测 missing：A 集中存在但 B 集无相似条款（关键词重合度低）。"""
    items: list[ConflictItem] = []
    b_tokens = [_tokenize_zh(f"{c.title} {c.original_text}") for c in clauses_b]
    for ca in clauses_a:
        ta = _tokenize_zh(f"{ca.title} {ca.original_text}")
        # 找 B 集中最相似的条款
        max_sim = 0.0
        best_cb: ClauseRecord | None = None
        for cb, tb in zip(clauses_b, b_tokens):
            sim = _jaccard(ta, tb)
            if sim > max_sim:
                max_sim = sim
                best_cb = cb
        # 若最大相似度低于 0.2，视为 B 集缺失
        if max_sim < 0.2:
            items.append(
                ConflictItem(
                    conflict_type="missing",
                    severity="minor",
                    standard_a=standard_a,
                    standard_b=standard_b,
                    clause_a_id=ca.clause_id,
                    clause_b_id="",
                    title_a=ca.title,
                    title_b="",
                    text_a=ca.original_text[:300],
                    text_b="",
                    description=f"规范集 {standard_b} 中未找到与 {standard_a} §{ca.clause_id} 相似的条款",
                    detection_method="keyword",
                )
            )
    return items


# ---------------------------------------------------------------------------
# LLM 检测
# ---------------------------------------------------------------------------


_LLM_PROMPT_TEMPLATE = """你是一名工程规范审查专家。请对比以下两条规范条款，判断它们是否存在冲突。

规范集 A（{standard_a}）条款 {clause_a_id}：{title_a}
正文：{text_a}

规范集 B（{standard_b}）条款 {clause_b_id}：{title_b}
正文：{text_b}

请仅输出 JSON，不要额外解释。JSON schema：
{{
  "conflict_type": "contradiction | duplicate | missing | enhancement | none",
  "severity": "critical | major | minor | info",
  "description": "冲突说明（中文，<200 字）"
}}

判定标准：
- contradiction：同一要求规定了不同的参数值或互相矛盾的规定
- duplicate：同一要求重复定义（措辞不同但语义一致）
- missing：B 集中完全无对应要求（仅当 B 集条款为空时使用）
- enhancement：B 集要求严于 A 集（措辞更严格或参数更严）
- none：无冲突
"""


def _llm_detect_pair(
    clause_a: ClauseRecord,
    clause_b: ClauseRecord,
    standard_a: str,
    standard_b: str,
) -> ConflictItem | None:
    """LLM 级检测一对条款。LLM 不可用时返回 None。"""
    try:
        from app.services.ai.base import (
            ChatMessage,
            get_llm_provider,
        )
    except ImportError as e:  # pragma: no cover
        log.warning("kb.conflict_detector.llm_unavailable", error=str(e))
        return None

    try:
        provider = get_llm_provider()
        if not provider.is_available():
            log.info("kb.conflict_detector.llm_not_available")
            return None
        prompt = _LLM_PROMPT_TEMPLATE.format(
            standard_a=standard_a,
            standard_b=standard_b,
            clause_a_id=clause_a.clause_id,
            clause_b_id=clause_b.clause_id,
            title_a=clause_a.title,
            title_b=clause_b.title,
            text_a=clause_a.original_text[:500],
            text_b=clause_b.original_text[:500],
        )
        msgs = [
            ChatMessage(
                role="system",
                content="你是工程规范冲突检测专家，只输出 JSON。",
            ),
            ChatMessage(role="user", content=prompt),
        ]
        resp = provider.chat(msgs, temperature=0.1, max_tokens=400)
        if not resp.content or not resp.content.strip():
            return None
        # 解析 JSON（容忍前后非 JSON 文本）
        content = resp.content.strip()
        # 找第一个 { 与最后一个 }
        start = content.find("{")
        end = content.rfind("}")
        if start < 0 or end <= start:
            return None
        data = json.loads(content[start : end + 1])
        ct = data.get("conflict_type", "none")
        if ct == "none" or ct not in ("contradiction", "duplicate", "missing", "enhancement"):
            return None
        severity = data.get("severity", "info")
        if severity not in ("critical", "major", "minor", "info"):
            severity = "info"
        return ConflictItem(
            conflict_type=ct,
            severity=severity,
            standard_a=standard_a,
            standard_b=standard_b,
            clause_a_id=clause_a.clause_id,
            clause_b_id=clause_b.clause_id,
            title_a=clause_a.title,
            title_b=clause_b.title,
            text_a=clause_a.original_text[:300],
            text_b=clause_b.original_text[:300],
            description=str(data.get("description", ""))[:500],
            detection_method="llm",
        )
    except Exception as e:  # noqa: BLE001
        log.warning("kb.conflict_detector.llm_call_failed", error=str(e))
        return None


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def detect_conflicts(
    clauses_a: list[ClauseRecord],
    clauses_b: list[ClauseRecord],
    standard_a: str,
    standard_b: str,
    use_llm: bool = True,
) -> ConflictReport:
    """检测两个规范集之间的冲突。

    Args:
        clauses_a: 规范集 A 的条款列表（通常为国标）
        clauses_b: 规范集 B 的条款列表（通常为企业标准）
        standard_a: 规范集 A 名称
        standard_b: 规范集 B 名称
        use_llm: 是否启用 LLM 检测（True 且 LLM 可用时双重检测）

    Returns:
        ConflictReport：含冲突列表与统计
    """
    conflicts: list[ConflictItem] = []
    llm_used = False

    # 配对策略：对 A 中每条条款，找 B 中标题/关键词最相似的条款配对
    b_tokens = [_tokenize_zh(f"{c.title} {c.original_text}") for c in clauses_b]

    for ca in clauses_a:
        ta = _tokenize_zh(f"{ca.title} {ca.original_text}")
        # 找最相似的 B 条款
        best_cb: ClauseRecord | None = None
        best_sim = 0.0
        for cb, tb in zip(clauses_b, b_tokens):
            sim = _jaccard(ta, tb)
            if sim > best_sim:
                best_sim = sim
                best_cb = cb
        if best_cb is None or best_sim < 0.1:
            # 相似度太低，跳过配对（missing 由专门逻辑处理）
            continue

        # 关键词检测
        kw_item = _keyword_detect_pair(ca, best_cb, standard_a, standard_b)

        # LLM 检测（可选）
        llm_item: ConflictItem | None = None
        if use_llm:
            llm_item = _llm_detect_pair(ca, best_cb, standard_a, standard_b)
            if llm_item is not None:
                llm_used = True

        # 合并结果
        if kw_item is not None and llm_item is not None:
            # 双重命中 → 标记 both，描述合并
            merged = kw_item.model_copy(update={
                "detection_method": "both",
                "description": f"[kw] {kw_item.description} | [llm] {llm_item.description}",
            })
            # 严重等级取较重者
            severity_order = {"info": 0, "minor": 1, "major": 2, "critical": 3}
            if severity_order.get(llm_item.severity, 0) > severity_order.get(kw_item.severity, 0):
                merged = merged.model_copy(update={"severity": llm_item.severity})
            if llm_item.conflict_type != kw_item.conflict_type:
                # 类型不一致时取 LLM 结果（语义级判断更准）
                merged = merged.model_copy(update={"conflict_type": llm_item.conflict_type})
            conflicts.append(merged)
        elif kw_item is not None:
            conflicts.append(kw_item)
        elif llm_item is not None:
            conflicts.append(llm_item)

    # missing 检测
    conflicts.extend(_detect_missing(clauses_a, clauses_b, standard_a, standard_b))

    # 统计
    by_type: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    for c in conflicts:
        by_type[c.conflict_type] = by_type.get(c.conflict_type, 0) + 1
        by_severity[c.severity] = by_severity.get(c.severity, 0) + 1

    log.info(
        "kb.conflict_detector.done",
        standard_a=standard_a,
        standard_b=standard_b,
        total=len(conflicts),
        llm_used=llm_used,
        by_type=by_type,
    )

    return ConflictReport(
        standard_a=standard_a,
        standard_b=standard_b,
        conflicts=conflicts,
        total=len(conflicts),
        by_type=by_type,
        by_severity=by_severity,
        llm_used=llm_used,
    )
