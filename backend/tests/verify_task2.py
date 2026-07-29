"""Task 2 综合验证脚本：一次性产出 5 项验证证据。

运行：
    python tests/verify_task2.py
"""

from __future__ import annotations

import json
from pathlib import Path

from app.schemas.cad_intermediate import CADIntermediateModel
from app.services.cad import (
    is_freecad_available,
    is_occ_available,
    is_odafc_available,
    parse_dxf_to_intermediate,
)

FIXTURE = Path(__file__).parent / "fixtures" / "sample.dxf"


def section(title: str) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'-' * 70}")


def main() -> None:
    # ===== 验证 2：DXF 解析 + JSON 片段 =====
    section("验证 2：DXF 解析为统一中间表示")
    model = parse_dxf_to_intermediate(FIXTURE)
    print(f"source_file      : {model.source_file}")
    print(f"source_format    : {model.source_format}")
    print(f"units            : {model.units}")
    print(f"layers count     : {len(model.layers)}")
    print(f"entities count   : {len(model.entities)}")
    print(f"dimensions count : {len(model.dimensions)}")
    print(f"blocks count     : {len(model.blocks)}")
    print(f"layouts count    : {len(model.layouts)}")
    print(f"title_block      : {model.title_block}")
    print(f"metadata         : {json.dumps(model.metadata, ensure_ascii=False)}")

    print("\n-- layers (前 6 个) --")
    for layer in model.layers[:6]:
        print(f"  {layer.model_dump_json()}")

    print("\n-- entities (前 5 个，简化展示 type/layer/properties) --")
    for ent in model.entities[:5]:
        print(
            f"  type={ent.type:10s} layer={ent.layer!s:10s} "
            f"coords_n={len(ent.coordinates)} props={ent.properties}"
        )

    print("\n-- dimensions (全部) --")
    for dim in model.dimensions:
        print(f"  {dim.model_dump_json()}")

    print("\n-- title_block JSON --")
    print(f"  {model.title_block.model_dump_json(indent=2) if model.title_block else 'None'}")

    # ===== 验证 3：ODA 可用性 =====
    section("验证 3：ODA File Converter 可用性检测")
    oda_ok = is_odafc_available()
    print(f"is_odafc_available() = {oda_ok}")
    print("(若返回 False，上方应已打印安装指引 URL)")

    # ===== 验证 4：OCC 可用性 =====
    section("验证 4：OCC (OCP / pythonocc-core) 可用性检测")
    occ_ok = is_occ_available()
    print(f"is_occ_available() = {occ_ok}")
    if occ_ok:
        # 进一步验证 STEP 读取 API 可调用（不实际读文件）
        from app.services.cad.occ_engine import _OCP_BACKEND
        print(f"OCC backend = {_OCP_BACKEND}")
        print("STEPControl_Reader / BRepBndLib / BRepGProp / BRepAlgoAPI 已成功导入")
    else:
        print("OCC 不可用（本机未安装 OCP / pythonocc-core）")

    # ===== 验证 5：FreeCAD 可用性 =====
    section("验证 5：FreeCAD 可用性检测")
    fc_ok = is_freecad_available()
    print(f"is_freecad_available() = {fc_ok}")
    print("(预期 False：测试环境未将 FreeCAD 配置为 Python 模块)")

    # ===== 验证 6：Schema 序列化往返 =====
    section("验证 6：CADIntermediateModel JSON 序列化/反序列化")
    json_str = model.model_dump_json()
    print(f"序列化 JSON 长度: {len(json_str)} 字符")
    restored = CADIntermediateModel.model_validate_json(json_str)
    print(f"反序列化 source_file   : {restored.source_file}")
    print(f"反序列化 source_format : {restored.source_format}")
    print(f"反序列化 entities 数   : {len(restored.entities)}")
    print(f"反序列化 layers 数     : {len(restored.layers)}")
    print(f"反序列化 title_block   : {restored.title_block is not None}")
    print(f"类型校验通过：{restored.source_format == 'dxf' and len(restored.entities) == len(model.entities)}")

    # 抽样打印反序列化后第一条 entity
    if restored.entities:
        e0 = restored.entities[0]
        print(f"\n反序列化后首条 entity: {e0.model_dump_json()}")

    print("\n所有验证完成。")


if __name__ == "__main__":
    main()
