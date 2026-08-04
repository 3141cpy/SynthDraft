"""AI Provider 统一配置 schema（Task 1.1 + split-llm-vlm-config）。

将原有 4 个分化 provider schema（OLLAMA_* / VLLM_* / OPENAI_* / ANTHROPIC_*）
统一为单一结构（provider_type / base_url / api_key / model / vlm_model），
所有 provider 一视同仁，仅 base_url 与 api_key 不同。

split-llm-vlm-config：新增 ``role`` 字段（``"llm"`` / ``"vlm"``），按 role
动态校验 ``model`` / ``vlm_model`` 必填项：
- ``role="llm"``：``model`` 必填，``vlm_model`` 留空
- ``role="vlm"``：``vlm_model`` 必填，``model`` 留空

遵循项目现有 Pydantic v2 模式（``from __future__ import annotations`` + BaseModel）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


# 统一的 provider 类型枚举：
# - ollama: 本地 Ollama 服务
# - openai_compatible: OpenAI 官方 / DeepSeek / 通义千问 / 智谱 / vLLM 等 OpenAI 兼容 API
# - anthropic: Anthropic Claude
ProviderType = Literal["ollama", "openai_compatible", "anthropic"]

# 配置角色枚举：
# - llm: 文本模型配置（model 必填，vlm_model 留空）
# - vlm: 视觉模型配置（vlm_model 必填，model 留空）
ConfigRole = Literal["llm", "vlm"]


class AIProviderConfigBase(BaseModel):
    """Provider 配置基类：统一字段结构 + 配置名称 + role。

    - ``role="llm"``：``model`` 必填，``vlm_model`` 必须留空
    - ``role="vlm"``：``vlm_model`` 必填，``model`` 必须留空

    本地模型（如 Ollama）api_key 留空。
    """

    name: str = Field(..., min_length=1, max_length=100, description="配置名称")
    provider_type: ProviderType = Field(..., description="Provider 类型")
    base_url: str = Field(..., min_length=1, max_length=500, description="服务基础 URL")
    api_key: str = Field("", max_length=500, description="API key，本地模型留空")
    # model / vlm_model 默认空串，按 role 动态校验非空
    model: str = Field("", max_length=200, description="文本模型名称（role=llm 时必填）")
    vlm_model: str = Field("", max_length=200, description="视觉模型名称（role=vlm 时必填）")
    role: ConfigRole = Field("llm", description="配置角色：llm=文本模型 / vlm=视觉模型")

    @model_validator(mode="after")
    def _validate_role_fields(self) -> "AIProviderConfigBase":
        """按 role 校验 model / vlm_model 必填项。"""
        if self.role == "llm":
            if not self.model or not self.model.strip():
                raise ValueError("role=llm 时 model（文本模型名称）必填")
            if self.vlm_model and self.vlm_model.strip():
                # 不强制报错，但显式提示：llm 配置中的 vlm_model 不会被使用
                # 这里选择静默忽略以保持向前兼容（旧 .env 迁移可能两者都有）
                pass
        elif self.role == "vlm":
            if not self.vlm_model or not self.vlm_model.strip():
                raise ValueError("role=vlm 时 vlm_model（视觉模型名称）必填")
            if self.model and self.model.strip():
                # 同样静默忽略，vlm 配置中的 model 不会被使用
                pass
        return self


class AIProviderConfigCreate(AIProviderConfigBase):
    """新增 provider 配置请求体。"""


class AIProviderConfigUpdate(BaseModel):
    """更新 provider 配置请求体（所有字段可选）。

    注意：``role`` 字段一般不更新（创建后即固定）；如需切换 role 应新建配置。
    此处仍允许更新以保持 schema 一致性，但调用方应避免在 UI 暴露 role 修改。
    """

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    provider_type: Optional[ProviderType] = None
    base_url: Optional[str] = Field(None, min_length=1, max_length=500)
    api_key: Optional[str] = Field(None, max_length=500, description="留 None 表示不修改")
    model: Optional[str] = Field(None, max_length=200)
    vlm_model: Optional[str] = Field(None, max_length=200)
    role: Optional[ConfigRole] = None


class AIProviderConfigResponse(BaseModel):
    """Provider 配置响应体（api_key 脱敏返回）。"""

    id: int
    name: str
    provider_type: ProviderType
    base_url: str
    api_key: str = Field("", description="脱敏值：有 key 返回 '***'，无 key 返回空串")
    model: str
    vlm_model: str
    role: ConfigRole
    is_active: bool
    created_at: datetime
    updated_at: datetime


class AIConfigTestResult(BaseModel):
    """测试连接结果。"""

    available: bool = Field(..., description="文本模型是否可用")
    vlm_available: bool = Field(..., description="视觉模型是否可用")
    latency_ms: int = Field(..., description="探测往返延迟（毫秒）")
    error: str = Field("", description="失败时的错误信息，成功时为空")
