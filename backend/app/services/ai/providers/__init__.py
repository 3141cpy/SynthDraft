"""AI Provider 实现集合。

- ollama_provider：本地 Ollama（SubTask 3.2）
- openai_provider：OpenAI 兼容（含 vLLM / DeepSeek / 通义千问 / 智谱 GLM，SubTask 3.3）
- anthropic_provider：Anthropic Claude（SubTask 3.4）
- vllm_provider：vLLM 本地 GPU 推理（SubTask 13.1）
"""

from __future__ import annotations
