"""诊断 SolidWorks FeatureExtrusion2 正确参数数目的脚本。"""
import sys
sys.path.insert(0, r"d:\SynthDraft\backend")

from pathlib import Path
from app.services.solidworks.sw_session import SolidWorksSession, SW_DOC_PART
from win32com.client import VARIANT
import pythoncom

session = SolidWorksSession()
session.start(visible=False)
print(f"SolidWorks 版本: {session.revision}")

# 创建新零件
doc = session.new_document(doc_type=SW_DOC_PART)
print(f"新零件文档: type={type(doc).__name__}")

ext = doc.Extension
sm = doc.SketchManager
fm = doc.FeatureManager

# ===== 步骤 1：用正确方式选择前视基准面 =====
print("\n--- 步骤 1：选择前视基准面 ---")
nothing = VARIANT(pythoncom.VT_DISPATCH, None)
try:
    sel = ext.SelectByID2("前视基准面", "PLANE", 0.0, 0.0, 0.0, False, 0, nothing, 0)
    print(f"SelectByID2(前视基准面): {sel}")
except Exception as e:
    print(f"SelectByID2 失败: {e}")

# ===== 步骤 2：进入草图并创建矩形 =====
print("\n--- 步骤 2：创建草图 ---")
try:
    sm.InsertSketch(True)
    print("InsertSketch(True) 进入草图模式")
    sm.CreateCenterRectangle(0.0, 0.0, 0.0, 0.01, 0.01, 0.0)
    print("CreateCenterRectangle(20x20mm) 成功")
    sm.InsertSketch(True)
    print("InsertSketch(True) 退出草图")
except Exception as e:
    print(f"草图创建失败: {e}")

# ===== 步骤 3：测试 FeatureExtrusion2 不同参数数目 =====
print("\n--- 步骤 3：FeatureExtrusion2 参数数目测试 ---")

# SolidWorks API Help 2025 中 FeatureExtrusion2 的官方签名为 21 参数：
# FeatureExtrusion2(Sd, Flip, Dir2, T1, T2, ExtDim, ExtDim2,
#                   Dchkpt1, Dchkpt2, Ddir1, Ddir2, DAng1, DAng2,
#                   Merge, UseFeatScope, UseAutoSelect,
#                   StartThickness, EndThickness, MidPlaneThickness,
#                   FlipStartOffset, StartOffset) As Feature

# 但 SolidWorks 2025 (33.x) 可能是 24 参数版本（增加 CapEnd 相关）

param_sets = [
    ("16参数", [
        True, False, False,     # Sd, Flip, Dir2
        0, 0,                   # T1, T2
        0.01, 0.0,              # ExtDim, ExtDim2
        False, False,           # Dchkpt1, Dchkpt2
        False, False,           # Ddir1, Ddir2
        0.0, 0.0,               # DAng1, DAng2
        True,                   # Merge
        False,                  # UseFeatScope
        True,                   # UseAutoSelect
    ]),
    ("21参数", [
        True, False, False,     # Sd, Flip, Dir2
        0, 0,                   # T1, T2
        0.01, 0.0,              # ExtDim, ExtDim2
        False, False,           # Dchkpt1, Dchkpt2
        False, False,           # Ddir1, Ddir2
        0.0, 0.0,               # DAng1, DAng2
        True,                   # Merge
        False,                  # UseFeatScope
        True,                   # UseAutoSelect
        0.0, 0.0, 0.0,          # StartThickness, EndThickness, MidPlaneThickness
        False,                  # FlipStartOffset
        0.0,                    # StartOffset
    ]),
    ("22参数(+Merge2)", [
        True, False, False,
        0, 0,
        0.01, 0.0,
        False, False, False, False, 0.0, 0.0,
        True, False, True,
        0.0, 0.0, 0.0,
        False,                  # Merge2
        False, 0.0,             # FlipStartOffset, StartOffset
    ]),
    ("24参数(+CapEnd)", [
        True, False, False,
        0, 0,
        0.01, 0.0,
        False, False, False, False, 0.0, 0.0,
        True, False, True,
        0.0, 0.0, 0.0,
        False,                  # Merge2
        False, 0.0,             # FlipStartOffset, StartOffset
        False, "",              # CapEndSurface, CapEndSurfaceName
    ]),
    ("20参数(无startOffset)", [
        True, False, False,
        0, 0,
        0.01, 0.0,
        False, False, False, False, 0.0, 0.0,
        True, False, True,
        0.0, 0.0, 0.0,
        False,                  # FlipStartOffset
    ]),
]

for name, params in param_sets:
    try:
        feat = fm.FeatureExtrusion2(*params)
        print(f"  {name}({len(params)}): 成功! feat={feat}")
        # 如果成功，跳出循环
        if feat is not None:
            break
    except Exception as e:
        print(f"  {name}({len(params)}): 失败 - {e}")

# ===== 步骤 4：检查 FeatureExtrusion3 是否存在并可用 =====
print("\n--- 步骤 4：检查 FeatureExtrusion3 ---")
if hasattr(fm, 'FeatureExtrusion3'):
    try:
        feat = fm.FeatureExtrusion3(
            True, False, False,     # Sd, Flip, Dir2
            0, 0,                   # T1, T2
            0.01, 0.0,              # ExtDim, ExtDim2
            False, False,           # Dchkpt1, Dchkpt2
            False, False,           # Ddir1, Ddir2
            0.0, 0.0,               # DAng1, DAng2
            True,                   # Merge
            False,                  # UseFeatScope
            True,                   # UseAutoSelect
            0.0, 0.0, 0.0,          # StartThickness, EndThickness, MidPlaneThickness
            False,                  # Merge2
            False, 0.0,             # FlipStartOffset, StartOffset
            False,                  # FlipEndOffset
            0.0,                    # EndOffset
        )
        print(f"  FeatureExtrusion3(23): 成功! feat={feat}")
    except Exception as e:
        print(f"  FeatureExtrusion3(23): 失败 - {e}")
else:
    print("  FeatureExtrusion3 不存在")

# ===== 步骤 5：检查是否使用 FeatureBossThin =====
print("\n--- 步骤 5：检查 FeatureBossThin 等其他拉伸方法 ---")
for m in ['FeatureBossThin', 'FeatureBoss', 'FeatureCutThin', 'ExtrudedCut']:
    if hasattr(fm, m):
        print(f"  {m}: 存在")
    else:
        print(f"  {m}: 不存在")

# ===== 步骤 6：尝试 SaveAs3 =====
print("\n--- 步骤 6：SaveAs3 测试 ---")
output_path = Path(r"d:\SynthDraft\backend\tmp_realtest\writer_debug_part.sldprt")
if output_path.exists():
    output_path.unlink()

errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
warnings = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
try:
    # SaveAs3 签名：(FileName, Version, Options, Errors, Warnings)
    # Version: 0 = swSaveAsCurrentVersion
    # Options: 0 = swSaveAsOptions_Silent
    save_result = doc.SaveAs3(
        str(output_path),
        0,    # swSaveAsCurrentVersion
        0,    # swSaveAsOptions_Silent
        errors,
        warnings,
    )
    print(f"  SaveAs3 返回: {save_result}")
    print(f"  文件存在: {output_path.is_file()}")
    if output_path.is_file():
        print(f"  文件大小: {output_path.stat().st_size} bytes")
except Exception as e:
    print(f"  SaveAs3 失败: {e}")

# 清理
try:
    session.close_document(doc, save_changes=False)
except Exception:
    pass
session.close()
print("\n诊断完成。")
