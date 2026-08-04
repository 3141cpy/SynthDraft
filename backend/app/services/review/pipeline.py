"""审图管线核心：DXF 解析 → 图片渲染 → 语义融合（SubTask 4.1 + 4.3）。

复用 Task 2 的 parse_dxf_to_intermediate()，叠加：
- render_dxf_to_image()：ezdxf matplotlib addon 渲染 DXF 为 PNG
- prepare_review_context()：组合解析结果 + 渲染图片为 ReviewContext
- fuse_to_semantic_model()：CADIntermediateModel + VLM 结果 → SemanticModel

官方 API 参考：
- ezdxf.addons.drawing.matplotlib:
  https://ezdxf.readthedocs.io/en/stable/addons/drawing/matplotlib.html
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from app.logging import get_logger
from app.schemas.cad_intermediate import CADIntermediateModel
from app.schemas.review_detail import (
    GeometryLayer,
    ReviewContext,
    SemanticLayer,
    SemanticModel,
    TopologyLayer,
)
from app.services.cad.dxf_parser import parse_dxf_to_intermediate

log = get_logger(__name__)


def _get_default_image_dir() -> Path:
    """从配置读取渲染图片默认输出目录。"""
    from app.config import settings

    return Path(settings.REVIEW_IMAGE_DIR)


def render_dxf_to_image(
    dxf_path: Path,
    output_path: Path | None = None,
    dpi: int = 150,
) -> Path:
    """用 ezdxf matplotlib addon 将 DXF 渲染为 PNG。

    Args:
        dxf_path: DXF 文件路径
        output_path: 输出 PNG 路径；None 则生成在 REVIEW_IMAGE_DIR 配置目录下，
            文名与 DXF 同名 + .png
        dpi: 渲染分辨率

    Returns:
        PNG 文件路径

    Raises:
        RuntimeError: 渲染失败（matplotlib 不可用或 DXF 损坏）
    """
    dxf_path = Path(dxf_path)
    if output_path is None:
        image_dir = _get_default_image_dir()
        image_dir.mkdir(parents=True, exist_ok=True)
        output_path = image_dir / f"{dxf_path.stem}.png"
    else:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        # 延迟导入：matplotlib + ezdxf.addons.drawing 在某些 headless 环境
        # 需要 Agg 后端，避免 tkinter 依赖
        import matplotlib

        matplotlib.use("Agg")
        from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
        from ezdxf.addons.drawing import RenderContext, Frontend
        import ezdxf
    except ImportError as e:
        raise RuntimeError(
            f"渲染依赖不可用（matplotlib/ezdxf.addons）: {e}"
        ) from e

    t0 = time.perf_counter()
    try:
        doc = ezdxf.readfile(str(dxf_path))
        msp = doc.modelspace()
        fig, ax = _make_fig()
        ctx = RenderContext(doc)
        out = MatplotlibBackend(ax)
        Frontend(ctx, out).draw_layout(msp)
        fig.savefig(
            str(output_path),
            dpi=dpi,
            bbox_inches="tight",
            facecolor="white",
        )
        # 关闭 figure 释放内存
        import matplotlib.pyplot as plt

        plt.close(fig)
    except Exception as e:
        raise RuntimeError(f"DXF 渲染为 PNG 失败: {dxf_path} ({e})") from e

    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    log.info(
        "review.render.image_done",
        dxf=str(dxf_path),
        image=str(output_path),
        dpi=dpi,
        elapsed_ms=elapsed_ms,
    )
    return output_path


def _make_fig() -> tuple[Any, Any]:
    """创建 matplotlib figure/axes（隔离以便测试 mock）。"""
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    ax.set_aspect("equal")
    return fig, ax


def prepare_review_context(file_path: Path) -> ReviewContext:
    """准备审图上下文：按文件类型分流处理。

    - DXF 文件：解析 + 渲染图片
    - 图片文件（JPG/PNG）：跳过 CAD 解析，直接使用图片路径
    - PDF 文件：渲染为 PNG 后复用 image 路径
    - DWG 文件：经 ODA File Converter 转 DXF 后复用 DXF 管线
    - 其他类型：抛出 ValueError

    Args:
        file_path: 输入文件路径

    Returns:
        ReviewContext
    """
    file_path = Path(file_path)
    suffix = file_path.suffix.lower()

    if suffix == ".dxf":
        return _build_dxf_context(file_path)
    if suffix in (".jpg", ".jpeg", ".png"):
        return _build_image_context(file_path)
    if suffix == ".pdf":
        return _build_pdf_context(file_path)
    if suffix == ".dwg":
        return _build_dwg_context(file_path)
    if suffix == ".sldprt":
        return _build_sldprt_context(file_path)
    if suffix == ".sldasm":
        return _build_sldasm_context(file_path)
    if suffix in (".step", ".stp"):
        return _build_step_context(file_path)
    if suffix in (".iges", ".igs"):
        return _build_iges_context(file_path)
    raise ValueError(f"暂不支持的文件类型: {suffix}")


def _build_dxf_context(file_path: Path) -> ReviewContext:
    """DXF 文件审图上下文：解析 + 渲染图片。

    解析失败时抛出 CADParseError（来自 Task 2）；
    渲染失败时仅记录 warning，image_path 置 None（不阻断审图）。
    """
    t0 = time.perf_counter()

    cad_model = parse_dxf_to_intermediate(file_path)

    image_path: str | None = None
    render_error: str | None = None
    try:
        png = render_dxf_to_image(file_path)
        image_path = str(png)
    except Exception as e:
        render_error = str(e)
        log.warning("review.render.failed", dxf=str(file_path), error=render_error)

    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    metadata: dict[str, Any] = {
        "prepare_elapsed_ms": elapsed_ms,
        "render_error": render_error,
        "entity_count": len(cad_model.entities),
        "dimension_count": len(cad_model.dimensions),
        "layer_count": len(cad_model.layers),
        "has_title_block": cad_model.title_block is not None,
    }

    return ReviewContext(
        source_file=str(file_path.resolve()),
        source_format=cad_model.source_format,
        cad_model=cad_model,
        image_path=image_path,
        parse_metadata=metadata,
    )


def _build_image_context(file_path: Path) -> ReviewContext:
    """构造图片文件的审图上下文：跳过 CAD 解析，直接使用图片路径。"""
    t0 = time.perf_counter()
    cad_model = CADIntermediateModel(
        source_file=str(file_path.resolve()),
        source_format="image",
        metadata={"source_type": "image"},
    )
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    metadata: dict[str, Any] = {
        "prepare_elapsed_ms": elapsed_ms,
        "source_type": "image",
        "entity_count": 0,
        "dimension_count": 0,
        "layer_count": 0,
        "has_title_block": False,
    }
    return ReviewContext(
        source_file=str(file_path.resolve()),
        source_format="image",
        cad_model=cad_model,
        image_path=str(file_path),
        parse_metadata=metadata,
    )


def _build_pdf_context(file_path: Path) -> ReviewContext:
    """构造 PDF 文件的审图上下文：渲染为 PNG 后复用 image 路径。

    PDF 不含矢量实体，仅渲染为位图供 VLM 识别；
    渲染失败时仅记录 warning，image_path 置 None（不阻断审图）。
    """
    from app.services.review.pdf_renderer import render_pdf_to_image

    t0 = time.perf_counter()
    image_path: str | None = None
    render_error: str | None = None
    try:
        output_png = str(file_path.with_suffix(".png"))
        image_path = render_pdf_to_image(file_path, output_path=output_png)
        log.info("review.pipeline.pdf_rendered", pdf=str(file_path), png=image_path)
    except ValueError as e:
        render_error = str(e)
        log.warning(
            "review.pipeline.pdf_render_failed",
            pdf=str(file_path),
            error=render_error,
        )

    cad_model = CADIntermediateModel(
        source_file=str(file_path.resolve()),
        source_format="image",
        metadata={"source_type": "pdf"},
    )
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    metadata: dict[str, Any] = {
        "prepare_elapsed_ms": elapsed_ms,
        "source_type": "pdf",
        "render_error": render_error,
        "entity_count": 0,
        "dimension_count": 0,
        "layer_count": 0,
        "has_title_block": False,
    }
    return ReviewContext(
        source_file=str(file_path.resolve()),
        source_format="image",
        cad_model=cad_model,
        image_path=image_path,
        parse_metadata=metadata,
    )


def _build_dwg_context(file_path: Path) -> ReviewContext:
    """DWG 文件审图上下文：先转 DXF，再复用 DXF 解析与渲染管线。

    依赖 ODA File Converter（外部二进制）。不可用时抛 DependencyMissingError。
    临时 DXF 文件在 TemporaryDirectory 退出时自动清理；
    渲染产出的 PNG 持久化在 REVIEW_IMAGE_DIR 配置目录，供后续审图使用。
    """
    from app.services.cad import is_odafc_available, dwg_to_dxf
    from app.services.review.dependency_check import DependencyMissingError

    if not is_odafc_available():
        raise DependencyMissingError(
            dependency_name="ODA File Converter",
            install_hint="请从 https://www.opendesign.com/guestfiles/oda_file_converter 下载安装，"
            "并设置环境变量 ODAFC_PATH 指向 ODAFileConverter.exe 路径",
            file_type="dwg",
        )

    import tempfile

    t0 = time.perf_counter()

    with tempfile.TemporaryDirectory() as tmp_dir:
        # DWG → DXF（临时目录，退出 with 时清理）
        dxf_path = dwg_to_dxf(file_path, output_dir=Path(tmp_dir))

        # 复用 DXF 解析
        cad_model = parse_dxf_to_intermediate(dxf_path)
        # 覆写来源标注：原始文件是 DWG，而非解析器默认的 dxf
        cad_model.source_format = "dwg"
        cad_model.source_file = str(file_path.resolve())

        # 复用 DXF 渲染（PNG 输出到 REVIEW_IMAGE_DIR 配置目录，不在临时目录内）
        image_path: str | None = None
        render_error: str | None = None
        try:
            png = render_dxf_to_image(dxf_path)
            image_path = str(png)
        except Exception as e:
            render_error = str(e)
            log.warning("review.render.failed", dxf=str(dxf_path), error=render_error)

    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    metadata: dict[str, Any] = {
        "prepare_elapsed_ms": elapsed_ms,
        "render_error": render_error,
        "entity_count": len(cad_model.entities),
        "dimension_count": len(cad_model.dimensions),
        "layer_count": len(cad_model.layers),
        "has_title_block": cad_model.title_block is not None,
        "original_dwg_path": str(file_path.resolve()),
        "conversion_note": "DWG→DXF via ODA",
    }

    return ReviewContext(
        source_file=str(file_path.resolve()),
        source_format="dwg",
        cad_model=cad_model,
        image_path=image_path,
        parse_metadata=metadata,
    )


def _build_sldprt_context(file_path: Path) -> ReviewContext:
    """SLDPRT 文件审图上下文：多级降级提取 PNG 预览图。"""
    return _build_solidworks_context(file_path, "sldprt")


def _build_sldasm_context(file_path: Path) -> ReviewContext:
    """SLDASM 文件审图上下文：多级降级提取 PNG 预览图。"""
    return _build_solidworks_context(file_path, "sldasm")


def _build_solidworks_context(file_path: Path, source_format: str) -> ReviewContext:
    """SolidWorks 文件审图上下文：多级降级提取 PNG。

    降级链路因文件类型而异（关键差异：eDrawings OCX 加载 SLDASM 时崩溃，
    但加载 SLDPRT 正常且分辨率高于 Shell Thumbnail）：

    SLDPRT（OCX 不崩溃，L3a 分辨率 ~10KB 高于 L2 ~5KB）:
      L1 sw_docmgr → L3a edrawings_cli（优先，高分辨率）→ L2 shell_thumbnail → L3b solidworks_com

    SLDASM（eDrawings OCX 崩溃，跳过 L3a）:
      L1 sw_docmgr → L2 shell_thumbnail（优先）→ L3b solidworks_com

    L3b SolidWorks COM 暂未实现（reader 无 PNG 导出能力），留待扩展。
    全失败 → image_path=None（不阻断审图，VLM 降级）。

    Args:
        file_path: SLDPRT/SLDASM 文件路径
        source_format: "sldprt" 或 "sldasm"
    """
    from app.services.review.dependency_check import (
        is_edrawings_available,
        is_shell_thumbnail_available,
        is_solidworks_available,
        is_sw_docmgr_available,
    )

    t0 = time.perf_counter()
    image_path: str | None = None
    render_error: str | None = None
    renderer_used: str | None = None

    output_png = str(file_path.with_suffix(".png"))

    def _try_docmgr() -> str | None:
        from app.services.solidworks.docmgr_renderer import (
            render_sldprt_via_docmgr,
        )

        return render_sldprt_via_docmgr(file_path, output_png)

    def _try_edrawings() -> str | None:
        from app.services.solidworks.edrawings_cli import (
            render_sldprt_via_edrawings,
        )

        return render_sldprt_via_edrawings(file_path, output_png)

    def _try_shell() -> str | None:
        from app.services.solidworks.shell_thumbnail_renderer import (
            render_sldprt_via_shell,
        )

        return render_sldprt_via_shell(file_path, output_png)

    # 根据文件类型构建降级链路顺序
    # SLDPRT: OCX 不崩溃，L3a edrawings_cli 分辨率(~10KB)高于 L2 shell_thumbnail(~5KB)，优先 L3a
    # SLDASM: eDrawings OCX 加载 SLDASM 时崩溃，跳过 L3a，直接用 L2 shell_thumbnail
    if source_format == "sldasm":
        # SLDASM: L1 → L2 → L3b（跳过 L3a，OCX 崩溃）
        chain = [
            ("sw_docmgr", is_sw_docmgr_available, _try_docmgr),
            ("shell_thumbnail", is_shell_thumbnail_available, _try_shell),
            ("solidworks_com", is_solidworks_available, None),
        ]
    else:
        # SLDPRT: L1 → L3a → L2 → L3b（L3a 分辨率高于 L2）
        chain = [
            ("sw_docmgr", is_sw_docmgr_available, _try_docmgr),
            ("edrawings_cli", is_edrawings_available, _try_edrawings),
            ("shell_thumbnail", is_shell_thumbnail_available, _try_shell),
            ("solidworks_com", is_solidworks_available, None),
        ]

    for name, check_fn, render_fn in chain:
        if image_path is not None:
            break
        if not check_fn():
            continue
        if render_fn is None:
            # L3b solidworks_com：reader 无 PNG 导出能力，暂跳过
            log.debug(
                "review.pipeline.solidworks_com_skipped",
                file=str(file_path),
                reason="reader 无 PNG 导出能力",
            )
            continue
        try:
            result = render_fn()
            if result:
                image_path = result
                renderer_used = name
        except Exception as e:
            log.warning(
                "review.pipeline.render_failed",
                renderer=name,
                file=str(file_path),
                error=str(e),
            )

    # 全失败
    if image_path is None:
        render_error = "所有 SolidWorks 渲染方案均不可用"

    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    metadata: dict[str, Any] = {
        "prepare_elapsed_ms": elapsed_ms,
        "render_error": render_error,
        "renderer": renderer_used,
        "source_file": str(file_path.resolve()),
    }

    cad_model = CADIntermediateModel(
        source_file=str(file_path.resolve()),
        source_format=source_format,  # type: ignore[arg-type]
    )
    return ReviewContext(
        source_file=str(file_path.resolve()),
        source_format=source_format,  # type: ignore[arg-type]
        cad_model=cad_model,
        image_path=image_path,
        parse_metadata=metadata,
    )


def _build_step_context(file_path: Path) -> ReviewContext:
    """STEP 文件审图上下文：OCCT 加载 + 离屏渲染为 PNG。"""
    return _build_3d_context(file_path, "step")


def _build_iges_context(file_path: Path) -> ReviewContext:
    """IGES 文件审图上下文：OCCT 加载 + 离屏渲染为 PNG。"""
    return _build_3d_context(file_path, "iges")


def _build_3d_context(file_path: Path, source_format: str) -> ReviewContext:
    """3D CAD 文件（STEP/IGES）审图上下文：OCCT 加载 + 渲染为 PNG。

    渲染降级链路：OCCT 离屏 → trimesh+pyrender → image_path=None（不阻断审图）
    """
    from app.services.cad import read_iges_file, read_step_file

    t0 = time.perf_counter()

    # 加载 3D 模型（read_*_file 返回 dict，shape 在 "shape" 键）
    if source_format == "step":
        result = read_step_file(file_path)
    else:
        result = read_iges_file(file_path)
    shape = result["shape"]

    # 渲染为 PNG
    image_path: str | None = None
    render_error: str | None = None
    renderer_used: str | None = None

    output_png = str(file_path.with_suffix(".png"))

    # 尝试 OCCT 离屏渲染
    try:
        from app.services.cad.occ_engine import OCCTRenderError, render_to_png

        render_to_png(shape, output_png)
        image_path = output_png
        renderer_used = "occt_offscreen"
    except OCCTRenderError as e:
        log.warning(
            "review.pipeline.occt_render_failed",
            file=str(file_path),
            error=str(e),
        )
        # 降级到 trimesh+pyrender
        try:
            from app.services.review.step_renderer import render_via_trimesh

            render_via_trimesh(shape, output_png)
            image_path = output_png
            renderer_used = "trimesh_pyrender"
        except Exception as e2:
            render_error = str(e2)
            log.warning(
                "review.pipeline.trimesh_render_failed",
                file=str(file_path),
                error=str(e2),
            )
    except Exception as e:
        render_error = str(e)
        log.warning(
            "review.pipeline.render_failed", file=str(file_path), error=str(e)
        )

    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    metadata: dict[str, Any] = {
        "prepare_elapsed_ms": elapsed_ms,
        "render_error": render_error,
        "renderer": renderer_used,
        "source_file": str(file_path.resolve()),
    }

    cad_model = CADIntermediateModel(
        source_file=str(file_path.resolve()),
        source_format=source_format,  # type: ignore[arg-type]
    )
    return ReviewContext(
        source_file=str(file_path.resolve()),
        source_format=source_format,  # type: ignore[arg-type]
        cad_model=cad_model,
        image_path=image_path,
        parse_metadata=metadata,
    )


# ===== SubTask 4.3：三层语义融合 =====


def fuse_to_semantic_model(
    cad_model: CADIntermediateModel,
    vlm_result: dict[str, Any] | None = None,
) -> SemanticModel:
    """融合矢量数据与 VLM 视觉结果，输出"几何/拓扑/语义"三层结构化对象。

    Args:
        cad_model: Task 2 解析得到的 CAD 中间表示
        vlm_result: VLM OCR 结果（不可用时为 None 或空 dict）

    Returns:
        SemanticModel
    """
    vlm_result = vlm_result or {}

    # ===== 几何层 =====
    geometry = _build_geometry_layer(cad_model)

    # ===== 拓扑层 =====
    topology = _build_topology_layer(cad_model, geometry)

    # ===== 语义层 =====
    semantic = _build_semantic_layer(cad_model, vlm_result)

    stats = {
        "entity_total": len(cad_model.entities),
        "geometry_line_count": len(geometry.lines),
        "geometry_circle_count": len(geometry.circles),
        "geometry_arc_count": len(geometry.arcs),
        "geometry_polyline_count": len(geometry.polylines),
        "geometry_text_count": len(geometry.texts),
        "topology_shared_endpoint_count": len(topology.shared_endpoints),
        "topology_concentric_pair_count": len(topology.concentric_pairs),
        "semantic_dimension_count": semantic.dimension_count,
        "semantic_has_title_block": semantic.has_title_block,
        "semantic_has_tolerance": semantic.has_tolerance,
        "semantic_has_surface_roughness": semantic.has_surface_roughness,
        "vlm_available": bool(vlm_result),
    }

    return SemanticModel(
        geometry=geometry,
        topology=topology,
        semantic=semantic,
        source_file=cad_model.source_file,
        stats=stats,
    )


def _build_geometry_layer(cad_model: CADIntermediateModel) -> GeometryLayer:
    lines: list[dict[str, Any]] = []
    circles: list[dict[str, Any]] = []
    arcs: list[dict[str, Any]] = []
    polylines: list[dict[str, Any]] = []
    texts: list[dict[str, Any]] = []
    others: list[dict[str, Any]] = []

    for ent in cad_model.entities:
        etype = ent.type
        coords = ent.coordinates
        props = ent.properties

        if etype == "LINE" and len(coords) >= 2:
            lines.append(
                {
                    "start": list(coords[0]),
                    "end": list(coords[1]),
                    "length": props.get("length"),
                    "layer": ent.layer,
                }
            )
        elif etype == "CIRCLE" and len(coords) >= 1:
            circles.append(
                {
                    "center": list(coords[0]),
                    "radius": props.get("radius"),
                    "layer": ent.layer,
                }
            )
        elif etype == "ARC" and len(coords) >= 1:
            arcs.append(
                {
                    "center": list(coords[0]),
                    "radius": props.get("radius"),
                    "start_angle": props.get("start_angle"),
                    "end_angle": props.get("end_angle"),
                    "layer": ent.layer,
                }
            )
        elif etype in ("LWPOLYLINE", "POLYLINE") and coords:
            polylines.append(
                {
                    "vertices": [list(c) for c in coords],
                    "is_closed": props.get("is_closed", False),
                    "layer": ent.layer,
                }
            )
        elif etype in ("TEXT", "MTEXT"):
            pos = list(coords[0]) if coords else [0.0, 0.0, 0.0]
            texts.append(
                {
                    "position": pos,
                    "content": props.get("text", ""),
                    "height": props.get("height") or props.get("char_height"),
                    "layer": ent.layer,
                }
            )
        else:
            others.append(
                {
                    "type": etype,
                    "layer": ent.layer,
                    "coords_count": len(coords),
                }
            )

    return GeometryLayer(
        lines=lines,
        circles=circles,
        arcs=arcs,
        polylines=polylines,
        texts=texts,
        others=others,
    )


def _build_topology_layer(
    cad_model: CADIntermediateModel, geometry: GeometryLayer
) -> TopologyLayer:
    """推断拓扑关系：共享端点 + 同心圆。

    P0 阶段实现基本启发式：
    - 共享端点：两条 LINE 端点距离 < 1e-6 视为共享
    - 同心圆：两个 CIRCLE 圆心距离 < 1e-6 视为同心
    - 相切：P0 暂不检测（留待 P1 几何引擎）
    """
    shared: list[dict[str, Any]] = []
    lines = geometry.lines

    # 简化：仅检测前 200 条线对，避免 O(n^2) 爆炸
    sample = lines[:200]
    for i, a in enumerate(sample):
        for j in range(i + 1, len(sample)):
            b = sample[j]
            for pa in (a["start"], a["end"]):
                for pb in (b["start"], b["end"]):
                    if _points_equal(pa, pb):
                        shared.append(
                            {
                                "entity_a": i,
                                "entity_b": j,
                                "point": pa,
                            }
                        )

    concentric: list[dict[str, Any]] = []
    circles = geometry.circles[:100]
    for i, a in enumerate(circles):
        for j in range(i + 1, len(circles)):
            b = circles[j]
            if _points_equal(a["center"], b["center"]):
                concentric.append(
                    {
                        "circle_a": i,
                        "circle_b": j,
                        "center": a["center"],
                    }
                )

    return TopologyLayer(
        shared_endpoints=shared,
        tangencies=[],  # P0 不检测
        concentric_pairs=concentric,
    )


def _build_semantic_layer(
    cad_model: CADIntermediateModel, vlm_result: dict[str, Any]
) -> SemanticLayer:
    """构建语义层：标注类型/标题栏字段/形位公差/表面粗糙度。"""
    dim_types: dict[str, int] = {}
    for d in cad_model.dimensions:
        dim_types[d.type] = dim_types.get(d.type, 0) + 1

    tb = cad_model.title_block
    has_tb = tb is not None
    tb_fields: dict[str, str | None] = {}
    if tb is not None:
        tb_fields = {
            "drawing_number": tb.drawing_number,
            "title": tb.title,
            "scale": tb.scale,
            "material": tb.material,
            "drawn_by": tb.drawn_by,
            "checked_by": tb.checked_by,
            "date": tb.date,
            "version": tb.version,
            "project": tb.project,
        }

    # 形位公差：检测 TOLERANCE 实体或含形位公差符号的 MTEXT
    has_tol = any(e.type == "TOLERANCE" for e in cad_model.entities)
    if not has_tol:
        # 兜底：在 MTEXT 中搜索形位公差符号特征（Ø ⌖ ⊥ ∥ 等）
        tol_chars = ("⌖", "⊥", "∥", "∠", "◎")
        for e in cad_model.entities:
            if e.type in ("TEXT", "MTEXT"):
                txt = e.properties.get("text", "") or ""
                if any(c in txt for c in tol_chars):
                    has_tol = True
                    break

    # 表面粗糙度：检测 Ra/Rz 标记或表面粗糙度符号 (∇ / Ra / Rz)
    has_sr = False
    sr_chars = ("Ra", "Rz", "∇", "Ry")
    for e in cad_model.entities:
        if e.type in ("TEXT", "MTEXT"):
            txt = e.properties.get("text", "") or ""
            if any(c in txt for c in sr_chars):
                has_sr = True
                break

    layer_names = [l.name for l in cad_model.layers]

    # VLM OCR 补充（若可用）
    vlm_extras: dict[str, Any] = {}
    if vlm_result:
        vlm_extras = {
            k: v for k, v in vlm_result.items() if k != "regions"
        }

    return SemanticLayer(
        dimension_count=len(cad_model.dimensions),
        dimension_types=dim_types,
        has_title_block=has_tb,
        title_block_fields=tb_fields,
        has_tolerance=has_tol,
        has_surface_roughness=has_sr,
        layer_names=layer_names,
        vlm_ocr_extras=vlm_extras,
    )


def _points_equal(a: list[float] | tuple[float, ...], b: list[float] | tuple[float, ...], tol: float = 1e-6) -> bool:
    """判断两个 2D/3D 点是否在容差内相等。"""
    if len(a) < 2 or len(b) < 2:
        return False
    return abs(a[0] - b[0]) < tol and abs(a[1] - b[1]) < tol
