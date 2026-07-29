"""审查报告导出（SubTask 4.7）：HTML + PDF。

- generate_html_report()：Jinja2 渲染 HTML，含基本信息/评分/缺陷表/图片高亮
- generate_pdf_report()：HTML→PDF，支持多后端（weasyprint / wkhtmltopdf / playwright / xhtml2pdf）
  由 settings.PDF_BACKEND 控制，默认 "auto" 按优先级降级；全部不可用时返回 None（仅 HTML）

报告模板：templates/report.html.j2
默认输出目录：./reports/
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from pathlib import Path

from app.logging import get_logger
from app.schemas.review_detail import ReviewReportData, ReviewResult
from app.services.review.scoring import severity_counts

log = get_logger(__name__)

# 默认报告输出目录（相对 backend/）
_DEFAULT_REPORT_DIR = Path("./reports")
# 默认模板目录
_DEFAULT_TEMPLATE_DIR = Path(__file__).parent / "templates"
# 默认模板文件名
_DEFAULT_TEMPLATE_NAME = "report.html.j2"


def _read_image_as_base64(image_path: str | Path) -> str | None:
    """读取图片为 base64 字符串（用于 HTML 内嵌）。"""
    p = Path(image_path)
    if not p.is_file():
        return None
    try:
        return base64.b64encode(p.read_bytes()).decode("ascii")
    except Exception as e:  # noqa: BLE001
        log.warning("review.report.image_encode_failed", path=str(p), error=str(e))
        return None


def _build_report_data(result: ReviewResult) -> ReviewReportData:
    """从 ReviewResult 构造模板数据。"""
    counts = severity_counts(result.defects)
    image_b64: str | None = None
    image_filename: str | None = None
    if result.metadata.get("image_path"):
        image_b64 = _read_image_as_base64(result.metadata["image_path"])
        if image_b64 is None:
            image_filename = Path(result.metadata["image_path"]).name

    return ReviewReportData(
        task_id=result.task_id,
        file_key=result.file_key,
        file_type=result.file_type,
        compliance_score=result.compliance_score,
        severity_counts=counts,
        defects=result.defects,
        standards_applied=result.standards_applied,
        review_mode=result.review_mode,
        image_filename=image_filename,
        image_base64=image_b64,
        generated_at=datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        metadata=result.metadata,
    )


def generate_html_report(
    result: ReviewResult,
    template_dir: Path | None = None,
    output_path: Path | None = None,
) -> Path:
    """用 Jinja2 渲染 HTML 报告。

    Args:
        result: 审图结果
        template_dir: 模板目录；None 用默认 _DEFAULT_TEMPLATE_DIR
        output_path: 输出 HTML 路径；None 生成在 _DEFAULT_REPORT_DIR 下，
            文名为 review_{task_id}.html

    Returns:
        HTML 文件路径
    """
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    tmpl_dir = Path(template_dir) if template_dir else _DEFAULT_TEMPLATE_DIR
    if output_path is None:
        _DEFAULT_REPORT_DIR.mkdir(parents=True, exist_ok=True)
        output_path = _DEFAULT_REPORT_DIR / f"review_{result.task_id}.html"
    else:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

    data = _build_report_data(result)

    env = Environment(
        loader=FileSystemLoader(str(tmpl_dir)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template(_DEFAULT_TEMPLATE_NAME)
    html = template.render(**data.model_dump())

    output_path.write_text(html, encoding="utf-8")

    log.info(
        "review.report.html_done",
        path=str(output_path),
        size_bytes=output_path.stat().st_size,
    )
    return output_path


def _generate_pdf_via_weasyprint(html_path: Path, output_path: Path) -> Path | None:
    """weasyprint 后端：原生 CSS 渲染最佳，但 Windows 需要 GTK 运行时库。

    捕获自身异常并 log.warning，不向上抛。
    """
    try:
        from weasyprint import HTML
    except Exception as e:  # noqa: BLE001
        log.warning(
            "review.report.weasyprint_unavailable",
            error=str(e),
            hint="weasyprint 需要 GTK 运行时库；Windows 请安装 MSYS2 或改用其他 PDF_BACKEND",
        )
        return None
    try:
        HTML(filename=str(html_path)).write_pdf(str(output_path))
        return output_path
    except Exception as e:  # noqa: BLE001
        log.warning("review.report.weasyprint_failed", error=str(e))
        return None


def _generate_pdf_via_wkhtmltopdf(html_path: Path, output_path: Path) -> Path | None:
    """wkhtmltopdf 后端：基于 QtWebKit，需 wkhtmltopdf.exe。

    CSS 支持有限；捕获自身异常并 log.warning，不向上抛。
    """
    try:
        import pdfkit  # type: ignore[import-not-found]
    except Exception as e:  # noqa: BLE001
        log.warning(
            "review.report.wkhtmltopdf_no_pdfkit",
            error=str(e),
            hint="请 `pip install pdfkit` 并安装 wkhtmltopdf.exe",
        )
        return None
    try:
        # pdfkit.from_file 接受 str 路径；options 关闭 smart shrinking 保证尺寸稳定
        options = {
            "encoding": "UTF-8",
            "quiet": "",
            "enable-local-file-access": "",
        }
        pdfkit.from_file(str(html_path), str(output_path), options=options)
        if output_path.is_file() and output_path.stat().st_size > 0:
            return output_path
        log.warning("review.report.wkhtmltopdf_empty_output", path=str(output_path))
        return None
    except Exception as e:  # noqa: BLE001
        log.warning("review.report.wkhtmltopdf_failed", error=str(e))
        return None


def _generate_pdf_via_playwright(html_path: Path, output_path: Path) -> Path | None:
    """playwright 后端：headless chromium 打印 PDF。

    仅 chromium 支持 page.pdf()；捕获自身异常并 log.warning，不向上抛。
    """
    try:
        from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]
    except Exception as e:  # noqa: BLE001
        log.warning(
            "review.report.playwright_unavailable",
            error=str(e),
            hint="请 `pip install playwright` 并 `python -m playwright install chromium`",
        )
        return None
    try:
        # file:// URL：Windows 路径需用正斜杠
        file_url = html_path.resolve().as_uri()
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page()
                page.goto(file_url, wait_until="load")
                page.pdf(path=str(output_path), format="A4", print_background=True)
            finally:
                browser.close()
        if output_path.is_file() and output_path.stat().st_size > 0:
            return output_path
        log.warning("review.report.playwright_empty_output", path=str(output_path))
        return None
    except Exception as e:  # noqa: BLE001
        log.warning("review.report.playwright_failed", error=str(e))
        return None


def _generate_pdf_via_xhtml2pdf(html_path: Path, output_path: Path) -> Path | None:
    """xhtml2pdf 后端：纯 Python 无外部依赖，CSS 支持最有限。

    捕获自身异常并 log.warning，不向上抛。
    """
    try:
        from xhtml2pdf import pisa  # type: ignore[import-not-found]
    except Exception as e:  # noqa: BLE001
        log.warning(
            "review.report.xhtml2pdf_unavailable",
            error=str(e),
            hint="请 `pip install xhtml2pdf`",
        )
        return None
    try:
        # xhtml2pdf 对中文支持有限，需 HTML 内嵌 @font-face 或 CSS 指定 CJK 字体
        # 这里使用文件源 + 输出文件流的标准用法
        source_html = html_path.read_text(encoding="utf-8")
        with open(output_path, "wb") as out_fh:
            result = pisa.CreatePDF(
                src=source_html,
                dest=out_fh,
                encoding="utf-8",
            )
        # pisa.CreatePDF 返回 context 对象，err 属性记录错误数
        err_count = getattr(result, "err", 1) if result else 1
        if err_count > 0:
            log.warning(
                "review.report.xhtml2pdf_errors",
                err_count=err_count,
                log=getattr(result, "log", None),
            )
        if output_path.is_file() and output_path.stat().st_size > 0:
            return output_path
        log.warning("review.report.xhtml2pdf_empty_output", path=str(output_path))
        return None
    except Exception as e:  # noqa: BLE001
        log.warning("review.report.xhtml2pdf_failed", error=str(e))
        return None


# 后端优先级顺序（auto 模式按此顺序尝试）
_PDF_BACKENDS: tuple[tuple[str, callable], ...] = (
    ("weasyprint", _generate_pdf_via_weasyprint),
    ("wkhtmltopdf", _generate_pdf_via_wkhtmltopdf),
    ("playwright", _generate_pdf_via_playwright),
    ("xhtml2pdf", _generate_pdf_via_xhtml2pdf),
)


def generate_pdf_report(
    html_path: Path,
    output_path: Path | None = None,
) -> Path | None:
    """将 HTML 转 PDF，支持多后端（weasyprint / wkhtmltopdf / playwright / xhtml2pdf）。

    后端选择由 settings.PDF_BACKEND 控制：
        - "auto": 按优先级 weasyprint → wkhtmltopdf → playwright → xhtml2pdf 依次尝试
        - 显式指定: 仅用指定后端，失败即返回 None
    全部失败时返回 None 并 log.warning（保持现有降级语义）。

    Args:
        html_path: HTML 文件路径
        output_path: 输出 PDF 路径；None 同目录下同名 .pdf

    Returns:
        PDF 文件路径；后端全部不可用时返回 None
    """
    html_path = Path(html_path)
    if output_path is None:
        output_path = html_path.with_suffix(".pdf")
    else:
        output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 延迟导入避免循环依赖
    from app.config import settings

    backend_cfg = (settings.PDF_BACKEND or "auto").strip().lower()

    if backend_cfg == "auto":
        # auto 模式：按优先级依次尝试，每个后端失败则降级到下一个
        for name, fn in _PDF_BACKENDS:
            log.info("review.report.pdf_try_backend", backend=name, mode="auto")
            result = fn(html_path, output_path)
            if result is not None:
                log.info(
                    "review.report.pdf_done",
                    path=str(result),
                    size_bytes=result.stat().st_size,
                    backend=name,
                )
                return result
        log.warning(
            "review.report.pdf_all_backends_failed",
            mode="auto",
            tried=[name for name, _ in _PDF_BACKENDS],
        )
        return None

    # 显式后端模式
    fn = dict(_PDF_BACKENDS).get(backend_cfg)
    if fn is None:
        log.warning("review.report.pdf_unknown_backend", backend=backend_cfg)
        return None
    log.info("review.report.pdf_try_backend", backend=backend_cfg, mode="explicit")
    result = fn(html_path, output_path)
    if result is not None:
        log.info(
            "review.report.pdf_done",
            path=str(result),
            size_bytes=result.stat().st_size,
            backend=backend_cfg,
        )
        return result
    log.warning(
        "review.report.pdf_backend_failed",
        backend=backend_cfg,
        mode="explicit",
    )
    return None
