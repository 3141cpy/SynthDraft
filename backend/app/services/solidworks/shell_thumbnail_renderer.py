"""Windows Shell Thumbnail 渲染器（Task 13）。

通过 Windows Shell API 提取 SolidWorks 文件的缩略图（资源管理器预览图）。
依赖 SolidWorks 已安装（注册 Shell Extension Thumbnail Provider）。

实现双路径：
- 路径 A（主）：ctypes 直接调用 IShellItemImageFactory::GetImage
  仅依赖 pywin32（已安装）+ PIL，无需外部 DLL。
  通过 SHCreateItemFromParsingName 获取 IShellItemImageFactory 接口，
  调用 GetImage 提取 HBITMAP，再用 GetDIBits 转 PIL Image。
- 路径 B（备）：pythonnet + Microsoft.WindowsAPICodePack.Shell
  需额外安装 WindowsAPICodePack.Shell.dll（非 PyPI 包，需手动部署）。
  通过 ShellObject.FromParsingName(path).Thumbnail.Bitmap 提取。

API 参考：
- IShellItemImageFactory::GetImage:
  https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/nf-shobjidl_core-ishellitemimagefactory-getimage
- SHCreateItemFromParsingName:
  https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/nf-shobjidl_core-shcreateitemfromparsingname

注意：缩略图质量取决于 SolidWorks 保存文件时写入的预览图分辨率，
通常低于 DocMgr 提取的预览图。作为 DocMgr 不可用时的降级方案。
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import POINTER, WINFUNCTYPE, byref, c_void_p, c_ubyte, c_uint32, c_ulong, c_ushort, wintypes
from pathlib import Path

from app.logging import get_logger

log = get_logger(__name__)


# ===== COM / Shell 结构与常量 =====


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", c_ulong),
        ("Data2", c_ushort),
        ("Data3", c_ushort),
        ("Data4", c_ubyte * 8),
    ]


class _SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", c_uint32),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", c_ushort),
        ("biBitCount", c_ushort),
        ("biCompression", c_uint32),
        ("biSizeImage", c_uint32),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", c_uint32),
        ("biClrImportant", c_uint32),
    ]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", _BITMAPINFOHEADER), ("bmiColors", c_uint32 * 3)]


class _BITMAP(ctypes.Structure):
    _fields_ = [
        ("bmType", ctypes.c_long),
        ("bmWidth", ctypes.c_long),
        ("bmHeight", ctypes.c_long),
        ("bmWidthBytes", ctypes.c_long),
        ("bmPlanes", c_ushort),
        ("bmBitsPixel", c_ushort),
        ("bmBits", c_void_p),
    ]


# IShellItemImageFactory IID: {BCC18B79-BA16-442F-80C4-8A59C30C463B}
_UBYTE8 = c_ubyte * 8
_IID_ISHELL_ITEM_IMAGE_FACTORY = _GUID(
    0xBCC18B79, 0xBA16, 0x442F,
    _UBYTE8(0x80, 0xC4, 0x8A, 0x59, 0xC3, 0x0C, 0x46, 0x3B),
)

# SIIGBF flags
_SIIGBF_RESIZETOFIT = 0x00000000
_SIIGBF_BIGGERSIZEOK = 0x00000001
_SIIGBF_SCALEUP = 0x00000100

# HRESULT
_S_OK = 0
# COINIT_APARTMENTTHREADED = 0x2 (STA, required for Shell COM)
_COINIT_APARTMENTTHREADED = 0x2


def _ensure_com_initialized() -> None:
    """初始化 COM（STA 模式，Shell API 要求）。

    使用 pythoncom（pywin32）若可用，否则用 ctypes。
    多次调用安全（返回 S_FALSE 表示已初始化）。
    """
    try:
        import pythoncom

        pythoncom.CoInitialize()
        return
    except ImportError:
        pass
    # ctypes 兜底
    ctypes.windll.ole32.CoInitializeEx(None, _COINIT_APARTMENTTHREADED)


def _extract_thumbnail_ctypes(file_path_str: str, size: int) -> int | None:
    """通过 ctypes 直接调用 IShellItemImageFactory::GetImage 提取 HBITMAP。

    Returns:
        HBITMAP 句柄（调用方需 DeleteObject）；失败返回 None
    """
    shell32 = ctypes.windll.shell32
    shell32.SHCreateItemFromParsingName.argtypes = [
        wintypes.LPCWSTR,
        c_void_p,
        POINTER(_GUID),
        POINTER(c_void_p),
    ]
    shell32.SHCreateItemFromParsingName.restype = ctypes.c_long

    ppv = c_void_p()
    hr = shell32.SHCreateItemFromParsingName(
        file_path_str, None, byref(_IID_ISHELL_ITEM_IMAGE_FACTORY), byref(ppv)
    )
    if hr != _S_OK or not ppv.value:
        log.warning(
            "solidworks.shell_thumbnail.create_item_failed",
            file=file_path_str,
            hr=f"0x{hr & 0xFFFFFFFF:08X}",
        )
        return None

    try:
        # vtable: [QueryInterface(0), AddRef(1), Release(2), GetImage(3)]
        vtable_ptr = ctypes.cast(ppv, POINTER(c_void_p))[0]
        func_ptrs = ctypes.cast(vtable_ptr, POINTER(c_void_p))
        get_image_ptr = func_ptrs[3]

        # HRESULT GetImage(SIZE size, DWORD flags, HBITMAP *phbm)
        prototype = WINFUNCTYPE(
            ctypes.c_long,        # HRESULT
            c_void_p,             # this
            _SIZE,                # size
            c_uint32,             # flags
            POINTER(wintypes.HBITMAP),  # phbm
        )
        get_image = prototype(get_image_ptr)

        sz = _SIZE(size, size)
        phbm = wintypes.HBITMAP()
        flags = _SIIGBF_RESIZETOFIT | _SIIGBF_BIGGERSIZEOK | _SIIGBF_SCALEUP
        hr = get_image(ppv, sz, flags, byref(phbm))
        if hr != _S_OK:
            log.warning(
                "solidworks.shell_thumbnail.get_image_failed",
                file=file_path_str,
                hr=f"0x{hr & 0xFFFFFFFF:08X}",
            )
            return None
        return phbm.value
    finally:
        # Release COM 对象（vtable index 2）
        vtable_ptr = ctypes.cast(ppv, POINTER(c_void_p))[0]
        func_ptrs = ctypes.cast(vtable_ptr, POINTER(c_void_p))
        release_ptr = func_ptrs[2]
        release_proto = WINFUNCTYPE(c_ulong, c_void_p)
        release = release_proto(release_ptr)
        release(ppv)


def _hbitmap_to_png(hbitmap: int, output_path_str: str) -> bool:
    """将 HBITMAP 转换为 PNG 文件（GetDIBits + PIL）。

    调用方将 HBITMAP 所有权移交本函数；无论成功或失败，本函数均负责
    调用 DeleteObject 释放 HBITMAP，避免 GDI 句柄泄漏。

    Returns:
        True 成功；False 失败
    """
    gdi32 = ctypes.windll.gdi32
    user32 = ctypes.windll.user32

    # 设置所有 GDI/user32 函数 argtypes（x64 句柄为指针大小）
    gdi32.GetObjectW.argtypes = [c_void_p, ctypes.c_int, c_void_p]
    gdi32.GetObjectW.restype = ctypes.c_int
    gdi32.CreateCompatibleDC.argtypes = [c_void_p]
    gdi32.CreateCompatibleDC.restype = c_void_p
    gdi32.DeleteDC.argtypes = [c_void_p]
    gdi32.DeleteDC.restype = ctypes.c_int
    gdi32.DeleteObject.argtypes = [c_void_p]
    gdi32.DeleteObject.restype = ctypes.c_int
    gdi32.GetDIBits.argtypes = [
        c_void_p, c_void_p, c_uint32, c_uint32,
        c_void_p, POINTER(_BITMAPINFO), c_uint32,
    ]
    gdi32.GetDIBits.restype = ctypes.c_int
    user32.GetDC.argtypes = [c_void_p]
    user32.GetDC.restype = c_void_p
    user32.ReleaseDC.argtypes = [c_void_p, c_void_p]
    user32.ReleaseDC.restype = ctypes.c_int

    try:
        from PIL import Image

        bm = _BITMAP()
        if gdi32.GetObjectW(hbitmap, ctypes.sizeof(_BITMAP), byref(bm)) == 0:
            log.warning("solidworks.shell_thumbnail.get_object_failed")
            return False

        width = bm.bmWidth
        height = bm.bmHeight
        if width <= 0 or height <= 0:
            log.warning(
                "solidworks.shell_thumbnail.invalid_dims",
                width=width, height=height,
            )
            return False

        # GetDIBits 提取像素数据（top-down BGRA）
        hdc = user32.GetDC(None)
        mdc = gdi32.CreateCompatibleDC(hdc)

        bi = _BITMAPINFO()
        bi.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bi.bmiHeader.biWidth = width
        bi.bmiHeader.biHeight = -height  # 负值 = top-down
        bi.bmiHeader.biPlanes = 1
        bi.bmiHeader.biBitCount = 32
        bi.bmiHeader.biCompression = 0  # BI_RGB

        buffer_size = width * height * 4
        pixel_data = (c_ubyte * buffer_size)()

        rows = gdi32.GetDIBits(
            mdc, hbitmap, 0, height, pixel_data, byref(bi), 0  # DIB_RGB_COLORS
        )
        gdi32.DeleteDC(mdc)
        user32.ReleaseDC(None, hdc)

        if rows == 0:
            log.warning("solidworks.shell_thumbnail.get_dibits_failed")
            return False

        # BGRA -> RGBA via PIL，再合成到白底（审图可读性）
        img = Image.frombuffer(
            "RGBA", (width, height), bytes(pixel_data), "raw", "BGRA", 0, 1
        )
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[3] if img.mode == "RGBA" else None)
        Path(output_path_str).parent.mkdir(parents=True, exist_ok=True)
        background.save(output_path_str, "PNG")
        return True
    finally:
        # 无论成功或失败，均释放 HBITMAP 避免 GDI 句柄泄漏
        gdi32.DeleteObject(hbitmap)


def _render_via_ctypes(
    file_path: str | Path, output_path: str | Path, size: int = 1024
) -> str | None:
    """路径 A：ctypes 直接调用 IShellItemImageFactory 提取缩略图。"""
    if sys.platform != "win32":
        return None

    file_path_str = str(file_path)
    output_path_str = str(output_path)

    _ensure_com_initialized()
    hbitmap = _extract_thumbnail_ctypes(file_path_str, size)
    if hbitmap is None:
        return None

    if _hbitmap_to_png(hbitmap, output_path_str):
        log.info(
            "solidworks.shell_thumbnail.ctypes_extracted",
            file=file_path_str,
            png=output_path_str,
            size=size,
        )
        return output_path_str
    return None


def _render_via_pythonnet(
    file_path: str | Path, output_path: str | Path, size: int = 1024
) -> str | None:
    """路径 B：pythonnet + WindowsAPICodePack.Shell 提取缩略图。

    需 WindowsAPICodePack.Shell.dll 部署到 pythonnet 可加载路径。
    """
    try:
        import clr

        clr.AddReference("Microsoft.WindowsAPICodePack.Shell")
        from Microsoft.WindowsAPICodePack.Shell import ShellObject
        from System.Drawing.Imaging import ImageFormat

        file_path_str = str(file_path)
        shell_obj = ShellObject.FromParsingName(file_path_str)
        try:
            from System.Drawing import Size

            shell_obj.Thumbnail.CurrentSize = Size(size, size)
        except Exception:  # noqa: BLE001
            pass

        bitmap = shell_obj.Thumbnail.Bitmap
        if bitmap is None:
            log.warning("solidworks.shell_thumbnail.no_thumbnail", file=file_path_str)
            return None

        output_path_str = str(output_path)
        Path(output_path_str).parent.mkdir(parents=True, exist_ok=True)
        bitmap.Save(output_path_str, ImageFormat.Png)
        log.info(
            "solidworks.shell_thumbnail.pythonnet_extracted",
            file=file_path_str,
            png=output_path_str,
        )
        return output_path_str
    except Exception as e:
        log.warning(
            "solidworks.shell_thumbnail.pythonnet_failed",
            file=str(file_path), error=str(e),
        )
        return None


def render_sldprt_via_shell(
    file_path: str | Path, output_path: str | Path, size: int = 1024
) -> str | None:
    """用 Windows Shell API 提取 SLDPRT/SLDASM 缩略图。

    优先路径 A（ctypes，无外部 DLL 依赖），失败时尝试路径 B（pythonnet）。

    Args:
        file_path: SLDPRT/SLDASM 文件路径
        output_path: 输出 PNG 路径
        size: 缩略图尺寸（像素），默认 1024

    Returns:
        输出 PNG 路径；不可用或失败时返回 None
    """
    if sys.platform != "win32":
        log.warning("solidworks.shell_thumbnail.not_windows")
        return None

    # 路径 A：ctypes（主，无外部 DLL 依赖）
    try:
        result = _render_via_ctypes(file_path, output_path, size)
        if result:
            return result
    except Exception as e:
        log.warning(
            "solidworks.shell_thumbnail.ctypes_exception",
            file=str(file_path), error=str(e),
        )

    # 路径 B：pythonnet + WindowsAPICodePack（备）
    try:
        result = _render_via_pythonnet(file_path, output_path, size)
        if result:
            return result
    except Exception as e:
        log.warning(
            "solidworks.shell_thumbnail.pythonnet_exception",
            file=str(file_path), error=str(e),
        )

    return None
