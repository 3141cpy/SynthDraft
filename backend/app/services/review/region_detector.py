"""YOLOv11 工程图区域检测模块（Task 9.3）。

替代 P0 阶段纯 VLM 区域检测路径，提供：
- 高精度区域定位（YOLOv11，比 VLM 坐标更精确、更快）
- 7 类工程图区域：标题栏/标注区/视图区/明细栏/修订栏/技术要求/其他
- 三级降级：YOLOv11 → VLM（vlm_ocr.vlm_detect_regions）→ 空列表

设计原则（八荣八耻）：
- 以复用现有为荣：复用 vlm_ocr.vlm_detect_regions() / image_preprocess.load_image()
- 以瞎猜接口为耻：ultralytics API 调用经官方文档核实
  （https://docs.ultralytics.com/zh/modes/predict/）
    from ultralytics import YOLO
    model = YOLO("yolo11n.pt")
    results = model(image_path, conf=0.25)  # 返回 list[Results]
    result.boxes.xyxy  # (N, 4) tensor，x1y1x2y2 像素坐标
    result.boxes.conf  # (N,) tensor，置信度
    result.boxes.cls   # (N,) tensor，类别索引
    result.names       # dict {int: str}，类别索引→类名
    result.orig_shape  # (height, width)
- 以实事求是为荣：P1 阶段无标注数据集，权重不存在时如实降级，不假装训练过
- 失败时优雅降级（参考 ocr_paddle.py 的 _paddleocr: Any = None 模式）

依赖：
- ultralytics >= 8.3（YOLOv11 官方包；未安装时降级到 VLM）
- 模型权重：P1 阶段无标注数据集，权重不存在时降级到 VLM
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from app.logging import get_logger
from app.schemas.region_detection import (
    Region,
    RegionDetectionResult,
    RegionSource,
    RegionType,
)

log = get_logger(__name__)

# ===== 优雅降级：尝试导入 ultralytics =====
# 参考 ocr_paddle.py 的 _paddleocr: Any = None 模式
_ultralytics: Any = None
_YOLO: Any = None
try:
    from ultralytics import YOLO  # type: ignore[import-not-found]

    _ultralytics = __import__("ultralytics")
    _YOLO = YOLO
except ImportError:
    _ultralytics = None
    _YOLO = None

# 模型实例缓存（避免每次调用都重新加载权重）
_model_instance: Any = None
# 已确认权重不存在的标记（避免重复 stat 系统调用）
_weight_missing_logged: bool = False


def _get_weight_path() -> Path:
    """从环境变量获取 YOLO 区域检测模型权重路径。

    默认指向 backend/models/yolo11_regions.pt。
    可通过环境变量 SYNTHDRAFT_YOLO_REGION_WEIGHTS 覆盖。
    """
    env_val = os.environ.get("SYNTHDRAFT_YOLO_REGION_WEIGHTS", "")
    if env_val:
        return Path(env_val)
    # 默认：backend/models/yolo11_regions.pt
    # 本文件位于 backend/app/services/review/region_detector.py
    # 上溯 4 级到 backend/，再进 models/
    return Path(__file__).resolve().parents[3] / "models" / "yolo11_regions.pt"


def is_ultralytics_installed() -> bool:
    """检查 ultralytics 包是否已安装（仅检查包，不检查权重）。"""
    return _ultralytics is not None and _YOLO is not None


def is_detector_available() -> bool:
    """检查 YOLOv11 区域检测器是否可用。

    可用条件：
    1. ultralytics 包已安装
    2. 模型权重文件存在（P1 阶段无标注数据集，权重通常不存在）

    实测结论（本环境）：
    - ultralytics 未安装 → 返回 False，降级到 VLM
    - 权重不存在 → 返回 False，降级到 VLM
    """
    if not is_ultralytics_installed():
        return False

    weight_path = _get_weight_path()
    if not weight_path.is_file():
        global _weight_missing_logged
        if not _weight_missing_logged:
            log.info(
                "region_detector.weight_not_found",
                weight_path=str(weight_path),
                hint="P1 阶段无标注数据集，降级到 VLM 检测；"
                "训练完成后通过 SYNTHDRAFT_YOLO_REGION_WEIGHTS 指定权重路径",
            )
            _weight_missing_logged = True
        return False
    return True


def _get_model_instance() -> Any:
    """获取或创建 YOLO 模型实例（单例）。

    ultralytics YOLO API（官方文档核实）：
        model = YOLO("yolo11n.pt")  # 加载权重
        results = model(image, conf=0.25)  # 推理
    """
    global _model_instance
    if _model_instance is not None:
        return _model_instance

    if not is_detector_available():
        raise RuntimeError("YOLOv11 检测器不可用")

    weight_path = _get_weight_path()
    log.info("region_detector.loading_model", weight=str(weight_path))
    t0 = time.monotonic()
    _model_instance = _YOLO(str(weight_path))
    elapsed = time.monotonic() - t0
    log.info("region_detector.model_ready", elapsed_ms=f"{elapsed*1000:.1f}")
    return _model_instance


def _get_image_size(image_path: Path) -> tuple[int, int] | None:
    """获取图片尺寸 (width, height)。

    优先复用 image_preprocess.load_image()（处理中文路径），
    失败时降级到 PIL，再失败返回 None。
    """
    # 优先复用 image_preprocess
    try:
        from app.services.review.image_preprocess import is_preprocess_available, load_image

        if is_preprocess_available():
            img = load_image(image_path)
            # ndarray.shape = (height, width, channels)
            h, w = img.shape[:2]
            return (int(w), int(h))
    except Exception as e:  # noqa: BLE001
        log.debug("region_detector.load_image_fallback", error=str(e))

    # 降级到 PIL
    try:
        from PIL import Image

        with Image.open(str(image_path)) as im:
            return (int(im.width), int(im.height))
    except Exception as e:  # noqa: BLE001
        log.warning("region_detector.get_size_failed", path=str(image_path), error=str(e))
        return None


def _map_class_name_to_region_type(name: str) -> RegionType:
    """将 YOLO 类名映射到 RegionType。

    约定训练时类名与 RegionType 枚举值一致（title_block/dimension_area 等）。
    未知类名归为 OTHER。
    """
    if not name:
        return RegionType.OTHER
    try:
        return RegionType(name.lower().strip())
    except ValueError:
        return RegionType.OTHER


def _xyxy_to_normalized(
    xyxy: list[float], width: int, height: int
) -> list[float]:
    """像素 xyxy [x1,y1,x2,y2] → 归一化 [x, y, w, h]。"""
    x1, y1, x2, y2 = xyxy
    x = x1 / width if width > 0 else 0.0
    y = y1 / height if height > 0 else 0.0
    w = (x2 - x1) / width if width > 0 else 0.0
    h = (y2 - y1) / height if height > 0 else 0.0
    # 钳制到 [0, 1]
    return [max(0.0, min(1.0, v)) for v in (x, y, w, h)]


def _normalized_xywh_to_pixel(
    norm: list[float], width: int, height: int
) -> list[float]:
    """归一化 [x, y, w, h] → 像素 [x1, y1, x2, y2]。"""
    x, y, w, h = norm
    x1 = x * width
    y1 = y * height
    x2 = (x + w) * width
    y2 = (y + h) * height
    return [float(x1), float(y1), float(x2), float(y2)]


def _detect_with_yolo(
    image_path: Path, confidence_threshold: float, width: int, height: int
) -> list[Region]:
    """用 YOLOv11 检测区域。

    ultralytics API（官方文档核实，未在本环境运行时测试——ultralytics 未安装）：
        results = model(str(image_path), conf=confidence_threshold)
        result = results[0]
        result.boxes.xyxy  # (N, 4) tensor
        result.boxes.conf  # (N,) tensor
        result.boxes.cls   # (N,) tensor
        result.names       # dict {int: str}
    """
    model = _get_model_instance()
    t0 = time.monotonic()

    # model() 与 model.predict() 等价；用 predict 显式传参更清晰
    results = model.predict(str(image_path), conf=confidence_threshold, verbose=False)
    elapsed = time.monotonic() - t0

    if not results:
        log.info("region_detector.yolo.no_result", path=str(image_path))
        return []

    result = results[0]
    boxes = getattr(result, "boxes", None)
    if boxes is None:
        return []

    names = getattr(result, "names", {}) or {}

    # 提取张量并转 CPU numpy（避免 GPU 张量无法直接索引）
    try:
        xyxy_tensor = boxes.xyxy  # (N, 4)
        conf_tensor = boxes.conf  # (N,)
        cls_tensor = boxes.cls    # (N,)
        # 统一转 cpu + numpy + tolist
        xyxy_list = _tensor_to_list(xyxy_tensor)
        conf_list = _tensor_to_list(conf_tensor)
        cls_list = _tensor_to_list(cls_tensor)
    except Exception as e:  # noqa: BLE001
        log.warning("region_detector.yolo.parse_failed", error=str(e))
        return []

    regions: list[Region] = []
    for i, xyxy in enumerate(xyxy_list):
        conf = float(conf_list[i]) if i < len(conf_list) else 0.0
        cls_idx = int(cls_list[i]) if i < len(cls_list) else -1
        cls_name = names.get(cls_idx, "other")
        region_type = _map_class_name_to_region_type(str(cls_name))
        # 钳制 bbox 到图像边界
        x1, y1, x2, y2 = xyxy
        x1 = max(0.0, min(float(x1), width))
        y1 = max(0.0, min(float(y1), height))
        x2 = max(0.0, min(float(x2), width))
        y2 = max(0.0, min(float(y2), height))
        bbox_pixel = [x1, y1, x2, y2]
        bbox_norm = _xyxy_to_normalized(bbox_pixel, width, height)
        regions.append(
            Region(
                region_type=region_type,
                bbox=bbox_pixel,
                bbox_normalized=bbox_norm,
                confidence=conf,
                source="yolov11",
            )
        )

    log.info(
        "region_detector.yolo.detected",
        path=str(image_path),
        count=len(regions),
        elapsed_ms=f"{elapsed*1000:.1f}",
    )
    return regions


def _tensor_to_list(tensor: Any) -> list:
    """将 torch tensor / numpy array 递归转为 list[float]/list[list[float]]。

    兼容 ultralytics 返回的 torch tensor 与 numpy array 两种情况。
    """
    # torch tensor
    if hasattr(tensor, "cpu"):
        tensor = tensor.cpu().numpy()
    # numpy array
    if hasattr(tensor, "tolist"):
        return tensor.tolist()
    # 已经是 list
    return list(tensor)


def _detect_with_vlm(image_path: Path, width: int, height: int) -> list[Region]:
    """用 VLM 检测区域（复用 vlm_ocr.vlm_detect_regions）。

    vlm_detect_regions 返回 [{"name": "title_block", "bbox": [x,y,w,h]}, ...]
    其中 bbox 为归一化 [x, y, w, h]。

    此处再次调用 ``_normalize_bbox`` 做防御性规范化，以兼容：
    - VLM 直接返回嵌套列表 ``[[x,y,w,h]]`` 的噪声
    - mock 测试绕过 ``vlm_detect_regions`` 直接注入 raw bbox 的场景
    """
    try:
        from app.services.review.vlm_ocr import _normalize_bbox, vlm_detect_regions
    except ImportError as e:
        log.warning("region_detector.vlm_import_failed", error=str(e))
        return []

    raw_regions = vlm_detect_regions(image_path)
    if not raw_regions:
        return []

    regions: list[Region] = []
    for raw in raw_regions:
        name = raw.get("name", "other")
        bbox_norm = raw.get("bbox") or raw.get("bbox_normalized")
        # 规范化：展开嵌套列表 / 钳制越界值 / 验证长度
        norm = _normalize_bbox(bbox_norm)
        if norm is None:
            continue
        bbox_pixel = _normalized_xywh_to_pixel(norm, width, height)
        try:
            region_type = RegionType(str(name).lower().strip())
        except ValueError:
            region_type = RegionType.OTHER
        regions.append(
            Region(
                region_type=region_type,
                bbox=bbox_pixel,
                bbox_normalized=norm,
                confidence=0.6,  # VLM 检测无明确置信度，给固定中值
                source="vlm",
            )
        )

    log.info("region_detector.vlm.detected", path=str(image_path), count=len(regions))
    return regions


def detect_regions(
    image_path: Path, confidence_threshold: float = 0.25
) -> list[Region]:
    """检测工程图区域，返回带 bbox 的区域列表。

    三级降级策略：
    1. YOLOv11 模型可用 → 直接推理
    2. 模型不可用 → 调用 vlm_ocr.vlm_detect_regions()
    3. VLM 也不可用 → 返回空列表，由调用方标注 reference_level

    Args:
        image_path: 输入图片路径
        confidence_threshold: YOLO 置信度阈值（默认 0.25）

    Returns:
        list[Region]：检测到的区域列表（可能为空）
    """
    image_path = Path(image_path)
    if not image_path.is_file():
        log.warning("region_detector.image_not_found", path=str(image_path))
        return []

    size = _get_image_size(image_path)
    if size is None:
        log.warning("region_detector.size_unknown", path=str(image_path))
        return []
    width, height = size

    # 1. YOLOv11 路径
    if is_detector_available():
        try:
            regions = _detect_with_yolo(image_path, confidence_threshold, width, height)
            if regions:
                return regions
        except Exception as e:  # noqa: BLE001
            log.warning("region_detector.yolo.failed_fallback_vlm", error=str(e))

    # 2. VLM 降级路径
    regions = _detect_with_vlm(image_path, width, height)
    if regions:
        return regions

    # 3. 全部不可用 → 空列表
    log.info("region_detector.all_fallback_empty", path=str(image_path))
    return []


def detect_regions_detailed(
    image_path: Path, confidence_threshold: float = 0.25
) -> RegionDetectionResult:
    """检测工程图区域，返回带元信息的完整结果。

    相比 detect_regions()，额外返回 detector_source / elapsed_ms / warnings，
    便于 pipeline 与 self_test 追踪实际使用的检测器与降级路径。

    Args:
        image_path: 输入图片路径
        confidence_threshold: YOLO 置信度阈值

    Returns:
        RegionDetectionResult
    """
    image_path = Path(image_path)
    t0 = time.monotonic()
    warnings: list[str] = []
    detector_source = "none"

    if not image_path.is_file():
        return RegionDetectionResult(
            image_path=str(image_path),
            image_size=(0, 0),
            regions=[],
            detector_source="none",
            elapsed_ms=0,
            warnings=["图片不存在"],
        )

    size = _get_image_size(image_path)
    if size is None:
        return RegionDetectionResult(
            image_path=str(image_path),
            image_size=(0, 0),
            regions=[],
            detector_source="none",
            elapsed_ms=int((time.monotonic() - t0) * 1000),
            warnings=["无法读取图片尺寸"],
        )
    width, height = size

    regions: list[Region] = []

    # 1. YOLOv11
    if is_detector_available():
        try:
            regions = _detect_with_yolo(image_path, confidence_threshold, width, height)
            if regions:
                detector_source = "yolov11"
            else:
                warnings.append("YOLOv11 未检测到区域，降级到 VLM")
        except Exception as e:  # noqa: BLE001
            warnings.append(f"YOLOv11 异常: {e}")
    else:
        if not is_ultralytics_installed():
            warnings.append("ultralytics 未安装，YOLOv11 路径不可用")
        else:
            warnings.append(f"权重不存在: {_get_weight_path()}")

    # 2. VLM 降级
    if not regions:
        regions = _detect_with_vlm(image_path, width, height)
        if regions:
            detector_source = "vlm"
        else:
            warnings.append("VLM 检测未返回区域（Ollama 未运行或无视觉模型）")

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    return RegionDetectionResult(
        image_path=str(image_path),
        image_size=(width, height),
        regions=regions,
        detector_source=detector_source,
        elapsed_ms=elapsed_ms,
        warnings=warnings,
    )


def self_test() -> dict:
    """自检：验证 YOLOv11 可用性 + 实际加载图片检测 + 降级路径。

    Returns:
        {
            "ultralytics_installed": bool,
            "ultralytics_version": str,
            "weight_path": str,
            "weight_exists": bool,
            "detector_available": bool,
            "checks": {...},
            "degradation_path": str,  # 实际触发的降级路径
        }
    """
    weight_path = _get_weight_path()
    result: dict[str, Any] = {
        "ultralytics_installed": is_ultralytics_installed(),
        "ultralytics_version": getattr(_ultralytics, "__version__", "") if _ultralytics else "",
        "weight_path": str(weight_path),
        "weight_exists": weight_path.is_file(),
        "detector_available": is_detector_available(),
        "checks": {},
        "degradation_path": "unknown",
    }

    # 检查 ultralytics 关键 API
    if is_ultralytics_installed():
        result["checks"]["YOLO_class_exists"] = _YOLO is not None
        result["checks"]["ultralytics_module_importable"] = _ultralytics is not None
    else:
        result["checks"]["ultralytics"] = "未安装（pip install ultralytics>=8.3）"

    # 降级路径判定
    if is_detector_available():
        result["degradation_path"] = "yolov11"
    else:
        # 检查 VLM 是否可用（不实际调用，仅探测 Ollama）
        try:
            from app.services.review.vlm_ocr import is_vlm_available

            if is_vlm_available():
                result["degradation_path"] = "vlm"
            else:
                result["degradation_path"] = "empty"
        except Exception:
            result["degradation_path"] = "empty"

    return result


if __name__ == "__main__":
    # 命令行直接运行：自检 + 实测 tmp_review_images 下 PNG
    import sys

    print("=" * 60)
    print("YOLOv11 区域检测模块自检（Task 9.3）")
    print("=" * 60)

    report = self_test()
    print(f"\nultralytics 已安装: {report['ultralytics_installed']}")
    print(f"ultralytics 版本: {report['ultralytics_version'] or '(未安装)'}")
    print(f"权重路径: {report['weight_path']}")
    print(f"权重存在: {report['weight_exists']}")
    print(f"检测器可用: {report['detector_available']}")
    print(f"降级路径: {report['degradation_path']}")
    print("\n检查项:")
    for k, v in report["checks"].items():
        print(f"  - {k}: {v}")

    # 端到端实测
    test_dir = Path(__file__).resolve().parent.parent.parent.parent / "tmp_review_images"
    print(f"\n实测目录: {test_dir}")
    if not test_dir.is_dir():
        print(f"目录不存在，自检终止。")
        sys.exit(1)

    png_files = sorted(test_dir.glob("*.png"))
    print(f"找到 {len(png_files)} 个 PNG 文件\n")

    for png in png_files:
        print(f"处理: {png.name}")
        det_result = detect_regions_detailed(png)
        print(f"  图片尺寸 (WxH): {det_result.image_size}")
        print(f"  检测器: {det_result.detector_source}")
        print(f"  耗时: {det_result.elapsed_ms} ms")
        print(f"  区域数: {len(det_result.regions)}")
        if det_result.warnings:
            print(f"  告警: {det_result.warnings}")
        for i, region in enumerate(det_result.regions):
            print(
                f"    [{i+1}] type={region.region_type.value} "
                f"bbox={[round(v, 1) for v in region.bbox]} "
                f"norm={[round(v, 3) for v in region.bbox_normalized]} "
                f"conf={region.confidence:.3f} src={region.source}"
            )
        print()

    print("=" * 60)
    print("自检完成")
    print("=" * 60)
