"""SolidWorks 类型库加载与 COM 对象包装（SubTask 7.2 补充）。

背景：
  win32com 动态 Dispatch 无法可靠访问 SolidWorks Feature API：
  - GetFirstFeature() 报"成员未找到"
  - GetTypeName2() / GetNextFeature() 等方法无法绑定
  原因：SolidWorks COM 接口的 IDispatch 实现不完整，需通过类型库
  （.tlb）进行早期绑定。

  EnsureDispatch 在 SolidWorks 2025 上失败：
  "This COM object can not automate the makepy process"
  原因：COM 对象的 GetTypeInfo() 返回"找不到元素"。
  解决方案：手动运行 makepy 生成类型库缓存，然后用 ISldWorks(oleobj)
  直接包装 COM 对象。

依赖：
  - pywin32（win32com.client.makepy / gencache）
  - SolidWorks 安装目录下的 sldworks.tlb（约 2MB）
  - swconst.tlb（约 768KB，枚举常量）

类型库信息（实测 SolidWorks 2025 SP3.0）：
  - GUID: {83A33D31-27C5-11CE-BFD4-00400513BB57}
  - MajorVersion: 33
  - MinorVersion: 0
  - LCID: 0
  - 类型数: 1015（ISldWorks, IModelDoc2, IFeature 等）

公共接口：
  - get_typelib_module(): 加载/生成类型库模块，返回模块对象
  - wrap_object(com_obj, interface_name): 包装 COM 对象为强类型接口
  - is_typelib_available(): 检查类型库是否可用

使用示例：
  from app.services.solidworks.typelib import get_typelib_module, wrap_object

  sw_app = win32com.client.Dispatch("SldWorks.Application")
  sw_strong = wrap_object(sw_app, "ISldWorks")
  # 现在可以调用强类型方法
  doc = sw_strong.OpenDoc6(filepath, 1, 2, "", 0, 0)
  # OpenDoc6 返回 tuple: (IModelDoc2, errors, warnings)

部署约束：
  - 类型库缓存生成在 .venv/Lib/site-packages/win32com/gen_py/ 下
  - 首次运行需 ~5s 生成缓存，后续秒级加载
  - 缓存与 Python 版本绑定（升级 Python 需重新生成）
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Any

from app.logging import get_logger

log = get_logger(__name__)


# ===== 类型库常量（SolidWorks 2025 实测）=====
# 来源：sldworks.tlb 文件头 + makepy 输出
SW_TYPELIB_GUID = "{83A33D31-27C5-11CE-BFD4-00400513BB57}"
SW_TYPELIB_MAJOR = 33
SW_TYPELIB_MINOR = 0
SW_TYPELIB_LCID = 0

# SolidWorks 安装目录下类型库文件相对路径
SW_TLB_FILENAME = "sldworks.tlb"
SW_CONST_TLB_FILENAME = "swconst.tlb"

# 候选 SolidWorks 安装根目录（实测优先级）
# 1. 通过注册表 LocalServer32 获取（最可靠）
# 2. 常见硬编码路径
_SW_INSTALL_CANDIDATES = [
    r"D:\Program Files\SOLIDWORKS Corp\SOLIDWORKS",
    r"D:\Program Files\SolidWorks Corp\SolidWorks",
    r"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS",
    r"C:\Program Files\SolidWorks Corp\SolidWorks",
    r"E:\Program Files\SOLIDWORKS Corp\SOLIDWORKS",
    r"E:\Program Files\SolidWorks Corp\SolidWorks",
]

# 模块级缓存：类型库模块（避免重复加载）
_typelib_module: Any = None
_typelib_load_attempted = False


def is_typelib_available() -> bool:
    """检查类型库是否可用（pywin32 已安装 + 类型库文件可找到）。

    Returns:
        True 表示类型库可用（可调用 get_typelib_module() 获取模块）
    """
    try:
        import win32com.client  # noqa: F401
        import pythoncom  # noqa: F401
    except ImportError:
        return False
    return _find_sldworks_tlb() is not None


def get_typelib_module() -> Any:
    """加载 SolidWorks 类型库模块（带缓存）。

    加载流程：
    1. 若已缓存（_typelib_module），直接返回
    2. 尝试从 gen_py 缓存目录加载已生成的模块
    3. 若缓存不存在，运行 makepy 生成缓存
    4. 返回模块对象（包含 ISldWorks, IModelDoc2, IFeature 等类）

    Returns:
        类型库模块对象，包含所有 SolidWorks 接口类

    Raises:
        RuntimeError: 类型库不可用或加载失败
    """
    global _typelib_module, _typelib_load_attempted

    if _typelib_module is not None:
        return _typelib_module

    if _typelib_load_attempted:
        # 之前尝试失败，不再重试（避免每次调用都尝试加载）
        raise RuntimeError("类型库加载之前已失败，请检查日志")

    _typelib_load_attempted = True

    try:
        _typelib_module = _load_or_generate_typelib()
        log.info(
            "sw.typelib.loaded",
            guid=SW_TYPELIB_GUID,
            version=f"{SW_TYPELIB_MAJOR}.{SW_TYPELIB_MINOR}",
        )
        return _typelib_module
    except Exception as e:
        log.error("sw.typelib.load_failed", error=str(e))
        raise RuntimeError(f"SolidWorks 类型库加载失败: {e}") from e


def wrap_object(com_obj: Any, interface_name: str) -> Any:
    """将动态 Dispatch COM 对象包装为强类型接口。

    用法：
        sw_app = Dispatch("SldWorks.Application")
        sw_strong = wrap_object(sw_app, "ISldWorks")
        # 现在可以调用 sw_strong.OpenDoc6(...) 等强类型方法

    Args:
        com_obj: 动态 Dispatch 对象（CDispatch）或已有 _oleobj_ 的对象
        interface_name: 类型库中的接口名（如 "ISldWorks", "IModelDoc2",
                       "IFeature", "IModelDocExtension", "ICustomPropertyManager"）

    Returns:
        强类型接口实例（DispatchBaseClass 子类）

    Raises:
        RuntimeError: 类型库未加载
        AttributeError: 接口名不存在于类型库
    """
    module = get_typelib_module()
    iface_cls = getattr(module, interface_name, None)
    if iface_cls is None:
        raise AttributeError(
            f"类型库中不存在接口: {interface_name}"
        )

    # 获取底层 IDispatch 对象
    if hasattr(com_obj, "_oleobj_"):
        oleobj = com_obj._oleobj_
    elif hasattr(com_obj, "_oleobj"):
        oleobj = com_obj._oleobj
    else:
        # 可能已经是 IDispatch 对象
        oleobj = com_obj

    return iface_cls(oleobj)


def is_strong_typed(obj: Any) -> bool:
    """检查对象是否已是强类型接口（DispatchBaseClass 子类）。"""
    try:
        module = _typelib_module
        if module is None:
            return False
        # 检查是否是类型库模块中的类实例
        for attr_name in dir(module):
            cls = getattr(module, attr_name, None)
            if isinstance(cls, type) and isinstance(obj, cls):
                return True
    except Exception:
        pass
    return False


# ===== 内部实现 =====


def _find_sldworks_tlb() -> Path | None:
    """查找 SolidWorks 类型库文件路径。

    查找策略（按优先级）：
    1. 通过注册表 CLSID → LocalServer32 获取安装路径
    2. 候选硬编码路径
    3. PATH 环境变量中的 sldworks.exe

    Returns:
        sldworks.tlb 文件路径，找不到返回 None
    """
    # 1. 尝试通过注册表获取安装路径
    try:
        import winreg

        # SldWorks.Application 的 CLSID
        # HKLM\SOFTWARE\Classes\SldWorks.Application\CLSID
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Classes\SldWorks.Application\CLSID",
        ) as key:
            clsid = winreg.QueryValue(key, "")

        if clsid:
            # HKLM\SOFTWARE\Classes\CLSID\{clsid}\LocalServer32
            for root in (
                rf"SOFTWARE\Classes\CLSID\{clsid}\LocalServer32",
                rf"SOFTWARE\Classes\WOW6432Node\CLSID\{clsid}\LocalServer32",
            ):
                try:
                    with winreg.OpenKey(
                        winreg.HKEY_LOCAL_MACHINE, root
                    ) as key:
                        exe_path = winreg.QueryValue(key, "")
                        if exe_path:
                            install_dir = Path(exe_path).parent
                            tlb_path = install_dir / SW_TLB_FILENAME
                            if tlb_path.is_file():
                                return tlb_path
                except OSError:
                    continue
    except Exception as e:  # noqa: BLE001
        log.debug("sw.typelib.registry_lookup_failed", error=str(e))

    # 2. 候选硬编码路径
    for candidate in _SW_INSTALL_CANDIDATES:
        tlb_path = Path(candidate) / SW_TLB_FILENAME
        if tlb_path.is_file():
            return tlb_path

    return None


def _get_gen_py_dir() -> Path:
    """获取 win32com gen_py 缓存目录路径。"""
    try:
        import win32com

        base = Path(win32com.__file__).parent / "gen_py"
        base.mkdir(exist_ok=True)
        return base
    except Exception as e:  # noqa: BLE001
        log.warning("sw.typelib.gen_py_dir_failed", error=str(e))
        # 回退到默认路径
        import sysconfig

        site_packages = Path(sysconfig.get_paths()["purelib"])
        return site_packages / "win32com" / "gen_py"


def _get_cached_module_path() -> Path | None:
    """查找已生成的类型库缓存模块路径。

    文件名格式：{GUID}x{lcid}x{major}x{minor}.py
    实例：83A33D31-27C5-11CE-BFD4-00400513BB57x0x33x0.py
    """
    gen_py_dir = _get_gen_py_dir()
    # 文件名格式：{guid}x{lcid}x{major}x{minor}.py
    # 注意：major/minor 在文件名中是十进制字符串（非 hex）
    expected_name = (
        f"{SW_TYPELIB_GUID.strip('{}')}"
        f"x{SW_TYPELIB_LCID}"
        f"x{SW_TYPELIB_MAJOR}"
        f"x{SW_TYPELIB_MINOR}.py"
    )
    # 兼容带/不带大括号的格式
    candidates = [
        gen_py_dir / expected_name,
        gen_py_dir / f"{SW_TYPELIB_GUID}x{SW_TYPELIB_LCID}x{SW_TYPELIB_MAJOR}x{SW_TYPELIB_MINOR}.py",
    ]
    # 也搜索通配符匹配
    for p in candidates:
        if p.is_file():
            return p

    # 通配符搜索（以防格式微调）
    pattern = f"*{SW_TYPELIB_GUID.strip('{}')}*.py"
    for p in gen_py_dir.glob(pattern):
        return p

    return None


def _load_or_generate_typelib() -> Any:
    """加载已缓存的类型库模块，或运行 makepy 生成。

    Returns:
        类型库模块对象
    """
    # 1. 尝试从缓存加载
    cached_path = _get_cached_module_path()
    if cached_path is not None:
        log.info("sw.typelib.loading_cached", path=str(cached_path))
        return _load_module_from_path(cached_path)

    # 2. 缓存不存在，运行 makepy 生成
    log.info("sw.typelib.cache_not_found_generating")
    tlb_path = _find_sldworks_tlb()
    if tlb_path is None:
        raise RuntimeError(
            "未找到 SolidWorks 类型库文件 sldworks.tlb。"
            "请确认 SolidWorks 已安装，或手动指定路径。"
        )

    log.info("sw.typelib.generating", tlb=str(tlb_path))
    _run_makepy(tlb_path)

    # 也生成 swconst.tlb（枚举常量）
    const_tlb = tlb_path.parent / SW_CONST_TLB_FILENAME
    if const_tlb.is_file():
        try:
            _run_makepy(const_tlb)
        except Exception as e:  # noqa: BLE001
            log.warning("sw.typelib.const_generate_failed", error=str(e))

    # 重新查找缓存文件
    cached_path = _get_cached_module_path()
    if cached_path is None:
        raise RuntimeError(
            f"makepy 生成后仍未找到缓存文件，请检查 gen_py 目录: {_get_gen_py_dir()}"
        )

    return _load_module_from_path(cached_path)


def _run_makepy(tlb_path: Path) -> None:
    """运行 makepy 生成类型库缓存。

    Args:
        tlb_path: .tlb 文件路径

    Raises:
        RuntimeError: makepy 失败
    """
    try:
        from win32com.client import makepy

        # makepy.main() 从 sys.argv 读取参数
        original_argv = sys.argv
        sys.argv = ["makepy", str(tlb_path)]
        try:
            makepy.main()
        finally:
            sys.argv = original_argv

        log.info("sw.typelib.generated", tlb=str(tlb_path))
    except Exception as e:
        raise RuntimeError(f"makepy 生成类型库失败: {e}") from e


def _load_module_from_path(module_path: Path) -> Any:
    """从文件路径加载 Python 模块。

    Args:
        module_path: .py 文件路径

    Returns:
        模块对象
    """
    spec = importlib.util.spec_from_file_location(
        "sw_typelib_sldworks", module_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法创建模块 spec: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _reset_cache() -> None:
    """重置模块级缓存（仅供测试使用）。"""
    global _typelib_module, _typelib_load_attempted
    _typelib_module = None
    _typelib_load_attempted = False
