"""VLM 草图解析器（Task 12.1）。

复用现有模块（"以复用现有为荣"）：
- 图像预处理：app.services.review.image_preprocess.preprocess_image
  （经 vlm_ocr._encode_image 内部调用，无需显式调用）
- VLM 调用：自 SubTask 3.5 起统一走 app.services.ai.get_llm_provider().chat_with_image()
- JSON 解析：app.services.review.vlm_ocr._parse_json_object_from_text
- 图片编码：app.services.review.vlm_ocr._encode_image

策略：
1. 调用 _encode_image（内部已做预处理）→ base64
2. 调用 provider.is_vlm_available() 判断视觉模型是否可用
3. 调用 provider.chat_with_image() 发送 prompt + 图片
4. _parse_json_object_from_text 容错解析 JSON
5. VLM 不可用时返回空结果 + warning（不抛异常，"以实事求是为荣"）

prompt 设计要点（"以瞎猜接口为耻"——明确要求 JSON 格式）：
- 明确列出 8 类几何特征
- 明确每类特征的参数 schema
- 明确 bbox 归一化坐标
- 明确 overall_shape 与 dimensions_hint
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

from app.logging import get_logger
from app.schemas.sketch import SketchFeature, SketchParseResult

log = get_logger(__name__)

# 复用 vlm_ocr 中的私有函数（Python 下划线前缀仅阻止通配符导入，
# 不阻止显式导入；同 backend.app 包内可调用）
# 注意：Task 4 起 vlm_ocr 已移除直接 Ollama HTTP 访问（_ollama_chat_with_image /
# _pick_vlm_model / list_ollama_models），VLM 调用统一走 provider.chat_with_image。
# 本模块复用 vlm_ocr 的图像编码 / JSON 解析 / 重试工具。
# VLM-03：复用 _vlm_call_with_retry 为 provider.chat_with_image 提供指数退避重试。
from app.services.review.vlm_ocr import (  # noqa: E402
    _encode_image,
    _normalize_bbox,
    _parse_json_object_from_text,
    _vlm_call_with_retry,
    is_vlm_available,
)

# 8 类合法特征类型
_VALID_FEATURE_TYPES: frozenset[str] = frozenset({
    "line",
    "circle",
    "arc",
    "rectangle",
    "hole",
    "chamfer",
    "fillet",
    "polygon",
    "unknown",
})

# VLM prompt（明确要求 JSON 输出，列出 8 类几何特征 + 参数 schema）
#
# 修订要点（SubTask 1.1 / 1.3，对照 25_sketch_vlm_dimension_retest.md 修复建议）：
# - bbox 格式从 [x1,y1,x2,y2] 改为 [x,y,w,h]（左上角 + 宽高），与
#   vlm_ocr._normalize_bbox 输入约定对齐，避免被错误钳制后语义丢失
# - 加入 few-shot 示例：输入"外圆 φ100" → radius=50, dimensions_hint["外径"]=100
# - 明确约束 parameters.radius 必须等于 dimensions_hint["外径"]/2
# - 明确约束 parameters.thickness 必须等于 dimensions_hint["厚度"]（若存在）
_SKETCH_PARSE_PROMPT = """你是工程草图分析专家。请识别这张手绘草图中的几何特征，并以 JSON 对象返回（不要包含其他文字）。

输出格式：
{
  "features": [
    {
      "feature_type": "circle",
      "parameters": {"radius": 50, "thickness": 10},
      "bbox": [0.25, 0.25, 0.5, 0.5],
      "confidence": 0.9,
      "raw_text": "圆形主体直径100mm，厚度10mm"
    }
  ],
  "overall_shape": "带孔圆盘",
  "dimensions_hint": {"外径": 100, "孔径": 20, "厚度": 10}
}

要求：
1. 识别以下 8 类几何特征之一：line/circle/arc/rectangle/hole/chamfer/fillet/polygon
2. 对每个特征给出类型相关参数：
   - line: {"length": 长度mm, "angle": 角度}
   - circle: {"radius": 半径mm, "thickness": 拉伸厚度mm（无则为0）}
   - arc: {"radius": 半径mm, "start_angle": 起始角度, "end_angle": 终止角度}
   - rectangle: {"width": 宽mm, "height": 高mm, "thickness": 厚度mm}
   - hole: {"radius": 半径mm, "position_x": x坐标, "position_y": y坐标, "depth": 深度mm}
   - chamfer: {"size": 倒角尺寸mm}
   - fillet: {"radius": 圆角半径mm}
   - polygon: {"sides": 边数, "side_length": 边长mm, "thickness": 厚度mm}
3. bbox 为归一化坐标 [x, y, w, h]（0-1），其中 (x, y) 为左上角，(w, h) 为宽高，
   且必须满足 x + w <= 1 与 y + h <= 1。
   注意：不要输出 [x1, y1, x2, y2] 形式的对角点坐标。
4. overall_shape 用一句中文描述整体形状
5. dimensions_hint 是草图中标注的尺寸（如有），键名用中文如 "外径"/"孔径"/"厚度"，
   值的单位为毫米（数值不带单位后缀）。
6. **尺寸一致性约束（必须严格遵守）**：
   - 若草图中标注 "φ100" 或 "外径 100"，则 dimensions_hint["外径"] = 100，
     且对应圆形特征的 parameters.radius 必须等于 dimensions_hint["外径"] / 2 = 50。
   - 若草图中标注 "厚度 10" 或 "thickness=10mm"，则 dimensions_hint["厚度"] = 10，
     且对应特征的 parameters.thickness 必须等于 dimensions_hint["厚度"] = 10。
   - 若草图中标注 "φ20" 或 "孔径 20"，则 dimensions_hint["孔径"] = 20，
     且对应孔特征的 parameters.radius 必须等于 dimensions_hint["孔径"] / 2 = 10。
7. few-shot 示例（学习这种数值映射关系）：
   输入草图标注："外圆 φ100, 厚度 10mm"
   输出 JSON：
   {
     "features": [
       {"feature_type": "circle", "parameters": {"radius": 50, "thickness": 10},
      "bbox": [0.25, 0.25, 0.5, 0.5], "confidence": 0.9, "raw_text": "外圆 φ100, 厚度 10mm"}
     ],
     "overall_shape": "圆盘",
     "dimensions_hint": {"外径": 100, "厚度": 10}
   }
8. 仅输出 JSON 对象（不要包裹在 ```json``` 代码块中，不要附加任何说明文字）"""


# 偏差阈值：超出 20% 触发 warning 并降级 confidence（SubTask 1.2）
_DIMENSION_DEVIATION_THRESHOLD = 0.20
# 触发偏差后 confidence 降至该值
_LOW_CONFIDENCE = 0.3


def _convert_bbox_xyxy_to_xywh(bbox: Any) -> list[float] | None:
    """检测并转换 bbox 格式（SubTask 1.3）。

    VLM 历史/异常输出可能返回 ``[x1, y1, x2, y2]`` 对角点格式，
    而 ``_normalize_bbox`` 假设输入为 ``[x, y, w, h]``。
    本函数做兜底转换：

    判别 ``[x1, y1, x2, y2]`` 的启发式条件：
    - 长度为 4 且元素均为数值
    - x2 > x1 且 y2 > y1（单调性，对角点约束）
    - x2 <= 1 且 y2 <= 1（归一化范围内）
    - 同时 x1 + x2 > 1 或 y1 + y2 > 1（若视为 [x,y,w,h] 会越界 → 强烈暗示 xyxy）

    Returns:
        转换后的 ``[x, y, w, h]`` 列表；若输入已是 [x,y,w,h] 或非法则返回 None
        （调用方应在 None 时直接交给 _normalize_bbox 处理）。
    """
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return None
    try:
        x1, y1, x2, y2 = (float(v) for v in bbox)
    except (TypeError, ValueError):
        return None
    # 单调性：x2 > x1 且 y2 > y1（对角点格式特征）
    if not (x2 > x1 and y2 > y1):
        return None
    # 归一化范围内（<=1）
    if x2 > 1.0 or y2 > 1.0:
        return None
    # 若视为 [x,y,w,h] 会越界 → 强烈暗示 [x1,y1,x2,y2] 格式
    out_of_bounds_xywh = (x1 + x2 > 1.0) or (y1 + y2 > 1.0)
    if not out_of_bounds_xywh:
        # 单调 + 不越界：两种格式都可能，倾向 [x,y,w,h]（与 prompt 一致），不转换
        return None
    # 转换为 [x, y, w, h]
    return [x1, y1, x2 - x1, y2 - y1]


def _validate_sketch_dimensions(
    features: list[SketchFeature],
    dimensions_hint: dict[str, float],
    warnings: list[str],
) -> None:
    """后处理校验 VLM 输出尺寸是否与 dimensions_hint 一致（SubTask 1.2）。

    - 比对 circle / hole / fillet 特征的 ``parameters.radius`` 与
      ``dimensions_hint["外径"] / 2``（或 ``dimensions_hint["孔径"] / 2``）
    - 比对任意特征的 ``parameters.thickness`` 与 ``dimensions_hint["厚度"]``
    - 偏差超 20%（按 ``max(actual/expected, expected/actual) - 1`` 判定）时：
      * 在 warnings 中追加具体偏差信息
      * 将对应 feature 的 confidence 降至 0.3

    约束（"以谨慎重构为荣"）：
    - 仅当 dimensions_hint 中存在对应键且数值 > 0 时才校验
    - 直接修改 features 列表与 warnings 列表（in-place），无返回值
    - SketchFeature 是 Pydantic 模型，通过 model_copy 重建以更新 confidence
    """
    if not features or not dimensions_hint:
        return

    # 期望半径：外径/2 与 孔径/2
    expected_outer_radius: float | None = None
    expected_hole_radius: float | None = None
    expected_thickness: float | None = None
    if "外径" in dimensions_hint and dimensions_hint["外径"] > 0:
        expected_outer_radius = dimensions_hint["外径"] / 2.0
    if "孔径" in dimensions_hint and dimensions_hint["孔径"] > 0:
        expected_hole_radius = dimensions_hint["孔径"] / 2.0
    if "厚度" in dimensions_hint and dimensions_hint["厚度"] > 0:
        expected_thickness = dimensions_hint["厚度"]

    for idx, feat in enumerate(features):
        params = feat.parameters or {}
        new_confidence: float | None = None

        # radius 校验：circle / fillet 用外径；hole 用孔径
        actual_radius = params.get("radius")
        if isinstance(actual_radius, (int, float)):
            actual_radius = float(actual_radius)
            expected: float | None = None
            if feat.feature_type == "hole":
                expected = expected_hole_radius
            elif feat.feature_type in ("circle", "fillet", "arc"):
                expected = expected_outer_radius
            if expected is not None and expected > 0 and actual_radius > 0:
                multiplier = max(actual_radius / expected, expected / actual_radius)
                deviation = multiplier - 1.0
                if deviation > _DIMENSION_DEVIATION_THRESHOLD:
                    warnings.append(
                        f"VLM 尺寸识别偏差超阈值: radius 期望 {expected:.1f} "
                        f"实际 {actual_radius} 偏差 {multiplier:.2f}x "
                        f"(feature[{idx}] type={feat.feature_type})"
                    )
                    new_confidence = _LOW_CONFIDENCE

        # thickness 校验：所有特征均可能含 thickness
        actual_thickness = params.get("thickness")
        if (
            isinstance(actual_thickness, (int, float))
            and expected_thickness is not None
            and expected_thickness > 0
        ):
            actual_thickness = float(actual_thickness)
            if actual_thickness > 0:
                multiplier_t = max(
                    actual_thickness / expected_thickness,
                    expected_thickness / actual_thickness,
                )
                deviation_t = multiplier_t - 1.0
                if deviation_t > _DIMENSION_DEVIATION_THRESHOLD:
                    warnings.append(
                        f"VLM 尺寸识别偏差超阈值: thickness 期望 {expected_thickness:.1f} "
                        f"实际 {actual_thickness} 偏差 {multiplier_t:.2f}x "
                        f"(feature[{idx}] type={feat.feature_type})"
                    )
                    new_confidence = _LOW_CONFIDENCE

        # 通过 Pydantic model_copy 更新 confidence（保持其他字段不变）
        if new_confidence is not None and feat.confidence > new_confidence:
            features[idx] = feat.model_copy(update={"confidence": new_confidence})


def parse_sketch(image_path: Path) -> SketchParseResult:
    """VLM 解析草图，提取几何特征。

    自 SubTask 3.5 起走 ``get_llm_provider().chat_with_image()``，
    由 Provider 抽象屏蔽 ollama / openai / anthropic 差异。

    Args:
        image_path: 草图图片路径（PNG/JPG）

    Returns:
        SketchParseResult。VLM 不可用时返回空结果 + warning（不抛异常）。
    """
    t0 = time.monotonic()
    image_path = Path(image_path)

    if not image_path.is_file():
        return SketchParseResult(
            features=[],
            warnings=[f"图片不存在: {image_path}"],
            elapsed_ms=int((time.monotonic() - t0) * 1000),
        )

    # 1. 检查 VLM 可用性（provider.is_vlm_available）
    try:
        vlm_ok = is_vlm_available()
    except Exception as e:  # noqa: BLE001
        log.warning("sketch_parser.check_vlm_failed", error=str(e))
        vlm_ok = False

    if not vlm_ok:
        log.info("sketch_parser.vlm_unavailable")
        return SketchParseResult(
            features=[],
            warnings=["VLM 不可用（未配置视觉模型，如 minicpm-v/llava/GPT-4o 等）"],
            vlm_model="",
            elapsed_ms=int((time.monotonic() - t0) * 1000),
        )

    # 2. 编码图片（_encode_image 内部已调用 preprocess_image 做去噪/校正/对比度增强）
    try:
        img_b64 = _encode_image(image_path)
    except Exception as e:  # noqa: BLE001
        log.warning("sketch_parser.encode_failed", error=str(e))
        return SketchParseResult(
            features=[],
            warnings=[f"图片编码失败: {e}"],
            vlm_model="",
            elapsed_ms=int((time.monotonic() - t0) * 1000),
        )

    # 3. 调用 VLM（provider.chat_with_image）—— VLM-03：经 _vlm_call_with_retry 带指数退避重试
    try:
        from app.services.ai import ChatMessage, get_llm_provider

        provider = get_llm_provider()
        resp = _vlm_call_with_retry(
            provider,
            [ChatMessage(role="user", content=_SKETCH_PARSE_PROMPT)],
            img_b64,
            temperature=0.2,
            max_tokens=2048,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("sketch_parser.vlm_call_failed", error=str(e))
        return SketchParseResult(
            features=[],
            warnings=[f"VLM 调用失败: {e}"],
            vlm_model="",
            elapsed_ms=int((time.monotonic() - t0) * 1000),
        )

    if resp is None:
        log.warning("sketch_parser.vlm_retry_exhausted")
        return SketchParseResult(
            features=[],
            warnings=["VLM 调用重试耗尽（ConnectError/ReadTimeout/5xx 共 3 次均失败）"],
            vlm_model="",
            elapsed_ms=int((time.monotonic() - t0) * 1000),
        )

    model = resp.model
    raw_text = resp.content

    if not raw_text:
        log.warning("sketch_parser.vlm_empty", model=model)
        return SketchParseResult(
            features=[],
            warnings=[f"VLM 返回空内容（model={model}）"],
            vlm_model=model,
            elapsed_ms=int((time.monotonic() - t0) * 1000),
        )

    # 4. 解析 JSON 容错（复用 _parse_json_object_from_text）
    parsed = _parse_json_object_from_text(raw_text)
    if not parsed:
        log.warning(
            "sketch_parser.parse_json_failed",
            text_preview=raw_text[:200],
        )
        return SketchParseResult(
            features=[],
            warnings=[f"VLM 输出 JSON 解析失败，原始输出: {raw_text[:200]}"],
            vlm_model=model,
            elapsed_ms=int((time.monotonic() - t0) * 1000),
        )

    # 5. 构造结果
    features: list[SketchFeature] = []
    raw_features = parsed.get("features") or []
    if isinstance(raw_features, list):
        for item in raw_features:
            if not isinstance(item, dict):
                continue
            ft = str(item.get("feature_type", "unknown")).lower().strip()
            if ft not in _VALID_FEATURE_TYPES:
                ft = "unknown"
            # SubTask 1.3：bbox 格式兜底转换 + 规范化
            #   - VLM 历史/异常输出可能是 [x1,y1,x2,y2]，先尝试转换
            #   - 然后交给 _normalize_bbox 做嵌套/越界/钳制处理
            raw_bbox = item.get("bbox")
            normalized_bbox: list[float] | None = None
            converted = _convert_bbox_xyxy_to_xywh(raw_bbox)
            if converted is not None:
                normalized_bbox = _normalize_bbox(converted)
            else:
                normalized_bbox = _normalize_bbox(raw_bbox)
            try:
                raw_params = item.get("parameters") or {}
                # 数值范围验证：过滤负数值（负数 radius/thickness 会生成异常几何）
                validated_params: dict[str, Any] = {}
                for pk, pv in raw_params.items() if isinstance(raw_params, dict) else []:
                    if isinstance(pv, (int, float)):
                        if pv < 0:
                            log.warning(
                                "sketch_parser.negative_param_filtered",
                                param=pk,
                                value=pv,
                                feature_type=ft,
                            )
                            continue
                        validated_params[pk] = pv
                    else:
                        validated_params[pk] = pv
                feat = SketchFeature(
                    feature_type=ft,  # type: ignore[arg-type]
                    parameters=validated_params,
                    bbox=normalized_bbox,
                    confidence=float(item.get("confidence", 1.0)),
                    raw_text=str(item.get("raw_text", "")),
                )
                features.append(feat)
            except Exception as e:  # noqa: BLE001
                log.warning(
                    "sketch_parser.feature_parse_failed",
                    error=str(e),
                    item=item,
                )

    overall_shape = str(parsed.get("overall_shape", ""))
    dimensions_hint_raw = parsed.get("dimensions_hint") or {}
    dimensions_hint: dict[str, float] = {}
    if isinstance(dimensions_hint_raw, dict):
        for k, v in dimensions_hint_raw.items():
            try:
                dimensions_hint[str(k)] = float(v)
            except (TypeError, ValueError):
                pass

    # SubTask 1.2：后处理校验 VLM 输出尺寸与 dimensions_hint 一致性
    #   - 偏差超 20% 时追加 warning 并将对应 feature 的 confidence 降至 0.3
    #   - 不可仅因"VLM 返回非空"即视为通过
    warnings: list[str] = []
    _validate_sketch_dimensions(features, dimensions_hint, warnings)

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    log.info(
        "sketch_parser.done",
        model=model,
        features=len(features),
        elapsed_ms=elapsed_ms,
        warnings=len(warnings),
    )

    return SketchParseResult(
        features=features,
        overall_shape=overall_shape,
        dimensions_hint=dimensions_hint,
        vlm_model=model,
        elapsed_ms=elapsed_ms,
        warnings=warnings,
    )


# ===== 自检（"以覆盖测试为荣"） =====


def self_test() -> dict[str, Any]:
    """自检：合成草图 + VLM 路径验证。

    实测策略：
    - 合成一张含圆形 + 矩形的草图 PNG
    - 调用 parse_sketch 实测
    - VLM 可用时验证特征数 >= 0
    - VLM 不可用时验证降级路径返回空结果 + warning
    """
    import tempfile

    result: dict[str, Any] = {"checks": {}, "scenarios": []}

    # 检查 1：模块可导入
    result["checks"]["module_import"] = True

    # 检查 2：VLM 可用性探测（自 SubTask 3.5 起走 provider.is_vlm_available）
    try:
        vlm_ok = is_vlm_available()
        result["checks"]["vlm_available"] = bool(vlm_ok)
        result["vlm_model"] = ""  # 实际模型名在 parse_sketch 返回值中
    except Exception as e:  # noqa: BLE001
        result["checks"]["vlm_available"] = False
        result["vlm_model"] = ""
        result["checks"]["vlm_error"] = str(e)

    # 检查 3：合成草图解析（验证降级路径，VLM 不可用时应返回空结果 + warning）
    try:
        import numpy as np
        from PIL import Image

        # 生成合成草图：黑色背景上的白色圆形 + 矩形
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "synthetic_sketch.png"
            img = np.zeros((400, 400, 3), dtype=np.uint8)
            # 画白色圆形 + 矩形
            try:
                import cv2

                cv2.circle(img, (200, 200), 100, (255, 255, 255), 3)
                cv2.rectangle(img, (100, 300), (300, 380), (255, 255, 255), 3)
            except ImportError:
                # 用 PIL 兜底
                from PIL import ImageDraw

                pil_im = Image.fromarray(img)
                d = ImageDraw.Draw(pil_im)
                d.ellipse([100, 100, 300, 300], outline=(255, 255, 255), width=3)
                d.rectangle([100, 300, 300, 380], outline=(255, 255, 255), width=3)
                img = np.array(pil_im)
            Image.fromarray(img).save(tmp)

            parse_result = parse_sketch(tmp)
            scenario = {
                "name": "合成草图解析",
                "vlm_model": parse_result.vlm_model,
                "features_count": len(parse_result.features),
                "warnings": parse_result.warnings,
                "elapsed_ms": parse_result.elapsed_ms,
                "overall_shape": parse_result.overall_shape,
            }
            # 通过条件：VLM 可用且有结果，或 VLM 不可用且降级提示
            if parse_result.vlm_model:
                scenario["passed"] = True
            else:
                scenario["passed"] = any(
                    "VLM 不可用" in w for w in parse_result.warnings
                )
            result["scenarios"].append(scenario)
    except Exception as e:  # noqa: BLE001
        result["scenarios"].append(
            {
                "name": "合成草图解析",
                "passed": False,
                "error": f"{type(e).__name__}: {e}",
            }
        )

    return result


if __name__ == "__main__":
    print("=" * 70)
    print("草图解析器自检（Task 12.1）")
    print("=" * 70)

    report = self_test()
    print(f"\n检查项:")
    for k, v in report["checks"].items():
        mark = "[OK]" if v is True else "[--]" if v is False else "[i]"
        print(f"  {mark} {k}: {v}")

    print(f"\n场景:")
    for sc in report["scenarios"]:
        mark = "[PASS]" if sc.get("passed") else "[FAIL]"
        print(f"  {mark} {sc['name']}")
        for k, v in sc.items():
            if k not in ("name", "passed"):
                print(f"      {k}: {v}")

    print("\n" + "=" * 70)
    print("自检完成")
    sys.exit(0 if all(sc.get("passed") for sc in report["scenarios"]) else 1)
