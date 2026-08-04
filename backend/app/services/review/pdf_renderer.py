"""PDF 文件渲染为 PNG 图片（供 VLM 识别）。

使用 pypdfium2（基于 PDFium）将 PDF 页面渲染为位图。
- 单页 PDF：直接保存为 PNG
- 多页 PDF：纵向拼接为一张长图（最大高度 8192px）

版本要求（2026-08-02 调研后更新）：
- pypdfium2 >= 5.12.1（2026-07-17 最新稳定版）
- 5.x 与 4.x API 完全兼容，无需代码改动
- 锁定 <6.0 上限，避免 API 破坏性变更

内存保护（针对 A0/A1 工程图）：
- 单页像素数上限 _MAX_SINGLE_PAGE_PIXELS（默认 8000 万像素，约 8000x10000）
- 超过时自动降低 DPI 渲染，并在日志中警告
- 防止 A0 PDF 在 200 DPI 下产生 ~135M 像素 × 4 字节 = ~540MB 内存峰值导致 OOM
"""

from __future__ import annotations

from pathlib import Path

from app.logging import get_logger

log = get_logger(__name__)

# 多页拼接长图最大高度（像素）
_MAX_LONG_IMAGE_HEIGHT = 8192

# 单页像素数上限（防止 A0/A1 工程图 OOM）
# A0 @ 200 DPI ≈ 13890×9724 = 135M 像素 → 约 540MB 内存（RGBA）
# 上限设为 80M 像素（约 8000×10000），超过时自动降低 DPI
_MAX_SINGLE_PAGE_PIXELS = 80_000_000

# 单页任一维度像素上限（PNG 单边硬上限，避免 PIL 保存失败）
_MAX_SINGLE_PAGE_DIMENSION = 16384


def render_pdf_to_image(
    pdf_path: str | Path,
    output_path: str | Path | None = None,
    dpi: int = 200,
    max_pages: int | None = None,
) -> str:
    """将 PDF 渲染为 PNG 图片。

    单页 PDF 直接保存为 PNG；多页 PDF 纵向拼接为一张长图。

    Args:
        pdf_path: PDF 文件路径
        output_path: 输出 PNG 路径；None 则生成在 pdf_path 同目录下同名 .png
        dpi: 渲染分辨率，默认 200 DPI；超大页面会自动降级防止 OOM
        max_pages: 最大渲染页数；None 表示全部，超出会截断并 log

    Returns:
        输出 PNG 文件路径

    Raises:
        ValueError: PDF 损坏或加密无法渲染
    """
    # 延迟导入：避免模块加载时强依赖 pypdfium2
    import pypdfium2

    pdf_path = Path(pdf_path)
    if output_path is None:
        output_path = pdf_path.with_suffix(".png")
    else:
        output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    scale = dpi / 72  # PDF 默认 72 DPI

    # 打开 PDF：区分加密与损坏
    try:
        pdf = pypdfium2.PdfDocument(str(pdf_path))
    except pypdfium2.PdfiumError as e:
        msg = str(e).lower()
        if "password" in msg or "encrypt" in msg:
            raise ValueError(f"PDF 文件已加密，无法渲染: {pdf_path}") from e
        raise ValueError(f"PDF 文件损坏或无法解析: {pdf_path}") from e
    except Exception as e:
        raise ValueError(f"PDF 文件损坏或无法解析: {pdf_path}") from e

    try:
        total_pages = len(pdf)
        log.info(
            "review.pdf.opened",
            pdf=str(pdf_path),
            total_pages=total_pages,
            dpi=dpi,
        )

        # 应用 max_pages 截断
        if max_pages is not None and total_pages > max_pages:
            render_pages = max_pages
            log.warning(
                "review.pdf.pages_truncated",
                pdf=str(pdf_path),
                total_pages=total_pages,
                max_pages=max_pages,
            )
        else:
            render_pages = total_pages

        # 逐页渲染为 PIL 图片，拼接时受长图高度限制
        pil_images: list = []
        current_height = 0
        for i in range(render_pages):
            page = pdf[i]
            # 获取页面尺寸（point 单位，1 point = 1/72 inch）以计算预期像素数
            try:
                page_width_pt = float(page.get_width())
                page_height_pt = float(page.get_height())
            except Exception:  # noqa: BLE001
                # 获取尺寸失败时用原始 scale
                page_width_pt = None
                page_height_pt = None

            page_scale = scale
            if page_width_pt is not None and page_height_pt is not None:
                expected_width_px = int(page_width_pt * scale)
                expected_height_px = int(page_height_pt * scale)
                expected_pixels = expected_width_px * expected_height_px

                # 像素上限保护：超过则按比例降低 scale
                if expected_pixels > _MAX_SINGLE_PAGE_PIXELS:
                    # 计算降级系数：sqrt(max_pixels / expected_pixels)
                    reduction = (_MAX_SINGLE_PAGE_PIXELS / expected_pixels) ** 0.5
                    page_scale = scale * reduction
                    log.warning(
                        "review.pdf.page_scale_reduced",
                        pdf=str(pdf_path),
                        page=i,
                        original_scale=scale,
                        reduced_scale=page_scale,
                        original_pixels=expected_pixels,
                        max_pixels=_MAX_SINGLE_PAGE_PIXELS,
                    )

                # 同时检查单维度上限（PNG 单边硬上限，避免 PIL 保存失败）
                expected_w = int(page_width_pt * page_scale)
                expected_h = int(page_height_pt * page_scale)
                if (
                    expected_w > _MAX_SINGLE_PAGE_DIMENSION
                    or expected_h > _MAX_SINGLE_PAGE_DIMENSION
                ):
                    dim_reduction = _MAX_SINGLE_PAGE_DIMENSION / max(
                        expected_w, expected_h
                    )
                    page_scale = page_scale * dim_reduction
                    log.warning(
                        "review.pdf.page_dimension_capped",
                        pdf=str(pdf_path),
                        page=i,
                        reduced_scale=page_scale,
                        max_dimension=_MAX_SINGLE_PAGE_DIMENSION,
                    )

            bitmap = page.render(scale=page_scale)
            pil_image = bitmap.to_pil()
            # 多页拼接时检查长图高度上限
            if pil_images and current_height + pil_image.height > _MAX_LONG_IMAGE_HEIGHT:
                log.warning(
                    "review.pdf.long_image_truncated",
                    pdf=str(pdf_path),
                    rendered_pages=len(pil_images),
                    max_height=_MAX_LONG_IMAGE_HEIGHT,
                )
                break
            pil_images.append(pil_image)
            current_height += pil_image.height

        actual_pages = len(pil_images)
        if actual_pages == 0:
            raise ValueError(f"PDF 无可渲染页面: {pdf_path}")

        if actual_pages == 1:
            # 单页直接保存
            pil_images[0].save(str(output_path), "PNG")
        else:
            # 多页纵向拼接：宽度取最大，高度累加
            from PIL import Image

            max_width = max(img.width for img in pil_images)
            total_height = sum(img.height for img in pil_images)
            canvas = Image.new("RGB", (max_width, total_height), "white")
            y_offset = 0
            for img in pil_images:
                canvas.paste(img, (0, y_offset))
                y_offset += img.height
            canvas.save(str(output_path), "PNG")

        file_size = output_path.stat().st_size
        log.info(
            "review.pdf.render_done",
            pdf=str(pdf_path),
            png=str(output_path),
            total_pages=total_pages,
            rendered_pages=actual_pages,
            file_size=file_size,
        )
        return str(output_path)
    finally:
        pdf.close()
