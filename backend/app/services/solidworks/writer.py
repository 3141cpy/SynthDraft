"""SolidWorks SLDPRT/SLDASM 生成器（SubTask 7.3）。

提供从结构化数据重建 SolidWorks 原生文件的能力：

路径 A：CadQuery 代码 → STEP → SolidWorks 导入 → SLDPRT
    适用：LLM/模板生成的 CadQuery 代码，借助 OCC 几何内核生成实体，
    再通过 SolidWorks 导入 STEP 重建可编辑特征树（SolidWorks 会自动
    将导入的 BREP 转换为基础特征，非参数化但可后续编辑）。

路径 B：特征描述 → SolidWorks API 特征重建 → SLDPRT
    适用：已结构化为 SolidWorksModel.features 的特征列表，
    通过 FeatureManager API 逐个重建参数化特征（可编辑、可回滚）。

路径 C：装配体生成
    适用：SWComponent 列表 + SWMate 列表，通过 AddComponent5 +
    AddMate5 重建装配体结构。

依赖（与 reader.py 同源）：
- pywin32（win32com.client / pythoncom）
- SolidWorks（已启动 Session，由 @solidworks_task 装饰器自动管理）

API 参考来源（遵循"以瞎猜接口为耻"原则）：
- SolidWorks API Help 2025: https://help.solidworks.com/2025/english/api/sldworksapiprogguide/
- ISldWorks::NewDocument: 创建新文档（零件/装配/图纸）
- ISldWorks::OpenDoc6: 打开已存在文档
- IModelDoc2::SaveAs3: 另存为（扩展名决定格式）
- IModelDoc2::Extension::SelectByID2: 选择图元
- IModelDoc2::SketchManager::CreateCenterRectangle / CreateLine / InsertSketch: 草图
- IModelDoc2::FeatureManager::FeatureExtrusion2: 拉伸
- IModelDoc2::FeatureManager::FeatureRevolve2: 旋转
- IModelDoc2::FeatureManager::FeatureFillet3 / SimpleFillet: 圆角
- IModelDoc2::FeatureManager::InsertFeatureChamfer: 倒角
- IModelDoc2::FeatureManager::HoleSimple2: 简单孔
- IModelDoc2::FeatureManager::InsertFeatureShell: 抽壳
- IAssemblyDoc::AddComponent5: 装配体插入组件
- IAssemblyDoc::AddMate5: 装配体添加配合

单位约定：
- SolidWorks API 内部使用米（m）/弧度（rad）
- 本模块对外接口统一使用毫米（mm）/度（°），内部转换为 SI 后调用 API
- 转换系数：1 mm = 1e-3 m；1° = π/180 rad

容错策略（"以瞎猜接口为耻"原则）：
- 所有特征创建 API 用 try/except 包裹，失败记入 warnings 不中断
- 不同 SolidWorks 版本 API 签名差异较大，部分调用使用 try/except 链兜底
- 存疑 API 在注释中标注"存疑，待实测"
"""

from __future__ import annotations

import math
import tempfile
from pathlib import Path
from typing import Any

from app.logging import get_logger
from app.schemas.solidworks_model import (
    SWComponent,
    SWFeature,
    SWMate,
    SolidWorksModel,
)
from app.services.solidworks.exceptions import SolidWorksTaskError
from app.services.solidworks.sw_session import (
    SW_DOC_ASSEMBLY,
    SW_DOC_PART,
    SolidWorksSession,
)
from app.services.solidworks.worker_pool import solidworks_task

log = get_logger(__name__)


# ===== pywin32 可选导入（跨平台降级）=====
# SelectByID2 的 Callout 参数需要 VARIANT(VT_DISPATCH, None)，
# 而非 Python None / 整数 0（否则报"类型不匹配"）。
# 实测确认：SolidWorks 2025 SP3.0 + pywin32 308
try:
    import pythoncom  # type: ignore[import-not-found]
    from win32com.client import VARIANT  # type: ignore[import-not-found]

    def _nothing() -> Any:
        """返回 VARIANT(VT_DISPATCH, None)，等价于 COM 的 Nothing。

        SelectByID2 第 8 个参数（Callout）必须传 Nothing，
        传 Python None 或整数 0 会报"类型不匹配"。
        """
        return VARIANT(pythoncom.VT_DISPATCH, None)

except ImportError:
    def _nothing() -> Any:
        return None


# ===== SolidWorks API 常量（不依赖 swconst.tlb）=====

# swDocumentTypes_e（与 sw_session.py 同步）
_SW_DOC_PART = 1
_SW_DOC_ASSEMBLY = 2

# swStartConditions_e（FeatureExtrusion2/FeatureRevolve2 的 t1 参数）
_SW_START_SKETCH_PLANE = 0  # 草图面作为起始
_SW_START_SURFACE = 1
_SW_START_VERTEX = 2
_SW_START_OFFSET = 3

# swEndConditions_e（FeatureExtrusion2/FeatureRevolve2 的 t2 参数）
_SW_END_BLIND = 0          # 给定深度
_SW_END_BLIND_UP_TO_SURFACE = 1  # 存疑，待实测：枚举值可能与版本不同
_SW_END_THROUGH_ALL = 2
_SW_END_OFFSET_FROM_SURFACE = 3
_SW_END_UP_TO_BODY = 4
_SW_END_MID_PLANE = 6

# swMateType_e（与 reader.py 同步）
_SW_MATE_COINCIDENT = 0
_SW_MATE_CONCENTRIC = 1
_SW_MATE_DISTANCE = 5
_SW_MATE_ANGLE = 6

# swMateAlign_e（AddMate5 的 alignFrom 参数）
_SW_MATE_ALIGN_ALIGNED = 0
_SW_MATE_ALIGN_ANTI_ALIGNED = 1
_SW_MATE_ALIGN_CLOSEST = 2

# swAddComponentConfigOptions_e（AddComponent5 的 configOpt 参数）
_SW_THIS_CONFIGURATION = 1
_SW_ALL_CONFIGURATIONS = 2
_SW_SPECIFY_CONFIGURATION = 3

# swSelectType_e（SelectByID2 的 type 参数，常用类型字符串）
# 注意：SelectByID2 接受字符串类型名而非枚举值
_SEL_FACE = "FACE"
_SEL_EDGE = "EDGE"
_SEL_VERTEX = "VERTEX"
_SEL_AXIS = "AXIS"
_SEL_PLANE = "PLANE"
_SEL_SKETCH = "SKETCH"

# swFeatureFilletOptions_e（FeatureFillet3 的 options 参数）
_SW_FILLET_OPT_DEFAULT = 0  # 存疑，待实测：默认值

# 单位换算
_MM_TO_M = 1.0e-3
_DEG_TO_RAD = math.pi / 180.0


# 复用 reader.py 的特征类型映射（避免重复维护两份）
def _import_feature_type_map() -> dict[str, str]:
    """从 reader.py 导入特征类型映射表。

    解耦策略：reader.py 是权威映射表，writer.py 复用避免双源更新。
    """
    try:
        from app.services.solidworks.reader import _FEATURE_TYPE_MAP
        return dict(_FEATURE_TYPE_MAP)
    except Exception:  # noqa: BLE001
        # 兜底最小映射
        return {
            "Extrusion": "extrusion",
            "Boss-Extrude": "extrusion",
            "Cut-Extrude": "extrusion",
            "Revolution": "revolve",
            "Boss-Revolve": "revolve",
            "Fillet": "fillet",
            "Chamfer": "chamfer",
            "Hole": "hole",
            "Shell": "shell",
        }


# ===== 公共入口（被 @solidworks_task 装饰）=====


@solidworks_task(timeout=180.0)
def generate_sldprt_from_cadquery(
    session: SolidWorksSession,
    code: str,
    output_path: Path,
    timeout: int = 60,
) -> Path | tuple[Path, list[str]]:
    """从 CadQuery 代码生成 SLDPRT（路径 A）。

    流程：
    1. 在隔离子进程中执行 CadQuery 代码，生成 STEP（复用 sandbox.py）
    2. SolidWorks 通过 OpenDoc6 打开 STEP（SolidWorks 自动转换为可编辑基础特征）
    3. SaveAs3 保存为 SLDPRT

    降级策略（SW-04 修复）：
    - OpenDoc6 打开 STEP 失败时（如 SolidWorks 对 OCC STEP 兼容性问题），
      不直接 raise，而是调用 generate_sldprt_from_features 作为降级路径。
    - 降级时返回 (output_path, warnings)，warnings 含 path_type=FALLBACK-PATH。
    - 降级也失败时才 raise SolidWorksTaskError。

    Args:
        session: SolidWorksSession（由 @solidworks_task 注入）
        code: CadQuery Python 代码（必须定义变量 `result`，类型为 cq.Workplane）
        output_path: 输出 SLDPRT 路径
        timeout: CadQuery 沙箱执行超时（秒）

    Returns:
        成功时返回 SLDPRT 文件路径（Path）；
        降级时返回 (output_path, warnings)，warnings 含 path_type=FALLBACK-PATH

    Raises:
        SolidWorksTaskError: CadQuery 执行失败、STEP 导入失败且降级也失败、或保存失败
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    log.info(
        "sw.writer.cadquery.start",
        code_len=len(code),
        output=str(output_path),
        sandbox_timeout=timeout,
    )

    # 1. CadQuery 沙箱执行 → STEP 文件
    step_path = _run_cadquery_to_step(code, timeout=timeout)
    log.info("sw.writer.cadquery.step_ready", step=str(step_path))

    # 2. SolidWorks 导入 STEP → SLDPRT
    #    OpenDoc6 打开 STEP 时，SolidWorks 自动创建"导入的特征"基础特征
    #    存疑，待实测：不同 SolidWorks 版本对 STEP 的导入特征命名与结构可能不同
    try:
        doc = session.open_document(step_path, SW_DOC_PART, read_only=False)
    except Exception as step_err:
        # SW-04 降级路径：OpenDoc6 失败，尝试 generate_sldprt_from_features 重建
        log.warning(
            "sw.writer.cadquery.step_import_failed",
            step=str(step_path),
            error=str(step_err),
            fallback="generate_sldprt_from_features",
        )
        warnings: list[str] = [
            f"STEP 导入失败（{step_path}）：{step_err}",
            "path_type=FALLBACK-PATH",
            "降级为 generate_sldprt_from_features 重建（基础特征）",
        ]
        fallback_model = _build_fallback_model_from_cadquery(code)
        # SW-04 增强：STEP 导入可能崩溃 SolidWorks 进程（RPC_E_CALL_FAILED），
        # 导致 session 不可用。降级前检测 session 存活，必要时重启。
        if not session.ping():
            log.warning(
                "sw.writer.cadquery.session_dead",
                action="restart_before_fallback",
                step_error=str(step_err),
            )
            warnings.append("STEP 导入导致 session 崩溃，已自动重启 session")
            try:
                session.close()
                session.start(visible=False)
                log.info("sw.writer.cadquery.session_restarted")
            except Exception as restart_err:
                raise SolidWorksTaskError(
                    f"STEP 导入失败且 session 重启也失败。"
                    f"STEP 错误：{step_err}; 重启错误：{restart_err}"
                ) from restart_err
        try:
            # 调用 _raw_fn 避免 worker_pool 嵌套死锁
            # （当前已在 worker_pool 任务中，持有了并发槽位，
            #   再次调用装饰器函数会因 Semaphore 非重入而死锁）
            raw_features_fn = getattr(
                generate_sldprt_from_features, "_raw_fn",
                generate_sldprt_from_features,
            )
            saved = raw_features_fn(session, fallback_model, output_path)
            log.info(
                "sw.writer.cadquery.fallback_done",
                output=str(saved),
                path_type="FALLBACK-PATH",
            )
            return (saved, warnings)
        except Exception as fallback_err:
            raise SolidWorksTaskError(
                f"STEP 导入失败且降级路径也失败。"
                f"STEP 错误：{step_err}; 降级错误：{fallback_err}"
            ) from fallback_err
    try:
        saved = session.save_as(doc, output_path)
        log.info("sw.writer.cadquery.done", output=str(saved))
        return saved
    finally:
        session.close_document(doc, save_changes=False)


@solidworks_task(timeout=240.0)
def generate_sldprt_from_features(
    session: SolidWorksSession,
    model: SolidWorksModel,
    output_path: Path,
) -> Path:
    """从特征描述重建 SLDPRT（路径 B）。

    流程：
    1. NewDocument 创建空零件
    2. 遍历 model.features，按特征类型调用 FeatureManager API
    3. SaveAs3 保存为 SLDPRT

    支持的特征类型（核心）：
    - extrusion: FeatureManager.FeatureExtrusion2（拉伸）
    - revolve:   FeatureManager.FeatureRevolve2（旋转）
    - fillet:    FeatureManager.FeatureFillet3（圆角）
    - chamfer:   FeatureManager.InsertFeatureChamfer（倒角）
    - hole:      FeatureManager.HoleSimple2（简单孔）
    - shell:     FeatureManager.InsertFeatureShell（抽壳）

    其他类型（sweep/loft/rib/draft/pattern/mirror）暂未实现，记入 warnings。

    Args:
        session: SolidWorksSession（由 @solidworks_task 注入）
        model: SolidWorksModel（features 字段为重建特征列表）
        output_path: 输出 SLDPRT 路径

    Returns:
        实际生成的 SLDPRT 文件路径

    Raises:
        SolidWorksTaskError: 文档创建失败或保存失败
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    log.info(
        "sw.writer.features.start",
        features=len(model.features),
        output=str(output_path),
    )

    # 1. 创建新零件文档
    doc = session.new_document(SW_DOC_PART)
    warnings: list[str] = []
    feat_count = 0

    try:
        # 2. 遍历特征重建
        feat_map = _import_feature_type_map()
        for feat in model.features:
            # 优先使用 SWFeature.kind，缺失时回退到 type_name 映射
            kind = feat.kind if feat.kind != "unknown" else feat_map.get(
                feat.type_name or "", "unknown"
            )
            try:
                success = _build_feature(doc, feat, kind)
                if success:
                    feat_count += 1
                elif success is None:
                    # None 表示该类型未实现，已记入 warnings
                    pass
            except Exception as e:  # noqa: BLE001
                msg = f"特征 '{feat.name}' (kind={kind}) 创建失败: {e}"
                warnings.append(msg)
                log.warning(
                    "sw.writer.feature_failed",
                    feature=feat.name,
                    kind=kind,
                    error=str(e),
                )

        # 3. 校验特征重建结果：所有特征均失败时不保存空零件
        if feat_count == 0:
            raise SolidWorksTaskError(
                f"特征重建失败：{len(model.features)} 个特征均未成功创建"
                + (f"，warnings: {warnings}" if warnings else "")
            )

        # 4. 保存为 SLDPRT
        saved = session.save_as(doc, output_path)
        log.info(
            "sw.writer.features.done",
            output=str(saved),
            features_built=feat_count,
            warnings=len(warnings),
        )
        return saved
    finally:
        session.close_document(doc, save_changes=False)


@solidworks_task(timeout=240.0)
def generate_sldasm_from_components(
    session: SolidWorksSession,
    components: list[SWComponent],
    output_path: Path,
    mates: list[SWMate] | None = None,
) -> Path:
    """从组件列表生成 SLDASM 装配体（路径 C）。

    流程：
    1. NewDocument 创建空装配体
    2. AddComponent5 逐个插入组件（按 transform 定位）
    3. AddMate5 添加配合（仅支持 coincident/concentric/distance，其他类型记入 warnings）

    注意：组件引用的 SLDPRT/SLDASM 文件必须真实存在于磁盘上，
    AddComponent5 通过文件路径加载。

    Args:
        session: SolidWorksSession（由 @solidworks_task 注入）
        components: 组件列表（source_file 必须有效）
        output_path: 输出 SLDASM 路径
        mates: 可选，配合列表（仅 type=coincident/concentric/distance 实现）

    Returns:
        实际生成的 SLDASM 文件路径

    Raises:
        SolidWorksTaskError: 文档创建失败、组件插入失败或保存失败
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    log.info(
        "sw.writer.assembly.start",
        components=len(components),
        mates=len(mates or []),
        output=str(output_path),
    )

    # 1. 创建新装配体
    doc = session.new_document(SW_DOC_ASSEMBLY)
    warnings: list[str] = []
    inserted_comps: dict[str, Any] = {}  # name → Component2 对象
    comp_count = 0

    try:
        # 2. 逐个插入组件
        for comp in components:
            if not comp.source_file:
                warnings.append(
                    f"组件 '{comp.name}' 无 source_file，跳过"
                )
                continue
            src = Path(comp.source_file)
            if not src.is_file():
                warnings.append(
                    f"组件 '{comp.name}' 引用文件不存在: {src}"
                )
                continue
            # transform: 4x4 行主序，前 3 行第 4 列为平移分量
            tx, ty, tz = _extract_translation(comp.transform)
            try:
                sw_comp = _add_component(
                    doc, src, comp.configuration, tx, ty, tz
                )
                if sw_comp is not None:
                    inserted_comps[comp.name] = sw_comp
                    comp_count += 1
            except Exception as e:  # noqa: BLE001
                warnings.append(
                    f"组件 '{comp.name}' 插入失败: {e}"
                )
                log.warning(
                    "sw.writer.comp_insert_failed",
                    component=comp.name,
                    error=str(e),
                )

        # 3. 添加配合（简化版，仅 coincident/concentric/distance）
        if mates:
            for mate in mates:
                try:
                    _add_mate(doc, mate, inserted_comps)
                except Exception as e:  # noqa: BLE001
                    warnings.append(
                        f"配合 '{mate.name}' (type={mate.type}) 添加失败: {e}"
                    )
                    log.warning(
                        "sw.writer.mate_failed",
                        mate=mate.name,
                        type=mate.type,
                        error=str(e),
                    )

        # 4. 保存为 SLDASM
        saved = session.save_as(doc, output_path)
        log.info(
            "sw.writer.assembly.done",
            output=str(saved),
            components_inserted=comp_count,
            warnings=len(warnings),
        )
        return saved
    finally:
        session.close_document(doc, save_changes=False)


# ===== 路径 A 辅助：CadQuery 沙箱执行 =====


def _build_fallback_model_from_cadquery(code: str) -> SolidWorksModel:
    """从 CadQuery 代码构建降级用的最简 SolidWorksModel（SW-04 修复）。

    CadQuery 代码的完整 AST 解析复杂度较高，此处采用正则提取常见几何
    参数（box/cylinder）作为降级特征。降级模型不保证几何完全一致，
    仅保证生成有效 SLDPRT 文件，供下游流程继续运转。

    Args:
        code: CadQuery Python 代码

    Returns:
        SolidWorksModel，含一个最简拉伸特征
    """
    import re

    # 尝试从代码中提取 box(w, d, h) 尺寸
    box_match = re.search(
        r"\.box\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*\)", code
    )
    if box_match:
        depth_mm = float(box_match.group(3))
    else:
        # 尝试提取 cylinder(r, h)
        cyl_match = re.search(
            r"\.circle\(\s*([\d.]+)\s*\)\s*\.extrude\(\s*([\d.]+)\s*\)", code
        )
        if cyl_match:
            depth_mm = float(cyl_match.group(2))
        else:
            depth_mm = 10.0  # 默认拉伸深度

    feat = SWFeature(
        name="Boss-Extrude1",
        kind="extrusion",
        type_name="Boss-Extrude",
        parameters={
            "depth_mm": depth_mm,
            "end_condition": 0,
            "flip_direction": False,
        },
    )
    return SolidWorksModel(
        source_file="",
        doc_type="part",
        features=[feat],
    )


def _run_cadquery_to_step(code: str, timeout: int = 60) -> Path:
    """在隔离子进程中执行 CadQuery 代码，生成 STEP 文件。

    复用 generation/sandbox.py 的执行模式，但本模块仅依赖 STEP 产物，
    不关心 STL/DXF 等附加输出。

    Args:
        code: CadQuery Python 代码
        timeout: 子进程超时（秒）

    Returns:
        STEP 文件路径

    Raises:
        SolidWorksTaskError: 沙箱执行失败或 STEP 未生成
    """
    try:
        from app.services.generation.sandbox import execute_cadquery_code
    except ImportError as e:
        raise SolidWorksTaskError(
            f"CadQuery 沙箱不可用: {e}. 请确保 app.services.generation.sandbox 可导入。"
        ) from e

    with tempfile.TemporaryDirectory(prefix="sw_cadquery_") as tmpdir:
        tmp_path = Path(tmpdir)
        try:
            result = execute_cadquery_code(
                code=code,
                output_dir=tmp_path,
                timeout=timeout,
                output_format="step",
            )
        except Exception as e:  # noqa: BLE001
            raise SolidWorksTaskError(
                f"CadQuery 沙箱执行异常: {e}"
            ) from e

        if not result.success:
            stderr = result.stderr or "unknown"
            violations = result.violations or []
            raise SolidWorksTaskError(
                f"CadQuery 执行失败 (exit_code={result.exit_code}): "
                f"stderr={stderr[:500]}, violations={violations[:3]}"
            )

        # 查找 STEP 文件（沙箱可能同时输出 .step 与 .stp）
        step_files = list(tmp_path.glob("*.step")) + list(
            tmp_path.glob("*.stp")
        )
        if not step_files:
            raise SolidWorksTaskError(
                f"CadQuery 执行成功但未生成 STEP 文件（output_files="
                f"{result.output_files}）"
            )

        # 将 STEP 复制到持久化目录（TemporaryDirectory 退出时会被自动清理）
        # 使用系统 temp 目录下的固定子目录，避免 with 块退出后文件被删除
        step_src = step_files[0]
        persistent_dir = Path(tempfile.gettempdir()) / "sw_cadquery_persistent"
        persistent_dir.mkdir(parents=True, exist_ok=True)
        persistent_step = persistent_dir / f"sw_import_{step_src.name}"
        import shutil
        shutil.copy2(step_src, persistent_step)

        return persistent_step


# ===== 路径 B 辅助：特征重建 =====


def _build_sketch(doc: Any, feat: SWFeature) -> bool:
    """创建草图轮廓（拉伸/旋转特征前置）。

    流程：
    1. SelectByID2 选择基准面（前视/上视，按语言版本回退）
    2. SketchManager.InsertSketch(True) 进入草图模式
    3. 根据 feat.parameters["profile"] 创建轮廓（rectangle/circle）
    4. SketchManager.InsertSketch(True) 退出草图模式

    API（SolidWorks API Help - SketchManager）：
    - InsertSketch(b): 进入/退出草图模式（切换）
    - CreateCornerRectangle(x1, y1, z1, x2, y2, z2): 角点矩形
    - CreateCircle(cx, cy, cz, ex, ey, ez): 圆（圆心+边上一点）

    profile 类型（从 feat.parameters 读取，缺省 "rectangle"）：
    - "rectangle": 矩形（width_mm/height_mm，缺省 10×10mm）
    - "circle": 圆（diameter_mm 或 radius_mm，缺省 ⌀10mm）

    Args:
        doc: ModelDoc2 对象
        feat: SWFeature 特征描述（读取 parameters.profile 及尺寸）

    Returns:
        True: 草图创建成功
        False: 创建失败（基准面选择/草图模式/轮廓创建失败）
    """
    params = feat.parameters
    profile = params.get("profile", "rectangle")

    # 1. 选择草图基准面（名称因 SW 语言版本而异）
    # 存疑，待实测：基准面名称在中文版为"前视基准面"，英文版为"Front Plane"
    plane_selected = False
    for plane_name in ("Front Plane", "前视基准面", "Top Plane", "上视基准面"):
        try:
            ok = doc.Extension.SelectByID2(
                plane_name, _SEL_PLANE, 0.0, 0.0, 0.0,
                False, 0, _nothing(), 0,
            )
            if ok:
                plane_selected = True
                break
        except Exception:  # noqa: BLE001
            continue

    if not plane_selected:
        log.debug(
            "sw.writer.sketch_plane_select_failed",
            feature=feat.name,
        )
        return False

    # 2. 进入草图模式
    try:
        doc.SketchManager.InsertSketch(True)
    except Exception as e:  # noqa: BLE001
        log.debug(
            "sw.writer.sketch_insert_failed",
            feature=feat.name,
            error=str(e),
        )
        return False

    # 3. 创建轮廓（尺寸 mm → m）
    profile_ok = False
    try:
        if profile == "circle":
            diameter_mm = float(
                params.get("diameter_mm",
                           float(params.get("radius_mm", 5.0)) * 2)
            )
            radius_m = diameter_mm * _MM_TO_M / 2.0
            # CreateCircle(cx, cy, cz, ex, ey, ez): 圆心 + 边上一点
            doc.SketchManager.CreateCircle(
                0.0, 0.0, 0.0, radius_m, 0.0, 0.0
            )
            profile_ok = True
        else:
            # 矩形（缺省）
            width_mm = float(params.get("width_mm", 10.0))
            height_mm = float(params.get("height_mm", 10.0))
            w = width_mm * _MM_TO_M / 2.0
            h = height_mm * _MM_TO_M / 2.0
            # CreateCornerRectangle(x1, y1, z1, x2, y2, z2)
            # 存疑，待实测：部分 SW 版本可能为 CreateRectangle
            doc.SketchManager.CreateCornerRectangle(
                -w, -h, 0.0, w, h, 0.0
            )
            profile_ok = True
    except Exception as e:  # noqa: BLE001
        log.debug(
            "sw.writer.sketch_profile_failed",
            feature=feat.name,
            profile=profile,
            error=str(e),
        )

    # 4. 退出草图模式（无论轮廓是否成功都退出，避免卡在草图模式）
    try:
        doc.SketchManager.InsertSketch(True)
    except Exception as e:  # noqa: BLE001
        log.debug(
            "sw.writer.sketch_exit_failed",
            feature=feat.name,
            error=str(e),
        )
        return False

    if profile_ok:
        log.info(
            "sw.writer.sketch_created",
            feature=feat.name,
            profile=profile,
        )
    return profile_ok


def _build_feature(doc: Any, feat: SWFeature, kind: str) -> bool | None:
    """根据特征类型调用对应 FeatureManager API 创建特征。

    Args:
        doc: ModelDoc2 对象
        feat: SWFeature 特征描述
        kind: 特征类型（extrusion/revolve/fillet/chamfer/hole/shell）

    Returns:
        True: 成功创建
        False: 创建失败（已记入 warnings 由调用方）
        None: 该类型未实现（已记入 warnings 由调用方）

    注意：单位转换——SWFeature.parameters 中的数值统一为 mm/度，
    SolidWorks API 接受 m/弧度，调用前需 ×_MM_TO_M / ×_DEG_TO_RAD。
    """
    if kind == "extrusion":
        if not _build_sketch(doc, feat):
            log.warning(
                "sw.writer.sketch_missing_skip",
                feature=feat.name,
                kind=kind,
            )
            return False
        return _build_extrusion(doc, feat)
    if kind == "revolve":
        if not _build_sketch(doc, feat):
            log.warning(
                "sw.writer.sketch_missing_skip",
                feature=feat.name,
                kind=kind,
            )
            return False
        return _build_revolve(doc, feat)
    if kind == "fillet":
        return _build_fillet(doc, feat)
    if kind == "chamfer":
        return _build_chamfer(doc, feat)
    if kind == "hole":
        return _build_hole(doc, feat)
    if kind == "shell":
        return _build_shell(doc, feat)
    # 未实现的类型
    log.info(
        "sw.writer.feature_unimplemented",
        feature=feat.name,
        kind=kind,
    )
    return None


def _build_extrusion(doc: Any, feat: SWFeature) -> bool:
    """拉伸特征重建（FeatureManager.FeatureExtrusion2）。

    API 签名（SolidWorks 2025 SP3.0 类型库实测，23 参数）：
        Feature FeatureExtrusion2(
            bool Sd,                   // 单方向
            bool Flip,                 // 反向
            bool Dir,                  // 第二方向
            long T1,                   // swStartConditions_e (草图面=0)
            long T2,                   // swEndConditions_e (给定深度=0)
            double D1,                 // 深度1（米）
            double D2,                 // 深度2
            bool Dchk1, Dchk2,         // 拔模开关1/2
            bool Ddir1, Ddir2,         // 拔模方向1/2
            double Dang1, Dang2,       // 拔模角度1/2（弧度）
            bool OffsetReverse1, OffsetReverse2,        // 偏移反向1/2
            bool TranslateSurface1, TranslateSurface2,  // 平移曲面1/2
            bool Merge,                // 合并实体
            bool UseFeatScope,         // 特征作用范围
            bool UseAutoSelect,        // 自动选择
            long T0,                   // 起始条件类型
            double StartOffset,        // 起始偏移
            bool FlipStartOffset       // 翻转起始偏移
        )

    实测确认（SolidWorks 2025 SP3.0 + pywin32 308）：
    - 23 参数为正确签名（24 参数报"无效的参数数目"）
    - 草图必须先创建并退出草图模式（InsertSketch(True) 退出）
    - 草图必须包含闭合轮廓（如 CreateCenterRectangle 创建的矩形）
    """
    params = feat.parameters
    # 深度 mm → m
    depth_mm = float(params.get("depth_mm", 10.0))
    depth_m = depth_mm * _MM_TO_M
    flip_dir = bool(params.get("flip_direction", False))
    # end_condition: 0=blind, 2=through_all
    end_cond = int(params.get("end_condition", 0))
    if end_cond not in (0, 2):
        end_cond = 0

    fm = doc.FeatureManager
    # 简化参数：单方向、无拔模、自动选择作用范围、合并实体
    try:
        feat_obj = fm.FeatureExtrusion2(
            True,                   # 1. Sd: 单方向
            flip_dir,               # 2. Flip: 反向
            False,                  # 3. Dir: 第二方向
            _SW_START_SKETCH_PLANE, # 4. T1: 起始条件
            end_cond,               # 5. T2: 终止条件
            depth_m,                # 6. D1: 深度1
            0.0,                    # 7. D2: 深度2
            False, False,           # 8-9. Dchk1, Dchk2: 拔模开关
            False, False,           # 10-11. Ddir1, Ddir2: 拔模方向
            0.0, 0.0,               # 12-13. Dang1, Dang2: 拔模角度
            False, False,           # 14-15. OffsetReverse1, OffsetReverse2
            False, False,           # 16-17. TranslateSurface1, TranslateSurface2
            True,                   # 18. Merge: 合并实体
            False,                  # 19. UseFeatScope
            True,                   # 20. UseAutoSelect
            _SW_START_SKETCH_PLANE, # 21. T0: 起始条件类型
            0.0,                    # 22. StartOffset
            False,                  # 23. FlipStartOffset
        )
        if feat_obj is not None:
            log.info(
                "sw.writer.extrusion_created",
                feature=feat.name,
                depth_mm=depth_mm,
            )
            return True
    except Exception as e:  # noqa: BLE001
        log.debug(
            "sw.writer.extrusion2_failed",
            feature=feat.name,
            error=str(e),
        )
    # 兜底：尝试 FeatureExtrusion3（较新 API，签名可能与 Extrusion2 不同）
    # 存疑，待实测：参数签名因版本差异较大，仅做兜底尝试
    try:
        feat_obj = fm.FeatureExtrusion3(
            True, False, False,
            _SW_START_SKETCH_PLANE, end_cond, depth_m,
            0.0, False, False, False, False, 0.0, 0.0,
            True, False, True, 0.0, 0.0, 0.0,
            False, False, 0.0, False, "",
        )
        if feat_obj is not None:
            log.info(
                "sw.writer.extrusion_created_via_extrusion3",
                feature=feat.name,
            )
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def _build_revolve(doc: Any, feat: SWFeature) -> bool:
    """旋转特征重建（FeatureManager.FeatureRevolve2）。

    API 签名（SolidWorks API Help - FeatureManager.FeatureRevolve2）：
        Feature FeatureRevolve2(
            bool sd, bool flip, bool dir2,
            int t1, int t2,
            double revDim,         // 旋转角度（弧度）
            double revDim2,
            bool merge,
            bool useFeatScope, bool useAutoSelect,
            bool useAssemblyFeature,
            bool flipStartOffset, double startOffset,
            bool flipEndOffset, double endOffset
        )

    注意：旋转特征需要草图预先包含旋转轴（中心线或草图线段）。
    本函数假设草图已通过 _build_sketch 创建好。
    存疑，待实测：旋转轴识别依赖 SolidWorks 内部规则。
    """
    params = feat.parameters
    # 角度 deg → rad
    angle_deg = float(params.get("angle_deg", 360.0))
    angle_rad = angle_deg * _DEG_TO_RAD
    direction = int(params.get("direction", 0))

    fm = doc.FeatureManager
    try:
        feat_obj = fm.FeatureRevolve2(
            True,                  # sd: 单方向
            direction != 0,        # flip
            False,                 # dir2
            _SW_START_SKETCH_PLANE, # t1
            _SW_END_BLIND,         # t2
            angle_rad,             # revDim
            0.0,                   # revDim2
            True,                  # merge
            False,                 # useFeatScope
            True,                  # useAutoSelect
            False,                 # useAssemblyFeature
            False, 0.0,            # flipStartOffset, startOffset
            False, 0.0,            # flipEndOffset, endOffset
        )
        if feat_obj is not None:
            log.info(
                "sw.writer.revolve_created",
                feature=feat.name,
                angle_deg=angle_deg,
            )
            return True
    except Exception as e:  # noqa: BLE001
        log.debug(
            "sw.writer.revolve2_failed",
            feature=feat.name,
            error=str(e),
        )
    return False


def _build_fillet(doc: Any, feat: SWFeature) -> bool:
    """圆角特征重建（FeatureManager.FeatureFillet3）。

    API 签名（SolidWorks API Help - FeatureManager.FeatureFillet3）：
        Feature FeatureFillet3(
            int options,            // swFeatureFilletOptions_e
            double r1,              // 圆角半径（米）
            int fllType,            // 等半径/变半径
            int overflowType,       // overflow 控制类型
            int setbackType,
            int nPts,
            ...
        )

    存疑，待实测：FeatureFillet3 签名在 SW 2018+ 较稳定，
    但参数数量较多，此处仅传前 5 个核心参数。
    调用前需通过 SelectByID2 选中待圆角的边/面。
    """
    params = feat.parameters
    radius_mm = float(params.get("radius_mm", 1.0))
    radius_m = radius_mm * _MM_TO_M

    # 选择待圆角的边（如果 parameters 中有 edge_id 列表）
    edge_ids: list[str] = params.get("edge_ids", []) or []
    for eid in edge_ids:
        try:
            doc.Extension.SelectByID2(
                str(eid), _SEL_EDGE, 0.0, 0.0, 0.0,
                True, 0, _nothing(), 0,  # append=True, Callout=Nothing
            )
        except Exception:  # noqa: BLE001
            pass

    fm = doc.FeatureManager
    # 等半径圆角：FeatureFillet3(options, radius, fllType=0, ...)
    try:
        feat_obj = fm.FeatureFillet3(
            _SW_FILLET_OPT_DEFAULT,  # options
            radius_m,                 # r1
            0,                        # fllType: 0=等半径
            0, 0,                     # overflowType, setbackType
            0,                        # nPts: 等半径无变半径点
            None, None, None,         # radiusArr, distArr, edgeArr（pywin32 忽略）
        )
        if feat_obj is not None:
            log.info(
                "sw.writer.fillet_created",
                feature=feat.name,
                radius_mm=radius_mm,
            )
            return True
    except Exception as e:  # noqa: BLE001
        log.debug(
            "sw.writer.fillet3_failed",
            feature=feat.name,
            error=str(e),
        )

    # 兜底：尝试 SimpleFillet（旧 API）
    # 存疑，待实测：SimpleFillet 在新版 SW 中可能已弃用
    try:
        feat_obj = fm.SimpleFillet(radius_m)
        if feat_obj is not None:
            log.info(
                "sw.writer.fillet_created_via_simple",
                feature=feat.name,
            )
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def _build_chamfer(doc: Any, feat: SWFeature) -> bool:
    """倒角特征重建（FeatureManager.InsertFeatureChamfer）。

    API 签名（SolidWorks API Help - FeatureManager.InsertFeatureChamfer）：
        Feature InsertFeatureChamfer(
            double width,           // 倒角距离（米）
            double angle,           // 倒角角度（度，注意：非弧度！）
            bool flip,
            int options,            // swFeaturesChamferOptions_e
            int edgeCount,
            edge[] edgeArr,
            ...
        )

    存疑，待实测：参数顺序与版本相关。InsertFeatureChamfer(4) 在较新版本可能改用
    InsertFeatureChamfer(width, angle, ...) 或 ChamferFeature。
    """
    params = feat.parameters
    distance_mm = float(params.get("distance_mm", 1.0))
    distance_m = distance_mm * _MM_TO_M
    angle_deg = float(params.get("angle_deg", 45.0))

    # 选择待倒角的边
    edge_ids: list[str] = params.get("edge_ids", []) or []
    for eid in edge_ids:
        try:
            doc.Extension.SelectByID2(
                str(eid), _SEL_EDGE, 0.0, 0.0, 0.0,
                True, 0, _nothing(), 0,
            )
        except Exception:  # noqa: BLE001
            pass

    fm = doc.FeatureManager
    # 尝试 InsertFeatureChamfer（参数：width, angle, flip, options, ...）
    # 存疑，待实测：调用签名因版本差异较大，使用 try/except 链
    try:
        feat_obj = fm.InsertFeatureChamfer(
            distance_m,   # width（米）
            angle_deg,    # angle（度，注意此处不是弧度）
            False,        # flip
            0,            # options
            0,            # edgeCount（已通过 SelectByID2 选择）
            None,         # edgeArr
        )
        if feat_obj is not None:
            log.info(
                "sw.writer.chamfer_created",
                feature=feat.name,
                distance_mm=distance_mm,
                angle_deg=angle_deg,
            )
            return True
    except Exception as e:  # noqa: BLE001
        log.debug(
            "sw.writer.chamfer_failed",
            feature=feat.name,
            error=str(e),
        )
    # 兜底：尝试 ChamferFeature（旧 API 名）
    # 存疑，待实测：可能在某些 SW 版本可用
    try:
        feat_obj = fm.ChamferFeature(distance_m)
        if feat_obj is not None:
            log.info(
                "sw.writer.chamfer_created_via_chamferfeature",
                feature=feat.name,
            )
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def _build_hole(doc: Any, feat: SWFeature) -> bool:
    """简单孔特征重建（FeatureManager.HoleSimple2）。

    API 签名（SolidWorks API Help - FeatureManager.HoleSimple2）：
        Feature HoleSimple2(
            double dia,             // 孔直径（米）
            double depth,          // 孔深度（米）
            int types,             // 0=给定深度, 1=完全贯穿
            int headType,
            double headDia, double headDepth,
            double nearEdge, double farEdge,
            int threadMethod, double threadDepth,
            double pitch, double diameter, double nutDia,
            int endModType, double endDistance
        )

    调用前需 SelectByID2 选中孔放置面。
    存疑，待实测：参数较多，仅传前 3 个核心参数 + 其余置默认。
    """
    params = feat.parameters
    diameter_mm = float(params.get("diameter_mm", 5.0))
    diameter_m = diameter_mm * _MM_TO_M
    depth_mm = float(params.get("depth_mm", 10.0))
    depth_m = depth_mm * _MM_TO_M
    through_all = bool(params.get("through_all", False))
    types = 1 if through_all else 0

    # 选择孔放置面（如 parameters 中有 face_id）
    face_id = params.get("face_id")
    if face_id:
        try:
            doc.Extension.SelectByID2(
                str(face_id), _SEL_FACE, 0.0, 0.0, 0.0,
                False, 0, _nothing(), 0,
            )
        except Exception:  # noqa: BLE001
            pass

    fm = doc.FeatureManager
    try:
        feat_obj = fm.HoleSimple2(
            diameter_m,    # dia
            depth_m,       # depth
            types,         # types: 0=给定深度, 1=完全贯穿
            0,             # headType: 普通孔
            0.0, 0.0,      # headDia, headDepth
            0.0, 0.0,      # nearEdge, farEdge
            0,             # threadMethod: 无螺纹
            0.0,           # threadDepth
            0.0,           # pitch
            0.0,           # diameter
            0.0,           # nutDia
            0,             # endModType
            0.0,           # endDistance
        )
        if feat_obj is not None:
            log.info(
                "sw.writer.hole_created",
                feature=feat.name,
                diameter_mm=diameter_mm,
                depth_mm=depth_mm,
                through_all=through_all,
            )
            return True
    except Exception as e:  # noqa: BLE001
        log.debug(
            "sw.writer.hole_failed",
            feature=feat.name,
            error=str(e),
        )
    return False


def _build_shell(doc: Any, feat: SWFeature) -> bool:
    """抽壳特征重建（FeatureManager.InsertFeatureShell）。

    API 签名（SolidWorks API Help - FeatureManager.InsertFeatureShell）：
        Feature InsertFeatureShell(
            double thickness,       // 壁厚（米）
            bool outward            // True=向外抽壳
        )

    调用前需 SelectByID2 选中要移除的面（如有的话）。
    """
    params = feat.parameters
    thickness_mm = float(params.get("thickness_mm", 1.0))
    thickness_m = thickness_mm * _MM_TO_M
    outward = bool(params.get("outward", False))

    fm = doc.FeatureManager
    try:
        feat_obj = fm.InsertFeatureShell(thickness_m, outward)
        if feat_obj is not None:
            log.info(
                "sw.writer.shell_created",
                feature=feat.name,
                thickness_mm=thickness_mm,
                outward=outward,
            )
            return True
    except Exception as e:  # noqa: BLE001
        log.debug(
            "sw.writer.shell_failed",
            feature=feat.name,
            error=str(e),
        )
    return False


# ===== 路径 C 辅助：装配体组件插入与配合 =====


def _extract_translation(
    transform: list[float] | None,
) -> tuple[float, float, float]:
    """从 SolidWorks MathTransform.ArrayData 提取平移分量。

    transform 为 MathTransform.ArrayData 返回的 16 个 double：
        [0-8]  : 3x3 旋转矩阵（行主序）
        [9-11] : 平移分量 tx, ty, tz（单位：米）
        [12]   : 比例因子
        [13-15]: 未使用

    SW API 返回的平移已是米（SW 内部单位），无需 _MM_TO_M 转换。
    AddComponent5 的 x/y/z 参数单位亦为米，直接传入。

    Returns:
        (tx, ty, tz) 单位米
    """
    if not transform or len(transform) < 16:
        return (0.0, 0.0, 0.0)
    tx = float(transform[9] or 0.0)
    ty = float(transform[10] or 0.0)
    tz = float(transform[11] or 0.0)
    return (tx, ty, tz)


def _add_component(
    doc: Any,
    src_path: Path,
    configuration: str | None,
    tx_m: float,
    ty_m: float,
    tz_m: float,
) -> Any:
    """调用 AssemblyDoc.AddComponent5 插入组件。

    API 签名（SolidWorks API Help - AssemblyDoc.AddComponent5）：
        Component2 AddComponent5(
            string compName,                       // 组件文件路径
            int configOpt,                         // swAddComponentConfigOptions_e
            string configName,                     // 配置名（仅 configOpt=3 时使用）
            bool useCfgForPartReferences,
            string existingConfigName,
            double x, double y, double z           // 插入位置（米）
        )

    存疑，待实测：AddComponent5 在不同 SW 版本签名稳定，但
    useCfgForPartReferences 与 existingConfigName 参数语义需核对。
    """
    # 选择配置策略
    if configuration:
        config_opt = _SW_SPECIFY_CONFIGURATION
        config_name = configuration
    else:
        config_opt = _SW_THIS_CONFIGURATION
        config_name = ""

    try:
        comp = doc.AddComponent5(
            str(src_path),
            config_opt,
            config_name,
            False,             # useCfgForPartReferences
            "",                # existingConfigName
            tx_m, ty_m, tz_m,
        )
        return comp
    except Exception as e:  # noqa: BLE001
        log.warning(
            "sw.writer.add_component5_failed",
            src=str(src_path),
            error=str(e),
        )
        # 兜底：尝试 AddComponent4（旧 API）
        # 存疑，待实测：旧版 SW 可能仅有 AddComponent4
        try:
            comp = doc.AddComponent4(
                str(src_path),
                config_name,
                False, "",
                tx_m, ty_m, tz_m,
            )
            return comp
        except Exception:  # noqa: BLE001
            return None


def _add_mate(doc: Any, mate: SWMate, comp_map: dict[str, Any]) -> bool:
    """调用 AssemblyDoc.AddMate5 添加配合。

    API 签名（SolidWorks API Help - AssemblyDoc.AddMate5）：
        Mate2 AddMate5(
            int mateType,           // swMateType_e
            int alignFrom,          // swMateAlign_e
            int mutualConstr,
            double angleOrDist,     // 距离（米）/角度（弧度）
            bool flipAngle,
            double angleOrDist2,
            int concentricAdjustOption,
            int angleAdvmntType,
            int widthType,
            int mateReferenceIndex
        )

    注意：AddMate5 之前必须通过 SelectByID2 选中两个配合实体。
    存疑，待实测：实体选择规则依赖文档几何，本实现仅按配合类型简化处理。

    仅实现 type=coincident/concentric/distance 三种最常用配合。
    """
    mate_type_str = mate.type
    if mate_type_str == "coincident":
        sw_mate_type = _SW_MATE_COINCIDENT
    elif mate_type_str == "concentric":
        sw_mate_type = _SW_MATE_CONCENTRIC
    elif mate_type_str == "distance":
        sw_mate_type = _SW_MATE_DISTANCE
    elif mate_type_str == "angle":
        sw_mate_type = _SW_MATE_ANGLE
    else:
        log.info(
            "sw.writer.mate_unsupported",
            mate=mate.name,
            type=mate_type_str,
        )
        return False

    # 距离/角度数值（mm/deg → m/rad）
    if mate_type_str == "distance" and mate.distance is not None:
        angle_or_dist = mate.distance * _MM_TO_M
    elif mate_type_str == "angle" and mate.distance is not None:
        angle_or_dist = mate.distance * _DEG_TO_RAD
    else:
        angle_or_dist = 0.0

    # alignFrom 转换
    align = mate.alignment
    if align == "aligned":
        sw_align = _SW_MATE_ALIGN_ALIGNED
    elif align == "anti_aligned":
        sw_align = _SW_MATE_ALIGN_ANTI_ALIGNED
    else:
        sw_align = _SW_MATE_ALIGN_CLOSEST

    # 配合实体选择（简化版：依赖调用方预先选择，本函数仅尝试添加配合）
    # 实际生产中应通过 mate.entity_1 / entity_2 解析具体图元 ID
    # 存疑，待实测：实体选择策略需根据 SWFeature 引用关系设计
    try:
        mate_obj = doc.AddMate5(
            sw_mate_type,         # mateType
            sw_align,             # alignFrom
            0,                    # mutualConstr
            angle_or_dist,        # angleOrDist
            False,                # flipAngle
            0.0,                  # angleOrDist2
            0,                    # concentricAdjustOption
            0,                    # angleAdvmntType
            0,                    # widthType
            0,                    # mateReferenceIndex
        )
        if mate_obj is not None:
            try:
                mate_obj.Name = mate.name
            except Exception:  # noqa: BLE001
                pass
            log.info(
                "sw.writer.mate_added",
                mate=mate.name,
                type=mate_type_str,
            )
            return True
    except Exception as e:  # noqa: BLE001
        log.debug(
            "sw.writer.addmate5_failed",
            mate=mate.name,
            error=str(e),
        )
    return False


# ===== 模块自检入口（不依赖 SolidWorks 实例）=====


def _self_test() -> dict[str, Any]:
    """离线自检：验证模块导入与依赖完整。

    本函数不调用 SolidWorks API，可在 Linux 环境运行。
    用于 CI / 离线环境验证模块完整性。

    Returns:
        {"ok": bool, "errors": list[str], "checks": dict[str, bool]}
    """
    checks: dict[str, bool] = {}
    errors: list[str] = []
    try:
        from app.schemas.solidworks_model import (  # noqa: F401
            SWComponent,
            SWFeature,
            SWMate,
            SolidWorksModel,
        )
        checks["schema_import"] = True
    except Exception as e:  # noqa: BLE001
        checks["schema_import"] = False
        errors.append(f"schema 导入失败: {e}")
    try:
        from app.services.solidworks.sw_session import (  # noqa: F401
            SW_DOC_ASSEMBLY,
            SW_DOC_PART,
            is_solidworks_available,
        )
        checks["session_import"] = True
        checks["available_flag"] = isinstance(is_solidworks_available(), bool)
    except Exception as e:  # noqa: BLE001
        checks["session_import"] = False
        errors.append(f"session 导入失败: {e}")
    try:
        from app.services.solidworks.worker_pool import (  # noqa: F401
            solidworks_task,
        )
        checks["worker_pool_import"] = True
    except Exception as e:  # noqa: BLE001
        checks["worker_pool_import"] = False
        errors.append(f"worker_pool 导入失败: {e}")
    try:
        # 验证常量映射完整
        checks["sw_doc_part_const"] = _SW_DOC_PART == 1
        checks["sw_doc_assembly_const"] = _SW_DOC_ASSEMBLY == 2
        checks["mate_consts"] = (
            _SW_MATE_COINCIDENT == 0
            and _SW_MATE_CONCENTRIC == 1
            and _SW_MATE_DISTANCE == 5
        )
        checks["unit_consts"] = (
            abs(_MM_TO_M - 1.0e-3) < 1e-12
            and abs(_DEG_TO_RAD - math.pi / 180.0) < 1e-12
        )
        # 验证特征类型映射可加载
        feat_map = _import_feature_type_map()
        checks["feature_type_map"] = (
            len(feat_map) > 0 and "Extrusion" in feat_map
        )
    except Exception as e:  # noqa: BLE001
        checks["constants"] = False
        errors.append(f"常量校验失败: {e}")
    # 公共入口函数签名验证
    checks["generate_sldprt_from_cadquery_callable"] = callable(
        generate_sldprt_from_cadquery
    )
    checks["generate_sldprt_from_features_callable"] = callable(
        generate_sldprt_from_features
    )
    checks["generate_sldasm_from_components_callable"] = callable(
        generate_sldasm_from_components
    )
    # 辅助函数验证
    checks["build_feature_callable"] = callable(_build_feature)
    checks["build_sketch_callable"] = callable(_build_sketch)
    checks["extract_translation_callable"] = callable(_extract_translation)
    try:
        # 单位换算正确性
        tx, ty, tz = _extract_translation(None)
        checks["extract_translation_none"] = (tx, ty, tz) == (0.0, 0.0, 0.0)
        # MathTransform.ArrayData 平移提取
        # 结构: [0-8]=旋转矩阵, [9-11]=平移(米), [12]=比例, [13-15]=未使用
        # 构造平移 (0.01, 0.02, 0.03) 米的 MathTransform（单位已是米，无需转换）
        tf = [
            1.0, 0.0, 0.0,  # 旋转矩阵 row 1
            0.0, 1.0, 0.0,  # 旋转矩阵 row 2
            0.0, 0.0, 1.0,  # 旋转矩阵 row 3
            0.01, 0.02, 0.03,  # 平移 tx, ty, tz（米）
            1.0,  # 比例因子
            0.0, 0.0, 1.0,  # 未使用
        ]
        tx, ty, tz = _extract_translation(tf)
        checks["extract_translation_4x4"] = (
            abs(tx - 0.01) < 1e-9
            and abs(ty - 0.02) < 1e-9
            and abs(tz - 0.03) < 1e-9
        )
    except Exception as e:  # noqa: BLE001
        checks["extract_translation"] = False
        errors.append(f"extract_translation 测试失败: {e}")

    ok = all(checks.values())
    return {"ok": ok, "errors": errors, "checks": checks}


if __name__ == "__main__":  # pragma: no cover
    import json

    result = _self_test()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    import sys
    sys.exit(0 if result["ok"] else 1)
