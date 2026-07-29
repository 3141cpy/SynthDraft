"""LLM 生成 CadQuery 代码（SubTask 5.2 + 5.6）。

主路径：调用 Ollama ``qwen2.5-coder:7b`` chat API 生成 CadQuery Python 代码。
降级路径：LLM 不可用时调用 ``templates.template_match_generate``。

注意（铁律）：
- ``openai`` 包被 llama-index 降级到 1.x，不可用于 Ollama 调用
- 优先使用 ``ollama`` Python 包的 ``chat`` API
- 模型名来自 ``settings.LLM_MODEL``（默认 qwen2.5-coder:7b）
"""

from __future__ import annotations

import re
import time
from typing import Any

from app.config import settings
from app.logging import get_logger
from app.services.generation.prompts import (
    BUILD_STEPS_PROMPT_TEMPLATE,
    MULTI_TURN_DIFF_PROMPT_TEMPLATE,
    SYSTEM_PROMPT,
    _BUILD_STEPS_EXAMPLES,  # noqa: F401  (用于 BUILD_STEPS_PROMPT_TEMPLATE 格式化)
)
from app.services.generation.templates import template_match_generate

__all__ = [
    "is_llm_available",
    "generate_cadquery_code",
    "apply_multi_turn_edit",
    "template_match_generate",
]

log = get_logger(__name__)

# 用于从 LLM 输出中提取 python 代码块的正则
_PYTHON_BLOCK_RE = re.compile(
    r"```(?:python|py)?\s*\n(.*?)\n```",
    re.DOTALL,
)


# ===== Ollama 客户端（懒加载）=====
# 注意：自 SubTask 3.5 起，业务路径统一改走 app.services.ai.get_llm_provider()。
# 以下 _get_ollama_client / _ollama_* 缓存变量保留仅供向后兼容与潜在外部调用，
# 不再被 generate_cadquery_code / apply_multi_turn_edit 使用。

_ollama_client: Any = None
_ollama_checked: bool = False
_ollama_available: bool = False


def _get_ollama_client() -> Any:
    """[Deprecated] 懒加载 ollama Python 客户端，返回 None 表示不可用。

    自 SubTask 3.5 起业务路径改走 ``get_llm_provider().chat()``，
    本函数保留仅为向后兼容，不再被 generate / multi_turn 路径调用。
    """
    global _ollama_client, _ollama_checked, _ollama_available
    if _ollama_checked:
        return _ollama_client if _ollama_available else None
    _ollama_checked = True
    try:
        import ollama  # type: ignore[import-not-found]

        # 通过 list() 探测服务可达性
        client = ollama.Client(host=settings.OLLAMA_HOST_URL)
        _ollama_client = client
        _ollama_available = True
        log.info(
            "ollama.client.loaded",
            host=settings.OLLAMA_HOST_URL,
        )
        return client
    except Exception as e:  # noqa: BLE001
        _ollama_available = False
        log.warning("ollama.client.unavailable", error=str(e))
        return None


def is_llm_available() -> bool:
    """检查 LLM 是否可用。

    自 SubTask 3.5 起转调 ``get_llm_provider().is_available()``，
    由 Provider 抽象屏蔽 ollama / openai / anthropic 差异。

    Returns:
        True 表示当前 Provider 文本模型可用
    """
    try:
        from app.services.ai import get_llm_provider

        return get_llm_provider().is_available()
    except Exception as e:  # noqa: BLE001
        log.warning("llm.provider.unavailable", error=str(e))
        return False


# ===== 代码块提取 =====


def _extract_python_code(text: str) -> str:
    """从 LLM 输出中提取 Python 代码块。

    若没有代码块围栏，尝试整段当作代码返回（容错）。
    """
    if not text:
        return ""
    matches = _PYTHON_BLOCK_RE.findall(text)
    if matches:
        # 取最后一个代码块（避免示例污染）
        return matches[-1].strip()
    # 无围栏：去掉行首可能的 ``` 标记后整段返回
    cleaned = "\n".join(
        line for line in text.splitlines()
        if not line.strip().startswith("```")
    )
    return cleaned.strip()


# ===== 生成入口 =====


def _is_valid_llm_code(code: str | None) -> tuple[bool, str | None]:
    """校验 LLM 生成的代码：含 cadquery import + 语法可编译。

    Returns:
        (is_valid, reason) —— reason 为 None 表示通过，否则给出失败原因
        （用于日志与降级路径诊断）。

    注意：
    - ``compile()`` 仅做语法解析，不执行代码；不会触发 import 副作用。
    - 语义错误（如调用不存在的 CadQuery API ``.workplane(centered=...)``）
      无法在此检出，需依赖沙箱执行阶段的运行时错误捕获。
    """
    if not code or "import cadquery" not in code:
        return False, "missing_import"
    try:
        compile(code, "<llm_generated>", "exec")
    except SyntaxError as e:
        return False, f"syntax_error:{e}"
    return True, None


def generate_cadquery_code(
    prompt: str,
    history: list[dict] | None = None,
) -> tuple[str, str]:
    """根据自然语言 prompt 生成 CadQuery 代码。

    Args:
        prompt: 用户自然语言零件描述
        history: 多轮对话历史（可选）

    Returns:
        (code, mode) 元组：
        - code: CadQuery Python 代码字符串
        - mode: "llm" 或 "template"
    """
    if not prompt or not prompt.strip():
        raise ValueError("prompt 不能为空")

    if not is_llm_available():
        log.info("generate.fallback.template", reason="llm_unavailable")
        return template_match_generate(prompt), "template"

    try:
        code = _call_ollama_generate(prompt, history)
        valid, reason = _is_valid_llm_code(code)
        if valid:
            return code, "llm"
        # LLM 输出异常（缺 import / 语法错误），降级到模板
        log.warning(
            "generate.llm.bad_output, fallback to template",
            reason=reason,
            code_preview=(code or "")[:200],
        )
        return template_match_generate(prompt), "template"
    except Exception as e:  # noqa: BLE001
        log.warning("generate.llm.failed, fallback to template", error=str(e))
        return template_match_generate(prompt), "template"


def _call_ollama_generate(
    prompt: str,
    history: list[dict] | None,
) -> str:
    """实际调用 LLM chat API（自 SubTask 3.5 起走 provider 抽象）。"""
    from app.services.ai import ChatMessage, get_llm_provider

    provider = get_llm_provider()

    user_msg = BUILD_STEPS_PROMPT_TEMPLATE.format(
        system=SYSTEM_PROMPT,
        examples=_BUILD_STEPS_EXAMPLES,
        user_prompt=prompt,
    )

    messages: list[ChatMessage] = [ChatMessage(role="system", content=SYSTEM_PROMPT)]
    # 简短历史注入（最近 4 轮）
    if history:
        for h in history[-4:]:
            role = h.get("role", "user")
            content = h.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append(ChatMessage(role=role, content=str(content)))
    messages.append(ChatMessage(role="user", content=user_msg))

    t0 = time.time()
    log.info("llm.chat.start", provider=type(provider).__name__, messages=len(messages))
    resp = provider.chat(messages, temperature=0.2, max_tokens=2048)
    elapsed = time.time() - t0
    log.info("llm.chat.done", elapsed_s=round(elapsed, 2))

    return _extract_python_code(resp.content)


# ===== 多轮修改（SubTask 5.6）=====


def apply_multi_turn_edit(
    original_code: str,
    edit_instruction: str,
    history: list[dict] | None = None,
) -> str:
    """对原 CadQuery 代码做多轮增量修改。

    主路径：构造 MULTI_TURN_DIFF_PROMPT_TEMPLATE 调用 LLM。
    降级路径：用正则提取参数变更（如"外径改为120"）做字符串替换。

    Args:
        original_code: 原始 CadQuery Python 代码
        edit_instruction: 用户修改意图（自然语言）
        history: 对话历史

    Returns:
        修改后的完整 CadQuery Python 代码
    """
    if not original_code.strip():
        raise ValueError("original_code 不能为空")
    if not edit_instruction.strip():
        raise ValueError("edit_instruction 不能为空")

    if not is_llm_available():
        log.info("multiturn.fallback.regex", reason="llm_unavailable")
        return _regex_edit(original_code, edit_instruction)

    try:
        from app.services.ai import ChatMessage, get_llm_provider

        provider = get_llm_provider()

        # 历史简短摘要
        history_str = "(无历史)"
        if history:
            lines = []
            for h in history[-4:]:
                role = h.get("role", "user")
                content = str(h.get("content", ""))[:200]
                lines.append(f"  - {role}: {content}")
            history_str = "\n".join(lines)

        user_msg = MULTI_TURN_DIFF_PROMPT_TEMPLATE.format(
            system=SYSTEM_PROMPT,
            original_code=original_code,
            edit_instruction=edit_instruction,
            history=history_str,
        )

        t0 = time.time()
        log.info("llm.multiturn.start", provider=type(provider).__name__)
        resp = provider.chat(
            [
                ChatMessage(role="system", content=SYSTEM_PROMPT),
                ChatMessage(role="user", content=user_msg),
            ],
            temperature=0.1,
            max_tokens=2048,
        )
        log.info("llm.multiturn.done", elapsed_s=round(time.time() - t0, 2))

        new_code = _extract_python_code(resp.content)
        if new_code and "import cadquery" in new_code and new_code != original_code:
            return new_code
        # 若 LLM 输出与原代码相同或无 cadquery，尝试正则降级
        log.warning("multiturn.llm.no_change_or_bad, fallback to regex")
        return _regex_edit(original_code, edit_instruction)
    except Exception as e:  # noqa: BLE001
        log.warning("multiturn.llm.failed, fallback to regex", error=str(e))
        return _regex_edit(original_code, edit_instruction)


# ===== 正则降级：参数替换 =====

# 匹配 "外径改为120" / "外径改为 120 mm" / "把外径改为120" / "外径=120" / "outer_diameter=120"
_PARAM_EDIT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?:把|将)?\s*(外径|外直径|outer_diameter|outer diameter)\s*(?:改为|改成|调整为|改成|=\s*|设为)\s*(\d+(?:\.\d+)?)"), "outer_diameter"),
    (re.compile(r"(?:把|将)?\s*(内径|内直径|inner_diameter|inner diameter)\s*(?:改为|改成|调整为|=\s*|设为)\s*(\d+(?:\.\d+)?)"), "inner_diameter"),
    (re.compile(r"(?:把|将)?\s*(厚度|厚|thickness)\s*(?:改为|改成|调整为|=\s*|设为)\s*(\d+(?:\.\d+)?)"), "thickness"),
    (re.compile(r"(?:把|将)?\s*(孔径|孔直径|hole_diameter|hole diameter)\s*(?:改为|改成|调整为|=\s*|设为)\s*(\d+(?:\.\d+)?)"), "hole_diameter"),
    (re.compile(r"(?:把|将)?\s*(分度圆|节圆|bolt_circle_diameter|pcd)\s*(?:改为|改成|调整为|=\s*|设为)\s*(\d+(?:\.\d+)?)"), "bolt_circle_diameter"),
    (re.compile(r"(?:把|将)?\s*(长度|长|length)\s*(?:改为|改成|调整为|=\s*|设为)\s*(\d+(?:\.\d+)?)"), "length"),
    (re.compile(r"(?:把|将)?\s*(宽度|宽|width)\s*(?:改为|改成|调整为|=\s*|设为)\s*(\d+(?:\.\d+)?)"), "width"),
    (re.compile(r"(?:把|将)?\s*(孔数|孔个数|hole_count|holes)\s*(?:改为|改成|调整为|=\s*|设为)\s*(\d+)"), "hole_count"),
    (re.compile(r"(?:把|将)?\s*(边长|size)\s*(?:改为|改成|调整为|=\s*|设为)\s*(\d+(?:\.\d+)?)"), "size"),
    (re.compile(r"(?:把|将)?\s*(左段直径|seg1_diameter)\s*(?:改为|改成|调整为|=\s*|设为)\s*(\d+(?:\.\d+)?)"), "seg1_diameter"),
    (re.compile(r"(?:把|将)?\s*(左段长度|seg1_length)\s*(?:改为|改成|调整为|=\s*|设为)\s*(\d+(?:\.\d+)?)"), "seg1_length"),
    (re.compile(r"(?:把|将)?\s*(右段直径|seg2_diameter)\s*(?:改为|改成|调整为|=\s*|设为)\s*(\d+(?:\.\d+)?)"), "seg2_diameter"),
    (re.compile(r"(?:把|将)?\s*(右段长度|seg2_length)\s*(?:改为|改成|调整为|=\s*|设为)\s*(\d+(?:\.\d+)?)"), "seg2_length"),
]


def _regex_edit(original_code: str, edit_instruction: str) -> str:
    """正则降级：从修改意图提取参数变更并替换代码中的赋值。"""
    new_code = original_code
    any_change = False
    for pat, param_name in _PARAM_EDIT_PATTERNS:
        m = pat.search(edit_instruction)
        if not m:
            continue
        new_value = m.group(2)
        # 在代码中查找形如  param_name = <old>
        # 替换为 param_name = <new>
        assign_pat = re.compile(
            rf"^(\s*{re.escape(param_name)}\s*=\s*)(\d+(?:\.\d+)?)",
            re.MULTILINE,
        )
        replaced, n = assign_pat.subn(rf"\g<1>{new_value}", new_code, count=1)
        if n > 0:
            new_code = replaced
            any_change = True
            log.info("multiturn.regex.applied", param=param_name, new_value=new_value)
    if not any_change:
        log.warning("multiturn.regex.no_match", instruction=edit_instruction)
    return new_code
