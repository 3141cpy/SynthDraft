"""Ollama Provider 实现（SubTask 3.2）。

复用 ``vlm_ocr.py`` 的 ``list_ollama_models`` / ``_pick_vlm_model`` 逻辑，
复用 ``code_generator.py`` 的 ``is_llm_available`` 探测逻辑。

调用路径：
- ``chat()``：优先使用 ``ollama`` Python 包的 ``Client.chat``（与 ``code_generator.py`` 一致）
- ``chat_with_image()``：使用 ``httpx`` 直接调 Ollama ``/api/chat`` HTTP API
  （与 ``vlm_ocr._ollama_chat_with_image`` 一致），便于控制 timeout 与错误处理

降级策略：服务不可达或模型未拉取时返回空 ``ChatResponse`` + warning 日志，不抛异常。

注意（铁律）：
- ``openai`` 包被 llama-index 降级到 1.x，不可用于 Ollama 调用
- 关键参数从 ``settings`` 读取：``OLLAMA_HOST_URL`` / ``LLM_MODEL``
- 不读 ``settings.VLM_MODEL``：Ollama 路径靠 ``_pick_vlm_model`` 自动探测已安装的视觉模型
"""

from __future__ import annotations

from typing import Any

import httpx

from app.config import settings
from app.logging import get_logger
from app.services.ai.base import BaseLLMProvider, ChatMessage, ChatResponse

log = get_logger(__name__)


# ===== 视觉模型探测（与 vlm_ocr.py 保持一致，3.5 重构时统一）=====

# 已知视觉模型关键字（用于 ollama list 匹配）
_KNOWN_VLM_KEYWORDS = (
    "minicpm-v",
    "llava",
    "qwen2.5-vl",  # 暂未在 Ollama 官方库，预留
    "qwen2-vl",
    "llama3.2-vision",
    "moondream",
)

# 已知视觉模型的优先级顺序（首个可用者使用）
_VLM_PREFERENCE = (
    "minicpm-v",
    "llava:7b",
    "llava:13b",
    "llava",
    "moondream",
)


def _list_ollama_models() -> list[str]:
    """列出 Ollama 中已安装的模型名（通过 GET /api/tags）。

    与 ``vlm_ocr.list_ollama_models`` 一致，复刻以保持 provider 自洽。
    """
    url = settings.OLLAMA_HOST_URL.rstrip("/")
    try:
        resp = httpx.get(f"{url}/api/tags", timeout=10.0)
        resp.raise_for_status()
        data = resp.json()
        return [m.get("name", "") or m.get("model", "") for m in data.get("models", [])]
    except Exception as e:  # noqa: BLE001
        log.warning("ai.ollama.list_models_failed", error=str(e))
        return []


def _pick_vlm_model() -> str | None:
    """从已安装模型中挑选首选视觉模型。

    与 ``vlm_ocr._pick_vlm_model`` 一致：先按优先级顺序匹配，再按关键字兜底。
    """
    models = _list_ollama_models()
    if not models:
        return None
    lower_models = [m.lower() for m in models]
    # 优先级顺序匹配
    for pref in _VLM_PREFERENCE:
        for i, m in enumerate(lower_models):
            if pref in m:
                return models[i]
    # 关键字兜底
    for i, m in enumerate(lower_models):
        if any(kw in m for kw in _KNOWN_VLM_KEYWORDS):
            return models[i]
    return None


# ===== OllamaProvider =====


class OllamaProvider(BaseLLMProvider):
    """Ollama Provider：通过本地 Ollama 服务调用 LLM/VLM。"""

    def __init__(self) -> None:
        # 客户端懒加载缓存（与 code_generator._ollama_client 模式一致）
        self._client: Any = None
        self._client_checked: bool = False
        self._client_available: bool = False

    def _get_client(self) -> Any:
        """懒加载 ``ollama`` Python 客户端，返回 None 表示不可用。

        与 ``code_generator._get_ollama_client`` 一致：
        通过 ``client.list()`` 探测服务可达性。
        """
        if self._client_checked:
            return self._client if self._client_available else None
        self._client_checked = True
        try:
            import ollama  # type: ignore[import-not-found]

            client = ollama.Client(host=settings.OLLAMA_HOST_URL)
            # 通过 list() 探测服务可达性（触发实际 HTTP 请求）
            client.list()
            self._client = client
            self._client_available = True
            log.info("ai.ollama.client.loaded", host=settings.OLLAMA_HOST_URL)
            return client
        except Exception as e:  # noqa: BLE001
            self._client_available = False
            log.warning("ai.ollama.client.unavailable", error=str(e))
            return None

    # ===== 可用性检测 =====

    def is_available(self) -> bool:
        """检测文本 LLM 是否可用（Ollama 可达 + ``LLM_MODEL`` 已拉取）。

        与 ``code_generator.is_llm_available`` 一致：
        兼容 ollama 0.6.x 的 ModelList 对象 / dict 两种返回，
        兼容 ``:latest`` 后缀与 ``startswith`` 前缀匹配。
        """
        client = self._get_client()
        if client is None:
            return False
        try:
            resp = client.list()
            # ollama 0.6.x 返回 ModelList 类型，含 .models 属性
            models = getattr(resp, "models", None)
            if models is None and isinstance(resp, dict):
                models = resp.get("models", [])
            available_names: list[str] = []
            for m in models or []:
                name = getattr(m, "model", None) or getattr(m, "name", None)
                if name is None and isinstance(m, dict):
                    name = m.get("model") or m.get("name")
                if name:
                    available_names.append(str(name))
            target = settings.LLM_MODEL
            # 兼容 :latest 后缀
            target_variants = {target, f"{target}:latest"}
            ok = any(n in target_variants or n.startswith(target) for n in available_names)
            if not ok:
                log.warning(
                    "ai.ollama.llm_model.not_pulled",
                    target=target,
                    available=available_names,
                )
            return ok
        except Exception as e:  # noqa: BLE001
            log.warning("ai.ollama.llm_list.failed", error=str(e))
            return False

    def is_vlm_available(self) -> bool:
        """检测视觉 VLM 是否可用（已安装模型名匹配 VLM 关键字）。

        与 ``vlm_ocr.is_vlm_available`` 一致。
        """
        models = _list_ollama_models()
        for m in models:
            lower = m.lower()
            if any(kw in lower for kw in _KNOWN_VLM_KEYWORDS):
                log.info("ai.ollama.vlm.available", model=m)
                return True
        log.info("ai.ollama.vlm.not_available", models=models)
        return False

    # ===== 调用入口 =====

    def chat(
        self,
        messages: list[ChatMessage],
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> ChatResponse:
        """文本对话：调用 ``ollama.Client.chat``。

        降级：服务不可达或调用失败时返回空 ``ChatResponse``，不抛异常。
        """
        client = self._get_client()
        if client is None:
            log.warning("ai.ollama.chat.skipped", reason="client_unavailable")
            return ChatResponse(content="", model=settings.LLM_MODEL)

        # ChatMessage -> ollama messages dict
        ollama_messages: list[dict[str, Any]] = []
        for m in messages:
            msg: dict[str, Any] = {"role": m.role, "content": m.content}
            if m.images:
                msg["images"] = m.images
            ollama_messages.append(msg)

        try:
            resp = client.chat(
                model=settings.LLM_MODEL,
                messages=ollama_messages,
                options={
                    "temperature": temperature,
                    "num_predict": max_tokens,
                    "top_p": 0.9,
                },
            )
            return _parse_chat_response(resp, settings.LLM_MODEL)
        except Exception as e:  # noqa: BLE001
            log.warning("ai.ollama.chat.failed", error=str(e))
            return ChatResponse(content="", model=settings.LLM_MODEL)

    def stream_chat(
        self,
        messages: list[ChatMessage],
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> Any:
        """流式文本对话（SubTask 17.4）：调用 ``ollama.Client.chat(stream=True)``。

        Yields:
            str: 响应文本片段

        降级：服务不可达时 yield 空字符串并返回，不抛异常。
        """
        client = self._get_client()
        if client is None:
            log.warning("ai.ollama.stream_chat.skipped", reason="client_unavailable")
            return
        ollama_messages: list[dict[str, Any]] = []
        for m in messages:
            msg: dict[str, Any] = {"role": m.role, "content": m.content}
            if m.images:
                msg["images"] = m.images
            ollama_messages.append(msg)
        try:
            stream = client.chat(
                model=settings.LLM_MODEL,
                messages=ollama_messages,
                stream=True,
                options={
                    "temperature": temperature,
                    "num_predict": max_tokens,
                    "top_p": 0.9,
                },
            )
            for chunk in stream:
                # ollama stream chunk：dict 含 message.content 或对象 .message.content
                if isinstance(chunk, dict):
                    msg_obj = chunk.get("message") or {}
                    content = msg_obj.get("content", "")
                else:
                    msg_obj = getattr(chunk, "message", None)
                    content = getattr(msg_obj, "content", "") if msg_obj else ""
                if content:
                    yield content
        except Exception as e:  # noqa: BLE001
            log.warning("ai.ollama.stream_chat.failed", error=str(e))
            return

    def chat_with_image(
        self,
        messages: list[ChatMessage],
        image_b64: str,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> ChatResponse:
        """视觉对话：调用 Ollama ``/api/chat`` HTTP API。

        与 ``vlm_ocr._ollama_chat_with_image`` 一致：使用 ``httpx`` 直接调 HTTP API，
        messages 中 user content 含 ``images`` 字段。

        模型选择靠 ``_pick_vlm_model`` 自动探测，不读 ``settings.VLM_MODEL``。

        降级：无可用 VLM 模型或调用失败时返回空 ``ChatResponse``，不抛异常。
        """
        model = _pick_vlm_model()
        if not model:
            log.warning("ai.ollama.chat_with_image.skipped", reason="no_vlm_model")
            return ChatResponse(content="", model="")

        # 构造 messages：把 image_b64 注入到 user 消息的 images 字段
        # （与 vlm_ocr._ollama_chat_with_image 的 images: [image_b64] 一致）
        ollama_messages: list[dict[str, Any]] = []
        for m in messages:
            msg: dict[str, Any] = {"role": m.role, "content": m.content}
            if m.role == "user":
                imgs = list(m.images) if m.images else []
                if image_b64 not in imgs:
                    imgs.append(image_b64)
                msg["images"] = imgs
            elif m.images:
                msg["images"] = m.images
            ollama_messages.append(msg)

        url = f"{settings.OLLAMA_HOST_URL.rstrip('/')}/api/chat"
        payload: dict[str, Any] = {
            "model": model,
            "messages": ollama_messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        try:
            resp = httpx.post(url, json=payload, timeout=120.0)
            resp.raise_for_status()
            data = resp.json()
            # 响应结构：{"message": {"role":"assistant","content":"..."}, ...}
            msg = data.get("message") or {}
            content = str(msg.get("content", ""))
            usage = data.get("usage") if isinstance(data.get("usage"), dict) else None
            return ChatResponse(content=content, model=model, usage=usage, raw=data)
        except Exception as e:  # noqa: BLE001
            log.warning("ai.ollama.chat_with_image.failed", model=model, error=str(e))
            return ChatResponse(content="", model=model)


# ===== 响应解析工具 =====


def _parse_chat_response(resp: Any, model: str) -> ChatResponse:
    """解析 ``ollama.Client.chat`` 响应。

    兼容 ollama 0.6.x 的 ChatResponse 对象（含 ``.message.content``）与 dict 形式。
    与 ``code_generator._call_ollama_generate`` 的响应解析逻辑一致。
    """
    content = ""
    usage: dict[str, int] | None = None
    raw: dict[str, Any] | None = None

    if isinstance(resp, dict):
        content = (resp.get("message") or {}).get("content", "")
        u = resp.get("usage")
        if isinstance(u, dict):
            usage = u
        raw = resp
    else:
        msg = getattr(resp, "message", None)
        if msg is not None:
            content = getattr(msg, "content", "") or ""
        u = getattr(resp, "usage", None)
        if isinstance(u, dict):
            usage = u
        # ollama 0.6.x ChatResponse 是 pydantic 模型，可 model_dump
        if hasattr(resp, "model_dump"):
            try:
                raw = resp.model_dump()
            except Exception:  # noqa: BLE001
                raw = None

    return ChatResponse(
        content=content or "",
        model=model,
        usage=usage,
        raw=raw,
    )
