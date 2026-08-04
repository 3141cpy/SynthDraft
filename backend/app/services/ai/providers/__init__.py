"""AI Provider 实现集合。

import 本包即触发各 provider 模块的 ``@register_provider`` 装饰器执行，将
provider 类注册到 ``app.services.ai.registry`` 全局注册表。

- ollama_provider：本地 Ollama（SubTask 3.2，Task 2.3 适配统一配置）
- openai_provider：OpenAI 兼容（含 DeepSeek / 通义千问 / 智谱 GLM / vLLM 等，
  SubTask 3.3，Task 2.4 适配统一配置）
- anthropic_provider：Anthropic Claude（SubTask 3.4，Task 2.5 适配统一配置）

注意（Task 2.6）：原 ``vllm_provider`` 已移除——vLLM 暴露 OpenAI 兼容 API，
统一归为 ``openai_compatible`` 类型，由 ``OpenAIProvider`` 承载，仅 ``base_url``
不同。旧的 ``LLM_PROVIDER=vllm`` 在 ``base.py`` legacy fallback 中映射到
``openai_compatible``，并在 ``VLLM_ENABLED=False`` 时回退 ollama。
"""

from __future__ import annotations

# 预导入 provider 模块以触发 @register_provider 注册。
# 各模块仅在 import 时注册类，不实例化（避免触发 SDK/网络探测），实例化由
# base.get_llm_provider() 按需进行。
from app.services.ai.providers import (  # noqa: F401
    anthropic_provider,
    ollama_provider,
    openai_provider,
)
