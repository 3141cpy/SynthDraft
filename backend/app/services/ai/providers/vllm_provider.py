"""vLLM 本地 GPU 推理 Provider（SubTask 13.1）。

vLLM 是高性能 LLM 推理引擎，提供 OpenAI 兼容的 HTTP API。
本 provider 通过 HTTP 调用 vLLM 服务端（``http://vllm:8000/v1``），
不直接依赖 vLLM Python 包，避免本地 GPU 环境约束。

设计要点（遵循"以复用现有为荣"原则）：
- 复用 ``BaseLLMProvider`` 抽象基类与 ``ChatMessage`` / ``ChatResponse`` schema
- 复用 ``OpenAIProvider._build_vision_messages`` 的多模态消息构造思路（vLLM 兼容 OpenAI 协议）
- 复用 ``httpx`` 直接调 REST API（与 ``AnthropicProvider._invoke_httpx`` 一致风格）

配置项（已在 config.py 中添加）：
- ``VLLM_ENABLED``：是否启用（False 时降级到 Ollama）
- ``VLLM_BASE_URL``：vLLM 服务端点
- ``VLLM_MODEL``：模型名
- ``VLLM_QUANTIZATION``：量化方案（awq/gptq/int8/fp8）
- ``VLLM_TENSOR_PARALLEL_SIZE``：张量并行大小（仅元信息，实际由 vLLM 启动参数决定）
- ``VLLM_GPU_MEMORY_UTILIZATION``：GPU 显存利用率（同上）
- ``VLLM_VLM_MODEL``：视觉模型名（留空则不启用 VLM）

降级路径：
- ``VLLM_ENABLED=False`` 或 vLLM 端点不可达 → 返回空 ``ChatResponse`` + warning
- 工厂 ``get_llm_provider()`` 在 LLM_PROVIDER=vllm 但 VLLM_ENABLED=False 时自动回退到 Ollama

环境限制说明（实事求是标注）：
- 本 provider 仅发起 HTTP 调用，不在本地加载模型权重
- 实际 GPU 推理性能取决于 vLLM 服务端启动参数（--tensor-parallel-size / --gpu-memory-utilization）
- 量化方案需 vLLM 启动时通过 ``--quantization`` 指定，本 provider 仅作为元信息透传
"""

from __future__ import annotations

from typing import Any

import httpx

from app.config import settings
from app.logging import get_logger
from app.services.ai.base import BaseLLMProvider, ChatMessage, ChatResponse

log = get_logger(__name__)


class VLLMProvider(BaseLLMProvider):
    """vLLM 本地 GPU 推理 Provider。

    通过 OpenAI 兼容 HTTP API 调用 vLLM 服务端。
    降级路径：VLLM_ENABLED=False 或端点不可达时返回空 ``ChatResponse``。
    """

    def __init__(self) -> None:
        self._base_url: str = (settings.VLLM_BASE_URL or "").rstrip("/")
        self._model: str = settings.VLLM_MODEL or ""
        self._vlm_model: str = settings.VLLM_VLM_MODEL or ""
        self._enabled: bool = bool(settings.VLLM_ENABLED and self._base_url and self._model)
        # 量化/并行仅作为元信息透传到日志，HTTP 调用本身不传这些参数
        # （vLLM 启动时已通过 --quantization / --tensor-parallel-size 决定）
        self._quantization: str = settings.VLLM_QUANTIZATION or ""
        self._tensor_parallel: int = settings.VLLM_TENSOR_PARALLEL_SIZE
        self._gpu_mem_util: float = settings.VLLM_GPU_MEMORY_UTILIZATION
        self._client: httpx.Client | None = None
        if self._enabled:
            try:
                self._client = httpx.Client(timeout=120.0)
                log.info(
                    "ai.vllm.init_ok",
                    base_url=self._base_url,
                    model=self._model,
                    vlm_model=self._vlm_model or "",
                    quantization=self._quantization or "none",
                    tensor_parallel=self._tensor_parallel,
                    gpu_mem_util=self._gpu_mem_util,
                )
            except Exception as e:  # noqa: BLE001
                log.warning("ai.vllm.client_init_failed", error=str(e))
                self._client = None
                self._enabled = False
        else:
            log.info(
                "ai.vllm.disabled",
                reason="VLLM_ENABLED_false_or_misconfigured",
                has_base_url=bool(self._base_url),
                has_model=bool(self._model),
            )

    # ===== 可用性检测 =====

    def is_available(self) -> bool:
        """检测 vLLM 服务端是否可达（GET /v1/models 或 /v1/health）。

        vLLM v0.25+ 暴露 /v1/models（OpenAI 兼容）和 /health 端点。
        """
        if not self._enabled or self._client is None:
            return False
        # 离线模式下不允许外部网络调用，但 vLLM 是内网服务，仍然允许
        # （OFFLINE_MODE 禁的是 HF Hub / 公网 API，不禁内网 vLLM）
        try:
            # 优先 /v1/models（OpenAI 兼容）
            resp = self._client.get(f"{self._base_url}/models", timeout=10.0)
            if resp.status_code == 200:
                return True
            # 兜底 /health
            health_url = self._base_url.replace("/v1", "") + "/health"
            resp2 = self._client.get(health_url, timeout=5.0)
            return resp2.status_code == 200
        except Exception as e:  # noqa: BLE001
            log.warning("ai.vllm.ping_failed", error=str(e))
            return False

    def is_vlm_available(self) -> bool:
        """视觉模型是否可用：检查 VLLM_VLM_MODEL 是否配置且 vLLM 端点可达。

        为避免每次都发请求，仅做配置检查；实际调用 chat_with_image() 时若端点
        不支持视觉会降级返回空响应。
        """
        return bool(self._enabled and self._vlm_model)

    # ===== 文本对话 =====

    def chat(
        self,
        messages: list[ChatMessage],
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> ChatResponse:
        """文本对话：POST /v1/chat/completions（OpenAI 兼容）。

        降级：未启用或调用失败时返回空 ChatResponse，不抛异常。
        """
        if not self._enabled or self._client is None:
            log.warning("ai.vllm.chat.skipped", reason="not_enabled_or_no_client")
            return ChatResponse(content="", model=self._model)
        payload_messages = [{"role": m.role, "content": m.content} for m in messages]
        body: dict[str, Any] = {
            "model": self._model,
            "messages": payload_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        try:
            resp = self._client.post(
                f"{self._base_url}/chat/completions",
                json=body,
                timeout=120.0,
            )
            resp.raise_for_status()
            return self._convert_response(resp.json())
        except Exception as e:  # noqa: BLE001
            log.warning("ai.vllm.chat.failed", model=self._model, error=str(e))
            return ChatResponse(content="", model=self._model)

    def chat_with_image(
        self,
        messages: list[ChatMessage],
        image_b64: str,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> ChatResponse:
        """多模态对话：将最后一条 user message 改为 [text, image_url] 数组。

        vLLM 通过 OpenAI 兼容协议支持视觉模型（如 Qwen2-VL / MiniCPM-V）。
        降级：未配置 VLM 模型或调用失败时返回空 ChatResponse。
        """
        if not self._enabled or self._client is None:
            log.warning("ai.vllm.chat_image.skipped", reason="not_enabled_or_no_client")
            return ChatResponse(content="", model=self._vlm_model or self._model)
        if not self._vlm_model:
            log.warning("ai.vllm.chat_image.skipped", reason="no_vlm_model")
            return ChatResponse(content="", model="")

        payload_messages = self._build_vision_messages(messages, image_b64)
        body: dict[str, Any] = {
            "model": self._vlm_model,
            "messages": payload_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        try:
            resp = self._client.post(
                f"{self._base_url}/chat/completions",
                json=body,
                timeout=180.0,
            )
            resp.raise_for_status()
            return self._convert_response(resp.json())
        except Exception as e:  # noqa: BLE001
            log.warning("ai.vllm.chat_image.failed", model=self._vlm_model, error=str(e))
            return ChatResponse(content="", model=self._vlm_model)

    # ===== 内部工具 =====

    @staticmethod
    def _build_vision_messages(
        messages: list[ChatMessage],
        image_b64: str,
    ) -> list[dict[str, Any]]:
        """将 messages 中最后一条 user message 的 content 替换为多模态数组。

        与 ``OpenAIProvider._build_vision_messages`` 一致（vLLM 兼容 OpenAI 协议）。
        """
        payload: list[dict[str, Any]] = [
            {"role": m.role, "content": m.content} for m in messages
        ]
        last_user_idx = -1
        for i in range(len(payload) - 1, -1, -1):
            if payload[i]["role"] == "user":
                last_user_idx = i
                break
        vision_content = [
            {
                "type": "text",
                "text": str(payload[last_user_idx]["content"]) if last_user_idx >= 0 else "",
            },
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{image_b64}"},
            },
        ]
        if last_user_idx >= 0:
            payload[last_user_idx]["content"] = vision_content
        else:
            payload.append({"role": "user", "content": vision_content})
        return payload

    @staticmethod
    def _convert_response(data: dict[str, Any]) -> ChatResponse:
        """将 vLLM OpenAI 兼容响应 dict 转换为统一 ChatResponse。"""
        content = ""
        model = str(data.get("model", "") or "")
        usage: dict[str, int] | None = None
        try:
            choices = data.get("choices") or []
            if choices:
                msg = choices[0].get("message") or {}
                content = str(msg.get("content", "") or "")
            u = data.get("usage")
            if isinstance(u, dict):
                usage = {
                    "prompt_tokens": int(u.get("prompt_tokens", 0) or 0),
                    "completion_tokens": int(u.get("completion_tokens", 0) or 0),
                    "total_tokens": int(u.get("total_tokens", 0) or 0),
                }
        except Exception as e:  # noqa: BLE001
            log.warning("ai.vllm.convert_failed", error=str(e))

        return ChatResponse(content=content, model=model, usage=usage, raw=data)

    def close(self) -> None:
        """关闭 httpx 客户端（资源释放）。"""
        if self._client is not None:
            try:
                self._client.close()
            except Exception:  # noqa: BLE001
                pass
            self._client = None
