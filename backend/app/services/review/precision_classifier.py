"""精度分级模块（Task 9.6）。

依据 spec.md 风险项 R5（多模态 VLM 对工程图理解精度不足），
对审图结果做精度分级，输出三个等级之一：

- VECTOR_LEVEL（矢量级）：CAD 矢量数据完整可信
- REFERENCE_LEVEL（参考级）：扫描/PDF，需人工复核
- SKETCH_LEVEL（草图级）：手绘草图，强制人工校准

判定证据来源（四类）：
1. 输入源类型：矢量（dxf/dwg/step）/ 光栅（pdf/png/jpg）/ 草图（sketch）
2. OCR 置信度：来自 ocr_paddle.ocr_extract() 的 confidence 字段
3. 区域检测置信度：来自区域检测模型的平均置信度
4. 标识符归一化命中率：来自标识符归一化模块的 match_rate

设计原则（八荣八耻）：
- 以复用现有为荣：assess_image_quality 复用 image_preprocess（load_image/to_gray/deskew）
- 以瞎猜接口为耻：所有阈值在模块顶部 _TH_* 常量中显式声明，便于审计
- 以覆盖测试为荣：self_test() 覆盖 6 个典型场景
- 以实事求是为荣：证据不足时降级到 REFERENCE_LEVEL，多证据冲突取较低等级（保守原则）
"""

from __future__ import annotations

import statistics
from pathlib import Path
from typing import Any

from app.logging import get_logger
from app.schemas.precision import (
    PrecisionClassification,
    PrecisionEvidence,
    PrecisionLevel,
)

log = get_logger(__name__)


# ============================================================================
# 阈值常量（"以瞎猜接口为耻"——所有阈值显式声明，便于审计与调参）
# ============================================================================

# 矢量源格式（CAD 原生数据，最高可信度）
_VECTOR_FORMATS: frozenset[str] = frozenset({"dxf", "dwg", "step", "iges", "stp"})

# 光栅源格式（扫描/渲染图，需 OCR/区域检测补救）
_RASTER_FORMATS: frozenset[str] = frozenset({"pdf", "png", "jpg", "jpeg", "bmp", "tiff", "tif"})

# 草图格式
_SKETCH_FORMATS: frozenset[str] = frozenset({"sketch", "sk"})

# OCR 置信度阈值
_TH_OCR_HIGH: float = 0.85       # 高于等于此值：可参与提升至 VECTOR_LEVEL
_TH_OCR_LOW: float = 0.50        # 低于此值：强制降至 SKETCH_LEVEL

# 标识符归一化命中率阈值
_TH_ID_MATCH_HIGH: float = 0.70  # 高于等于此值：可参与提升至 VECTOR_LEVEL
_TH_ID_MATCH_LOW: float = 0.30   # 低于此值：可能降至 SKETCH_LEVEL（综合判定）

# 区域检测置信度阈值
_TH_REGION_HIGH: float = 0.80    # 高于等于此值且来源为 yolov11：可提升至 VECTOR_LEVEL
_PREFERRED_REGION_SOURCE: str = "yolov11"

# 倾斜角阈值（度）：超过此值认为有显著倾斜
_TH_SKEW_WARN: float = 0.5

# 低分辨率阈值（总像素）：低于此值视为低质量图像
_TH_LOW_RESOLUTION_PIXELS: int = 100_000  # 约 316x316

# 低 DPI 阈值：低于此值视为扫描质量差
_TH_LOW_DPI: int = 100

# A 系列图纸幅面（mm）：用于 DPI 估算
# (名称, 短边 mm, 长边 mm)
_A_SERIES_MM: tuple[tuple[str, int, int], ...] = (
    ("A0", 841, 1189),
    ("A1", 594, 841),
    ("A2", 420, 594),
    ("A3", 297, 420),
    ("A4", 210, 297),
)


# ============================================================================
# 核心 API
# ============================================================================


def classify_precision(
    source_format: str,
    ocr_results: list[dict] | None = None,
    region_detection_result: dict | None = None,
    normalize_result: dict | None = None,
    image_path: Path | None = None,
    is_sketch: bool = False,
) -> PrecisionClassification:
    """精度分级主入口。

    判定规则（spec.md R5）：

    1. VECTOR_LEVEL（矢量级）：
       - 输入为 dxf/dwg/step 且矢量解析成功
       - OR 光栅源但 OCR 置信度 > 0.85 且标识符命中率 > 0.7
       - OR 区域检测来源为 yolov11 且置信度 > 0.8

    2. REFERENCE_LEVEL（参考级）：
       - 输入为 pdf/png/jpg（非草图）
       - OCR 置信度 0.5-0.85 之间
       - OR 标识符命中率 0.3-0.7 之间
       - 建议人工复核

    3. SKETCH_LEVEL（草图级）：
       - 输入为手绘草图（is_sketch=True 或 source_format="sketch"）
       - OR OCR 置信度 < 0.5
       - 强制人工校准尺寸环节

    边界处理：
    - 证据不足时（如纯矢量源无 OCR），按矢量源判定
    - 多个证据冲突时，取较低等级（保守原则）
    - 始终输出 rationale 说明判定理由

    Args:
        source_format: 输入源格式（dxf/dwg/step/pdf/png/jpg/sketch 等）
        ocr_results: OCR 结果列表，每条形如 {"text","bbox","confidence"}
        region_detection_result: 区域检测结果 dict
        normalize_result: 标识符归一化结果 dict
        image_path: 图像路径（用于评估图像质量）
        is_sketch: 是否为手绘草图

    Returns:
        PrecisionClassification
    """
    fmt = (source_format or "").lower().strip()
    is_vector = fmt in _VECTOR_FORMATS
    is_raster = fmt in _RASTER_FORMATS
    is_sketch_flag = is_sketch or fmt in _SKETCH_FORMATS

    # ===== 步骤 1：收集证据 =====
    ocr_avg_conf, ocr_count = _aggregate_ocr_confidence(ocr_results)
    region_conf, region_source = _extract_region_evidence(region_detection_result)
    id_match_rate, id_total = _extract_identifier_evidence(normalize_result)

    # 图像质量证据（仅在提供 image_path 时采集，避免无谓开销）
    image_resolution: tuple[int, int] | None = None
    image_dpi: int | None = None
    has_skew = False
    skew_angle = 0.0
    if image_path is not None:
        quality = assess_image_quality(Path(image_path))
        image_resolution = quality.get("image_resolution")
        image_dpi = quality.get("image_dpi_estimate")
        has_skew = bool(quality.get("has_skew", False))
        skew_angle = float(quality.get("skew_angle", 0.0))

    evidence = PrecisionEvidence(
        source_format=fmt or "unknown",
        is_vector_source=is_vector,
        is_raster_source=is_raster,
        is_sketch=is_sketch_flag,
        ocr_avg_confidence=ocr_avg_conf,
        ocr_text_count=ocr_count,
        region_detection_confidence=region_conf,
        region_detection_source=region_source,
        identifier_match_rate=id_match_rate,
        identifier_total=id_total,
        image_resolution=image_resolution,
        image_dpi_estimate=image_dpi,
        has_skew=has_skew,
        skew_angle=skew_angle,
    )

    # ===== 步骤 2：按规则分级（保守原则——多证据冲突取较低等级）=====
    level, confidence, rationale, warnings, recommendations = _decide_level(
        evidence=evidence,
        fmt=fmt,
        is_vector=is_vector,
        is_raster=is_raster,
        is_sketch=is_sketch_flag,
        ocr_avg_conf=ocr_avg_conf,
        region_conf=region_conf,
        region_source=region_source,
        id_match_rate=id_match_rate,
        image_resolution=image_resolution,
        image_dpi=image_dpi,
        has_skew=has_skew,
        skew_angle=skew_angle,
    )

    classification = PrecisionClassification(
        level=level,
        confidence=confidence,
        evidence=evidence,
        rationale=rationale,
        warnings=warnings,
        recommendations=recommendations,
        metadata={
            "thresholds": {
                "ocr_high": _TH_OCR_HIGH,
                "ocr_low": _TH_OCR_LOW,
                "id_match_high": _TH_ID_MATCH_HIGH,
                "id_match_low": _TH_ID_MATCH_LOW,
                "region_high": _TH_REGION_HIGH,
                "preferred_region_source": _PREFERRED_REGION_SOURCE,
                "low_resolution_pixels": _TH_LOW_RESOLUTION_PIXELS,
                "low_dpi": _TH_LOW_DPI,
            },
        },
    )

    log.info(
        "precision.classified",
        source_format=fmt,
        level=level.value,
        confidence=confidence,
        ocr_avg_conf=ocr_avg_conf,
        region_conf=region_conf,
        id_match_rate=id_match_rate,
    )
    return classification


def estimate_dpi(image_path: Path) -> int:
    """估算图像 DPI（基于图像尺寸 + 假设 A 系列图纸幅面）。

    策略：
    - 读取图像像素尺寸 (w, h)
    - 对每个 A 系列（A0~A4）假设图像对应此纸张，计算短/长边 DPI
    - 取比例最匹配的纸张（短边 DPI 与长边 DPI 差异最小）的 DPI 均值

    Returns:
        估算的 DPI 整数值；读取失败返回 0
    """
    image_path = Path(image_path)
    w, h = _read_image_size(image_path)
    if w <= 0 or h <= 0:
        return 0

    long_px = max(w, h)
    short_px = min(w, h)

    best_dpi = 0.0
    best_ratio_diff = float("inf")

    for _name, sw_mm, sl_mm in _A_SERIES_MM:
        # 假设图像短边对应纸张短边，长边对应长边
        dpi_short = short_px / (sw_mm / 25.4)
        dpi_long = long_px / (sl_mm / 25.4)
        # 比例失真度：DPI 越接近，说明此纸张假设越合理
        denom = max(dpi_short, dpi_long) or 1.0
        ratio_diff = abs(dpi_short - dpi_long) / denom
        if ratio_diff < best_ratio_diff:
            best_ratio_diff = ratio_diff
            best_dpi = (dpi_short + dpi_long) / 2.0

    return int(best_dpi) if best_dpi > 0 else 0


def assess_image_quality(image_path: Path) -> dict:
    """评估图像质量（分辨率/倾斜/对比度），复用 image_preprocess。

    复用关系（"以复用现有为荣"）：
    - image_preprocess.is_preprocess_available() 检查 OpenCV
    - image_preprocess.load_image() 加载图像
    - image_preprocess.to_gray() 灰度化
    - image_preprocess.deskew() 检测倾斜角

    Returns:
        dict 含：
        - image_resolution: (w, h) 或 None
        - image_dpi_estimate: int 或 None
        - has_skew: bool
        - skew_angle: float（度）
        - contrast_std: float 或 None（灰度标准差，越大对比度越高）
        - error: str（仅在失败时填充）
    """
    result: dict[str, Any] = {
        "image_resolution": None,
        "image_dpi_estimate": None,
        "has_skew": False,
        "skew_angle": 0.0,
        "contrast_std": None,
    }

    image_path = Path(image_path)
    if not image_path.is_file():
        result["error"] = f"图片不存在：{image_path}"
        return result

    # 估算 DPI（不依赖 OpenCV，先用 PIL）
    result["image_dpi_estimate"] = estimate_dpi(image_path)

    try:
        from app.services.review.image_preprocess import (
            deskew,
            is_preprocess_available,
            load_image,
            to_gray,
        )
    except ImportError as e:
        result["error"] = f"image_preprocess 导入失败：{e}"
        return result

    if not is_preprocess_available():
        result["error"] = "OpenCV 不可用，跳过倾斜/对比度检测"
        return result

    try:
        img = load_image(image_path)
        h, w = img.shape[:2]
        result["image_resolution"] = (int(w), int(h))

        gray = to_gray(img)
        _, angle = deskew(gray)
        result["skew_angle"] = float(angle)
        result["has_skew"] = abs(angle) > _TH_SKEW_WARN

        # 对比度：灰度标准差（rendering 图通常 > 50，扫描图通常 > 30）
        try:
            import numpy as np

            result["contrast_std"] = float(np.std(gray))
        except Exception as e:  # noqa: BLE001
            log.debug("precision.contrast_calc_failed", error=str(e))
    except Exception as e:  # noqa: BLE001
        log.warning("precision.assess_quality_failed", path=str(image_path), error=str(e))
        result["error"] = str(e)

    return result


# ============================================================================
# 内部辅助函数
# ============================================================================


def _aggregate_ocr_confidence(
    ocr_results: list[dict] | None,
) -> tuple[float | None, int]:
    """从 ocr_paddle.ocr_extract() 返回结构中聚合平均置信度与条数。

    ocr_paddle.ocr_extract() 返回：
        [{"text": "M8x1.25", "bbox": [...], "confidence": 0.985}, ...]

    Returns:
        (平均置信度, 文字条数)；无 OCR 证据时返回 (None, 0)
    """
    if not ocr_results:
        return None, 0

    confs: list[float] = []
    for item in ocr_results:
        if not isinstance(item, dict):
            continue
        conf = item.get("confidence")
        if conf is None:
            continue
        try:
            confs.append(float(conf))
        except (TypeError, ValueError):
            continue

    if not confs:
        return None, len(ocr_results)

    return statistics.mean(confs), len(confs)


def _extract_region_evidence(
    region_detection_result: dict | None,
) -> tuple[float | None, str | None]:
    """从区域检测结果中提取平均置信度与来源。

    兼容多种键名（"以瞎猜接口为耻"——显式列出所有支持的键）：
    - 置信度：confidence / avg_confidence / mean_confidence / score
    - 来源：source / model / detector
    """
    if not region_detection_result or not isinstance(region_detection_result, dict):
        return None, None

    # 置信度
    conf = (
        region_detection_result.get("confidence")
        or region_detection_result.get("avg_confidence")
        or region_detection_result.get("mean_confidence")
        or region_detection_result.get("score")
    )
    conf_val: float | None = None
    if conf is not None:
        try:
            conf_val = float(conf)
        except (TypeError, ValueError):
            conf_val = None

    # 来源
    source = (
        region_detection_result.get("source")
        or region_detection_result.get("model")
        or region_detection_result.get("detector")
    )
    source_val = str(source).lower() if source else None

    return conf_val, source_val


def _extract_identifier_evidence(
    normalize_result: dict | None,
) -> tuple[float | None, int]:
    """从标识符归一化结果中提取命中率与总数。

    兼容多种键名：
    - 命中率：match_rate / identifier_match_rate / hit_rate / matched_ratio
    - 总数：total / identifier_total / count
    - 也可由 matched/total 计算
    """
    if not normalize_result or not isinstance(normalize_result, dict):
        return None, 0

    # 命中率
    rate = (
        normalize_result.get("match_rate")
        or normalize_result.get("identifier_match_rate")
        or normalize_result.get("hit_rate")
        or normalize_result.get("matched_ratio")
    )
    rate_val: float | None = None
    if rate is not None:
        try:
            rate_val = float(rate)
        except (TypeError, ValueError):
            rate_val = None

    # 总数
    total = (
        normalize_result.get("total")
        or normalize_result.get("identifier_total")
        or normalize_result.get("count")
        or 0
    )
    try:
        total_int = int(total)
    except (TypeError, ValueError):
        total_int = 0

    # 兜底：由 matched / total 反推
    if rate_val is None and total_int > 0:
        matched = normalize_result.get("matched")
        if matched is not None:
            try:
                rate_val = float(matched) / float(total_int)
            except (TypeError, ValueError, ZeroDivisionError):
                pass

    return rate_val, total_int


def _read_image_size(image_path: Path) -> tuple[int, int]:
    """读取图像宽高（优先用 PIL，兜底用 OpenCV）。

    Returns:
        (width, height)；失败返回 (0, 0)
    """
    image_path = Path(image_path)
    try:
        from PIL import Image  # type: ignore[import-not-found]

        with Image.open(image_path) as im:
            return int(im.size[0]), int(im.size[1])
    except Exception:
        pass

    try:
        from app.services.review.image_preprocess import is_preprocess_available, load_image

        if is_preprocess_available():
            img = load_image(image_path)
            h, w = img.shape[:2]
            return int(w), int(h)
    except Exception:
        pass

    return 0, 0


def _decide_level(
    *,
    evidence: PrecisionEvidence,
    fmt: str,
    is_vector: bool,
    is_raster: bool,
    is_sketch: bool,
    ocr_avg_conf: float | None,
    region_conf: float | None,
    region_source: str | None,
    id_match_rate: float | None,
    image_resolution: tuple[int, int] | None,
    image_dpi: int | None,
    has_skew: bool,
    skew_angle: float,
) -> tuple[PrecisionLevel, float, str, list[str], list[str]]:
    """根据证据做最终分级决策（保守原则）。

    Returns:
        (level, confidence, rationale, warnings, recommendations)
    """
    warnings: list[str] = []
    recommendations: list[str] = []

    # ===== 规则 1：草图优先（最高优先级） =====
    if is_sketch:
        rationale = (
            "输入为手绘草图（source_format=sketch 或 is_sketch=True），"
            "依据 spec.md R7 强制降级到草图级，需人工校准尺寸环节。"
        )
        recommendations.append("强制人工校准尺寸环节")
        recommendations.append("建议优先支持标注完整的工程草图而非随手涂鸦")
        if ocr_avg_conf is not None and ocr_avg_conf < _TH_OCR_LOW:
            warnings.append(
                f"OCR 置信度 {ocr_avg_conf:.2f} < {_TH_OCR_LOW}，进一步印证草图质量差"
            )
        return PrecisionLevel.SKETCH_LEVEL, 0.95, rationale, warnings, recommendations

    # ===== 规则 2：低 OCR 置信度直接降至草图级 =====
    if ocr_avg_conf is not None and ocr_avg_conf < _TH_OCR_LOW:
        rationale = (
            f"OCR 平均置信度 {ocr_avg_conf:.2f} < {_TH_OCR_LOW}，"
            "识别结果不可信，降级到草图级，强制人工校准。"
        )
        recommendations.append("重新扫描或提升图像质量后再次审图")
        recommendations.append("强制人工校准尺寸环节")
        # 同时检查图像质量
        if image_resolution is not None:
            total_px = image_resolution[0] * image_resolution[1]
            if total_px < _TH_LOW_RESOLUTION_PIXELS:
                warnings.append(
                    f"图像分辨率 {image_resolution[0]}x{image_resolution[1]} "
                    f"低于 {_TH_LOW_RESOLUTION_PIXELS} 像素"
                )
        if image_dpi is not None and image_dpi < _TH_LOW_DPI:
            warnings.append(f"估算 DPI {image_dpi} < {_TH_LOW_DPI}，扫描质量差")
        return PrecisionLevel.SKETCH_LEVEL, 0.85, rationale, warnings, recommendations

    # ===== 规则 3：矢量源直接判矢量级 =====
    if is_vector:
        # 矢量源本身就最高可信度，OCR/region 等仅作参考
        confidence = 0.95
        rationale = (
            f"输入为矢量源（{fmt}），CAD 矢量数据完整可信，"
            "判定为矢量级。"
        )
        # 但如果矢量源同时提供了低质量 OCR 证据（罕见，但保守原则）
        if (
            ocr_avg_conf is not None
            and _TH_OCR_LOW <= ocr_avg_conf < _TH_OCR_HIGH
        ):
            warnings.append(
                f"矢量源附带的 OCR 置信度 {ocr_avg_conf:.2f} 偏低，"
                "建议复核 OCR 模块工作状态"
            )
        return PrecisionLevel.VECTOR_LEVEL, confidence, rationale, warnings, recommendations

    # ===== 规则 4：光栅源——综合 OCR/区域/标识符证据判定 =====
    if is_raster or fmt in ("", "unknown"):
        # 收集"提升至矢量级"的证据
        promote_to_vector = False
        promote_reasons: list[str] = []

        if (
            ocr_avg_conf is not None
            and ocr_avg_conf >= _TH_OCR_HIGH
            and id_match_rate is not None
            and id_match_rate >= _TH_ID_MATCH_HIGH
        ):
            promote_to_vector = True
            promote_reasons.append(
                f"OCR 置信度 {ocr_avg_conf:.2f} ≥ {_TH_OCR_HIGH} "
                f"且标识符命中率 {id_match_rate:.2f} ≥ {_TH_ID_MATCH_HIGH}"
            )

        if (
            region_conf is not None
            and region_conf >= _TH_REGION_HIGH
            and region_source == _PREFERRED_REGION_SOURCE
        ):
            promote_to_vector = True
            promote_reasons.append(
                f"区域检测来源 {region_source} 且置信度 {region_conf:.2f} ≥ {_TH_REGION_HIGH}"
            )

        # 草图级降级证据
        demote_to_sketch = False
        if (
            ocr_avg_conf is not None
            and ocr_avg_conf < _TH_OCR_LOW
        ):
            demote_to_sketch = True
            warnings.append(
                f"OCR 置信度 {ocr_avg_conf:.2f} < {_TH_OCR_LOW}"
            )
        if (
            id_match_rate is not None
            and id_match_rate < _TH_ID_MATCH_LOW
            and id_match_rate > 0
        ):
            # 标识符命中率极低（但 > 0 表示有归一化结果），作为辅助证据
            warnings.append(
                f"标识符命中率 {id_match_rate:.2f} < {_TH_ID_MATCH_LOW}"
            )

        # 图像质量警告
        if image_resolution is not None:
            total_px = image_resolution[0] * image_resolution[1]
            if total_px < _TH_LOW_RESOLUTION_PIXELS:
                warnings.append(
                    f"图像分辨率 {image_resolution[0]}x{image_resolution[1]} 像素总数 "
                    f"{total_px} < {_TH_LOW_RESOLUTION_PIXELS}，质量偏低"
                )
        if image_dpi is not None and image_dpi < _TH_LOW_DPI:
            warnings.append(f"估算 DPI {image_dpi} < {_TH_LOW_DPI}")
        if has_skew:
            warnings.append(f"检测到倾斜角 {skew_angle:.2f}°，可能影响 OCR 精度")

        # 决策（保守原则：降级优先）
        if demote_to_sketch:
            rationale = (
                f"光栅源（{fmt}）OCR 置信度过低，"
                "降级到草图级，强制人工校准。"
            )
            recommendations.append("重新扫描或提升图像质量")
            recommendations.append("强制人工校准尺寸环节")
            return PrecisionLevel.SKETCH_LEVEL, 0.80, rationale, warnings, recommendations

        if promote_to_vector:
            rationale = (
                f"光栅源（{fmt}）但满足提升条件："
                + "；".join(promote_reasons)
                + "。提升至矢量级，但建议保留人工复核环节。"
            )
            recommendations.append("虽然是矢量级精度，仍建议对关键尺寸做人工抽检")
            # confidence 较纯矢量源低
            return (
                PrecisionLevel.VECTOR_LEVEL,
                0.80,
                rationale,
                warnings,
                recommendations,
            )

        # 默认光栅源 → 参考级
        # 证据不足时（如无 OCR/region/id 证据），实事求是降级
        evidence_count = sum(
            1 for v in (ocr_avg_conf, region_conf, id_match_rate) if v is not None
        )
        if evidence_count == 0:
            rationale = (
                f"光栅源（{fmt or 'unknown'}）缺少 OCR/区域检测/标识符归一化证据，"
                "按保守原则降级到参考级，建议人工复核。"
            )
            warnings.append("缺少 OCR 证据")
            warnings.append("缺少区域检测证据")
            warnings.append("缺少标识符归一化证据")
            confidence = 0.50  # 证据不足，置信度低
        else:
            # 有证据但未达提升/降级阈值
            parts: list[str] = []
            if ocr_avg_conf is not None:
                parts.append(f"OCR 置信度 {ocr_avg_conf:.2f}")
            if id_match_rate is not None:
                parts.append(f"标识符命中率 {id_match_rate:.2f}")
            if region_conf is not None:
                parts.append(f"区域检测置信度 {region_conf:.2f}")
            rationale = (
                f"光栅源（{fmt}）证据未达矢量级提升阈值（"
                + "，".join(parts)
                + "），判定为参考级，建议人工复核。"
            )
            confidence = 0.75

        recommendations.append("建议人工复核尺寸标注")
        recommendations.append("建议人工复核标题栏与材料牌号")
        return (
            PrecisionLevel.REFERENCE_LEVEL,
            confidence,
            rationale,
            warnings,
            recommendations,
        )

    # ===== 兜底：未知格式，保守降级到参考级 =====
    rationale = (
        f"未知源格式 {fmt!r}，按保守原则判定为参考级。"
    )
    warnings.append(f"未知源格式：{fmt}")
    recommendations.append("建议人工复核所有审图结论")
    return PrecisionLevel.REFERENCE_LEVEL, 0.40, rationale, warnings, recommendations


# ============================================================================
# 自检（"以覆盖测试为荣"——覆盖 6 个典型场景）
# ============================================================================


def self_test() -> dict:
    """精度分级模块自检：覆盖 6 个典型场景。

    Returns:
        {"scenarios": [...], "all_passed": bool}
    """
    scenarios: list[dict[str, Any]] = []

    # ----- 场景 1：DXF 矢量源 → VECTOR_LEVEL -----
    result1 = classify_precision(
        source_format="dxf",
        ocr_results=None,
        region_detection_result=None,
        normalize_result=None,
        image_path=None,
        is_sketch=False,
    )
    scenarios.append({
        "name": "场景1: DXF 矢量源 → VECTOR_LEVEL",
        "result": result1,
        "expected": PrecisionLevel.VECTOR_LEVEL,
        "passed": result1.level == PrecisionLevel.VECTOR_LEVEL,
    })

    # ----- 场景 2：PDF 光栅源 + 高 OCR 置信度 → VECTOR_LEVEL（提升） -----
    high_conf_ocr = [
        {"text": "M8x1.25", "bbox": [0, 0, 10, 10], "confidence": 0.92},
        {"text": "Ø20", "bbox": [0, 0, 10, 10], "confidence": 0.88},
        {"text": "GB/T 4457.4", "bbox": [0, 0, 10, 10], "confidence": 0.95},
    ]
    result2 = classify_precision(
        source_format="pdf",
        ocr_results=high_conf_ocr,
        region_detection_result={"confidence": 0.6, "source": "vlm"},
        normalize_result={"match_rate": 0.8, "total": 10, "matched": 8},
        image_path=None,
        is_sketch=False,
    )
    scenarios.append({
        "name": "场景2: PDF + 高 OCR 置信度 → VECTOR_LEVEL（提升）",
        "result": result2,
        "expected": PrecisionLevel.VECTOR_LEVEL,
        "passed": result2.level == PrecisionLevel.VECTOR_LEVEL,
    })

    # ----- 场景 3：PNG 光栅源 + 中等 OCR 置信度 → REFERENCE_LEVEL -----
    mid_conf_ocr = [
        {"text": "M8", "bbox": [0, 0, 10, 10], "confidence": 0.65},
        {"text": "Ø20", "bbox": [0, 0, 10, 10], "confidence": 0.62},
    ]
    result3 = classify_precision(
        source_format="png",
        ocr_results=mid_conf_ocr,
        region_detection_result={"confidence": 0.5, "source": "vlm"},
        normalize_result={"match_rate": 0.5, "total": 8, "matched": 4},
        image_path=None,
        is_sketch=False,
    )
    scenarios.append({
        "name": "场景3: PNG + 中等 OCR 置信度 → REFERENCE_LEVEL",
        "result": result3,
        "expected": PrecisionLevel.REFERENCE_LEVEL,
        "passed": result3.level == PrecisionLevel.REFERENCE_LEVEL,
    })

    # ----- 场景 4：手绘草图 → SKETCH_LEVEL -----
    result4 = classify_precision(
        source_format="sketch",
        ocr_results=None,
        region_detection_result=None,
        normalize_result=None,
        image_path=None,
        is_sketch=True,
    )
    scenarios.append({
        "name": "场景4: 手绘草图 → SKETCH_LEVEL",
        "result": result4,
        "expected": PrecisionLevel.SKETCH_LEVEL,
        "passed": result4.level == PrecisionLevel.SKETCH_LEVEL,
    })

    # ----- 场景 5：低质量图像（低分辨率 + 低置信度）→ SKETCH_LEVEL -----
    low_conf_ocr = [
        {"text": "?", "bbox": [0, 0, 10, 10], "confidence": 0.30},
        {"text": "?", "bbox": [0, 0, 10, 10], "confidence": 0.25},
    ]
    result5 = classify_precision(
        source_format="png",
        ocr_results=low_conf_ocr,
        region_detection_result=None,
        normalize_result=None,
        image_path=None,
        is_sketch=False,
    )
    scenarios.append({
        "name": "场景5: 低质量图像 + 低 OCR 置信度 → SKETCH_LEVEL",
        "result": result5,
        "expected": PrecisionLevel.SKETCH_LEVEL,
        "passed": result5.level == PrecisionLevel.SKETCH_LEVEL,
    })

    # ----- 场景 6：证据不足场景 → 默认 REFERENCE_LEVEL（保守） -----
    result6 = classify_precision(
        source_format="png",
        ocr_results=None,
        region_detection_result=None,
        normalize_result=None,
        image_path=None,
        is_sketch=False,
    )
    scenarios.append({
        "name": "场景6: 证据不足 → 默认 REFERENCE_LEVEL（保守）",
        "result": result6,
        "expected": PrecisionLevel.REFERENCE_LEVEL,
        "passed": (
            result6.level == PrecisionLevel.REFERENCE_LEVEL
            and result6.confidence <= 0.6  # 证据不足时置信度应较低
        ),
    })

    all_passed = all(s["passed"] for s in scenarios)
    return {"scenarios": scenarios, "all_passed": all_passed}


# ============================================================================
# 命令行入口
# ============================================================================


if __name__ == "__main__":
    import sys

    print("=" * 70)
    print("精度分级模块自检（Task 9.6）")
    print("=" * 70)
    print(f"阈值常量（便于审计）：")
    print(f"  _TH_OCR_HIGH               = {_TH_OCR_HIGH}")
    print(f"  _TH_OCR_LOW                = {_TH_OCR_LOW}")
    print(f"  _TH_ID_MATCH_HIGH          = {_TH_ID_MATCH_HIGH}")
    print(f"  _TH_ID_MATCH_LOW           = {_TH_ID_MATCH_LOW}")
    print(f"  _TH_REGION_HIGH            = {_TH_REGION_HIGH}")
    print(f"  _PREFERRED_REGION_SOURCE   = {_PREFERRED_REGION_SOURCE}")
    print(f"  _TH_SKEW_WARN              = {_TH_SKEW_WARN}")
    print(f"  _TH_LOW_RESOLUTION_PIXELS  = {_TH_LOW_RESOLUTION_PIXELS}")
    print(f"  _TH_LOW_DPI                = {_TH_LOW_DPI}")
    print(f"  _VECTOR_FORMATS            = {sorted(_VECTOR_FORMATS)}")
    print(f"  _RASTER_FORMATS            = {sorted(_RASTER_FORMATS)}")
    print(f"  _SKETCH_FORMATS            = {sorted(_SKETCH_FORMATS)}")
    print()

    report = self_test()

    for sc in report["scenarios"]:
        mark = "[PASS]" if sc["passed"] else "[FAIL]"
        print(f"{mark} {sc['name']}")
        r = sc["result"]
        print(f"  level        = {r.level.value}")
        print(f"  confidence   = {r.confidence:.2f}")
        print(f"  rationale    = {r.rationale}")
        if r.warnings:
            print(f"  warnings     =")
            for w in r.warnings:
                print(f"    - {w}")
        if r.recommendations:
            print(f"  recommendations =")
            for rec in r.recommendations:
                print(f"    - {rec}")
        # 证据摘要
        ev = r.evidence
        print(f"  evidence     = source={ev.source_format} vector={ev.is_vector_source} "
              f"raster={ev.is_raster_source} sketch={ev.is_sketch}")
        print(f"                 ocr_avg={ev.ocr_avg_confidence} count={ev.ocr_text_count}")
        print(f"                 region={ev.region_detection_confidence} ({ev.region_detection_source})")
        print(f"                 id_match={ev.identifier_match_rate} total={ev.identifier_total}")
        print(f"                 resolution={ev.image_resolution} dpi={ev.image_dpi_estimate} "
              f"skew={ev.skew_angle:.2f}°")
        print()

    print("=" * 70)
    if report["all_passed"]:
        print("全部 6 个场景通过 ✅")
        sys.exit(0)
    else:
        failed = [s["name"] for s in report["scenarios"] if not s["passed"]]
        print(f"失败场景：{failed}")
        sys.exit(1)
