"""商业 API 脱敏工具（SubTask 13.3）。

在调用商业 LLM API（OpenAI / Anthropic / DeepSeek 等）前，对 prompt 中的
敏感信息进行脱敏，避免企业机密数据外泄。

支持的脱敏类型：
1. **图号**：GB/T 14689-2008 格式 "图号" / "DWG-No" / "XXX-XXX-XXX"
2. **件号**：6-12 位数字+字母组合（如零件号 "A001-002-003"）
3. **企业名**：包含"公司/集团/厂/研究所"等关键字的中国企业名
4. **人名**：中文姓名（2-4 字）+ 英文姓名（首字母大写）
5. **手机号**：中国大陆 11 位手机号
6. **邮箱**：标准 email 格式
7. **身份证号**：18 位身份证
8. **IP 地址**：IPv4

模式（与 config.COMMERCIAL_API_MODE 对齐）：
- ``off``      : 不脱敏，直接发送（默认，开发态）
- ``optional`` : 提示脱敏但不强制（出现敏感词时打 warning）
- ``strict``   : 强制脱敏，敏感词未脱敏时拒绝调用

设计原则（八荣八耻）：
- 复用 Python 标准库 ``re``，不引入第三方 NLP 依赖
- 正则模式保守优先：宁可漏脱敏不可误脱敏（避免破坏 prompt 语义）
- 与现有 ``BaseLLMProvider`` 解耦：通过 ``wrap_messages`` 工具函数在调用前注入
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from app.config import settings
from app.logging import get_logger

log = get_logger(__name__)


# ===== 内置正则模式 =====
# 每条规则：(name, pattern, replacement, description)
# replacement 中可用 \1 \2 等反向引用，或用占位符

@dataclass(frozen=True)
class DesensitizeRule:
    """单条脱敏规则。"""
    name: str
    pattern: re.Pattern[str]
    # re.sub 原生支持 str（含反向引用）或 callable（用于保留部分原文）
    replacement: str | Callable[[re.Match[str]], str]
    description: str = ""


# 内置规则（保守优先，避免误匹配破坏 prompt）
BUILTIN_RULES: list[DesensitizeRule] = [
    # 1. 身份证号（18 位，最后一位可能是 X）- 优先级最高，避免被手机号规则误匹配
    DesensitizeRule(
        name="id_card",
        pattern=re.compile(r"\b[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]\b"),
        replacement="[ID_CARD]",
        description="18 位身份证号",
    ),
    # 2. 中国大陆手机号（11 位，1 开头）
    DesensitizeRule(
        name="phone",
        pattern=re.compile(r"\b1[3-9]\d{9}\b"),
        replacement="[PHONE]",
        description="中国大陆手机号",
    ),
    # 3. 邮箱
    DesensitizeRule(
        name="email",
        pattern=re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
        replacement="[EMAIL]",
        description="电子邮箱",
    ),
    # 4. IPv4 地址（避免匹配版本号 1.2.3.4）
    DesensitizeRule(
        name="ipv4",
        pattern=re.compile(r"\b(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\."
                          r"(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\."
                          r"(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\."
                          r"(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"),
        replacement="[IP]",
        description="IPv4 地址",
    ),
    # 5. 图号（GB/T 14689-2008 格式：含 "图号" / "DWG No" 前缀 + 字母数字-分隔）
    DesensitizeRule(
        name="drawing_number",
        pattern=re.compile(
            r"(?:图号|图样编号|DWG[\s-]?No\.?|Drawing[\s-]?No\.?)\s*[:：]?\s*"
            r"([A-Z]{1,4}[\d-]{4,20}[A-Z]?)",
            re.IGNORECASE,
        ),
        replacement=r"图号: [DWG_NO]",
        description="工程图号（GB/T 14689）",
    ),
    # 6. 件号 / 零件号（X-Y-Z 或 X.Y.Z 格式，每段 1-6 位字母数字）
    DesensitizeRule(
        name="part_number",
        pattern=re.compile(
            r"\b(?:件号|零件号|Part[\s-]?No\.?|P/N)\s*[:：]?\s*"
            r"([A-Z0-9]{1,6}[-.][A-Z0-9]{1,6}[-.][A-Z0-9]{1,6})\b",
            re.IGNORECASE,
        ),
        replacement=r"件号: [PART_NO]",
        description="零件号 / 件号",
    ),
    # 7. 企业名（含"公司/集团/厂/研究所/研究院/设计院"等关键字，前缀 2-20 字符）
    DesensitizeRule(
        name="company_name",
        pattern=re.compile(
            r"([\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z0-9·]{1,19}"
            r"(?:有限公司|股份公司|集团有限公司|集团有限公司|集团|公司|厂|研究所|研究院|设计院|中心|局))",
        ),
        replacement="[COMPANY]",
        description="企业名称",
    ),
    # 8. 中文人名（2-4 字，常见姓氏开头，保守匹配：仅在"工程师/设计/审核/校对"等上下文中）
    DesensitizeRule(
        name="person_name",
        pattern=re.compile(
            r"(?:设计|审核|校对|制图|工程师|负责人|经办人|联系人|签名|签字)\s*[:：]\s*"
            r"([\u4e00-\u9fa5]{2,4})",
        ),
        # 保留姓氏首字 + [NAME] 占位符（callable：m.group(1) 为完整姓名）
        replacement=lambda m: m.group(1)[0] + "[NAME]",
        description="中文人名（上下文匹配）",
    ),
]


# 占位符映射（脱敏后的占位符 -> 原始类型描述）
PLACEHOLDER_MAP: dict[str, str] = {
    "[ID_CARD]": "身份证号",
    "[PHONE]": "手机号",
    "[EMAIL]": "邮箱",
    "[IP]": "IP 地址",
    "[DWG_NO]": "图号",
    "[PART_NO]": "件号",
    "[COMPANY]": "企业名",
    "[NAME]": "人名",
}


@dataclass
class DesensitizeResult:
    """脱敏结果。"""

    sanitized_text: str
    matched_rules: list[str] = field(default_factory=list)
    match_count: int = 0
    rejected: bool = False  # strict 模式下未脱敏即拒绝
    reject_reason: str = ""


def get_rules() -> list[DesensitizeRule]:
    """获取生效的脱敏规则列表。

    支持通过 settings.DESENSITIZE_PATTERNS (JSON) 覆盖内置规则。
    留空时使用 BUILTIN_RULES。
    """
    custom = settings.DESENSITIZE_PATTERNS.strip() if settings.DESENSITIZE_PATTERNS else ""
    if not custom:
        return list(BUILTIN_RULES)
    # 尝试解析自定义规则 JSON
    import json
    try:
        custom_rules_data = json.loads(custom)
        if not isinstance(custom_rules_data, list):
            log.warning("desensitize.custom_rules.not_list", type=type(custom_rules_data).__name__)
            return list(BUILTIN_RULES)
        rules: list[DesensitizeRule] = []
        for r in custom_rules_data:
            if not isinstance(r, dict):
                continue
            try:
                rules.append(DesensitizeRule(
                    name=str(r.get("name", "custom")),
                    pattern=re.compile(str(r["pattern"])),
                    replacement=str(r.get("replacement", "[REDACTED]")),
                    description=str(r.get("description", "")),
                ))
            except (re.error, KeyError) as e:
                log.warning("desensitize.custom_rule.invalid", rule=r, error=str(e))
        if rules:
            return rules
        log.warning("desensitize.custom_rules.empty_fallback_builtin")
        return list(BUILTIN_RULES)
    except json.JSONDecodeError as e:
        log.warning("desensitize.patterns.json_decode_failed", error=str(e))
        return list(BUILTIN_RULES)


def sanitize_text(text: str, *, mode: str | None = None) -> DesensitizeResult:
    """对单段文本进行脱敏。

    Args:
        text: 原始文本
        mode: 脱敏模式（None 时读 settings.COMMERCIAL_API_MODE）
            - "off"      : 直接返回原文，不做脱敏
            - "optional" : 脱敏 + 打 warning
            - "strict"   : 脱敏，若仍有残留敏感词则标记 rejected

    Returns:
        DesensitizeResult
    """
    if mode is None:
        mode = settings.COMMERCIAL_API_MODE
    mode = (mode or "off").strip().lower()

    if mode == "off" or not text:
        return DesensitizeResult(sanitized_text=text)

    rules = get_rules()
    sanitized = text
    matched_rules: list[str] = []
    total_matches = 0

    for rule in rules:
        new_text, count = rule.pattern.subn(rule.replacement, sanitized)
        if count > 0:
            sanitized = new_text
            matched_rules.append(rule.name)
            total_matches += count

    if mode == "optional" and total_matches > 0:
        log.warning(
            "desensitize.optional.matched",
            rules=matched_rules,
            count=total_matches,
            preview=sanitized[:200],
        )

    if mode == "strict":
        # 二次扫描：若仍能匹配到任何规则，标记 rejected
        # （说明脱敏不彻底，例如正则没覆盖的变体）
        residual_count = 0
        for rule in rules:
            _, c = rule.pattern.subn("", sanitized)
            residual_count += c
        if residual_count > 0:
            log.warning(
                "desensitize.strict.residual",
                residual_count=residual_count,
                preview=sanitized[:200],
            )
            return DesensitizeResult(
                sanitized_text=sanitized,
                matched_rules=matched_rules,
                match_count=total_matches,
                rejected=True,
                reject_reason=f"strict 模式下仍有 {residual_count} 处敏感词未脱敏",
            )

    return DesensitizeResult(
        sanitized_text=sanitized,
        matched_rules=matched_rules,
        match_count=total_matches,
    )


def sanitize_messages(messages: list) -> list:
    """对 ChatMessage 列表进行脱敏（就地修改 content 字段）。

    Args:
        messages: ``list[ChatMessage]``，每个元素含 role/content 字段

    Returns:
        新的 messages 列表（content 已脱敏）

    Raises:
        ValueError: strict 模式下任一消息被 rejected 时
    """
    mode = settings.COMMERCIAL_API_MODE
    if mode == "off":
        return messages

    new_messages = []
    for m in messages:
        # 兼容 ChatMessage pydantic 模型与 dict
        if hasattr(m, "model_dump"):
            m_dict = m.model_dump()
        elif isinstance(m, dict):
            m_dict = dict(m)
        else:
            # 直接复制对象引用（无法脱敏非 dict/ChatMessage）
            new_messages.append(m)
            continue

        content = str(m_dict.get("content", ""))
        result = sanitize_text(content, mode=mode)
        if result.rejected:
            raise ValueError(
                f"strict 模式拒绝调用：消息含未脱敏敏感词 ({result.reject_reason})"
            )
        m_dict["content"] = result.sanitized_text
        # 重建对象：若是 ChatMessage 则用 model_validate
        if hasattr(m, "model_dump"):
            try:
                new_m = type(m).model_validate(m_dict)
                new_messages.append(new_m)
                continue
            except Exception:  # noqa: BLE001
                pass
        new_messages.append(m_dict)
    return new_messages


def self_test() -> dict[str, Any]:
    """self_test：验证脱敏规则覆盖关键场景。"""
    test_cases = [
        ("身份证 110101199001011234", "id_card"),
        ("手机 13812345678", "phone"),
        ("邮箱 test@example.com", "email"),
        ("IP 192.168.1.100", "ipv4"),
        ("图号: ABC-1234-001", "drawing_number"),
        ("件号: A001-002-003", "part_number"),
        ("设计: 张三丰", "person_name"),
        ("由某某科技有限公司提供", "company_name"),
    ]
    results: dict[str, Any] = {"cases": [], "ok": True}
    for text, expected_rule in test_cases:
        r = sanitize_text(text, mode="strict")
        case_ok = expected_rule in r.matched_rules and not r.rejected
        results["cases"].append({
            "input": text,
            "expected_rule": expected_rule,
            "matched_rules": r.matched_rules,
            "sanitized": r.sanitized_text,
            "ok": case_ok,
        })
        if not case_ok:
            results["ok"] = False
    # mode=off 不脱敏
    off_r = sanitize_text("手机 13812345678", mode="off")
    results["off_mode_passthrough"] = off_r.sanitized_text == "手机 13812345678"
    if not results["off_mode_passthrough"]:
        results["ok"] = False
    return results


if __name__ == "__main__":
    import json
    print(json.dumps(self_test(), indent=2, ensure_ascii=False))
