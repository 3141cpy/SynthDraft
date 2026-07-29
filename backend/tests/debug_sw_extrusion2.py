"""验证 FeatureExtrusion2 正确 23 参数签名 + SelectByID2 修复。"""
import sys
sys.path.insert(0, r"d:\SynthDraft\backend")

from pathlib import Path
from app.services.solidworks.sw_session import SolidWorksSession, SW_DOC_PART
from win32com.client import VARIANT
import pythoncom

session = SolidWorksSession()
session.start(visible=False)
print(f"SolidWorks 版本: {session.revision}")

doc = session.new_document(doc_type=SW_DOC_PART)
ext = doc.Extension
sm = doc.SketchManager
fm = doc.FeatureManager

# ===== 1. 选择前视基准面（修复：用 VARIANT VT_DISPATCH None 作为 Callout）=====
print("\n--- 1. 选择前视基准面 ---")
nothing = VARIANT(pythoncom.VT_DISPATCH, None)
sel = ext.SelectByID2("前视基准面", "PLANE", 0.0, 0.0, 0.0, False, 0, nothing, 0)
print(f"SelectByID2(前视基准面): {sel}")

# ===== 2. 创建草图（中心矩形 20x20mm）=====
print("\n--- 2. 创建草图 ---")
sm.InsertSketch(True)
sm.CreateCenterRectangle(0.0, 0.0, 0.0, 0.01, 0.01, 0.0)
sm.InsertSketch(True)
print("草图已创建（中心矩形 20x20mm）")

# ===== 3. FeatureExtrusion2 正确的 23 参数签名 =====
# 类型库实测签名（FeatureManager.FeatureExtrusion2）：
# FeatureExtrusion2(Sd, Flip, Dir, T1, T2, D1, D2, Dchk1, Dchk2,
#                   Ddir1, Ddir2, Dang1, Dang2, OffsetReverse1, OffsetReverse2,
#                   TranslateSurface1, TranslateSurface2, Merge, UseFeatScope,
#                   UseAutoSelect, T0, StartOffset, FlipStartOffset)
print("\n--- 3. FeatureExtrusion2 (23 参数) ---")
try:
    feat = fm.FeatureExtrusion2(
        True,           # 1. Sd - 单方向
        False,          # 2. Flip - 翻转方向
        False,          # 3. Dir - 方向2
        0,              # 4. T1 - 起始条件类型 (swStartSketchPlane=0)
        0,              # 5. T2 - 终止条件类型 (swEndBlind=0)
        0.01,           # 6. D1 - 深度1 (10mm)
        0.0,            # 7. D2 - 深度2
        False,          # 8. Dchk1 - 拔模检查1
        False,          # 9. Dchk2 - 拔模检查2
        False,          # 10. Ddir1 - 拔模方向1
        False,          # 11. Ddir2 - 拔模方向2
        0.0,            # 12. Dang1 - 拔模角度1
        0.0,            # 13. Dang2 - 拔模角度2
        False,          # 14. OffsetReverse1
        False,          # 15. OffsetReverse2
        False,          # 16. TranslateSurface1
        False,          # 17. TranslateSurface2
        True,           # 18. Merge - 合并结果
        False,          # 19. UseFeatScope
        True,           # 20. UseAutoSelect
        0,              # 21. T0 - 起始条件类型
        0.0,            # 22. StartOffset
        False,          # 23. FlipStartOffset
    )
    print(f"FeatureExtrusion2 成功! feat={feat}")
    print(f"feat type: {type(feat).__name__ if feat else 'None'}")
except Exception as e:
    print(f"FeatureExtrusion2 失败: {e}")
    feat = None

# ===== 4. SaveAs3 测试（3 参数版本）=====
print("\n--- 4. SaveAs3 (3 参数) ---")
output_path = Path(r"d:\SynthDraft\backend\tmp_realtest\writer_debug_part.sldprt")
if output_path.exists():
    output_path.unlink()
try:
    save_result = doc.SaveAs3(str(output_path), 0, 1)  # Silent
    print(f"SaveAs3 返回: {save_result}")
    print(f"文件存在: {output_path.is_file()}")
    if output_path.is_file():
        print(f"文件大小: {output_path.stat().st_size} bytes")
except Exception as e:
    print(f"SaveAs3 失败: {e}")

# ===== 5. 用 reader 读取生成的文件验证 =====
if output_path.is_file():
    print("\n--- 5. 用 reader 读取验证 ---")
    try:
        from app.services.solidworks.reader import read_sldprt
        raw_fn = getattr(read_sldprt, "_raw_fn", read_sldprt)
        model = raw_fn(session, output_path)
        print(f"读取成功: features={len(model.features)}")
        for f in model.features[:5]:
            print(f"  - {f.name} ({f.kind})")
    except Exception as e:
        print(f"读取失败: {e}")

# 清理
try:
    session.close_document(doc, save_changes=False)
except Exception:
    pass
session.close()
print("\n诊断完成。")
