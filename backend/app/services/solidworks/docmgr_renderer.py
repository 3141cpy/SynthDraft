"""SolidWorks Document Manager API 渲染器（Task 12）。

在不安装 SolidWorks 主程序的前提下，通过 SwDocumentMgr.dll 提取 SLDPRT/SLDASM
文件内嵌的预览图 PNG。仅需 DLL + license key（SolidWorks 订阅用户免费申请）。

依赖：
- pythonnet（clr 模块）
- SwDocumentMgr.dll（SolidWorks 安装后注册到共享目录）
- SW_DOCMGR_LICENSE_KEY（SolidWorks 客户门户申请）

API 参考：
- SwDMClassFactory.GetApplication(licenseKey)：获取 DocMgr 应用对象
- SwDMApplication.GetDocument(path, docType, readOnly, error)：打开文档
- SwDMDocument.GetPreviewBitmap()：提取内嵌预览位图
- System.Drawing.Bitmap.Save(path, ImageFormat.Png)：保存为 PNG

注意：以上 API 基于 SolidWorks Document Manager SDK 文档。
实际类名/方法名可能因 SwDocumentMgr.dll 版本差异需调整；
函数失败时返回 None（不抛异常），由 pipeline 降级到下一级。
"""

from __future__ import annotations

from pathlib import Path

from app.logging import get_logger

log = get_logger(__name__)


def render_sldprt_via_docmgr(
    file_path: str | Path, output_path: str | Path
) -> str | None:
    """用 SolidWorks Document Manager API 提取 SLDPRT/SLDASM 预览图。

    Args:
        file_path: SLDPRT/SLDASM 文件路径
        output_path: 输出 PNG 路径

    Returns:
        输出 PNG 路径；不可用或失败时返回 None
    """
    import sys

    if sys.platform != "win32":
        log.warning("solidworks.docmgr.not_windows")
        return None

    try:
        import clr
        from app.config import settings

        if not settings.SW_DOCMGR_LICENSE_KEY:
            log.warning("solidworks.docmgr.no_license_key")
            return None

        # 加载 SwDocumentMgr.dll
        clr.AddReference(settings.SW_DOCMGR_DLL_PATH)
        # SwDMClassFactory 在 SwDocumentMgr 命名空间
        from SwDocumentMgr import SwDMClassFactory

        app = SwDMClassFactory.GetApplication(settings.SW_DOCMGR_LICENSE_KEY)

        # 确定文档类型
        file_path_str = str(file_path)
        suffix = file_path_str.lower()
        if suffix.endswith(".sldprt"):
            doc_type = 1  # swDmDocumentPart
        elif suffix.endswith(".sldasm"):
            doc_type = 2  # swDmDocumentAssembly
        else:
            doc_type = 3  # swDmDocumentDrawing

        # 打开文档（ReadOnly）
        from SwDocumentMgr import SwDmDocumentError

        err = SwDmDocumentError.swDmDocumentOpenErrorNone
        doc = app.GetDocument(file_path_str, doc_type, False, err)

        if doc is None or err != SwDmDocumentError.swDmDocumentOpenErrorNone:
            log.warning("solidworks.docmgr.open_failed", file=file_path_str, error=err)
            return None

        # 提取预览图
        bitmap = doc.GetPreviewBitmap()
        if bitmap is None:
            log.warning("solidworks.docmgr.no_preview", file=file_path_str)
            doc.Close()
            return None

        # 保存为 PNG（bitmap 是 System.Drawing.Bitmap）
        from System.Drawing.Imaging import ImageFormat

        output_path_str = str(output_path)
        # 确保输出目录存在
        Path(output_path_str).parent.mkdir(parents=True, exist_ok=True)
        bitmap.Save(output_path_str, ImageFormat.Png)
        doc.Close()

        log.info(
            "solidworks.docmgr.preview_extracted",
            file=file_path_str,
            png=output_path_str,
        )
        return output_path_str

    except Exception as e:
        log.warning("solidworks.docmgr.failed", file=str(file_path), error=str(e))
        return None
