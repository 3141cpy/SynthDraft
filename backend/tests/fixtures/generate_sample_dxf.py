"""生成测试用最小 DXF fixture（SubTask 2.1 验证）。

包含：
- 1 个 LINE
- 1 个 CIRCLE
- 1 个 TEXT
- 1 个 LINEAR DIMENSION
- 1 个带属性的块定义 TITLE_BLOCK + 1 个 INSERT 实例（标题栏）
- 多个图层

运行：
    python tests/fixtures/generate_sample_dxf.py
生成：tests/fixtures/sample.dxf
"""

from __future__ import annotations

from pathlib import Path

import ezdxf
from ezdxf import colors
from ezdxf.enums import TextEntityAlignment


def generate(out_path: Path | None = None) -> Path:
    """生成最小测试 DXF，返回生成路径。"""
    # setup=True：自动加载标准样式（dimstyle EZDXF 等），DIMENSION 渲染需要
    doc = ezdxf.new(dxfversion="R2010", setup=True)

    # ===== 图层 =====
    doc.layers.add("OUTLINE", color=colors.WHITE)
    doc.layers.add("DIM", color=colors.RED)
    doc.layers.add("TEXT", color=colors.GREEN)
    doc.layers.add("TITLE", color=colors.CYAN)

    # 设置 $INSUNITS=4（mm）
    doc.header["$INSUNITS"] = 4

    msp = doc.modelspace()

    # ===== 实体 1：LINE（在 OUTLINE 层） =====
    msp.add_line((0, 0), (50, 0), dxfattribs={"layer": "OUTLINE"})

    # ===== 实体 2：CIRCLE（在 OUTLINE 层） =====
    msp.add_circle((25, 10), radius=5, dxfattribs={"layer": "OUTLINE"})

    # ===== 实体 3：TEXT（在 TEXT 层） =====
    msp.add_text(
        "SynthDraft Sample",
        height=2.5,
        dxfattribs={"layer": "TEXT", "color": colors.GREEN},
    ).set_placement((0, 20), align=TextEntityAlignment.LEFT)

    # ===== 实体 4：LINEAR DIMENSION（DIM 层） =====
    # 标注 0..50 的线段长度
    dim = msp.add_linear_dim(
        base=(0, 5),     # 尺寸线位置
        p1=(0, 0),       # 第一延伸线原点
        p2=(50, 0),      # 第二延伸线原点
        angle=0,
        dimstyle="EZ_TX",  # ezdxf setup=True 提供的样式
        override={"dimtxsty": "OpenSans-Bold"},
        dxfattribs={"layer": "DIM"},
    )
    dim.render()

    # ===== 实体 5：标题栏块定义 + INSERT 实例 =====
    title_block = doc.blocks.new("TITLE_BLOCK")
    # 标题栏边框
    title_block.add_lwpolyline(
        [(0, 0), (40, 0), (40, 10), (0, 10), (0, 0)],
        dxfattribs={"layer": "TITLE"},
    )
    title_block.add_line((20, 0), (20, 10), dxfattribs={"layer": "TITLE"})
    title_block.add_line((0, 5), (40, 5), dxfattribs={"layer": "TITLE"})

    # 属性定义 ATTDEF
    title_block.add_attdef(
        tag="DRAWINGNO", insert=(1, 8), text="DWG-000", height=1.0,
        dxfattribs={"layer": "TITLE"},
    )
    title_block.add_attdef(
        tag="TITLE", insert=(21, 8), text="UNTITLED", height=1.0,
        dxfattribs={"layer": "TITLE"},
    )
    title_block.add_attdef(
        tag="SCALE", insert=(1, 3), text="1:1", height=1.0,
        dxfattribs={"layer": "TITLE"},
    )
    title_block.add_attdef(
        tag="MATERIAL", insert=(21, 3), text="N/A", height=1.0,
        dxfattribs={"layer": "TITLE"},
    )
    title_block.add_attdef(
        tag="DRAWNBY", insert=(1, 1), text="-", height=1.0,
        dxfattribs={"layer": "TITLE"},
    )
    title_block.add_attdef(
        tag="CHECKEDBY", insert=(21, 1), text="-", height=1.0,
        dxfattribs={"layer": "TITLE"},
    )

    # 插入块引用并填充属性
    block_ref = msp.add_blockref(
        "TITLE_BLOCK",
        insert=(10, -20),
        dxfattribs={"layer": "TITLE"},
    )
    block_ref.add_auto_attribs({
        "DRAWINGNO": "SD-2026-001",
        "TITLE": "Test Bracket",
        "SCALE": "1:2",
        "MATERIAL": "Q235",
        "DRAWNBY": "alice",
        "CHECKEDBY": "bob",
    })

    if out_path is None:
        out_path = Path(__file__).parent / "sample.dxf"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(str(out_path))
    return out_path


if __name__ == "__main__":
    p = generate()
    print(f"sample.dxf generated: {p}")
