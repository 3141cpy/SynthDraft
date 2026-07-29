"""Task 9.3 + 9.4 覆盖测试脚本。

补充 self_test 未覆盖的代码路径（八荣八耻 §"以覆盖测试为荣"）：
  1. schema 校验（Region / RegionDetectionResult / RegionOCRResult / RegionType）
  2. region_detector 转换辅助函数（确定性输入输出）
     - _xyxy_to_normalized / _normalized_xywh_to_pixel
     - _map_class_name_to_region_type
     - _tensor_to_list（torch tensor / numpy array / list 兼容）
  3. region_detector VLM 转换路径（mock vlm_detect_regions，因 Ollama 无视觉模型）
  4. region_detector 降级路径（YOLO 不可用 → VLM → 空）
  5. region_ocr 结构化正则（title_block / dimension_area / parts_list / technical_requirements）
  6. region_ocr 裁剪边界钳制（bbox 超出图像边界）

运行：
    python tests/verify_task9_3_4.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

# 必须在 import paddleocr 之前设置（与 ocr_paddle.py 保持一致）
os.environ.setdefault("FLAGS_use_onednn", "0")
os.environ.setdefault("FLAGS_use_mkldnn", "0")

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def main() -> int:
    results: list[dict] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        mark = "[PASS]" if ok else "[FAIL]"
        print(f"  {mark} {name}: {detail}", flush=True)
        results.append({"name": name, "ok": ok, "detail": detail})

    print("=" * 70)
    print("Task 9.3 + 9.4 覆盖测试")
    print("=" * 70, flush=True)

    # ===== 阶段 1：schema 校验 =====
    print("\n阶段 1：schema 校验", flush=True)
    try:
        from app.schemas.region_detection import (
            Region,
            RegionDetectionResult,
            RegionOCRResult,
            RegionType,
        )
        check("schema 导入", True, "Region/RegionDetectionResult/RegionOCRResult/RegionType")
    except Exception as e:
        check("schema 导入", False, f"{type(e).__name__}: {e}")
        return _summary(results)

    # RegionType 枚举值
    expected_types = {
        "title_block", "dimension_area", "view_area", "parts_list",
        "revision_block", "technical_requirements", "other",
    }
    actual_types = {t.value for t in RegionType}
    check("RegionType 枚举完整", actual_types == expected_types, f"{sorted(actual_types)}")

    # Region 构造与校验
    try:
        r = Region(
            region_type=RegionType.TITLE_BLOCK,
            bbox=[10.0, 20.0, 100.0, 200.0],
            bbox_normalized=[0.1, 0.2, 0.5, 0.6],
            confidence=0.95,
            source="yolov11",
        )
        check("Region 构造", r.region_type == RegionType.TITLE_BLOCK, f"conf={r.confidence}")
    except Exception as e:
        check("Region 构造", False, str(e))

    # bbox 长度校验（min_length=4, max_length=4）
    try:
        Region(
            region_type=RegionType.OTHER,
            bbox=[1.0, 2.0, 3.0],  # 只有 3 个值，应失败
            bbox_normalized=[0.1, 0.2, 0.3, 0.4],
            confidence=0.5,
            source="heuristic",
        )
        check("Region bbox 长度校验", False, "3 元素 bbox 应被拒绝")
    except Exception:
        check("Region bbox 长度校验", True, "3 元素 bbox 被正确拒绝")

    # confidence 越界校验
    try:
        Region(
            region_type=RegionType.OTHER,
            bbox=[1.0, 2.0, 3.0, 4.0],
            bbox_normalized=[0.1, 0.2, 0.3, 0.4],
            confidence=1.5,  # > 1.0，应失败
            source="heuristic",
        )
        check("Region confidence 越界校验", False, "1.5 应被拒绝")
    except Exception:
        check("Region confidence 越界校验", True, "1.5 被正确拒绝")

    # RegionDetectionResult 含 tuple image_size
    try:
        dr = RegionDetectionResult(
            image_path="/tmp/x.png",
            image_size=(800, 600),
            regions=[],
            detector_source="none",
            elapsed_ms=10,
            warnings=["test"],
        )
        check("RegionDetectionResult 构造", dr.image_size == (800, 600), f"size={dr.image_size}")
    except Exception as e:
        check("RegionDetectionResult 构造", False, str(e))

    # RegionOCRResult
    try:
        ocr_r = RegionOCRResult(
            region_type=RegionType.TITLE_BLOCK,
            bbox=[1.0, 2.0, 3.0, 4.0],
            raw_texts=["图号:T-001"],
            raw_items=[{"text": "图号:T-001", "confidence": 0.9}],
            structured_data={"drawing_number": "T-001"},
            ocr_backend="paddle",
            avg_confidence=0.9,
            elapsed_ms=100,
        )
        check("RegionOCRResult 构造", ocr_r.ocr_backend == "paddle", f"backend={ocr_r.ocr_backend}")
    except Exception as e:
        check("RegionOCRResult 构造", False, str(e))

    # ===== 阶段 2：region_detector 转换辅助函数 =====
    print("\n阶段 2：region_detector 转换辅助函数", flush=True)
    try:
        from app.services.review import region_detector as rd
    except Exception as e:
        check("region_detector 导入", False, str(e))
        return _summary(results)
    check("region_detector 导入", True, "")

    # _xyxy_to_normalized：像素 → 归一化 [x,y,w,h]
    norm = rd._xyxy_to_normalized([100, 50, 200, 150], 400, 300)
    # x=100/400=0.25, y=50/300≈0.1667, w=100/400=0.25, h=100/300≈0.3333
    check(
        "_xyxy_to_normalized 基本转换",
        abs(norm[0] - 0.25) < 1e-6 and abs(norm[1] - 0.1667) < 1e-3
        and abs(norm[2] - 0.25) < 1e-6 and abs(norm[3] - 0.3333) < 1e-3,
        f"norm={[round(v, 4) for v in norm]}",
    )

    # 边界钳制：bbox 超出图像
    norm2 = rd._xyxy_to_normalized([-10, -10, 500, 500], 400, 300)
    check(
        "_xyxy_to_normalized 负值钳制",
        all(0.0 <= v <= 1.0 for v in norm2),
        f"norm={[round(v, 4) for v in norm2]}",
    )

    # 零尺寸防除零
    norm3 = rd._xyxy_to_normalized([10, 10, 20, 20], 0, 0)
    check("_xyxy_to_normalized 零尺寸防除零", norm3 == [0.0, 0.0, 0.0, 0.0], f"norm={norm3}")

    # _normalized_xywh_to_pixel：归一化 [x,y,w,h] → 像素 [x1,y1,x2,y2]
    pix = rd._normalized_xywh_to_pixel([0.25, 0.5, 0.5, 0.25], 400, 300)
    # x1=100, y1=150, x2=300, y2=225
    check(
        "_normalized_xywh_to_pixel 基本转换",
        abs(pix[0] - 100) < 1e-6 and abs(pix[1] - 150) < 1e-6
        and abs(pix[2] - 300) < 1e-6 and abs(pix[3] - 225) < 1e-6,
        f"pix={[round(v, 2) for v in pix]}",
    )

    # _map_class_name_to_region_type
    check(
        "_map_class_name title_block",
        rd._map_class_name_to_region_type("title_block") == RegionType.TITLE_BLOCK,
        "",
    )
    check(
        "_map_class_name 大写",
        rd._map_class_name_to_region_type("TITLE_BLOCK") == RegionType.TITLE_BLOCK,
        "大小写不敏感",
    )
    check(
        "_map_class_name 未知类",
        rd._map_class_name_to_region_type("unknown_thing") == RegionType.OTHER,
        "未知类归 OTHER",
    )
    check(
        "_map_class_name 空串",
        rd._map_class_name_to_region_type("") == RegionType.OTHER,
        "空串归 OTHER",
    )

    # _tensor_to_list：兼容 numpy / list / mock torch tensor
    import numpy as np

    arr = np.array([[1.0, 2.0, 3.0, 4.0], [5.0, 6.0, 7.0, 8.0]])
    lst = rd._tensor_to_list(arr)
    check(
        "_tensor_to_list numpy array",
        lst == [[1.0, 2.0, 3.0, 4.0], [5.0, 6.0, 7.0, 8.0]],
        f"len={len(lst)}",
    )

    lst2 = rd._tensor_to_list([1.0, 2.0, 3.0])
    check("_tensor_to_list 原生 list", lst2 == [1.0, 2.0, 3.0], "")

    # mock torch tensor（模拟 ultralytics 返回的 torch.Tensor）
    class _MockTensor:
        def __init__(self, arr):
            self._arr = np.asarray(arr)

        def cpu(self):
            return self

        def numpy(self):
            return self._arr

    mock_t = _MockTensor([0.95, 0.88])
    lst3 = rd._tensor_to_list(mock_t)
    check("_tensor_to_list mock torch tensor", lst3 == [0.95, 0.88], f"{lst3}")

    # ===== 阶段 3：region_detector VLM 转换路径（mock） =====
    print("\n阶段 3：region_detector VLM 转换路径（mock vlm_detect_regions）", flush=True)

    # 找一张真实图片用于测试（_detect_with_vlm 需要传 image_path，但 mock 后不会读图）
    test_img = BACKEND / "tmp_review_images" / "sample.png"
    if not test_img.is_file():
        check("测试图片存在", False, str(test_img))
    else:
        check("测试图片存在", True, test_img.name)

        # mock vlm_detect_regions 返回 VLM 风格结果
        mock_vlm_output = [
            {"name": "title_block", "bbox": [0.7, 0.8, 0.25, 0.18]},
            {"name": "dimension_area", "bbox": [0.1, 0.1, 0.4, 0.3]},
            {"name": "unknown_region", "bbox": [0.5, 0.5, 0.1, 0.1]},  # 未知类名 → OTHER
            {"name": "bad", "bbox": [0.1, 0.1]},  # bbox 长度不对，应被跳过
        ]
        with patch("app.services.review.vlm_ocr.vlm_detect_regions", return_value=mock_vlm_output):
            regions = rd._detect_with_vlm(test_img, 686, 584)

        check("VLM 转换区域数", len(regions) == 3, f"count={len(regions)}（应跳过 bad bbox）")
        if regions:
            check(
                "VLM 区域 source=vlm",
                all(r.source == "vlm" for r in regions),
                f"sources={[r.source for r in regions]}",
            )
            check(
                "VLM 区域 confidence=0.6",
                all(abs(r.confidence - 0.6) < 1e-6 for r in regions),
                "",
            )
            # 第一个区域 title_block，验证像素 bbox 计算正确
            r0 = regions[0]
            # norm [0.7, 0.8, 0.25, 0.18] → pixel [0.7*686, 0.8*584, (0.7+0.25)*686, (0.8+0.18)*584]
            expected_x1 = 0.7 * 686
            expected_y1 = 0.8 * 584
            check(
                "VLM 区域像素 bbox 计算",
                abs(r0.bbox[0] - expected_x1) < 1e-3 and abs(r0.bbox[1] - expected_y1) < 1e-3,
                f"x1={r0.bbox[0]:.2f}(期望{expected_x1:.2f}) y1={r0.bbox[1]:.2f}(期望{expected_y1:.2f})",
            )
            # 未知类名归 OTHER
            r2 = regions[2]
            check(
                "VLM 未知类名归 OTHER",
                r2.region_type == RegionType.OTHER,
                f"type={r2.region_type.value}",
            )

        # mock VLM 返回空
        with patch("app.services.review.vlm_ocr.vlm_detect_regions", return_value=[]):
            empty_regions = rd._detect_with_vlm(test_img, 686, 584)
        check("VLM 返回空时 _detect_with_vlm 返回 []", empty_regions == [], "")

    # ===== 阶段 4：region_detector 降级路径 =====
    print("\n阶段 4：region_detector 降级路径", flush=True)
    check("is_ultralytics_installed", rd.is_ultralytics_installed() is False, "本环境未装 ultralytics")
    check("is_detector_available", rd.is_detector_available() is False, "权重不存在")
    check(
        "detect_regions 不存在图片返回空",
        rd.detect_regions(Path("/nonexistent.png")) == [],
        "",
    )

    # detect_regions_detailed on real image → detector_source 应为 none（VLM 也无视觉模型）
    if test_img.is_file():
        det = rd.detect_regions_detailed(test_img)
        check(
            "降级路径 detector_source=none",
            det.detector_source == "none",
            f"source={det.detector_source}",
        )
        check(
            "降级路径 warnings 非空",
            len(det.warnings) >= 2,
            f"warnings={det.warnings}",
        )
        check(
            "降级路径 image_size 正确",
            det.image_size == (686, 584),
            f"size={det.image_size}",
        )

    # ===== 阶段 5：region_ocr 结构化正则 =====
    print("\n阶段 5：region_ocr 结构化正则", flush=True)
    try:
        from app.services.review import region_ocr as ro
    except Exception as e:
        check("region_ocr 导入", False, str(e))
        return _summary(results)
    check("region_ocr 导入", True, "")

    # title_block 中文字段
    tb = ro._structure_title_block(["图号:T-1001", "材料:45#", "比例:1:2", "日期:2024-01-01", "制图:张三", "V2"])
    check("title_block drawing_number", tb.get("drawing_number") == "T-1001", f"{tb.get('drawing_number')}")
    check("title_block material", tb.get("material") == "45#", f"{tb.get('material')}")
    check("title_block scale", tb.get("scale") == "1:2", f"{tb.get('scale')}")
    check("title_block date", tb.get("date") == "2024-01-01", f"{tb.get('date')}")
    check("title_block drawn_by", tb.get("drawn_by") == "张三", f"{tb.get('drawn_by')}")
    check("title_block version", tb.get("version") == "V2", f"{tb.get('version')}")

    # dimension_area 含 Ø/螺纹/半径/公差/角度
    dim = ro._structure_dimension_area(["Ø20", "M8x1.25", "R5", "±0.1", "45°", "100"])
    check("dimension diameters", dim.get("diameters") == ["20"], f"{dim.get('diameters')}")
    check("dimension threads", "M8x1.25" in dim.get("threads", []), f"{dim.get('threads')}")
    check("dimension radii", dim.get("radii") == ["5"], f"{dim.get('radii')}")
    check("dimension tolerances", dim.get("tolerances") == ["0.1"], f"{dim.get('tolerances')}")
    check("dimension angles", dim.get("angles") == ["45"], f"{dim.get('angles')}")
    check("dimension_count", dim.get("dimension_count") == 5, f"{dim.get('dimension_count')}")

    # parts_list 表格行解析
    pl = ro._structure_parts_list([
        "001  Bolt  10  Q235  none",
        "002  Nut   20  45#   spare",
        "single_column_row",
    ])
    check("parts_list row_count", pl.get("row_count") == 3, f"{pl.get('row_count')}")
    rows = pl.get("rows", [])
    if rows:
        check("parts_list row0 parts_number", rows[0].get("parts_number") == "001", f"{rows[0].get('parts_number')}")
        check("parts_list row0 name", rows[0].get("name") == "Bolt", f"{rows[0].get('name')}")
        check("parts_list row0 quantity", rows[0].get("quantity") == "10", f"{rows[0].get('quantity')}")
        check("parts_list row0 material", rows[0].get("material") == "Q235", f"{rows[0].get('material')}")

    # technical_requirements 拼接
    tr = ro._structure_technical_requirements(["技术要求", "1.未注公差按GB/T 1804-m", "2.去毛刺"])
    check(
        "tech_req text 拼接",
        "1.未注公差按GB/T 1804-m" in tr.get("text", ""),
        f"len={len(tr.get('text', ''))}",
    )
    check("tech_req line_count", tr.get("line_count") == 3, f"{tr.get('line_count')}")

    # default 结构化
    d = ro._structure_default(["a", "b"])
    check("default line_count", d.get("line_count") == 2, f"{d.get('line_count')}")

    # _structure_by_region_type 分发
    check(
        "分发 title_block",
        ro._structure_by_region_type(RegionType.TITLE_BLOCK, ["图号:T-1"]).get("drawing_number") == "T-1",
        "",
    )
    check(
        "分发 OTHER 走 default",
        "texts" in ro._structure_by_region_type(RegionType.OTHER, ["x"]),
        "",
    )

    # ===== 阶段 6：region_ocr 裁剪边界钳制 =====
    print("\n阶段 6：region_ocr 裁剪边界钳制", flush=True)
    # 用合成图测试 bbox 超出边界的裁剪
    import tempfile

    from PIL import Image

    tmp_dir = Path(tempfile.mkdtemp(prefix="verify_ocr_"))
    try:
        synth = tmp_dir / "clamp_test.png"
        Image.new("RGB", (200, 150), "white").save(str(synth))

        # bbox 超出边界 [(-10,-10), (300, 200)] → 应被钳制到 [(0,0),(200,150)]
        from app.schemas.region_detection import Region as R

        big_region = R(
            region_type=RegionType.OTHER,
            bbox=[-10.0, -10.0, 300.0, 200.0],
            bbox_normalized=[0.0, 0.0, 1.0, 1.0],
            confidence=1.0,
            source="heuristic",
        )
        ocr_results = ro.ocr_in_regions(synth, [big_region], ocr_backend="paddle")
        check("裁剪边界钳制返回结果", len(ocr_results) == 1, f"count={len(ocr_results)}")
        # 钳制后应为 200x150，不小于阈值，应执行 OCR（即使无文字）
        check(
            "裁剪边界钳制未跳过",
            ocr_results[0].ocr_backend in ("paddle", "none", "vlm"),
            f"backend={ocr_results[0].ocr_backend}",
        )

        # 过小区域跳过
        small_region = R(
            region_type=RegionType.OTHER,
            bbox=[5.0, 5.0, 25.0, 25.0],  # 20x20 < 50
            bbox_normalized=[0.0, 0.0, 0.1, 0.13],
            confidence=1.0,
            source="heuristic",
        )
        ocr_results2 = ro.ocr_in_regions(synth, [small_region], ocr_backend="paddle")
        check(
            "过小区域被跳过",
            ocr_results2[0].ocr_backend == "skipped",
            f"backend={ocr_results2[0].ocr_backend}",
        )
    finally:
        import shutil

        shutil.rmtree(tmp_dir, ignore_errors=True)

    return _summary(results)


def _summary(results: list[dict]) -> int:
    print("\n" + "=" * 70, flush=True)
    total = len(results)
    passed = sum(1 for r in results if r["ok"])
    failed = total - passed
    print(f"总计：{passed}/{total} PASS, {failed} FAIL", flush=True)
    if failed:
        print("\n失败项：", flush=True)
        for r in results:
            if not r["ok"]:
                print(f"  [FAIL] {r['name']}: {r['detail']}", flush=True)
    print("=" * 70, flush=True)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
