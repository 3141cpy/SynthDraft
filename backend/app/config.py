"""应用配置：基于 pydantic-settings 从环境变量加载。

遵循"以复用现有为荣"原则，使用 pydantic-settings 标准模式，
不重复造配置加载轮子。所有键名与 infra/.env.example 对齐。
"""

from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局配置。环境变量优先级高于默认值。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ===== 应用元信息 =====
    APP_ENV: str = "development"
    APP_DEBUG: bool = True
    APP_NAME: str = "SynthDraft Backend"
    APP_VERSION: str = "0.1.0"
    LOG_LEVEL: str = "DEBUG"
    UPLOAD_DIR: str = "./tmp_uploads"

    # ===== PostgreSQL =====
    POSTGRES_HOST: str = "postgres"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "synthdraft"
    POSTGRES_PASSWORD: str = "synthdraft_dev_pwd"
    POSTGRES_DB: str = "synthdraft"
    DATABASE_URL: str = (
        "postgresql+asyncpg://synthdraft:synthdraft_dev_pwd@postgres:5432/synthdraft"
    )

    # ===== Redis / Celery =====
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    REDIS_URL: str = "redis://redis:6379/0"
    CELERY_BROKER_URL: str = "redis://redis:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://redis:6379/2"

    # ===== Qdrant =====
    QDRANT_URL: str = "http://qdrant:6333"

    # ===== MinIO =====
    MINIO_ENDPOINT: str = "minio:9000"
    MINIO_ACCESS_KEY: str = "synthdraft_minio"
    MINIO_SECRET_KEY: str = "synthdraft_minio_secret"
    MINIO_BUCKET: str = "synthdraft-files"
    MINIO_SECURE: bool = False

    # ===== Ollama / vLLM =====
    OLLAMA_HOST_URL: str = "http://ollama:11434"
    VLLM_BASE_URL: str = "http://vllm:8000/v1"

    # ===== SubTask 13.1: vLLM 本地 GPU 推理优化 =====
    # 是否启用 vLLM provider（False 时即使 LLM_PROVIDER=vllm 也会降级到 ollama）
    VLLM_ENABLED: bool = False
    # vLLM 加载的模型名（HuggingFace repo 或本地路径）
    VLLM_MODEL: str = "Qwen/Qwen2.5-Coder-7B-Instruct"
    # 量化方案："" / "awq" / "gptq" / "int8" / "fp8"
    # 留空表示不量化；与 vLLM --quantization 参数对齐
    VLLM_QUANTIZATION: str = ""
    # 张量并行大小（多 GPU 卡数）
    VLLM_TENSOR_PARALLEL_SIZE: int = 1
    # GPU 显存利用率上限（0.0-1.0）
    VLLM_GPU_MEMORY_UTILIZATION: float = 0.9
    # vLLM 视觉模型名（留空则不启用 VLM 路径）
    VLLM_VLM_MODEL: str = ""

    # ===== SubTask 13.2: 离线安装包 =====
    # 离线模式开关：True 时禁用所有外部网络调用（HF 下载 / 模型拉取 / 远程 API）
    OFFLINE_MODE: bool = False

    # ===== SubTask 13.3: 商业 API 脱敏模式 =====
    # 商业 API 调用模式：
    #   - "off"      : 不脱敏，直接发送原始内容（默认，开发态）
    #   - "optional" : 提示脱敏但不强制（出现敏感词时打 warning）
    #   - "strict"   : 强制脱敏，敏感词未脱敏时拒绝调用
    COMMERCIAL_API_MODE: str = "off"
    # 脱敏规则覆盖（JSON 字符串），默认空表示使用 desensitize.py 内置规则
    DESENSITIZE_PATTERNS: str = ""

    # ===== SubTask 13.4: 合规加固 =====
    # 审计日志开关
    AUDIT_LOG_ENABLED: bool = True
    # 审计日志保留天数（过期自动清理）
    AUDIT_LOG_RETENTION_DAYS: int = 180
    # 审计日志持久化路径（相对 backend cwd）
    AUDIT_LOG_PATH: str = "./tmp_audit/security_audit.jsonl"

    # ===== LLM 模型 =====
    LLM_PROVIDER: str = "ollama"
    LLM_MODEL: str = "qwen2.5-coder:7b"
    VLM_MODEL: str = "qwen2.5-vl:7b"
    EMBEDDING_MODEL: str = "bge-m3"

    # ===== HuggingFace 镜像端点(中国境内加速 bge-m3 / sentence-transformers 下载)=====
    # 默认使用 hf-mirror.com;用户可通过环境变量覆盖(例如已配置代理时设为 https://huggingface.co)
    HF_ENDPOINT: str = "https://hf-mirror.com"
    # 大文件(~2GB bge-m3)下载超时秒数,避免默认超时被切断
    HF_HUB_DOWNLOAD_TIMEOUT: str = "60"

    # ===== OpenAI 兼容（vLLM / DeepSeek / 通义千问 / 智谱 GLM / OpenAI 官方）=====
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    OPENAI_MODEL: str = "gpt-4o-mini"
    OPENAI_VLM_MODEL: str = "gpt-4o"

    # ===== Anthropic Claude =====
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_BASE_URL: str = "https://api.anthropic.com"
    ANTHROPIC_MODEL: str = "claude-3-5-sonnet-latest"
    ANTHROPIC_VLM_MODEL: str = "claude-3-5-sonnet-latest"

    # ===== JWT =====
    JWT_SECRET_KEY: str = "change-this-in-production-use-a-strong-random-secret"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    # ===== OpenTelemetry =====
    OTEL_EXPORTER_OTLP_ENDPOINT: str = ""
    OTEL_SERVICE_NAME: str = "synthdraft-backend"
    OTEL_ENABLED: bool = False

    # ===== 可观测性（Task 16）=====
    # Celery 队列监控
    OBS_QUEUE_MONITOR_ENABLED: bool = True
    # 队列堆积告警阈值（排队任务数）
    OBS_QUEUE_BACKLOG_ALERT: int = 50
    # 队列失败率告警阈值（百分比 0-100）
    OBS_QUEUE_FAILURE_RATE_ALERT: float = 10.0
    # 队列状态采集间隔（秒，用于后台采集任务，API 端点实时探测不依赖此值）
    OBS_QUEUE_SCAN_INTERVAL_SEC: int = 60
    # 告警 webhook（可选，留空则仅记录 log）
    OBS_ALERT_WEBHOOK_URL: str = ""

    # LLM 推理指标持久化路径（相对 backend cwd）
    OBS_LLM_METRICS_PATH: str = "./tmp_metrics/llm_metrics.jsonl"

    # 用户反馈持久化路径（feedback_store 的 JSONL 文件）
    OBS_FEEDBACK_STORE_PATH: str = "./tmp_metrics/feedback.jsonl"

    # ===== CORS =====
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:8000"

    # ===== Task 17: 性能优化 =====
    # SubTask 17.1: SolidWorks Worker 池预热（默认 0=不预热，生产环境设 1-2）
    SOLIDWORKS_PREWARM_COUNT: int = 0

    # SubTask 17.2: CAD 解析结果缓存
    CAD_CACHE_ENABLED: bool = True
    CAD_CACHE_TTL: int = 86400  # 24 小时（秒）

    # SubTask 17.3: RAG 检索缓存
    RAG_CACHE_ENABLED: bool = True
    RAG_CACHE_TTL: int = 3600  # 1 小时（秒）

    # SubTask 17.4: LLM 流式输出
    LLM_STREAM_ENABLED: bool = True
    LLM_STREAM_TIMEOUT: int = 300  # 5 分钟（秒）

    # ===== PDF 报告后端 =====
    # 值域: "auto" / "weasyprint" / "wkhtmltopdf" / "playwright" / "xhtml2pdf"
    #   - auto: 按优先级 weasyprint → wkhtmltopdf → playwright → xhtml2pdf 尝试
    #   - weasyprint: 原生 CSS 渲染最佳，但 Windows 需要 GTK 运行时库 (libgobject-2.0-0)
    #       MSYS2 安装: `pacman -S mingw-w64-x86_64-gtk3` 并将 bin 加入 PATH
    #   - wkhtmltopdf: 基于 QtWebKit，需单独安装 wkhtmltopdf.exe (https://wkhtmltopdf.org/downloads.html)
    #       pip 包 pdfkit 只是封装；CSS 支持有限
    #   - playwright: headless chromium 打印 PDF，需 `pip install playwright` + `python -m playwright install chromium`
    #       仅 chromium 支持 page.pdf()，firefox/webkit 不支持
    #   - xhtml2pdf: 纯 Python 无外部依赖，CSS 支持最有限，但 Windows 上最稳定可用
    PDF_BACKEND: str = "auto"

    @field_validator("PDF_BACKEND")
    @classmethod
    def _validate_pdf_backend(cls, v: str) -> str:
        allowed = {"auto", "weasyprint", "wkhtmltopdf", "playwright", "xhtml2pdf"}
        v_norm = (v or "auto").strip().lower()
        if v_norm not in allowed:
            raise ValueError(
                f"PDF_BACKEND must be one of {sorted(allowed)}, got: {v!r}"
            )
        return v_norm

    @field_validator("COMMERCIAL_API_MODE")
    @classmethod
    def _validate_commercial_api_mode(cls, v: str) -> str:
        allowed = {"off", "optional", "strict"}
        v_norm = (v or "off").strip().lower()
        if v_norm not in allowed:
            raise ValueError(
                f"COMMERCIAL_API_MODE must be one of {sorted(allowed)}, got: {v!r}"
            )
        return v_norm

    @field_validator("VLLM_QUANTIZATION")
    @classmethod
    def _validate_vllm_quantization(cls, v: str) -> str:
        # 与 vLLM --quantization 参数对齐
        allowed = {"", "awq", "gptq", "int8", "fp8", "bitsandbytes"}
        v_norm = (v or "").strip().lower()
        if v_norm not in allowed:
            raise ValueError(
                f"VLLM_QUANTIZATION must be one of {sorted(allowed)}, got: {v!r}"
            )
        return v_norm

    @field_validator("CORS_ORIGINS")
    @classmethod
    def _normalize_cors(cls, v: str) -> str:
        # 保留原始字符串；通过 cors_origins_list 属性访问解析后的列表
        return v

    @model_validator(mode="after")
    def _validate_production_secrets(self) -> "Settings":
        """非开发环境禁止使用不安全的开发默认密钥（fail closed）。

        仅当 APP_ENV=development 时跳过校验；其他环境（含 production / staging /
        未显式设置为 development 的环境）均强制校验敏感字段，避免遗漏 APP_ENV
        配置时静默降级到不安全模式。
        """
        if self.is_development:
            return self
        insecure: list[str] = []
        if not self.POSTGRES_PASSWORD or not self.POSTGRES_PASSWORD.strip() or self.POSTGRES_PASSWORD == "synthdraft_dev_pwd":
            insecure.append("POSTGRES_PASSWORD")
        if not self.MINIO_SECRET_KEY or not self.MINIO_SECRET_KEY.strip() or self.MINIO_SECRET_KEY == "synthdraft_minio_secret":
            insecure.append("MINIO_SECRET_KEY")
        if not self.JWT_SECRET_KEY or not self.JWT_SECRET_KEY.strip() or self.JWT_SECRET_KEY == "change-this-in-production-use-a-strong-random-secret":
            insecure.append("JWT_SECRET_KEY")
        # DATABASE_URL 可能保留默认弱口令（即使 POSTGRES_PASSWORD 已改）
        if "synthdraft_dev_pwd" in self.DATABASE_URL:
            insecure.append("DATABASE_URL")
        if insecure:
            raise ValueError(
                "非开发环境（APP_ENV != development）必须通过环境变量设置安全密钥，"
                f"以下字段仍为不安全开发默认值：{insecure}。"
            )
        return self

    @property
    def cors_origins_list(self) -> List[str]:
        """CORS 允许来源列表。"""
        if not self.CORS_ORIGINS:
            return []
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.APP_ENV.lower() == "production"

    @property
    def is_development(self) -> bool:
        """是否为显式开发环境（仅 APP_ENV=development 时 True，其他 fail closed）。"""
        return self.APP_ENV.lower() == "development"

    @property
    def is_offline(self) -> bool:
        """离线模式：禁用所有外部网络调用（SubTask 13.2）。"""
        return bool(self.OFFLINE_MODE)

    @property
    def commercial_api_strict(self) -> bool:
        """商业 API 脱敏是否强制模式（SubTask 13.3）。"""
        return self.COMMERCIAL_API_MODE == "strict"

    @property
    def commercial_api_optional(self) -> bool:
        """商业 API 脱敏是否可选提示模式（SubTask 13.3）。"""
        return self.COMMERCIAL_API_MODE == "optional"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """单例 Settings，避免重复解析环境变量。"""
    return Settings()


# 模块级常量，便于直接 import
settings = get_settings()
