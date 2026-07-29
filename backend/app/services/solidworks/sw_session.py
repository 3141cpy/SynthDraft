"""SolidWorks COM 会话管理（SubTask 7.1）。

依赖：
- pywin32（PyPI 包名 pywin32，模块名 win32com）
  官方仓库：https://github.com/mhammond/pywin32
  仅 Windows 平台可用；Linux 部署时 is_solidworks_available() 返回 False
- SolidWorks（已安装且许可证有效）
  COM ProgID：SldWorks.Application
  官方 API 文档：https://help.solidworks.com/2025/english/api/sldworksapiprogguide/Welcome.htm

关键 API（已通过 spec.md §3 查询确认）：
- swApp.OpenDoc6 / NewDocument：打开/创建 SLDPRT/SLDASM/SLDDRW
- ModelDoc2.SaveAs3：保存为 SLDPRT 或导出 STEP/IGES/STL
- ModelDoc2.FeatureManager.FeatureExtrusion2：拉伸特征
- ModelDoc2.SketchManager.CreateCenterRectangle / InsertSketch：草图绘制
- PartDoc.GetFirstFeature / Feature.GetNextFeature：特征树遍历
- ModelDoc2.Extension.SelectByID2：选择图元
- swDocumentTypes_e：swDocPART=1, swDocASSEMBLY=2, swDocDRAWING=3

部署约束（spec.md §3 部署约束）：
SolidWorks 原生文件（SLDPRT/SLDASM）的生成与编辑必须在装有 SolidWorks 许可证的
Windows 机器上通过 API 完成；不可绕过。

会话管理策略：
- 进程内单例（SolidWorks Dispatch 启动开销 ~10s，复用避免重复启动）
- 线程安全（SolidWorks COM 是 STA，多线程访问需 CoInitialize）
- 健康检查（ping 通过 RevisionNumber 读取验证实例存活）
- 优雅退出（ExitApp 释放许可证）
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from app.logging import get_logger
from app.services.solidworks.exceptions import (
    SolidWorksLicenseError,
    SolidWorksNotAvailableError,
    SolidWorksSessionError,
    SolidWorksTaskError,
)

log = get_logger(__name__)

# ===== 优雅降级：尝试导入 pywin32 =====
# 优先级：仅 Windows + pywin32 已安装
_WIN32_BACKEND: str | None = None
_win32com: Any = None
_pythoncom: Any = None

try:
    import pythoncom  # type: ignore[import-not-found]
    import win32com.client  # type: ignore[import-not-found]

    _win32com = win32com.client
    _pythoncom = pythoncom
    _WIN32_BACKEND = "pywin32"
except ImportError:
    _WIN32_BACKEND = None


_INSTALL_HINT = (
    "SolidWorks 后端不可用。安装方式：\n"
    "  方式 A（Windows pip）：pip install pywin32  (>=308)\n"
    "  方式 B（conda）：conda install -c conda-forge pywin32\n"
    "  官方文档：\n"
    "    - pywin32: https://github.com/mhammond/pywin32\n"
    "    - SolidWorks API: https://help.solidworks.com/2025/english/api/sldworksapiprogguide/Welcome.htm\n"
    "  部署约束：SolidWorks 原生文件操作必须在装有 SolidWorks 许可证的 Windows 机器上。\n"
)


# ===== SolidWorks 文档类型枚举（swDocumentTypes_e）=====
# 来源：spec.md §3 + SolidWorks API 文档
SW_DOC_PART = 1  # swDocPART
SW_DOC_ASSEMBLY = 2  # swDocASSEMBLY
SW_DOC_DRAWING = 3  # swDocDRAWING


def is_solidworks_available() -> bool:
    """检测 pywin32 + SolidWorks COM 是否可用。

    Returns:
        True 表示 pywin32 已安装且为 Windows 平台
        注意：True 不保证 SolidWorks 已安装或许可证有效，
        需调用 SolidWorksSession.ping() 实际验证。
    """
    return _WIN32_BACKEND is not None


def _require_backend() -> None:
    """内部断言：pywin32 可用。"""
    if _WIN32_BACKEND is None:
        raise SolidWorksNotAvailableError(_INSTALL_HINT)


class SolidWorksSession:
    """SolidWorks COM 会话（进程内单例，线程安全）。

    用法：
        session = SolidWorksSession()  # 单例，重复调用返回同一实例
        session.start()  # Dispatch SldWorks.Application
        doc = session.open_document(Path("part.slprt"), SW_DOC_PART)
        session.save_as(doc, Path("output.step"))
        session.close_document(doc)
        session.close()  # ExitApp 释放许可证

    线程安全：
        SolidWorks COM 是 STA（Single-Threaded Apartment），
        多线程访问同一实例需通过 _lock 串行化。
        推荐每个 Worker 进程内单例 + 任务串行执行。
    """

    _instance: "SolidWorksSession | None" = None
    _singleton_lock = threading.Lock()

    def __new__(cls) -> "SolidWorksSession":
        if cls._instance is None:
            with cls._singleton_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False  # type: ignore[attr-defined]
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        _require_backend()
        self._sw_app: Any = None  # SldWorks.Application 对象
        self._lock = threading.RLock()  # COM 调用串行锁
        self._started = False
        self._revision: str = ""
        self._initialized = True

    @property
    def started(self) -> bool:
        """会话是否已启动（Dispatch 成功）。"""
        return self._started

    @property
    def revision(self) -> str:
        """SolidWorks 版本号（如 "33.3.0" 对应 SolidWorks 2025 SP3.0）。"""
        return self._revision

    def start(self, visible: bool = False) -> None:
        """启动 SolidWorks 实例（Dispatch "SldWorks.Application"）。

        Args:
            visible: 是否显示 SolidWorks GUI（默认 False，后台运行）

        Raises:
            SolidWorksSessionError: Dispatch 失败
            SolidWorksLicenseError: 许可证不可用

        实测结论（SolidWorks 2025 SP3.0 + pywin32 308）：
        - win32com.gencache.EnsureDispatch 失败："This COM object can not automate
          the makepy process"（COM 对象 GetTypeInfo 返回"找不到元素"）。
        - 解决方案：用 Dispatch 获取动态对象，再用 typelib.wrap_object("ISldWorks")
          包装为强类型接口（基于已生成的 sldworks.tlb 类型库缓存）。
        - 强类型接口可正确调用 OpenDoc6（ByRef 参数由类型库自动处理）、
          IModelDoc2.FirstFeature、IFeature.GetTypeName2 等方法。
        """
        with self._lock:
            if self._started:
                log.info("sw.session.already_started", revision=self._revision)
                return

            log.info("sw.session.starting", visible=visible)
            try:
                # 当前线程初始化 COM（STA）
                _pythoncom.CoInitialize()
                # 始终用 Dispatch（EnsureDispatch 在 SolidWorks 2025 上失败）
                self._sw_app = _win32com.Dispatch("SldWorks.Application")
                log.info("sw.session.dispatch", method="Dispatch")
                # 尝试用类型库包装为强类型 ISldWorks
                # 成功后 self._sw_app 将是 ISldWorks 实例，可调用强类型方法
                # 失败则保留动态 Dispatch（部分 ByRef API 将不可用）
                self._typelib_module = None
                try:
                    from app.services.solidworks.typelib import (
                        get_typelib_module,
                        wrap_object,
                    )
                    typelib_mod = get_typelib_module()
                    self._sw_app = wrap_object(self._sw_app, "ISldWorks")
                    self._typelib_module = typelib_mod
                    log.info("sw.session.strong_typed", interface="ISldWorks")
                except Exception as e_typelib:
                    log.warning(
                        "sw.session.typelib_wrap_failed",
                        error=str(e_typelib),
                        detail="退化为动态 Dispatch（部分 ByRef API 不可用）",
                    )
                # visible=False 避免抢占前台；UserControl=False 避免用户关闭
                self._sw_app.Visible = visible
                self._sw_app.UserControl = False
                # 读取版本号验证实例可用
                # 实测：强类型 ISldWorks 中 RevisionNumber 被暴露为方法（带括号调用），
                # 动态 Dispatch 中作为属性（不带括号）。
                rev = self._sw_app.RevisionNumber
                if callable(rev):
                    rev = rev()
                self._revision = str(rev)
                self._started = True
                log.info(
                    "sw.session.started",
                    revision=self._revision,
                    visible=visible,
                    strong_typed=self._typelib_module is not None,
                )
            except Exception as e:
                # 常见失败：许可证不可用、SolidWorks 未安装、COM 注册损坏
                err_msg = str(e).lower()
                if "license" in err_msg or "许可" in err_msg:
                    raise SolidWorksLicenseError(
                        f"SolidWorks 许可证不可用：{e}"
                    ) from e
                raise SolidWorksSessionError(
                    f"SolidWorks Dispatch 失败：{e}"
                ) from e

    @property
    def typelib_module(self) -> Any:
        """返回 SolidWorks 类型库模块（强类型接口类集合）。

        返回 None 表示未启用强类型访问（动态 Dispatch 模式）。
        下游模块（reader.py/writer.py）可借此包装 COM 对象为 IModelDoc2/IFeature 等。
        """
        return getattr(self, "_typelib_module", None)

    def ping(self) -> bool:
        """健康检查：读取 RevisionNumber 验证实例存活。

        Returns:
            True 表示实例可用；False 表示实例已崩溃需重启
        """
        if not self._started or self._sw_app is None:
            return False
        try:
            with self._lock:
                # 强类型 ISldWorks 中 RevisionNumber 是方法，需调用
                rev = self._sw_app.RevisionNumber
                if callable(rev):
                    rev = rev()
                _ = str(rev)
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("sw.session.ping_failed", error=str(e))
            return False

    def close(self) -> None:
        """退出 SolidWorks 实例，释放许可证。

        幂等：多次调用安全。
        """
        with self._lock:
            if not self._started or self._sw_app is None:
                return
            try:
                log.info("sw.session.closing", revision=self._revision)
                # ExitApp 优雅退出；参数 0 表示不保存未保存文档
                # 部分 SolidWorks 版本要求无参数调用
                try:
                    self._sw_app.ExitApp()
                except Exception:  # noqa: BLE001
                    pass
            finally:
                self._sw_app = None
                self._started = False
                try:
                    _pythoncom.CoUninitialize()
                except Exception:  # noqa: BLE001
                    pass
                log.info("sw.session.closed")

    # ===== 文档操作 API（SubTask 7.2/7.3 将扩展）=====

    def open_document(
        self,
        path: Path,
        doc_type: int,
        read_only: bool = True,
    ) -> Any:
        """打开 SolidWorks 文档（OpenDoc6 封装）。

        Args:
            path: 文件路径（SLDPRT/SLDASM/SLDDRW）
            doc_type: SW_DOC_PART / SW_DOC_ASSEMBLY / SW_DOC_DRAWING
            read_only: 是否以只读模式打开（避免修改原文件）

        Returns:
            ModelDoc2 对象

        Raises:
            SolidWorksTaskError: 文件打开失败
        """
        self._ensure_started()
        path = Path(path)
        if not path.is_file():
            raise SolidWorksTaskError(f"文件不存在：{path}")

        # OpenDoc6 签名：
        # ModelDoc2 = swApp.OpenDoc6(
        #   filename: str,
        #   type: int,           # swDocumentTypes_e
        #   options: int,        # swOpenDocOptions_e（1=swOpenDocOptions_Silent
        #                         # 2=swOpenDocOptions_ReadOnly
        #                         # 4=swOpenDocOptions_ViewOnly）
        #   configName: str,     # 配置名（可空）
        #   errors: int (out),   # 返回错误码
        #   warnings: int (out)  # 返回警告码
        # )
        # swOpenDocOptions_Silent(1): 始终包含，避免弹窗阻塞 COM 调用
        # swOpenDocOptions_ReadOnly(2): 只读模式（read_only=True 时附加）
        options = 1  # swOpenDocOptions_Silent
        if read_only:
            options |= 2  # swOpenDocOptions_ReadOnly
        # swOpenDocOptions_OverrideDefaultTemplate(16): 外来格式（STEP/IGES）导入时
        # 若默认模板不可用，使用内置默认模板而不弹窗（invisible 模式必需）
        options |= 16

        with self._lock:
            try:
                # OpenDoc6 的 errors/warnings 是 ByRef out 参数。
                # 强类型接口（ISldWorks）：传普通整数 0 即可，类型库自动处理 ByRef。
                # 动态 Dispatch：需用 VARIANT(VT_BYREF|VT_I4) 包装。
                # 实测确认强类型 OpenDoc6 返回 tuple: (IModelDoc2, errors, warnings)
                # 动态 Dispatch 返回单个 doc 对象（ByRef 值通过 VARIANT 回传）
                doc: Any = None
                errors_val: Any = 0
                warnings_val: Any = 0

                if self._typelib_module is not None:
                    # 强类型路径
                    open_result = self._sw_app.OpenDoc6(
                        str(path), doc_type, options, "", 0, 0
                    )
                    if isinstance(open_result, tuple):
                        doc = open_result[0]
                        if len(open_result) > 1:
                            errors_val = open_result[1]
                        if len(open_result) > 2:
                            warnings_val = open_result[2]
                    else:
                        doc = open_result
                else:
                    # 动态 Dispatch 回退路径
                    from win32com.client import VARIANT
                    import pythoncom

                    errors_var = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
                    warnings_var = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
                    doc = self._sw_app.OpenDoc6(
                        str(path), doc_type, options, "", errors_var, warnings_var
                    )
                    errors_val = errors_var
                    warnings_val = warnings_var

                if doc is None:
                    raise SolidWorksTaskError(
                        f"OpenDoc6 返回 None，文件可能损坏或格式不匹配：{path}"
                        f"（errors={errors_val}, warnings={warnings_val}）"
                    )
                log.info(
                    "sw.doc.opened",
                    file=str(path),
                    doc_type=doc_type,
                    read_only=read_only,
                    errors=errors_val,
                    warnings=warnings_val,
                    strong_typed=self._typelib_module is not None,
                )
                return doc
            except SolidWorksTaskError:
                raise
            except Exception as e:
                raise SolidWorksTaskError(
                    f"打开文档失败 {path}：{e}"
                ) from e

    def new_document(
        self,
        doc_type: int,
        template_path: Path | None = None,
    ) -> Any:
        """创建新 SolidWorks 文档（NewDocument 封装）。

        API（SolidWorks API Help 2025 - ISldWorks::NewDocument）：
            ModelDoc2 = swApp.NewDocument(
                templateName: str,    # 模板文件路径（.prtdot / .asmdot / .drwdot）
                paperSize: int,       # swDwgPaperSizes_e（仅图纸有效，零件/装配传 0）
                width: double,        # 图纸宽度（米，仅图纸有效，零件/装配传 0）
                height: double        # 图纸高度（米，仅图纸有效，零件/装配传 0）
            )

        模板路径解析（按优先级回退）：
        1. 调用方显式传入 template_path
        2. swApp.GetUserPreferenceStringValue(swUserPreferenceStringValue_e)
           - swDefaultTemplatePart = 7  （存疑，待实测：枚举值因版本而异）
           - swDefaultTemplateAssembly = 8
           - swDefaultTemplateDrawing = 9
        3. SolidWorks 默认安装目录下的 gb 模板：
           - C:\\Program Files\\SolidWorks Corp\\SolidWorks\\templates\\gb\\零件.prtdot
           - C:\\Program Files\\SolidWorks Corp\\SolidWorks\\templates\\gb\\装配体.asmdot
           - C:\\Program Files\\SolidWorks Corp\\SolidWorks\\templates\\gb\\工程图.drwdot
        4. SolidWorks 默认安装目录下的英文模板：
           - ...\\templates\\Part.prtdot
           - ...\\templates\\Assembly.asmdot
           - ...\\templates\\Drawing.drwdot

        Args:
            doc_type: SW_DOC_PART / SW_DOC_ASSEMBLY / SW_DOC_DRAWING
            template_path: 显式指定模板路径（None 时自动查找默认模板）

        Returns:
            ModelDoc2 对象（已打开的空文档）

        Raises:
            SolidWorksTaskError: 模板未找到或 NewDocument 调用失败
        """
        self._ensure_started()

        # 解析模板路径
        if template_path is not None:
            tpl = Path(template_path)
            if not tpl.is_file():
                raise SolidWorksTaskError(f"模板文件不存在：{tpl}")
            tpl_str = str(tpl)
        else:
            tpl_str = self._find_default_template(doc_type)

        # 优先用 NewDocument（需要模板路径）
        if tpl_str:
            with self._lock:
                try:
                    doc = self._sw_app.NewDocument(tpl_str, 0, 0.0, 0.0)
                    if doc is not None:
                        log.info("sw.doc.created", template=tpl_str, doc_type=doc_type)
                        return doc
                    log.warning("sw.doc.new_document_none", template=tpl_str)
                except Exception as e:  # noqa: BLE001
                    log.warning("sw.doc.new_document_failed", template=tpl_str, error=str(e))

        # 回退：用 NewPart/NewAssembly（不需要模板路径，使用 SolidWorks 内置默认模板）
        # 实测确认：SolidWorks 2025 安装目录 data\templates\ 下可能只有 .drwdot，
        # 无 .prtdot/.asmdot，此时 NewDocument 不可用，改用 NewPart/NewAssembly。
        # API 依据：SolidWorks API Help - ISldWorks.NewPart / NewAssembly
        with self._lock:
            try:
                if doc_type == SW_DOC_PART:
                    doc = self._sw_app.NewPart()
                elif doc_type == SW_DOC_ASSEMBLY:
                    doc = self._sw_app.NewAssembly()
                else:
                    # 工程图必须有模板，无回退
                    raise SolidWorksTaskError(
                        f"未找到工程图模板（doc_type={doc_type}）。"
                        "请显式传入 template_path。"
                    )
                if doc is None:
                    raise SolidWorksTaskError(
                        f"NewPart/NewAssembly 返回 None（doc_type={doc_type}）"
                    )
                log.info("sw.doc.created_fallback", method="NewPart/NewAssembly", doc_type=doc_type)
                return doc
            except SolidWorksTaskError:
                raise
            except Exception as e:
                raise SolidWorksTaskError(
                    f"创建文档失败（NewPart/NewAssembly 回退）：{e}"
                ) from e

    def _find_default_template(self, doc_type: int) -> str | None:
        """查找 SolidWorks 默认模板路径。

        Args:
            doc_type: SW_DOC_PART / SW_DOC_ASSEMBLY / SW_DOC_DRAWING

        Returns:
            模板文件路径字符串（找不到返回 None）
        """
        # 1. 优先通过用户偏好获取（存疑，待实测：枚举值因版本而异）
        #    swUserPreferenceStringValue_e:
        #      swDefaultTemplatePart = 7
        #      swDefaultTemplateAssembly = 8
        #      swDefaultTemplateDrawing = 9
        pref_key_map = {
            SW_DOC_PART: 7,
            SW_DOC_ASSEMBLY: 8,
            SW_DOC_DRAWING: 9,
        }
        pref_key = pref_key_map.get(doc_type)
        if pref_key is not None:
            try:
                tpl = self._sw_app.GetUserPreferenceStringValue(pref_key)
                if tpl and Path(tpl).is_file():
                    return str(tpl)
            except Exception:  # noqa: BLE001
                pass

        # 2. 回退到 SolidWorks 默认安装目录下的 gb 模板
        #    常见安装路径：C:\\Program Files\\SolidWorks Corp\\SolidWorks
        #    模板子目录：templates\\gb\\
        tpl_filenames = {
            SW_DOC_PART: ("零件.prtdot", "Part.prtdot"),
            SW_DOC_ASSEMBLY: ("装配体.asmdot", "Assembly.asmdot"),
            SW_DOC_DRAWING: ("工程图.drwdot", "Drawing.drwdot"),
        }
        candidates = tpl_filenames.get(doc_type, ())
        # 候选安装根目录（SolidWorks 主程序所在目录的上一层）
        install_roots: list[str] = []
        try:
            # 通过 ExecutablePath 获取 SolidWorks 主程序路径（存疑，待实测）
            exe_path = None
            for attr in ("ExecutablePath", "GetExecutablePath"):
                try:
                    v = getattr(self._sw_app, attr, None)
                    if callable(v):
                        v = v()
                    if v:
                        exe_path = str(v)
                        break
                except Exception:  # noqa: BLE001
                    continue
            if exe_path:
                # 主程序路径通常为 ...\\SolidWorks Corp\\SolidWorks\\sldworks.exe
                # 模板路径在 ...\\SolidWorks Corp\\SolidWorks\\templates\\gb\\
                exe_p = Path(exe_path).resolve()
                install_roots.append(str(exe_p.parent))
                if exe_p.parent.parent.name == "SolidWorks Corp":
                    install_roots.append(str(exe_p.parent.parent / "SolidWorks"))
        except Exception:  # noqa: BLE001
            pass
        # 加入常见硬编码安装路径
        install_roots.extend([
            r"C:\Program Files\SolidWorks Corp\SolidWorks",
            r"C:\Program Files\SOLIDWORKS Corp\SolidWorks",
            r"D:\Program Files\SolidWorks Corp\SolidWorks",
            r"D:\Program Files\SOLIDWORKS Corp\SolidWorks",
        ])

        for root in install_roots:
            for fname in candidates:
                # 实测确认：SolidWorks 2025 模板在 data\templates\ 下
                for sub in ("data\\templates\\gb", "data\\templates",
                            "templates\\gb", "templates",
                            "lang\\chinese-simplified\\templates"):
                    tpl_path = Path(root) / sub / fname
                    if tpl_path.is_file():
                        return str(tpl_path)
        return None

    def close_document(self, doc: Any, save_changes: bool = False) -> None:
        """关闭文档。

        Args:
            doc: ModelDoc2 对象
            save_changes: 是否保存修改
        """
        self._ensure_started()
        with self._lock:
            try:
                if save_changes:
                    doc.Save3(2)  # swSaveAsOptions_Silent
                # 关闭文档（参数 0 = swCloseAllOpenDocs？实际上 Close 无参数）
                try:
                    doc.Close()
                except Exception:  # noqa: BLE001
                    pass
                log.info("sw.doc.closed", saved=save_changes)
            except Exception as e:  # noqa: BLE001
                log.warning("sw.doc.close_failed", error=str(e))

    def save_as(
        self,
        doc: Any,
        path: Path,
        version: int = 0,
    ) -> Path:
        """另存为（SaveAs3 封装）。

        Args:
            doc: ModelDoc2 对象
            path: 目标文件路径（扩展名决定格式：.SLDPRT/.STEP/.STL/.IGES/.DXF）
            version: 保存版本（0=当前版本，其他值对应 swSaveAsVersion_e）

        Returns:
            实际保存的文件路径

        Raises:
            SolidWorksTaskError: 保存失败

        实测结论（SolidWorks 2025 SP3.0 + pywin32 308）：
        - SaveAs3 完整签名为 5 参数（含 2 个 ByRef out）：
            bool SaveAs3(BSTR newName, long version, long options,
                         long* errors, long* warnings)
        - **动态 Dispatch（CDispatch，NewPart/NewAssembly 返回值）**：
          传 5 参数报 ``无效的参数数目`` (0x8002000E)；
          传 3 参数返回整数 errors 值（0 = 无错误，文件已实际保存）。
          ``bool(0) == False`` 导致原逻辑误判为失败。
        - **强类型 IModelDoc2**：传 5 参数返回 ``(bool, errors, warnings)`` 元组。
        - 修复策略：先尝试 3 参数路径（兼容动态/强类型），
          若返回 errors 整数（0=成功），以"文件存在且非空"为最终判据。
          仅当 3 参数失败时才尝试 5 参数路径（强类型专用）。
        """
        self._ensure_started()
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        # SaveAs3 签名（spec.md §3 + SolidWorks API Help 实测确认）：
        # bool = ModelDoc2.SaveAs3(
        #   newName: str,
        #   version: int,        # swSaveAsVersion_e
        #   options: int,        # swSaveAsOptions_e（1=Silent, 2=Copy, 4=SkipSaveAsToLatest）
        #   errors: int (out),   # swFileSaveError_e
        #   warnings: int (out)  # swFileSaveWarning_e
        # )
        with self._lock:
            try:
                result: Any = None
                errors_val = 0
                warnings_val = 0

                # 路径 A：3 参数（动态 Dispatch 兼容，实测可用）
                try:
                    result = doc.SaveAs3(str(path), version, 1)  # Silent
                except Exception as e_3arg:
                    err_3arg = str(e_3arg)
                    # 如果是"无效的参数数目"，尝试 5 参数路径（强类型）
                    if "8002000E" in err_3arg or "无效的参数数目" in err_3arg:
                        log.info(
                            "sw.doc.saveas3_5arg_fallback",
                            reason="3arg_rejected",
                        )
                        result = doc.SaveAs3(str(path), version, 1, 0, 0)
                    else:
                        raise

                # 解析返回值（兼容多种格式）
                if isinstance(result, bool):
                    success = result
                elif isinstance(result, (tuple, list)):
                    # 强类型 5 参数路径：(bool, errors, warnings)
                    if len(result) >= 3:
                        success = bool(result[0])
                        errors_val = int(result[1]) if result[1] is not None else 0
                        warnings_val = int(result[2]) if result[2] is not None else 0
                    elif len(result) == 2:
                        success = bool(result[0])
                        errors_val = int(result[1]) if result[1] is not None else 0
                    else:
                        success = bool(result[0])
                elif isinstance(result, int):
                    # 动态 Dispatch 3 参数路径返回 errors 整数
                    # 实测：0 = 无错误 = 成功（文件已实际保存）
                    success = (result == 0)
                    errors_val = result
                else:
                    # 其他类型（None 等）：以文件存在为准
                    success = path.is_file()

                # 最终判据：文件存在且非空（最可靠）
                # 实测：动态 Dispatch 返回 0 但文件已保存（42617 bytes），
                # 故文件存在是唯一可靠的判据
                file_exists = path.is_file()
                file_size = path.stat().st_size if file_exists else 0
                if file_exists and file_size > 0:
                    log.info(
                        "sw.doc.saved",
                        file=str(path),
                        size=file_size,
                        version=version,
                        errors=errors_val,
                        warnings=warnings_val,
                        retval_success=success,
                    )
                    return path

                # 文件不存在或为空：保存失败
                raise SolidWorksTaskError(
                    f"SaveAs3 保存失败：{path} "
                    f"(retval={result!r}, errors={errors_val}, "
                    f"warnings={warnings_val}, file_exists={file_exists})"
                )
            except SolidWorksTaskError:
                raise
            except Exception as e:
                raise SolidWorksTaskError(
                    f"另存为失败 {path}：{e}"
                ) from e

    def _ensure_started(self) -> None:
        """内部断言：会话已启动。"""
        if not self._started or self._sw_app is None:
            raise SolidWorksSessionError(
                "SolidWorks 会话未启动，请先调用 start()"
            )


# ===== 全局单例获取 =====

_session_instance: SolidWorksSession | None = None
_session_lock = threading.Lock()


def get_session() -> SolidWorksSession:
    """获取全局 SolidWorksSession 单例。

    注意：返回的会话可能未启动，调用方需显式调用 start()。
    """
    global _session_instance
    if _session_instance is None:
        with _session_lock:
            if _session_instance is None:
                _session_instance = SolidWorksSession()
    return _session_instance


__all__ = [
    "SW_DOC_ASSEMBLY",
    "SW_DOC_DRAWING",
    "SW_DOC_PART",
    "SolidWorksSession",
    "get_session",
    "is_solidworks_available",
]
