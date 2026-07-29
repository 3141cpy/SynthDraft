"""DXF 解析为统一中间表示（SubTask 2.1）。

依赖：ezdxf 1.4.x（PyPI 包名 ezdxf）。
官方文档：https://ezdxf.readthedocs.io/en/stable/

输入：DXF 文件路径
输出：CADIntermediateModel（与 DWG/STEP/IGES 解析结果同 schema）

提取内容：
- 图层（layers）
- 实体（entities，按类型分类：LINE/CIRCLE/ARC/LWPOLYLINE/TEXT/MTEXT/DIMENSION/INSERT/BLOCK 等）
- 标注（dimensions）
- 标题栏（title_block，从带属性的 INSERT 块提取）
- 视图区（layouts，按布局 space 分类）
- 块定义（blocks）

异常：文件不存在 / 非 DXF / 解析失败 → CADParseError
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import ezdxf
from ezdxf import units as ezdxf_units
from ezdxf.document import Drawing
from ezdxf.entities import DXFGraphic
from ezdxf.layouts import Modelspace
from ezdxf.lldxf.const import DXFStructureError

from app.schemas.cad_intermediate import (
    CADBlock,
    CADDimension,
    CADEntity,
    CADIntermediateModel,
    CADLayer,
    CADTitleBlock,
    CADViewLayout,
)
from app.services.cad.cache import cached_parse

__all__ = ["CADParseError", "parse_dxf_to_intermediate"]


class CADParseError(Exception):
    """CAD 文件解析失败。"""


# ===== 标题栏属性标签别名映射 =====
# 不同图纸模板字段命名差异较大，此处列举常见别名（不区分大小写）。
_TITLE_BLOCK_ATTR_MAP: dict[str, set[str]] = {
    "drawing_number": {
        "DRAWINGNO", "DRAWING_NO", "DRAWINGNUMBER", "DWGNO", "DWG_NO",
        "图号", "图号编号", "DRAWING#",
    },
    "title": {"TITLE", "图名", "图纸名称", "DRAWING_TITLE", "名称"},
    "scale": {"SCALE", "比例", "SCL", "RATIO"},
    "material": {"MATERIAL", "MAT", "材料", "材料牌号", "MATL"},
    "drawn_by": {"DRAWNBY", "DRAWN_BY", "DRAWN", "DRAWN-BY", "制图", "绘制", "DWNBY"},
    "checked_by": {"CHECKEDBY", "CHECKED_BY", "CHECKED", "校对", "审核", "CHKDBY"},
    "date": {"DATE", "日期", "DRAWNDATE"},
    "version": {"VERSION", "VER", "REV", "版本", "REVISION"},
    "project": {"PROJECT", "项目", "PROJECT_NAME", "PROJECTNAME"},
}

# DIMENSION dimtype 低 5 位类型编码（ezdxf 约定，参考 ezdxf 源码 dxfentities/dimension.py）
_DIM_TYPE_MAP: dict[int, str] = {
    0: "linear",
    1: "aligned",
    2: "angular",
    3: "diameter",
    4: "radius",
    5: "angular",  # angular 3p
    6: "ordinate",
}


@cached_parse("dxf")
def parse_dxf_to_intermediate(dxf_path: Path) -> CADIntermediateModel:
    """读取 DXF 文件，解析为 CADIntermediateModel。

    SubTask 17.2: 添加 ``@cached_parse("dxf")`` 装饰器，
    同一文件 hash 第二次解析直接返回缓存结果（Redis 后端）。
    CAD_CACHE_ENABLED=False 或 Redis 不可用时透明降级为直接解析。

    Args:
        dxf_path: DXF 文件路径

    Raises:
        CADParseError: 文件不存在 / 后缀非 .dxf / ezdxf 解析失败
    """
    path = Path(dxf_path)
    if not path.is_file():
        raise CADParseError(f"DXF 文件不存在: {path}")
    if path.suffix.lower() != ".dxf":
        raise CADParseError(f"非 DXF 文件（后缀 {path.suffix}）: {path}")

    t0 = time.perf_counter()
    try:
        # ezdxf.readfile 对二进制 DXF / ASCII DXF 均可自动识别；
        # 若文件已损坏，使用 recover 模式尽力恢复
        try:
            doc = ezdxf.readfile(str(path))
        except DXFStructureError:
            from ezdxf import recover
            doc, _auditor = recover.readfile(str(path))
    except DXFStructureError as exc:
        raise CADParseError(f"DXF 结构错误，无法解析: {path} ({exc})") from exc
    except Exception as exc:
        # 兜底：ezdxf 抛出的其他异常（IOError 等）转换为业务异常
        raise CADParseError(f"DXF 解析失败: {path} ({type(exc).__name__}: {exc})") from exc

    elapsed_ms = int((time.perf_counter() - t0) * 1000)

    layers = _extract_layers(doc)
    dimensions = _extract_dimensions(doc.modelspace())
    blocks = _extract_blocks(doc)
    layouts = _extract_layouts(doc)
    title_block = _extract_title_block(doc.modelspace(), blocks)

    # 统计每图层实体数（仅基于 model space 实体；layout 实体已分别计入 layouts）
    layer_entity_counts: dict[str, int] = {}
    msp_entities = _extract_entities_from_space(doc.modelspace())
    for ent in msp_entities:
        if ent.layer:
            layer_entity_counts[ent.layer] = layer_entity_counts.get(ent.layer, 0) + 1
    for layer in layers:
        layer.entities_count = layer_entity_counts.get(layer.name, 0)

    units_str: str | None = None
    try:
        insunits = doc.header.get("$INSUNITS", None)
        if insunits is not None:
            units_str = ezdxf_units.unit_name(int(insunits))
    except Exception:  # noqa: BLE001
        units_str = None

    metadata: dict[str, Any] = {
        "parser": "ezdxf",
        "ezdxf_version": ezdxf.__version__,
        "dxfversion": doc.dxfversion,
        "acad_release": getattr(doc, "acad_release", None),
        "parse_elapsed_ms": elapsed_ms,
        "entity_count_model_space": len(msp_entities),
        "layer_count": len(layers),
        "dimension_count": len(dimensions),
        "block_count": len(blocks),
        "layout_count": len(layouts),
    }

    return CADIntermediateModel(
        source_file=str(path),
        source_format="dxf",
        units=units_str,
        layers=layers,
        entities=msp_entities,
        dimensions=dimensions,
        title_block=title_block,
        blocks=blocks,
        layouts=layouts,
        metadata=metadata,
    )


# ===== 内部提取函数 =====


def _extract_layers(doc: Drawing) -> list[CADLayer]:
    layers: list[CADLayer] = []
    for layer in doc.layers:
        # layer.is_off() / is_frozen() 综合判定可见性
        is_visible = True
        try:
            is_visible = not (layer.is_off() or layer.is_frozen())
        except Exception:  # noqa: BLE001
            is_visible = True
        color = None
        try:
            color = int(layer.dxf.color)
        except Exception:  # noqa: BLE001
            color = None
        layers.append(
            CADLayer(
                name=layer.dxf.name,
                color=color,
                is_visible=is_visible,
                entities_count=0,  # 后填
            )
        )
    return layers


def _extract_entities_from_space(space: Modelspace) -> list[CADEntity]:
    """从给定 space 提取实体列表（model 或 paper）。"""
    entities: list[CADEntity] = []
    for ent in space:
        conv = _convert_entity(ent)
        if conv is not None:
            entities.append(conv)
    return entities


def _convert_entity(ent: DXFGraphic) -> CADEntity | None:
    """将 ezdxf 实体转为 CADEntity；未知类型返回 None（保留 raw_dxf_attribs 兜底）。

    对于 DIMENSION 实体，这里也产出一条 CADEntity（type=DIMENSION），
    完整语义信息在 dimensions 列表中。
    """
    etype = ent.dxftype()
    layer = None
    try:
        layer = ent.dxf.layer
    except Exception:  # noqa: BLE001
        layer = None

    coords: list[tuple[float, float, float]] = []
    props: dict[str, Any] = {}

    try:
        if etype == "LINE":
            s = ent.dxf.start
            e = ent.dxf.end
            coords = [(s.x, s.y, s.z), (e.x, e.y, e.z)]
            props["length"] = float((e - s).magnitude)
        elif etype == "CIRCLE":
            c = ent.dxf.center
            coords = [(c.x, c.y, c.z)]
            props["radius"] = float(ent.dxf.radius)
            props["thickness"] = float(getattr(ent.dxf, "thickness", 0.0) or 0.0)
        elif etype == "ARC":
            c = ent.dxf.center
            coords = [(c.x, c.y, c.z)]
            props["radius"] = float(ent.dxf.radius)
            props["start_angle"] = float(ent.dxf.start_angle)
            props["end_angle"] = float(ent.dxf.end_angle)
        elif etype in ("LWPOLYLINE", "POLYLINE"):
            if etype == "LWPOLYLINE":
                # lwpolyline.get_points() -> 返回 (x, y, _, bulge, _, _) 元组序列
                pts = ent.get_points()
                coords = [(float(p[0]), float(p[1]), 0.0) for p in pts]
                props["is_closed"] = bool(ent.closed)
                props["elevation"] = float(getattr(ent.dxf, "elevation", 0.0) or 0.0)
            else:
                # 3D POLYLINE
                coords = [(float(v.dxf.location.x), float(v.dxf.location.y),
                          float(v.dxf.location.z)) for v in ent.vertices]
                props["is_closed"] = bool(ent.is_closed)
        elif etype in ("TEXT", "MTEXT"):
            try:
                ins = ent.dxf.insert
                coords = [(float(ins.x), float(ins.y), float(ins.z))]
            except Exception:  # noqa: BLE001
                coords = []
            if etype == "TEXT":
                props["text"] = str(ent.dxf.text)
                props["height"] = float(ent.dxf.height)
            else:
                # MTEXT：优先用 .text（已解析的纯文本），回退 .raw_text / .text
                txt = getattr(ent, "text", None) or getattr(ent, "raw_text", "")
                props["text"] = str(txt)
                try:
                    props["char_height"] = float(ent.dxf.char_height)
                except Exception:  # noqa: BLE001
                    props["char_height"] = None
        elif etype == "INSERT":
            ins = ent.dxf.insert
            coords = [(float(ins.x), float(ins.y), float(ins.z))]
            props["block_name"] = str(ent.dxf.name)
            try:
                sx = float(ent.dxf.xscale); sy = float(ent.dxf.yscale); sz = float(ent.dxf.zscale)
                props["scale"] = (sx, sy, sz)
            except Exception:  # noqa: BLE001
                pass
            try:
                props["rotation"] = float(ent.dxf.rotation)
            except Exception:  # noqa: BLE001
                pass
            # 提取属性值（ATTDEF/ATTRIB）
            attribs: dict[str, str] = {}
            try:
                for attrib in ent.attribs:
                    attribs[str(attrib.dxf.tag)] = str(attrib.dxf.text)
            except Exception:  # noqa: BLE001
                pass
            if attribs:
                props["attributes"] = attribs
        elif etype == "POINT":
            p = ent.dxf.location
            coords = [(float(p.x), float(p.y), float(p.z))]
        elif etype == "SPLINE":
            try:
                cps = ent.control_points
                coords = [(float(p[0]), float(p[1]), float(p[2]) if len(p) > 2 else 0.0)
                          for p in cps]
                props["degree"] = int(ent.dxf.degree)
                props["is_closed"] = bool(getattr(ent, "closed", False))
            except Exception:  # noqa: BLE001
                pass
        elif etype == "ELLIPSE":
            c = ent.dxf.center
            coords = [(float(c.x), float(c.y), float(c.z))]
            props["major_axis"] = tuple(float(v) for v in ent.dxf.major_axis)
            props["ratio"] = float(ent.dxf.ratio)
            props["start_param"] = float(ent.dxf.start_param)
            props["end_param"] = float(ent.dxf.end_param)
        elif etype == "HATCH":
            try:
                paths_count = len(ent.paths) if hasattr(ent, "paths") else 0
                props["paths_count"] = int(paths_count)
                props["pattern_name"] = str(getattr(ent.dxf, "pattern_name", "") or "")
            except Exception:  # noqa: BLE001
                pass
        elif etype in ("LEADER", "MULTILEADER", "TOLERANCE"):
            # 后续 Task 4 处理；此处仅记录类型
            pass
        else:
            # 未识别类型：留空 coords/props，raw_dxf_attribs 兜底
            pass
    except Exception:  # noqa: BLE001
        # 单个实体解析失败不应导致整张图失败
        pass

    # raw_dxf_attribs：仅对未明确转换的字段保留，避免数据冗余
    raw_attribs: dict[str, Any] | None = None
    try:
        # 取若干常见属性作为兜底
        keys = ("color", "linetype", "lineweight", "thickness", "handle")
        dumped: dict[str, Any] = {}
        for k in keys:
            v = getattr(ent.dxf, k, None)
            if v is not None:
                dumped[k] = v if not hasattr(v, "clone") else str(v)
        if dumped:
            raw_attribs = dumped
    except Exception:  # noqa: BLE001
        raw_attribs = None

    return CADEntity(
        type=etype,
        layer=layer,
        coordinates=coords,
        properties=props,
        raw_dxf_attribs=raw_attribs,
    )


def _extract_dimensions(msp: Modelspace) -> list[CADDimension]:
    dims: list[CADDimension] = []
    for ent in msp.query("DIMENSION"):
        try:
            raw_dimtype = int(ent.dxf.dimtype)
        except Exception:  # noqa: BLE001
            raw_dimtype = 0
        dim_class = raw_dimtype & 0b11111  # 低 5 位为类型
        dim_type_str = _DIM_TYPE_MAP.get(dim_class, "unknown")

        layer = None
        try:
            layer = ent.dxf.layer
        except Exception:  # noqa: BLE001
            layer = None

        defpoints: list[tuple[float, float, float]] = []
        for attr in ("defpoint", "defpoint2", "defpoint3", "defpoint4", "defpoint5"):
            p = getattr(ent.dxf, attr, None)
            if p is not None:
                defpoints.append((float(p.x), float(p.y), float(p.z)))
        # text_midpoint
        tmp = getattr(ent.dxf, "text_midpoint", None)
        if tmp is not None:
            defpoints.append((float(tmp.x), float(tmp.y), float(tmp.z)))

        text = None
        try:
            text = str(ent.dxf.text)
        except Exception:  # noqa: BLE001
            text = None

        measurement: float | None = None
        try:
            measurement = float(ent.dxf.actual_measurement)
        except Exception:  # noqa: BLE001
            try:
                measurement = float(ent.get_measurement())
            except Exception:  # noqa: BLE001
                measurement = None

        dims.append(
            CADDimension(
                type=dim_type_str,  # type: ignore[arg-type]
                layer=layer,
                definition_points=defpoints,
                measurement=measurement,
                text=text,
            )
        )
    return dims


def _extract_blocks(doc: Drawing) -> list[CADBlock]:
    blocks: list[CADBlock] = []
    for blk in doc.blocks:
        # 跳过匿名/布局块（*Model_Space, *Paper_Space 等）
        name = blk.name
        if name.startswith("*"):
            # 但布局块需要标记为 is_layout
            is_layout = name in ("*Model_Space", "*Paper_Space") or name.startswith("*Paper_Space")
            if not is_layout:
                continue
        try:
            bp = blk.dxf.base_point
            base = (float(bp.x), float(bp.y), float(bp.z))
        except Exception:  # noqa: BLE001
            base = (0.0, 0.0, 0.0)
        ents: list[CADEntity] = []
        for sub in blk:
            conv = _convert_entity(sub)
            if conv is not None:
                ents.append(conv)
        is_layout = name.startswith("*Paper_Space") or name == "*Model_Space"
        blocks.append(
            CADBlock(
                name=name,
                base_point=base,
                entities=ents,
                is_layout=is_layout,
            )
        )
    return blocks


def _extract_layouts(doc: Drawing) -> list[CADViewLayout]:
    layouts: list[CADViewLayout] = []
    for layout in doc.layouts:
        name = layout.name
        # ezdxf layout.is_modelspace 判定
        is_model = bool(getattr(layout, "is_modelspace", False))
        try:
            ents: list[CADEntity] = []
            for ent in layout:
                conv = _convert_entity(ent)
                if conv is not None:
                    ents.append(conv)
        except Exception:  # noqa: BLE001
            ents = []
        layouts.append(
            CADViewLayout(
                space="model" if is_model else "paper",
                name=name,
                entities=ents,
            )
        )
    return layouts


def _extract_title_block(
    msp: Modelspace, blocks: list[CADBlock]
) -> CADTitleBlock | None:
    """从带属性的 INSERT 提取标题栏。

    启发式：扫描所有 INSERT 实体的属性键，若其 tag 命中 _TITLE_BLOCK_ATTR_MAP
    任一别名，则认为该 INSERT 是标题栏实例，按字段聚合。
    若同一字段在多个 INSERT 中出现，取首个非空值。
    """
    found: dict[str, str] = {}
    extras: dict[str, str] = {}

    for ent in msp.query("INSERT"):
        try:
            attribs = {str(a.dxf.tag): str(a.dxf.text) for a in ent.attribs}
        except Exception:  # noqa: BLE001
            continue
        if not attribs:
            continue

        # 块名包含 TITLE 也作为强信号
        block_name = ""
        try:
            block_name = str(ent.dxf.name).upper()
        except Exception:  # noqa: BLE001
            pass

        is_title_block = "TITLE" in block_name or any(
            _match_title_field(tag) is not None for tag in attribs
        )
        if not is_title_block:
            continue

        for tag, val in attribs.items():
            field = _match_title_field(tag)
            if field is None:
                # 未识别的属性放入 extras（仅非空）
                if val and val not in extras:
                    extras[tag] = val
                continue
            if val and field not in found:
                found[field] = val

    if not found and not extras:
        return None

    return CADTitleBlock(**found, extras=extras)


def _match_title_field(tag: str) -> str | None:
    """将属性 tag 匹配到 _TITLE_BLOCK_ATTR_MAP 中的字段名。"""
    upper = tag.upper().strip()
    for field, aliases in _TITLE_BLOCK_ATTR_MAP.items():
        if upper in aliases:
            return field
    return None
