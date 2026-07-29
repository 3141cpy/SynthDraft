"""区域受限 OCR 模块（Task 9.4）。

对 region_detector 检测到的每个区域裁剪后做 OCR，并按区域类型做结构化提取。

设计原则（八荣八耻）：
- 以复用现有为荣：复用 image_preprocess.load_image() / ocr_paddle.ocr_extract() /
  vlm_ocr.vlm_ocr_extract()，不重新实现 OCR
- 以瞎猜接口为耻：cv2 / paddleocr API 均经实测（cv2 4.10.0 + paddleocr 3.7.0）
- 以实事求是为荣：裁剪图过小则跳过；OCR 失败则返回 raw_texts，structured_data 为空
- 以覆盖测试为荣：self_test() 用合成工程图实测完整链路

策略：
1. 根据区域 bbox 裁剪原图（用 OpenCV，复用 image_preprocess.load_image）
2. 对裁剪图调用 PaddleOCR（复用 ocr_paddle.ocr_extract）
3. 区域类型决定 OCR 后处理（正则 + 关键字提取结构化字段）
4. VLM 兜底：PaddleOCR 置信度低或无结果时调用 VLM（复用 vlm_ocr.vlm_ocr_extract）
"""

from __future__ import annotations

import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from app.logging import get_logger
from app.schemas.region_detection import Region, RegionOCRResult, RegionType

log = get_logger(__name__)

# 裁剪图最小尺寸阈值（像素），小于此值跳过 OCR
_MIN_CROP_SIZE = 50

# PaddleOCR 平均置信度低于此值时触发 VLM 兜底
_VLM_FALLBACK_CONFIDENCE = 0.5


def _save_crop(crop_img: Any, out_path: Path) -> bool:
    """保存裁剪图，兼容中文路径（参考 image_preprocess 的 imencode 兜底）。"""
    try:
        import cv2  # type: ignore[import-not-found]

        try:
            ok = cv2.imwrite(str(out_path), crop_img)
        except Exception:
            ok, buf = cv2.imencode(".png", crop_img)
            if ok:
                buf.tofile(str(out_path))
        return bool(ok and out_path.is_file())
    except Exception as e:  # noqa: BLE001
        log.warning("region_ocr.save_crop_failed", path=str(out_path), error=str(e))
        return False


def _crop_region(image_path: Path, bbox: list[float], temp_dir: Path) -> Path | None:
    """根据 bbox 裁剪原图，保存到临时文件。

    Args:
        image_path: 原图路径
        bbox: 像素坐标 [x1, y1, x2, y2]
        temp_dir: 临时目录

    Returns:
        裁剪图路径；裁剪图过小或失败时返回 None。
    """
    try:
        from app.services.review.image_preprocess import is_preprocess_available, load_image

        if not is_preprocess_available():
            log.warning("region_ocr.cv2_unavailable")
            return None

        img = load_image(image_path)
    except Exception as e:  # noqa: BLE001
        log.warning("region_ocr.load_failed", path=str(image_path), error=str(e))
        return None

    h, w = img.shape[:2]
    x1, y1, x2, y2 = bbox
    # 钳制 bbox 到图像边界
    x1 = max(0, int(round(x1)))
    y1 = max(0, int(round(y1)))
    x2 = min(w, int(round(x2)))
    y2 = min(h, int(round(y2)))

    crop_w = x2 - x1
    crop_h = y2 - y1
    if crop_w < _MIN_CROP_SIZE or crop_h < _MIN_CROP_SIZE:
        log.info(
            "region_ocr.crop_too_small",
            path=str(image_path),
            size=f"{crop_w}x{crop_h}",
            bbox=bbox,
        )
        return None

    crop = img[y1:y2, x1:x2]
    crop_path = temp_dir / f"crop_{x1}_{y1}_{crop_w}x{crop_h}.png"
    if not _save_crop(crop, crop_path):
        return None

    log.debug("region_ocr.crop_saved", path=str(crop_path), size=f"{crop_w}x{crop_h}")
    return crop_path


def _ocr_with_paddle(crop_path: Path) -> tuple[list[dict], list[str], float]:
    """用 PaddleOCR 对裁剪图做 OCR（复用 ocr_paddle.ocr_extract）。

    Returns:
        (raw_items, raw_texts, avg_confidence)
    """
    try:
        from app.services.review.ocr_paddle import is_paddleocr_available, ocr_extract

        if not is_paddleocr_available():
            return [], [], 0.0

        items = ocr_extract(crop_path, return_boxes=True, return_confidence=True)
    except Exception as e:  # noqa: BLE001
        log.warning("region_ocr.paddle_failed", path=str(crop_path), error=str(e))
        return [], [], 0.0

    raw_texts = [it.get("text", "") for it in items if it.get("text")]
    confs = [float(it.get("confidence", 0.0)) for it in items if it.get("confidence") is not None]
    avg_conf = sum(confs) / len(confs) if confs else 0.0
    return items, raw_texts, avg_conf


def _ocr_with_vlm(crop_path: Path, region_type: RegionType) -> dict[str, Any]:
    """用 VLM 对裁剪图做 OCR（复用 vlm_ocr.vlm_ocr_extract）。

    vlm_ocr_extract 返回 dict（title/drawing_number/material/scale/dimensions/
    technical_requirements 等）。VLM 不可用时返回空 dict。
    """
    try:
        from app.services.review.vlm_ocr import vlm_ocr_extract

        return vlm_ocr_extract(crop_path) or {}
    except Exception as e:  # noqa: BLE001
        log.warning("region_ocr.vlm_failed", path=str(crop_path), error=str(e))
        return {}


# ===== 区域类型后处理（正则 + 关键字） =====


def _structure_title_block(raw_texts: list[str]) -> dict[str, Any]:
    """标题栏结构化：提取图号/图名/材料/比例/日期/制图/版本。"""
    full = "\n".join(raw_texts)
    result: dict[str, Any] = {}

    # 图号：图号:T-XXX / 图号 T-XXX / 独立 T-XXX
    m = re.search(r"图号\s*[:：]\s*([A-Za-z0-9\-_/.]+)", full)
    if m:
        result["drawing_number"] = m.group(1).strip()
    else:
        m = re.search(r"\b([A-Z]\-\d{2,6})\b", full)
        if m:
            result["drawing_number"] = m.group(1)

    # 图名
    m = re.search(r"图名\s*[:：]\s*(.+)", full)
    if m:
        result["title"] = m.group(1).strip().splitlines()[0]

    # 材料：材料:45# / 材料 Q235
    m = re.search(r"材料\s*[:：]\s*([\w#]+)", full)
    if m:
        result["material"] = m.group(1).strip()

    # 比例：比例:1:2 / 1:2
    m = re.search(r"比例\s*[:：]\s*(\d+\s*[:：]\s*\d+)", full)
    if m:
        result["scale"] = m.group(1).replace("：", ":").replace(" ", "")
    else:
        m = re.search(r"\b(\d+:\d+)\b", full)
        if m:
            result["scale"] = m.group(1)

    # 日期：2024-01-01 / 2024/01/01 / 2024年1月1日
    m = re.search(r"(\d{4}[-/年]\d{1,2}[-/月]\d{1,2})", full)
    if m:
        result["date"] = m.group(1)

    # 制图
    m = re.search(r"制图\s*[:：]\s*(\S+)", full)
    if m:
        result["drawn_by"] = m.group(1).strip()

    # 版本
    m = re.search(r"版本\s*[:：]\s*(\S+)", full)
    if m:
        result["version"] = m.group(1).strip()
    else:
        m = re.search(r"\bV\d+\b", full)
        if m:
            result["version"] = m.group(0)

    return result


def _structure_dimension_area(raw_texts: list[str]) -> dict[str, Any]:
    """尺寸标注区结构化：提取直径/螺纹/半径/公差/角度/通用尺寸列表。"""
    full = " ".join(raw_texts)
    result: dict[str, Any] = {}

    # 直径：Ø20 / ø20 / Φ20 / D20 / d20
    diameters = re.findall(r"[ØøΦ]\s*(\d+\.?\d*)", full)
    if diameters:
        result["diameters"] = diameters

    # 螺纹：M8x1.25 / M8×1.25
    threads = re.findall(r"M\d+\.?\d*\s*[x×]\s*\d+\.?\d*", full)
    if threads:
        result["threads"] = [t.replace("×", "x") for t in threads]

    # 半径：R5 / R2.5
    radii = re.findall(r"R\s*(\d+\.?\d*)", full)
    if radii:
        result["radii"] = radii

    # 公差：±0.1
    tolerances = re.findall(r"±\s*(\d+\.?\d*)", full)
    if tolerances:
        result["tolerances"] = tolerances

    # 角度：45°
    angles = re.findall(r"(\d+\.?\d*)\s*°", full)
    if angles:
        result["angles"] = angles

    # 通用尺寸数字（独立数字，排除已在 diameter/thread 中的）
    numbers = re.findall(r"(?<![A-Za-zØøΦ±])(\d+\.?\d*)(?![A-Za-z°])", full)
    if numbers:
        result["numbers"] = numbers

    result["dimension_count"] = (
        len(diameters) + len(threads) + len(radii) + len(tolerances) + len(angles)
    )
    return result


def _structure_parts_list(raw_texts: list[str]) -> dict[str, Any]:
    """明细栏结构化：按行解析件号/名称/数量/材料/备注。

    明细栏通常为表格，每行一条记录。P0 阶段用启发式：
    - 按连续 2+ 空格或制表符分列
    - 首列视为件号，尝试识别数量（纯数字列）与材料
    """
    rows: list[dict[str, Any]] = []
    for line in raw_texts:
        line = line.strip()
        if not line:
            continue
        # 按 2+ 空格或制表符分列
        cols = re.split(r"\s{2,}|\t", line)
        cols = [c.strip() for c in cols if c.strip()]
        if len(cols) < 2:
            # 单列也保留为件号候选
            rows.append({"raw": line, "parts_number": cols[0] if cols else line})
            continue

        row: dict[str, Any] = {"raw": line}
        row["parts_number"] = cols[0]
        row["name"] = cols[1] if len(cols) > 1 else None
        # 数量列：找纯数字
        qty = None
        for c in cols[2:]:
            if re.fullmatch(r"\d+", c):
                qty = c
                break
        row["quantity"] = qty
        # 材料列：含字母+数字+#
        for c in cols[2:]:
            if re.search(r"[A-Z]\d|#|Q\d", c) and c != qty:
                row["material"] = c
                break
        row["remark"] = cols[-1] if len(cols) > 3 else None
        rows.append(row)

    return {"rows": rows, "row_count": len(rows)}


def _structure_technical_requirements(raw_texts: list[str]) -> dict[str, Any]:
    """技术要求结构化：按行拼接为完整文本。"""
    text = "\n".join(t.strip() for t in raw_texts if t.strip())
    return {"text": text, "line_count": len([t for t in raw_texts if t.strip()])}


def _structure_default(raw_texts: list[str]) -> dict[str, Any]:
    """其他区域：仅保留原文列表。"""
    return {"texts": raw_texts, "line_count": len(raw_texts)}


def _structure_by_region_type(
    region_type: RegionType, raw_texts: list[str]
) -> dict[str, Any]:
    """按区域类型分发结构化提取。"""
    if region_type == RegionType.TITLE_BLOCK:
        return _structure_title_block(raw_texts)
    if region_type == RegionType.DIMENSION_AREA:
        return _structure_dimension_area(raw_texts)
    if region_type == RegionType.PARTS_LIST:
        return _structure_parts_list(raw_texts)
    if region_type == RegionType.TECHNICAL_REQUIREMENTS:
        return _structure_technical_requirements(raw_texts)
    return _structure_default(raw_texts)


def _merge_vlm_structured(
    base: dict[str, Any], vlm_result: dict[str, Any], region_type: RegionType
) -> dict[str, Any]:
    """将 VLM 结果合并到结构化字段（VLM 字段优先填充空缺）。"""
    if not vlm_result:
        return base

    if region_type == RegionType.TITLE_BLOCK:
        for k in ("drawing_number", "title", "material", "scale", "date"):
            v = vlm_result.get(k)
            if v and not base.get(k):
                base[k] = v
    elif region_type == RegionType.DIMENSION_AREA:
        dims = vlm_result.get("dimensions")
        if dims and not base.get("diameters") and not base.get("threads"):
            base["dimensions"] = dims
    elif region_type == RegionType.TECHNICAL_REQUIREMENTS:
        tr = vlm_result.get("technical_requirements")
        if tr and not base.get("text"):
            base["text"] = tr

    return base


def ocr_in_regions(
    image_path: Path,
    regions: list[Region],
    ocr_backend: str = "auto",
) -> list[RegionOCRResult]:
    """对每个区域裁剪后做 OCR，返回区域级 OCR 结果。

    策略：
    1. 根据区域 bbox 裁剪原图（用 OpenCV，复用 image_preprocess）
    2. 对裁剪图调用 PaddleOCR（复用 ocr_paddle.ocr_extract）
    3. 区域类型决定 OCR 后处理（正则 + 关键字）
    4. VLM 兜底：PaddleOCR 置信度低或无结果时调用 VLM（复用 vlm_ocr.vlm_ocr_extract）

    Args:
        image_path: 原图路径
        regions: 区域列表（来自 region_detector.detect_regions）
        ocr_backend: OCR 后端（paddle/vlm/auto）；auto=先 paddle 后 vlm 兜底

    Returns:
        list[RegionOCRResult]：与输入 regions 一一对应（跳过的区域仍返回空结果）
    """
    image_path = Path(image_path)
    results: list[RegionOCRResult] = []
    if not image_path.is_file():
        log.warning("region_ocr.image_not_found", path=str(image_path))
        return [RegionOCRResult(
            region_type=r.region_type, bbox=r.bbox, ocr_backend="none",
            avg_confidence=0.0, elapsed_ms=0,
        ) for r in regions] if regions else []

    temp_dir = Path(tempfile.mkdtemp(prefix="synthdraft_region_ocr_"))
    try:
        for region in regions:
            t0 = time.monotonic()
            raw_texts: list[str] = []
            raw_items: list[dict[str, Any]] = []
            structured: dict[str, Any] = {}
            avg_conf = 0.0
            used_backend = "none"

            # 裁剪
            crop_path = _crop_region(image_path, region.bbox, temp_dir)
            if crop_path is None:
                elapsed_ms = int((time.monotonic() - t0) * 1000)
                results.append(RegionOCRResult(
                    region_type=region.region_type,
                    bbox=region.bbox,
                    raw_texts=[],
                    raw_items=[],
                    structured_data={},
                    ocr_backend="skipped",
                    avg_confidence=0.0,
                    elapsed_ms=elapsed_ms,
                ))
                continue

            # Paddle 路径
            if ocr_backend in ("paddle", "auto"):
                items, texts, conf = _ocr_with_paddle(crop_path)
                raw_items = items
                raw_texts = texts
                avg_conf = conf
                if items:
                    used_backend = "paddle"

            # VLM 兜底：auto 模式且 paddle 结果不佳时
            need_vlm = (
                ocr_backend == "vlm"
                or (ocr_backend == "auto" and (not raw_texts or avg_conf < _VLM_FALLBACK_CONFIDENCE))
            )
            if need_vlm:
                vlm_result = _ocr_with_vlm(crop_path, region.region_type)
                if vlm_result:
                    used_backend = "vlm" if not raw_texts else "paddle+vlm"
                    # VLM 结果直接作为结构化字段候选
                    structured = _merge_vlm_structured(structured, vlm_result, region.region_type)

            # 基于 raw_texts 做正则结构化（覆盖 VLM 未提供的字段）
            if raw_texts:
                regex_structured = _structure_by_region_type(region.region_type, raw_texts)
                # regex 结果优先（更精确），VLM 填充空缺
                merged = dict(regex_structured)
                for k, v in structured.items():
                    if k not in merged or not merged[k]:
                        merged[k] = v
                structured = merged
            elif not structured:
                # 既无 paddle 文本也无 vlm 结果，structured 保持空
                pass

            elapsed_ms = int((time.monotonic() - t0) * 1000)
            results.append(RegionOCRResult(
                region_type=region.region_type,
                bbox=region.bbox,
                raw_texts=raw_texts,
                raw_items=raw_items,
                structured_data=structured,
                ocr_backend=used_backend,
                avg_confidence=avg_conf,
                elapsed_ms=elapsed_ms,
            ))
    finally:
        # 清理临时裁剪图
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:  # noqa: BLE001
            pass

    return results


def _make_synthetic_drawing(out_path: Path) -> tuple[int, int, list[Region]]:
    """生成合成工程图，返回 (width, height, regions)。

    用 PIL 绘制含标题栏/尺寸标注/技术要求的合成图，并返回对应的 Region 列表。
    用于 self_test 实测完整 OCR 链路（不依赖 Ollama/YOLO）。
    """
    from PIL import Image, ImageDraw, ImageFont

    import app.schemas.region_detection as rd

    W, H = 800, 600
    img = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(img)

    # 加载默认字体（支持基本 ASCII）；中文用系统字体兜底
    try:
        font_large = ImageFont.truetype("arial.ttf", 20)
        font_small = ImageFont.truetype("arial.ttf", 16)
    except Exception:
        font_large = ImageFont.load_default()
        font_small = ImageFont.load_default()

    # 标题栏区域（右下角）
    tb_x1, tb_y1, tb_x2, tb_y2 = 500, 480, 780, 580
    draw.rectangle([tb_x1, tb_y1, tb_x2, tb_y2], outline="black", width=2)
    draw.text((tb_x1 + 10, tb_y1 + 10), "DWG NO: T-1001", fill="black", font=font_small)
    draw.text((tb_x1 + 10, tb_y1 + 35), "MAT: 45#", fill="black", font=font_small)
    draw.text((tb_x1 + 10, tb_y1 + 60), "SCALE: 1:2", fill="black", font=font_small)
    draw.text((tb_x1 + 150, tb_y1 + 10), "DATE: 2024-01-01", fill="black", font=font_small)
    draw.text((tb_x1 + 150, tb_y1 + 35), "V1", fill="black", font=font_small)

    # 尺寸标注区（左上）
    dim_x1, dim_y1, dim_x2, dim_y2 = 30, 30, 300, 150
    draw.rectangle([dim_x1, dim_y1, dim_x2, dim_y2], outline="gray", width=1)
    draw.text((dim_x1 + 10, dim_y1 + 10), "D20", fill="black", font=font_large)
    draw.text((dim_x1 + 10, dim_y1 + 50), "M8x1.25", fill="black", font=font_large)
    draw.text((dim_x1 + 100, dim_y1 + 10), "R5", fill="black", font=font_large)
    draw.text((dim_x1 + 100, dim_y1 + 50), "100", fill="black", font=font_large)
    draw.text((dim_x1 + 10, dim_y1 + 90), "+/-0.1", fill="black", font=font_small)

    # 技术要求区（左下）
    tr_x1, tr_y1, tr_x2, tr_y2 = 30, 300, 400, 440
    draw.rectangle([tr_x1, tr_y1, tr_x2, tr_y2], outline="gray", width=1)
    draw.text((tr_x1 + 10, tr_y1 + 10), "Technical Requirements:", fill="black", font=font_small)
    draw.text((tr_x1 + 10, tr_y1 + 35), "1. All dims in mm", fill="black", font=font_small)
    draw.text((tr_x1 + 10, tr_y1 + 60), "2. Remove burrs", fill="black", font=font_small)

    img.save(str(out_path))

    regions = [
        Region(
            region_type=rd.RegionType.TITLE_BLOCK,
            bbox=[float(tb_x1), float(tb_y1), float(tb_x2), float(tb_y2)],
            bbox_normalized=[tb_x1 / W, tb_y1 / H, (tb_x2 - tb_x1) / W, (tb_y2 - tb_y1) / H],
            confidence=1.0,
            source="heuristic",
        ),
        Region(
            region_type=rd.RegionType.DIMENSION_AREA,
            bbox=[float(dim_x1), float(dim_y1), float(dim_x2), float(dim_y2)],
            bbox_normalized=[dim_x1 / W, dim_y1 / H, (dim_x2 - dim_x1) / W, (dim_y2 - dim_y1) / H],
            confidence=1.0,
            source="heuristic",
        ),
        Region(
            region_type=rd.RegionType.TECHNICAL_REQUIREMENTS,
            bbox=[float(tr_x1), float(tr_y1), float(tr_x2), float(tr_y2)],
            bbox_normalized=[tr_x1 / W, tr_y1 / H, (tr_x2 - tr_x1) / W, (tr_y2 - tr_y1) / H],
            confidence=1.0,
            source="heuristic",
        ),
        # 故意加一个过小区域，验证跳过逻辑
        Region(
            region_type=rd.RegionType.OTHER,
            bbox=[10.0, 10.0, 30.0, 30.0],  # 20x20 < 50x50
            bbox_normalized=[10 / W, 10 / H, 20 / W, 20 / H],
            confidence=1.0,
            source="heuristic",
        ),
    ]
    return W, H, regions


def self_test() -> dict:
    """自检：用合成工程图实测裁剪 + OCR + 结构化提取完整链路。

    Returns:
        {
            "available": bool,  # PaddleOCR 是否可用
            "synthetic_image": str,
            "image_size": (int, int),
            "results": [...],  # 每个 RegionOCRResult 的摘要
            "checks": {...},
        }
    """
    result: dict[str, Any] = {"available": False, "checks": {}}

    # 检查 PaddleOCR
    try:
        from app.services.review.ocr_paddle import is_paddleocr_available

        result["available"] = is_paddleocr_available()
    except Exception as e:
        result["checks"]["paddle_import_error"] = str(e)
        return result

    if not result["available"]:
        result["checks"]["skip"] = "PaddleOCR 不可用，跳过端到端实测"
        return result

    # 生成合成图
    test_dir = Path(tempfile.gettempdir()) / "synthdraft_selftest"
    test_dir.mkdir(parents=True, exist_ok=True)
    synth_path = test_dir / "synth_drawing.png"
    try:
        W, H, regions = _make_synthetic_drawing(synth_path)
    except Exception as e:
        result["checks"]["synth_failed"] = str(e)
        return result

    result["synthetic_image"] = str(synth_path)
    result["image_size"] = (W, H)
    result["checks"]["synth_created"] = synth_path.is_file()

    # 端到端 OCR
    t0 = time.monotonic()
    ocr_results = ocr_in_regions(synth_path, regions, ocr_backend="auto")
    elapsed = time.monotonic() - t0
    result["elapsed_ms"] = int(elapsed * 1000)

    summaries: list[dict[str, Any]] = []
    for r in ocr_results:
        summaries.append({
            "region_type": r.region_type.value,
            "ocr_backend": r.ocr_backend,
            "raw_texts": r.raw_texts[:5],
            "raw_text_count": len(r.raw_texts),
            "avg_confidence": round(r.avg_confidence, 3),
            "structured_data": r.structured_data,
            "elapsed_ms": r.elapsed_ms,
        })
    result["results"] = summaries

    # 校验
    checks = result["checks"]
    checks["result_count_matches"] = len(ocr_results) == len(regions)

    # 过小区域应被跳过
    skipped = [r for r in ocr_results if r.ocr_backend == "skipped"]
    checks["small_region_skipped"] = len(skipped) == 1

    # 标题栏应有结构化字段
    tb = next((r for r in ocr_results if r.region_type == RegionType.TITLE_BLOCK), None)
    if tb:
        checks["title_block_has_text"] = len(tb.raw_texts) > 0
        checks["title_block_structured"] = bool(tb.structured_data)
    else:
        checks["title_block_found"] = False

    # 尺寸区应有结构化字段
    dim = next((r for r in ocr_results if r.region_type == RegionType.DIMENSION_AREA), None)
    if dim:
        checks["dimension_area_has_text"] = len(dim.raw_texts) > 0
        checks["dimension_area_structured"] = bool(dim.structured_data)

    return result


if __name__ == "__main__":
    print("=" * 60)
    print("区域受限 OCR 模块自检（Task 9.4）")
    print("=" * 60)

    report = self_test()
    print(f"\nPaddleOCR 可用: {report['available']}")
    if not report["available"]:
        print(f"跳过原因: {report['checks'].get('skip', '未知')}")
        print("\n检查项:")
        for k, v in report["checks"].items():
            print(f"  - {k}: {v}")
    else:
        print(f"合成图: {report.get('synthetic_image')}")
        print(f"图片尺寸: {report.get('image_size')}")
        print(f"总耗时: {report.get('elapsed_ms')} ms")
        print("\n检查项:")
        for k, v in report["checks"].items():
            mark = "[OK]" if v is True else "[--]" if v is False else "[i]"
            print(f"  {mark} {k}: {v}")

        print("\n区域 OCR 结果:")
        for i, r in enumerate(report.get("results", [])):
            print(f"\n  [{i+1}] region={r['region_type']} backend={r['ocr_backend']} "
                  f"conf={r['avg_confidence']} texts={r['raw_text_count']} ms={r['elapsed_ms']}")
            if r["raw_texts"]:
                print(f"      原文(前5): {r['raw_texts']}")
            if r["structured_data"]:
                print(f"      结构化: {r['structured_data']}")

    print("\n" + "=" * 60)
    print("自检完成")
    print("=" * 60)
