"""bge-m3 Embedding 封装。

遵循"以复用现有为荣"原则，使用 FlagEmbedding 官方包加载 bge-m3。
优雅降级链：
1) bge-m3（FlagEmbedding，~2GB 权重，需可访问 HuggingFace）
2) sentence-transformers 的 paraphrase-multilingual-MiniLM-L12-v2（~470MB，CPU 友好）
3) Ollama HTTP API（model=nomic-embed-text，768 维，需本地 Ollama 服务）

bge-m3 输出维度 1024；sentence-transformers 回退模型输出维度 384；
Ollama nomic-embed-text 输出维度 768。
调用方应通过 `vector_size` 属性动态获取维度，不要硬编码。
"""

from __future__ import annotations

import os
import threading
from typing import Any

import httpx

from app.logging import get_logger

log = get_logger(__name__)

# 模型常量
_BGE_M3_MODEL = "BAAI/bge-m3"
_FALLBACK_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
_BGE_M3_DIM = 1024
_FALLBACK_DIM = 384
_OLLAMA_MODEL = "nomic-embed-text"
_OLLAMA_DIM = 768
_OLLAMA_DEFAULT_URL = "http://localhost:11434"

# 配置 HuggingFace 镜像端点(中国境内加速 bge-m3 / sentence-transformers 下载)。
# 必须在 `from FlagEmbedding import BGEM3FlagModel` 之前设置,因为 FlagEmbedding
# 在 import 阶段就会读取 HF_ENDPOINT 决定下载域名。
# 使用 setdefault:允许用户通过环境变量覆盖(例如已配置代理时)。
# 同步设置 HF_HUB_DOWNLOAD_TIMEOUT 避免大文件(~2GB)默认超时被切断。
# HF_HUB_DISABLE_XET=1: 禁用 HuggingFace xet CAS 后端(cas-server.xethub.hf.co),
#   xet 后端不尊重 HF_ENDPOINT 镜像且需要鉴权(会 401 Unauthorized),
#   禁用后走 legacy 下载路径,正常通过 hf-mirror 下载。
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "60")
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

# bge-m3 仓库中推理必需的文件清单。
# 仓库内还存在 imgs/.DS_Store 等 macOS 元数据/文档图片,在 hf-mirror 上 403 Forbidden,
# 若用 BGEM3FlagModel(model_id) 直接加载会触发全仓库文件拉取(含 .DS_Store)导致失败。
# 因此 _load_model 先用 snapshot_download(allow_patterns) 仅下载必需文件,
# 再用本地缓存路径加载 BGEM3FlagModel,绕开 .DS_Store 403。
_BGE_M3_ALLOW_PATTERNS = (
    "config.json",
    "config_sentence_transformers.json",
    "sentence_bert_config.json",
    "modules.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "sentencepiece.bpe.model",
    "special_tokens_map.json",
    "1_Pooling/config.json",
    "model.safetensors",
)


class BGEM3Embedder:
    """bge-m3 向量化封装（单例懒加载，线程安全）。

    用法：
        emb = BGEM3Embedder()
        vecs = emb.embed(["圆度公差", "尺寸标注基准"])
        dim = emb.vector_size  # 1024 或 384
    """

    _instance: "BGEM3Embedder | None" = None
    _lock = threading.Lock()

    def __new__(cls) -> "BGEM3Embedder":
        # 单例：避免重复加载大模型
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False  # type: ignore[attr-defined]
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._model: Any = None
        self._backend: str = ""  # "bge-m3" | "fallback" | "ollama"
        self._vector_size: int = 0
        self._ollama_url: str = ""
        # 标记加载流程已完成（含 Ollama fallback）。
        # Ollama 后端下 self._model 保持 None，若用 _model 判加载状态会重复触发
        # 完整加载链（bge-m3 → sentence-transformers → Ollama probe）。
        self._loaded: bool = False
        self._initialized = True

    @property
    def backend(self) -> str:
        """当前使用的后端名称。"""
        self._ensure_loaded()
        return self._backend

    @property
    def vector_size(self) -> int:
        """输出向量维度（bge-m3=1024，回退=384）。"""
        self._ensure_loaded()
        return self._vector_size

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            self._load_model()
            # _load_model 在所有成功路径(bge-m3/fallback/ollama)均会 return，
            # 全部失败则抛 RuntimeError；仅在成功后置位，避免 Ollama 路径下
            # _model=None 触发重复加载。
            self._loaded = True

    def _load_model(self) -> None:
        """尝试加载 bge-m3，失败则回退到 sentence-transformers，再回退到 Ollama。"""
        # 1) 优先 bge-m3
        # 再次 setdefault,确保即使本模块被部分 import(绕过顶部环境变量设置)
        # 也能在 FlagEmbedding import 前生效。
        os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
        os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "60")
        os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
        try:
            from FlagEmbedding import BGEM3FlagModel  # type: ignore[import-not-found]
            from huggingface_hub import snapshot_download

            log.info("kb.embedder.loading", model=_BGE_M3_MODEL, hf_endpoint=os.environ.get("HF_ENDPOINT"))
            # 预下载推理必需文件(allow_patterns 跳过 imgs/.DS_Store 等 mirror 403 文件)。
            # 仓库内 .DS_Store 在 hf-mirror 上 403,若用 model_id 直接加载会触发全仓库拉取导致失败。
            # 用 allow_patterns 仅拉必需文件后,用本地缓存路径加载,绕开 .DS_Store 403。
            local_path = snapshot_download(
                repo_id=_BGE_M3_MODEL,
                allow_patterns=list(_BGE_M3_ALLOW_PATTERNS),
            )
            log.info(
                "kb.embedder.snapshot_downloaded",
                model=_BGE_M3_MODEL,
                local_path=str(local_path),
            )
            # use_fp16=False：CPU 友好；GPU 环境可设 True
            # 用 local_path 而非 model_id,避免再次触发全仓库文件拉取
            self._model = BGEM3FlagModel(local_path, use_fp16=False)
            self._backend = "bge-m3"
            self._vector_size = _BGE_M3_DIM
            log.info(
                "kb.embedder.loaded",
                model=_BGE_M3_MODEL,
                backend=self._backend,
                dim=self._vector_size,
            )
            return
        except Exception as e:  # noqa: BLE001
            log.warning(
                "kb.embedder.bge_m3_unavailable",
                error=str(e),
                fallback=_FALLBACK_MODEL,
            )

        # 2) 回退：sentence-transformers
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]

            log.info("kb.embedder.loading_fallback", model=_FALLBACK_MODEL)
            self._model = SentenceTransformer(_FALLBACK_MODEL)
            self._backend = "fallback"
            self._vector_size = _FALLBACK_DIM
            log.warning(
                "kb.embedder.loaded_fallback",
                model=_FALLBACK_MODEL,
                backend=self._backend,
                dim=self._vector_size,
                reason="bge-m3 加载失败，已回退到 CPU 友好模型",
            )
            return
        except Exception as e:  # noqa: BLE001
            log.warning(
                "kb.embedder.sentence_transformers_unavailable",
                error=str(e),
                fallback="ollama:" + _OLLAMA_MODEL,
            )

        # 3) 第三优先级：Ollama HTTP API（nomic-embed-text，无需安装额外 Python 包）
        #    需本地 Ollama 服务运行并已 pull nomic-embed-text 模型
        ollama_url = os.environ.get("OLLAMA_HOST_URL") or _OLLAMA_DEFAULT_URL
        # 兼容 settings 配置（若已加载）：尝试读取但不强制依赖
        try:
            from app.config import settings  # type: ignore[import-not-found]

            ollama_url = getattr(settings, "OLLAMA_HOST_URL", ollama_url) or ollama_url
        except Exception:  # noqa: BLE001
            pass

        if self._probe_ollama(ollama_url):
            self._model = None  # Ollama 后端无需本地模型对象
            self._backend = "ollama"
            self._vector_size = _OLLAMA_DIM
            self._ollama_url = ollama_url
            log.warning(
                "kb.embedder.loaded_ollama",
                model=_OLLAMA_MODEL,
                backend=self._backend,
                dim=self._vector_size,
                ollama_url=ollama_url,
                reason="bge-m3 与 sentence-transformers 均不可用，回退到 Ollama HTTP API",
            )
            return

        log.error(
            "kb.embedder.all_models_failed",
            tried=["bge-m3", "sentence-transformers", "ollama"],
        )
        raise RuntimeError(
            "无法加载任何 embedding 模型：bge-m3 / sentence-transformers / Ollama 均失败"
        )

    def _probe_ollama(self, ollama_url: str) -> bool:
        """探测 Ollama 服务是否可用，且 nomic-embed-text 模型已就绪。

        通过 `/api/embeddings` 端点发送一个空文本探测请求：
        - 若返回 200 且响应体包含 embedding 字段，视为可用
        - 任何错误（连接失败、模型未拉取、超时）都视为不可用
        """
        try:
            resp = httpx.post(
                f"{ollama_url.rstrip('/')}/api/embeddings",
                json={"model": _OLLAMA_MODEL, "prompt": "ping"},
                timeout=10.0,
            )
            if resp.status_code == 200 and "embedding" in resp.json():
                return True
            log.warning(
                "kb.embedder.ollama_probe_failed",
                status_code=resp.status_code,
                body=resp.text[:200],
            )
            return False
        except Exception as e:  # noqa: BLE001
            log.warning("kb.embedder.ollama_unreachable", error=str(e))
            return False

    def _ollama_embed(self, texts: list[str]) -> list[list[float]]:
        """通过 Ollama HTTP API 批量生成向量。

        Ollama `/api/embeddings` 一次只接受一个 prompt，故按文本逐条调用。
        nomic-embed-text 输出维度 768。
        """
        results: list[list[float]] = []
        url = f"{self._ollama_url.rstrip('/')}/api/embeddings"
        with httpx.Client(timeout=60.0) as client:
            for text in texts:
                resp = client.post(
                    url, json={"model": _OLLAMA_MODEL, "prompt": text}
                )
                resp.raise_for_status()
                vec = resp.json().get("embedding", [])
                if not vec:
                    raise RuntimeError(
                        f"Ollama 返回空向量，text 长度={len(text)}"
                    )
                results.append(list(map(float, vec)))
        return results

    def embed(self, texts: list[str]) -> list[list[float]]:
        """批量生成向量。

        Args:
            texts: 文本列表

        Returns:
            list[list[float]]，每个内层 list 长度为 vector_size
        """
        if not texts:
            return []
        self._ensure_loaded()

        if self._backend == "bge-m3":
            # BGEM3FlagModel.encode 返回 dict，dense_vecs 为稠密向量
            out = self._model.encode(
                texts, batch_size=12, max_length=8192, return_dense=True
            )
            dense = out["dense_vecs"]
            # 转为 list[list[float]]，避免 numpy 类型泄漏
            return [list(map(float, row)) for row in dense]
        elif self._backend == "ollama":
            return self._ollama_embed(texts)
        else:
            # sentence-transformers：encode 返回 ndarray
            vecs = self._model.encode(texts, normalize_embeddings=True)
            return [list(map(float, row)) for row in vecs]

    def embed_one(self, text: str) -> list[float]:
        """单条文本向量化（便捷方法）。"""
        return self.embed([text])[0]


def get_embedder() -> BGEM3Embedder:
    """获取全局 BGEM3Embedder 单例。"""
    return BGEM3Embedder()
