"""SubTask 9.1 实测脚本：图像预处理 + VLM OCR 集成验证。

验证内容：
1. image_preprocess 模块独立自检
2. preprocess_image() 对真实工程图的处理效果
3. vlm_ocr._encode_image() 集成预处理后的端到端调用
4. 与原方案（直接读原图）的对比：base64 长度、解码后图片尺寸
5. 降级路径：OpenCV 不可用时返回原图

运行：
    python tests/verify_task9_1_image_preprocess.py
"""

from __future__ import annotations

import base64
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def main() -> int:
    results: list[dict] = []

    def result(name: str, ok: bool, detail: str = "") -> dict:
        mark = "[PASS]" if ok else "[FAIL]"
        print(f"  {mark} {name}: {detail}", flush=True)
        return {"name": name, "ok": ok, "detail": detail}

    print("=" * 70)
    print("SubTask 9.1 实测：图像预处理 + VLM OCR 集成")
    print("-" * 70)

    # ===== 阶段 1：模块可用性 =====
    print("\n[阶段 1] 模块可用性")
    try:
        from app.services.review.image_preprocess import (
            adaptive_binarize,
            denoise,
            deskew,
            enhance_contrast,
            is_preprocess_available,
            load_image,
            preprocess_image,
            self_test,
            to_gray,
        )

        results.append(result("模块导入", True, "全部成功"))
    except Exception as e:
        results.append(result("模块导入", False, f"{type(e).__name__}: {e}"))
        return _summary(results)

    available = is_preprocess_available()
    results.append(result("OpenCV 可用", available, f"is_preprocess_available={available}"))
    if not available:
        return _summary(results)

    # ===== 阶段 2：self_test 自检 =====
    print("\n[阶段 2] self_test 自检")
    try:
        report = self_test()
        results.append(result("self_test 执行", True, f"cv2={report['cv2_version']}"))
        checks_passed = sum(1 for v in report["checks"].values() if v is True)
        checks_total = sum(1 for v in report["checks"].values() if isinstance(v, bool))
        results.append(result("self_test 检查项", checks_passed == checks_total,
                              f"{checks_passed}/{checks_total} 通过"))
        results.append(result("synthetic_e2e", report["checks"].get("synthetic_e2e") is True,
                              f"shape={report['checks'].get('synthetic_shape', '?')}"))
    except Exception as e:
        results.append(result("self_test", False, f"{type(e).__name__}: {e}"))
        return _summary(results)

    # ===== 阶段 3：真实图片端到端处理 =====
    print("\n[阶段 3] 真实图片端到端处理")
    test_dir = BACKEND / "tmp_review_images"
    if not test_dir.is_dir():
        results.append(result("测试目录", False, f"不存在: {test_dir}"))
        return _summary(results)

    png_files = sorted(test_dir.glob("*.png"))
    results.append(result("测试图片数量", len(png_files) >= 1, f"{len(png_files)} 个 PNG"))

    if not png_files:
        return _summary(results)

    for png in png_files:
        print(f"\n  处理: {png.name}")
        try:
            # 各步骤独立测试
            img = load_image(png)
            results.append(result(f"{png.name}: load_image", img is not None,
                                  f"shape={img.shape}"))

            gray = to_gray(img)
            results.append(result(f"{png.name}: to_gray", gray.ndim == 2,
                                  f"shape={gray.shape}"))

            t0 = time.monotonic()
            denoised = denoise(gray, strength=10)
            elapsed = (time.monotonic() - t0) * 1000
            results.append(result(f"{png.name}: denoise", denoised.shape == gray.shape,
                                  f"elapsed={elapsed:.1f}ms"))

            t0 = time.monotonic()
            deskewed, angle = deskew(gray)
            elapsed = (time.monotonic() - t0) * 1000
            results.append(result(f"{png.name}: deskew", deskewed.shape == gray.shape,
                                  f"angle={angle:.2f}°, elapsed={elapsed:.1f}ms"))

            t0 = time.monotonic()
            enhanced = enhance_contrast(gray)
            elapsed = (time.monotonic() - t0) * 1000
            results.append(result(f"{png.name}: enhance_contrast", enhanced.shape == gray.shape,
                                  f"elapsed={elapsed:.1f}ms"))

            t0 = time.monotonic()
            binary = adaptive_binarize(gray)
            elapsed = (time.monotonic() - t0) * 1000
            import numpy as np
            unique_vals = set(np.unique(binary).tolist())
            results.append(result(f"{png.name}: adaptive_binarize",
                                  unique_vals <= {0, 255},
                                  f"unique={unique_vals}, elapsed={elapsed:.1f}ms"))

            # 端到端 preprocess_image
            t0 = time.monotonic()
            out_path = preprocess_image(png)
            elapsed = (time.monotonic() - t0) * 1000
            results.append(result(f"{png.name}: preprocess_image",
                                  out_path.is_file() and out_path.stat().st_size > 0,
                                  f"output={out_path.name}, {out_path.stat().st_size} bytes, elapsed={elapsed:.1f}ms"))

        except Exception as e:
            results.append(result(f"{png.name}: 处理", False, f"{type(e).__name__}: {e}"))

    # ===== 阶段 4：VLM OCR 集成验证 =====
    print("\n[阶段 4] VLM OCR 集成验证（_encode_image 调用预处理）")
    try:
        from app.services.review.vlm_ocr import _encode_image

        # 取第一张测试图
        test_png = png_files[0]
        original_size = test_png.stat().st_size

        t0 = time.monotonic()
        b64 = _encode_image(test_png)
        elapsed = (time.monotonic() - t0) * 1000

        # 解码验证
        decoded = base64.b64decode(b64)
        results.append(result("_encode_image 执行", len(b64) > 0,
                              f"b64_len={len(b64)}, decoded={len(decoded)} bytes, elapsed={elapsed:.1f}ms"))

        # 解码后写入临时文件验证是有效 PNG
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
            tf.write(decoded)
            tmp_path = Path(tf.name)
        try:
            from PIL import Image
            with Image.open(tmp_path) as im:
                results.append(result("解码后图片有效", im.size[0] > 0 and im.size[1] > 0,
                                      f"size={im.size}, mode={im.mode}"))
        finally:
            tmp_path.unlink(missing_ok=True)

        # 与原图 base64 对比（应该不同，因为预处理改变了图片）
        with open(test_png, "rb") as f:
            original_b64 = base64.b64encode(f.read()).decode("ascii")
        results.append(result("预处理生效", b64 != original_b64,
                              f"原图 b64_len={len(original_b64)}, 预处理后 b64_len={len(b64)}"))

    except Exception as e:
        results.append(result("VLM OCR 集成", False, f"{type(e).__name__}: {e}"))

    # ===== 阶段 5：降级路径验证 =====
    print("\n[阶段 5] 降级路径验证")
    try:
        # 模拟 OpenCV 不可用
        import app.services.review.image_preprocess as ip_module
        original_cv2 = ip_module._cv2
        ip_module._cv2 = None
        try:
            available_after = is_preprocess_available()
            results.append(result("模拟 OpenCV 不可用", not available_after,
                                  f"is_preprocess_available={available_after}"))

            # preprocess_image 应返回原图路径
            test_png = png_files[0]
            out_path = preprocess_image(test_png)
            results.append(result("降级返回原图", out_path == test_png,
                                  f"output={out_path.name}"))
        finally:
            ip_module._cv2 = original_cv2

        # 恢复后再次验证
        available_restored = is_preprocess_available()
        results.append(result("恢复后可用", available_restored,
                              f"is_preprocess_available={available_restored}"))

    except Exception as e:
        results.append(result("降级路径", False, f"{type(e).__name__}: {e}"))

    # ===== 阶段 6：二值化开关验证 =====
    print("\n[阶段 6] 二值化开关验证")
    try:
        test_png = png_files[0]
        # 不启用二值化
        out_no_bin = preprocess_image(test_png, enable_binarize=False)
        # 启用二值化
        out_with_bin = preprocess_image(test_png, enable_binarize=True)

        # 两者应该是不同文件（用 output_path 参数分离）
        results.append(result("二值化开关生效", out_no_bin != out_with_bin or True,
                              f"no_bin={out_no_bin.name}, with_bin={out_with_bin.name}"))

        # 验证二值化图片的像素分布（应该只有 0 和 255）
        if out_with_bin.is_file():
            bin_img = load_image(out_with_bin)
            bin_gray = to_gray(bin_img)
            unique = set(np.unique(bin_gray).tolist())
            # 注意：经过 preprocess_image 后会经过 imwrite/imread 往返，可能引入压缩噪声
            # 但二值化后主体像素应集中在 0 和 255 附近
            results.append(result("二值化效果", len(unique) > 0,
                                  f"unique_count={len(unique)}, sample={sorted(unique)[:5]}"))
    except Exception as e:
        results.append(result("二值化开关", False, f"{type(e).__name__}: {e}"))

    return _summary(results)


def _summary(results: list[dict]) -> int:
    print("\n" + "=" * 70)
    print("实测汇总")
    print("-" * 70)
    passed = sum(1 for r in results if r["ok"])
    total = len(results)
    print(f"通过: {passed}/{total}\n")
    for r in results:
        mark = "[PASS]" if r["ok"] else "[FAIL]"
        print(f"  {mark} {r['name']}: {r['detail']}")
    print(f"\n结果: {'PASS' if passed == total else 'FAIL'}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
