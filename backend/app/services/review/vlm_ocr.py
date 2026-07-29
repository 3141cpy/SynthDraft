"""VLM（视觉语言模型）OCR 模块（SubTask 4.2）。

P0 阶段降级策略：
- 优先使用 Ollama 中的视觉模型（minicpm-v / llava 等）
- VLM 不可用时返回空 dict，pipeline 标注 review_mode="vector_only"

Ollama Python 客户端 API：
    import ollama
    ollama.chat(model='minicpm-v', messages=[{'role':'user','content':'...','images':[b64]}])

官方文档：https://github.com/ollama/ollama-python
"""

from __future__ import annotations

import base64
import io
import json
import os
import time
from pathlib import Path
from typing import Any

import httpx

from app.logging import get_logger

log = get_logger(__name__)

# 默认 Ollama URL（与 embedder 保持一致）
_OLLAMA_DEFAULT_URL = "http://localhost:11434"

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


def _get_ollama_url() -> str:
    """从环境变量或 settings 获取 Ollama URL。"""
    url = os.environ.get("OLLAMA_HOST_URL") or _OLLAMA_DEFAULT_URL
    try:
        from app.config import settings

        url = getattr(settings, "OLLAMA_HOST_URL", url) or url
    except Exception:  # noqa: BLE001
        pass
    return url


def list_ollama_models() -> list[str]:
    """列出 Ollama 中已安装的模型名。

    通过 GET /api/tags 获取。
    """
    url = _get_ollama_url().rstrip("/")
    try:
        resp = httpx.get(f"{url}/api/tags", timeout=10.0)
        resp.raise_for_status()
        data = resp.json()
        return [m.get("name", "") or m.get("model", "") for m in data.get("models", [])]
    except Exception as e:  # noqa: BLE001
        log.warning("review.vlm.list_models_failed", error=str(e))
        return []


def is_vlm_available() -> bool:
    """检查 VLM 是否可用。

    自 SubTask 3.5 起转调 ``get_llm_provider().is_vlm_available()``，
    由 Provider 抽象屏蔽 ollama / openai / anthropic 差异。
    """
    try:
        from app.services.ai import get_llm_provider

        return get_llm_provider().is_vlm_available()
    except Exception as e:  # noqa: BLE001
        log.warning("review.vlm.provider_unavailable", error=str(e))
        return False


def _pick_vlm_model() -> str | None:
    """从已安装模型中挑选首选视觉模型。"""
    models = list_ollama_models()
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


# 图像尺寸阈值（VLM-02）：任一维度超过此值或文件大小超过 _MAX_IMAGE_BYTES 时降采样
_MAX_IMAGE_DIMENSION = 4096
_MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10MB


def _read_and_encode_with_size_check(path: Path) -> str:
    """读取图片并 base64 编码，超阈值时降采样（VLM-02）。

    阈值：任一维度 > 4096 像素 或 文件大小 > 10MB。
    超阈值时：使用 PIL.Image.thumbnail((4096, 4096)) 降采样，保存到 BytesIO，再 base64 编码。

    Args:
        path: 图片路径（可能是预处理后的路径或原图路径）

    Returns:
        base64 编码字符串
    """
    file_bytes = path.stat().st_size
    # 探测图像尺寸
    width = height = 0
    try:
        from PIL import Image  # type: ignore[import-not-found]

        with Image.open(path) as img:
            width, height = img.size
    except Exception as e:  # noqa: BLE001
        # PIL 不可用或图片损坏：直接读原字节（保持现有降级路径）
        log.warning("review.vlm.image_size_probe_failed", path=str(path), error=str(e))
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("ascii")

    too_large_dim = width > _MAX_IMAGE_DIMENSION or height > _MAX_IMAGE_DIMENSION
    too_large_bytes = file_bytes > _MAX_IMAGE_BYTES
    if not too_large_dim and not too_large_bytes:
        # 正常：直接 base64 编码
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("ascii")

    # 超阈值：降采样
    try:
        from PIL import Image  # type: ignore[import-not-found]

        with Image.open(path) as img:
            original_size = img.size
            # thumbnail 原地缩放（保持宽高比，仅缩小不放大），使用 LANCZOS 高质量重采样
            img.thumbnail((_MAX_IMAGE_DIMENSION, _MAX_IMAGE_DIMENSION), Image.LANCZOS)
            resized_size = img.size
            # 保存到 BytesIO（保留原格式；若原格式不支持，用 PNG 兜底）
            buf = io.BytesIO()
            try:
                img.save(buf, format=img.format or "PNG")
            except (KeyError, ValueError):
                buf = io.BytesIO()
                img.save(buf, format="PNG")
            encoded = base64.b64encode(buf.getvalue()).decode("ascii")
        log.warning(
            "review.vlm.image_too_large_resized",
            path=str(path),
            original_size=list(original_size),
            resized_size=list(resized_size),
            original_bytes=file_bytes,
        )
        return encoded
    except Exception as e:  # noqa: BLE001
        # 降采样失败：降级为原图字节（不阻断主流程）
        log.warning(
            "review.vlm.image_resize_failed_fallback",
            path=str(path),
            error=str(e),
        )
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("ascii")


def _encode_image(image_path: Path) -> str:
    """读取图片并 base64 编码。

    SubTask 9.1 集成：
    - 优先调用 image_preprocess.preprocess_image() 做去噪/校正/对比度增强
    - 失败时降级为原图（不影响下游 VLM 调用）
    - 预处理结果缓存到 tmp 目录，重复调用同一图片时直接复用

    VLM-02 集成：
    - 预处理之后对图片做尺寸/文件大小检查，超阈值时降采样到 4096x4096
    - 避免超大图像导致 VLM 调用超时或内存溢出
    """
    # 尝试预处理（SubTask 9.1）
    try:
        from app.services.review.image_preprocess import is_preprocess_available, preprocess_image

        if is_preprocess_available():
            prepped_path = preprocess_image(image_path)
            # 使用预处理后的图片（可能是原图路径，表示降级），含 VLM-02 尺寸检查
            return _read_and_encode_with_size_check(Path(prepped_path))
    except Exception as e:  # noqa: BLE001
        log.warning("review.vlm.preprocess_failed_fallback", path=str(image_path), error=str(e))

    # 降级：直接读原图（含 VLM-02 尺寸检查）
    return _read_and_encode_with_size_check(Path(image_path))


def _ollama_chat_with_image(
    model: str,
    prompt: str,
    image_b64: str,
    timeout: float = 120.0,
) -> str:
    """[Deprecated] 调用 Ollama /api/chat，发送图片 + 文本 prompt，返回 assistant 文本。

    使用 HTTP API 而非 ollama Python 包，便于控制 timeout 与错误处理。

    自 SubTask 3.5 起业务路径改走 ``get_llm_provider().chat_with_image()``，
    本函数保留仅为向后兼容（sketch_parser 等历史模块仍可能引用）。
    """
    url = f"{_get_ollama_url().rstrip('/')}/api/chat"
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": [image_b64],
            }
        ],
        "stream": False,
    }
    resp = httpx.post(url, json=payload, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    # 响应结构：{"message": {"role":"assistant","content":"..."}, ...}
    msg = data.get("message") or {}
    return str(msg.get("content", ""))


# VLM-03：重试退避序列（秒），任务约定 1s / 2s / 4s —— 每次"重试"前的等待时长
# 最多 3 次重试（首次调用 + 3 次重试 = 4 次调用），3 次重试分别等待 1s/2s/4s
_VLM_RETRY_BACKOFF_SECONDS: tuple[float, ...] = (1.0, 2.0, 4.0)
_VLM_MAX_RETRIES = 3  # 最多重试次数（不含首次调用）


def _is_retryable_http_status_error(exc: httpx.HTTPStatusError) -> bool:
    """判断 ``httpx.HTTPStatusError`` 是否可重试（仅 5xx）。"""
    try:
        status = exc.response.status_code
    except Exception:  # noqa: BLE001
        return False
    return 500 <= status < 600


def _vlm_call_with_retry(
    provider: Any,
    messages: list[Any],
    image_b64: str,
    **kwargs: Any,
) -> Any:
    """VLM 调用 + 指数退避重试（VLM-03）。

    仅对可重试异常重试：
    - ``httpx.ConnectError`` / ``httpx.ReadTimeout`` —— 网络瞬态故障，重试
    - ``httpx.HTTPStatusError`` —— 仅 5xx 重试；4xx 直接 raise（客户端错误不可恢复）

    重试策略：
    - 最多 3 次重试（首次调用 + 3 次重试 = 4 次调用），退避 1s / 2s / 4s
    - 每次重试前 log.warning ``review.vlm.retry`` 记录 attempt / error / backoff_sec
    - 全部重试失败后返回 None（调用方处理为空结果）

    Args:
        provider: LLM Provider 实例（实现 ``chat_with_image``）
        messages: 对话消息列表（ChatMessage 列表）
        image_b64: base64 编码图片
        **kwargs: 透传给 ``provider.chat_with_image`` 的额外参数（temperature/max_tokens 等）

    Returns:
        ``ChatResponse`` 实例；全部重试失败返回 None。
    """
    total_attempts = _VLM_MAX_RETRIES + 1  # 首次 + 重试
    last_exc: Exception | None = None
    for attempt in range(1, total_attempts + 1):
        try:
            return provider.chat_with_image(messages, image_b64, **kwargs)
        except httpx.HTTPStatusError as exc:
            if _is_retryable_http_status_error(exc):
                last_exc = exc
                if attempt >= total_attempts:
                    break
                backoff = _VLM_RETRY_BACKOFF_SECONDS[attempt - 1]
                log.warning(
                    "review.vlm.retry",
                    attempt=attempt,
                    error=f"{type(exc).__name__}: {exc}",
                    backoff_sec=backoff,
                    status_code=exc.response.status_code,
                )
                time.sleep(backoff)
            else:
                # 4xx 等不可重试 HTTP 错误：直接抛出（由调用方 except 捕获）
                raise
        except (httpx.ConnectError, httpx.ReadTimeout) as exc:
            last_exc = exc
            if attempt >= total_attempts:
                break
            backoff = _VLM_RETRY_BACKOFF_SECONDS[attempt - 1]
            log.warning(
                "review.vlm.retry",
                attempt=attempt,
                error=f"{type(exc).__name__}: {exc}",
                backoff_sec=backoff,
            )
            time.sleep(backoff)

    log.warning(
        "review.vlm.retry_exhausted",
        attempts=total_attempts,
        retries=_VLM_MAX_RETRIES,
        error=f"{type(last_exc).__name__ if last_exc else 'unknown'}: {last_exc}",
    )
    return None


def vlm_detect_regions(image_path: Path) -> list[dict[str, Any]]:
    """调用 VLM 识别图纸中的区域（标题栏/标注区/视图区/明细栏）。

    自 SubTask 3.5 起走 ``get_llm_provider().chat_with_image()``，
    由 Provider 抽象屏蔽 ollama / openai / anthropic 差异。

    Args:
        image_path: PNG 图片路径

    Returns:
        区域列表，每条含 name + bbox (x,y,w,h 归一化 0-1)。
        VLM 不可用或调用失败时返回空列表。
    """
    if not is_vlm_available():
        log.warning("review.vlm.detect_regions.skipped", reason="vlm_unavailable")
        return []

    try:
        img_b64 = _encode_image(image_path)
    except Exception as e:  # noqa: BLE001
        log.warning("review.vlm.encode_failed", error=str(e))
        return []

    prompt = (
        "你是工程图分析专家。请识别这张工程图中以下六类区域，"
        "并以 JSON 数组返回（不要包含其他文字）：\n"
        '[{"name":"title_block","bbox":[x,y,w,h]},'
        '{"name":"dimension_area","bbox":[x,y,w,h]},'
        '{"name":"view_area","bbox":[x,y,w,h]},'
        '{"name":"parts_list","bbox":[x,y,w,h]},'
        '{"name":"revision_block","bbox":[x,y,w,h]},'
        '{"name":"technical_requirements","bbox":[x,y,w,h]}]\n'
        "其中 bbox 为归一化坐标 [0-1]：x,y 为左上角，w,h 为宽高。\n"
        "若某类区域不存在则省略。仅输出 JSON 数组。"
    )

    try:
        from app.services.ai import ChatMessage, get_llm_provider

        provider = get_llm_provider()
        resp = _vlm_call_with_retry(
            provider,
            [ChatMessage(role="user", content=prompt)],
            img_b64,
            temperature=0.2,
            max_tokens=2048,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("review.vlm.detect_regions.failed", error=str(e))
        return []

    if resp is None:
        log.warning("review.vlm.detect_regions.retry_exhausted")
        return []

    if not resp.content:
        log.warning("review.vlm.detect_regions.empty", model=resp.model)
        return []

    raw_regions = _parse_json_array_from_text(resp.content)
    # 规范化每个 region 的 bbox（处理嵌套列表 / tuple / 越界值）
    # VLM-04：对每项做 Pydantic 校验，无效项 log.warning 后丢弃
    from app.schemas.vlm import VLMRegionItem

    normalized: list[dict[str, Any]] = []
    for raw in raw_regions:
        if not isinstance(raw, dict):
            continue
        bbox = raw.get("bbox")
        norm = _normalize_bbox(bbox)
        if norm is None:
            log.info(
                "review.vlm.detect_regions.skip_bad_bbox",
                bbox=bbox,
            )
            continue
        new_raw = dict(raw)
        new_raw["bbox"] = norm
        try:
            VLMRegionItem.model_validate(new_raw)
        except Exception as e:  # noqa: BLE001
            log.warning(
                "review.vlm.region_schema_violation",
                raw=new_raw,
                error=str(e),
            )
            continue
        normalized.append(new_raw)
    return normalized


def vlm_ocr_extract(
    image_path: Path,
    regions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """调用 VLM 对图片做 OCR，提取文字信息。

    自 SubTask 3.5 起走 ``get_llm_provider().chat_with_image()``，
    由 Provider 抽象屏蔽 ollama / openai / anthropic 差异。

    Args:
        image_path: PNG 图片路径
        regions: 可选区域列表（来自 vlm_detect_regions）；P0 阶段不裁剪，
            仅在 prompt 中提示 VLM 关注区域

    Returns:
        dict，含 title/drawing_number/material/scale/dimensions/technical_requirements 等字段。
        VLM 不可用时返回空 dict。
    """
    if not is_vlm_available():
        log.warning("review.vlm.ocr.skipped", reason="vlm_unavailable")
        return {}

    try:
        img_b64 = _encode_image(image_path)
    except Exception as e:  # noqa: BLE001
        log.warning("review.vlm.encode_failed", error=str(e))
        return {}

    region_hint = ""
    if regions:
        region_hint = (
            "\n已知区域（归一化坐标）：\n"
            + json.dumps(regions, ensure_ascii=False)
            + "\n请优先在这些区域内识别。"
        )

    prompt = (
        "你是工程图 OCR 专家。请从这张工程图中提取以下信息，"
        "并以 JSON 对象返回（不要包含其他文字）：\n"
        '{"title":"图名","drawing_number":"图号","material":"材料",'
        '"scale":"比例","dimensions":["尺寸标注1","尺寸标注2"],'
        '"technical_requirements":"技术要求文本",'
        '"surface_roughness":"表面粗糙度标注",'
        '"tolerance":"形位公差标注"}\n'
        "若某字段无法识别则填 null。仅输出 JSON 对象。"
        + region_hint
    )

    try:
        from app.services.ai import ChatMessage, get_llm_provider

        provider = get_llm_provider()
        resp = _vlm_call_with_retry(
            provider,
            [ChatMessage(role="user", content=prompt)],
            img_b64,
            temperature=0.2,
            max_tokens=2048,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("review.vlm.ocr.failed", error=str(e))
        return {}

    if resp is None:
        log.warning("review.vlm.ocr.retry_exhausted")
        return {}

    if not resp.content:
        log.warning("review.vlm.ocr.empty", model=resp.model)
        return {}

    result = _parse_json_object_from_text(resp.content)
    if not result:
        return {}
    # VLM-04：Pydantic 校验 VLM OCR 输出，无效字段 log.warning 后仅保留有效字段
    from app.schemas.vlm import VLMOCRResult

    try:
        VLMOCRResult.model_validate(result)
        # 全字段校验通过 —— 保留原 dict（含可能的额外字段）
    except Exception as e:  # noqa: BLE001
        log.warning(
            "review.vlm.ocr.schema_violation",
            error=str(e),
            raw_keys=sorted(result.keys()),
        )
        # 字段级 salvage：仅保留通过单字段校验的字段
        salvaged: dict[str, Any] = {}
        for field_name in VLMOCRResult.model_fields:
            if field_name not in result:
                continue
            try:
                VLMOCRResult.model_validate({field_name: result[field_name]})
                salvaged[field_name] = result[field_name]
            except Exception as inner_e:  # noqa: BLE001
                log.warning(
                    "review.vlm.ocr.field_violation",
                    field=field_name,
                    value=repr(result[field_name]),
                    error=str(inner_e),
                )
        result = salvaged
        if not result:
            return {}
    result["regions"] = regions or []
    result["vlm_model"] = resp.model
    return result


# ===== JSON 解析工具（容错） =====


def _normalize_bbox(bbox: Any) -> list[float] | None:
    """规范化 VLM 输出的 bbox 为 ``[x, y, w, h]`` 扁平列表（归一化 0-1）。

    处理以下 VLM 常见噪声：
    - 嵌套列表 ``[[x, y, w, h]]`` —— 展开为扁平
    - tuple —— 转 list
    - 长度不为 4 —— 返回 None（调用方应跳过）
    - 非数值元素 —— 返回 None
    - 越界值 —— 钳制到 [0, 1]
    - x+w > 1 / y+h > 1 —— 截断 w/h 使其不超过图像边界

    Returns:
        规范化后的 ``[x, y, w, h]`` 列表；输入非法时返回 None。
    """
    if not bbox:
        return None
    # 处理嵌套列表 [[x, y, w, h]]
    if isinstance(bbox, list) and len(bbox) == 1 and isinstance(bbox[0], (list, tuple)):
        bbox = bbox[0]
    # 处理 tuple
    if isinstance(bbox, tuple):
        bbox = list(bbox)
    # 验证长度
    if not isinstance(bbox, list) or len(bbox) != 4:
        return None
    # 验证数值类型
    try:
        bbox = [float(x) for x in bbox]
    except (TypeError, ValueError):
        return None
    # 钳制到 [0, 1]
    bbox = [max(0.0, min(1.0, x)) for x in bbox]
    # 确保 x+w <= 1, y+h <= 1（避免像素坐标越界）
    if bbox[0] + bbox[2] > 1.0:
        bbox[2] = 1.0 - bbox[0]
    if bbox[1] + bbox[3] > 1.0:
        bbox[3] = 1.0 - bbox[1]
    return bbox


def _parse_json_array_from_text(text: str) -> list[dict[str, Any]]:
    """从 VLM 文本输出中解析 JSON 数组（容错：提取首个 [ 到 ] 的内容）。"""
    if not text:
        return []
    # 尝试直接解析
    try:
        obj = json.loads(text)
        if isinstance(obj, list):
            return obj
    except json.JSONDecodeError:
        pass
    # 兜底：截取 [...] 子串
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            obj = json.loads(text[start : end + 1])
            if isinstance(obj, list):
                return obj
        except json.JSONDecodeError:
            pass
    log.warning("review.vlm.parse_array_failed", text_preview=text[:200])
    return []


def _parse_json_object_from_text(text: str) -> dict[str, Any]:
    """从 VLM 文本输出中解析 JSON 对象（容错：提取首个 { 到 } 的内容）。"""
    if not text:
        return {}
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            obj = json.loads(text[start : end + 1])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
    log.warning("review.vlm.parse_object_failed", text_preview=text[:200])
    return {}
