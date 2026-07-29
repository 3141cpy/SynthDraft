"""诊断 SolidWorks writer API：检查 SelectByID2/FeatureExtrusion2 的正确签名。"""
import sys
sys.path.insert(0, r"d:\SynthDraft\backend")

from app.services.solidworks.sw_session import SolidWorksSession, SW_DOC_PART

session = SolidWorksSession()
session.start(visible=False)
print(f"SolidWorks 版本: {session.revision}")

# 创建新零件
doc = session.new_document(doc_type=SW_DOC_PART)
print(f"\n新零件文档: type={type(doc).__name__}")

# ===== 1. 检查 Extension.SelectByID2 签名 =====
print("\n--- 1. Extension.SelectByID2 检查 ---")
ext = doc.Extension
print(f"Extension: type={type(ext).__name__}")

# 列出 Select 相关方法
select_methods = [m for m in dir(ext) if 'Select' in m and not m.startswith('_')]
print(f"Select 相关方法: {select_methods}")

# ===== 2. 检查 SketchManager 方法 =====
print("\n--- 2. SketchManager 检查 ---")
sm = doc.SketchManager
print(f"SketchManager: type={type(sm).__name__}")
insert_methods = [m for m in dir(sm) if 'Insert' in m and not m.startswith('_')]
print(f"Insert 相关方法: {insert_methods}")
create_methods = [m for m in dir(sm) if 'Create' in m and not m.startswith('_')][:10]
print(f"Create 相关方法（前10）: {create_methods}")

# ===== 3. 检查 FeatureManager.FeatureExtrusion* 方法 =====
print("\n--- 3. FeatureManager 检查 ---")
fm = doc.FeatureManager
print(f"FeatureManager: type={type(fm).__name__}")
extrusion_methods = [m for m in dir(fm) if 'Extrusion' in m or 'Extrude' in m]
print(f"Extrusion 相关方法: {extrusion_methods}")

# 检查 FeatureExtrusion2 的方法签名
try:
    import inspect
    # 强类型接口的方法签名
    feat_extrusion2 = getattr(fm, 'FeatureExtrusion2', None)
    print(f"\nFeatureExtrusion2 属性: {feat_extrusion2}")
    if feat_extrusion2 is not None:
        # 尝试获取参数信息
        if callable(feat_extrusion2):
            print(f"  callable: True")
            try:
                sig = inspect.signature(feat_extrusion2)
                print(f"  signature: {sig}")
            except Exception as e:
                print(f"  signature 不可用: {e}")
        else:
            print(f"  callable: False (可能是方法对象)")
except Exception as e:
    print(f"检查 FeatureExtrusion2 签名失败: {e}")

# ===== 4. 尝试不同的 SelectByID2 调用方式 =====
print("\n--- 4. SelectByID2 调用测试 ---")

# 4.1 尝试 Empty/None 作为 Callout 参数
try:
    # 使用 None 作为 Callout（第7个参数）
    result = ext.SelectByID2("前视基准面", "PLANE", 0.0, 0.0, 0.0, False, 0, None, 0)
    print(f"4.1 SelectByID2(前视基准面, None callout): {result}")
except Exception as e:
    print(f"4.1 SelectByID2(前视基准面, None callout) 失败: {e}")

# 4.2 使用 pythoncom.Missing 作参数
try:
    import pythoncom
    from win32com.client import VARIANT
    # 使用 Nothing (pythoncom.Missing)
    nothing = VARIANT(pythoncom.VT_DISPATCH, None)
    result = ext.SelectByID2("前视基准面", "PLANE", 0.0, 0.0, 0.0, False, 0, nothing, 0)
    print(f"4.2 SelectByID2(前视基准面, VARIANT VT_DISPATCH None): {result}")
except Exception as e:
    print(f"4.2 SelectByID2(前视基准面, VARIANT VT_DISPATCH None) 失败: {e}")

# 4.3 使用 SelectByID2 在 ISldWorks 上（而非 Extension）
try:
    sw = session._sw_app
    result = sw.SelectByID2("前视基准面", "PLANE", 0.0, 0.0, 0.0, False, 0, None, 0)
    print(f"4.3 ISldWorks.SelectByID2(前视基准面): {result}")
except Exception as e:
    print(f"4.3 ISldWorks.SelectByID2(前视基准面) 失败: {e}")

# 4.4 尝试使用英文名 + SelectByID4
try:
    if hasattr(ext, 'SelectByID4'):
        result = ext.SelectByID4("Front Plane", "PLANE", 0.0, 0.0, 0.0, False, 0, None, 0)
        print(f"4.4 SelectByID4(Front Plane): {result}")
    else:
        print("4.4 SelectByID4 不存在")
except Exception as e:
    print(f"4.4 SelectByID4 失败: {e}")

# ===== 5. 列出 IModelDoc2 中所有 Select 方法 =====
print("\n--- 5. doc 中 Select 相关方法 ---")
doc_select_methods = [m for m in dir(doc) if 'Select' in m and not m.startswith('_')]
print(f"doc.Select 方法: {doc_select_methods}")

# ===== 6. 列出可能的基准面访问方法 =====
print("\n--- 6. 基准面访问方法 ---")
plane_methods = [m for m in dir(doc) if 'Plane' in m and not m.startswith('_')]
print(f"doc.Plane 方法: {plane_methods}")

# ===== 7. 尝试 FeatureExtrusion3（如果存在）=====
print("\n--- 7. 检查 FeatureExtrusion3/FeatureExtrusionThin ---")
for m in ['FeatureExtrusion3', 'FeatureExtrusionThin', 'FeatureExtrusionThin2', 'FeatureBossThin']:
    if hasattr(fm, m):
        print(f"  {m}: 存在")
    else:
        print(f"  {m}: 不存在")

# ===== 8. 尝试不同参数数目的 FeatureExtrusion2 =====
print("\n--- 8. FeatureExtrusion2 参数数目测试 ---")
# 先确保选中前视基准面并进入草图
try:
    # 直接用 SketchManager.InsertSketch 不选择面（在新零件中默认进入前视基准面）
    sm.InsertSketch(True)
    print("8.1 InsertSketch(True) 成功（默认基准面）")
    
    # 创建矩形
    sm.CreateCenterRectangle(0.0, 0.0, 0.0, 0.01, 0.01, 0.0)
    print("8.2 CreateCenterRectangle 成功")
    
    # 退出草图
    sm.InsertSketch(True)
    print("8.3 退出草图成功")
    
    # 现在测试 FeatureExtrusion2 不同参数数目
    # 标准 FeatureExtrusion2 有 21 个参数（SolidWorks 2025 API Help）
    print("\n8.4 测试 FeatureExtrusion2 不同参数数目:")
    
    # 21 参数版本（无 capEnd 相关）
    try:
        feat = fm.FeatureExtrusion2(
            True,           # 1. sd
            False,          # 2. flip
            False,          # 3. dir2
            0,              # 4. t1
            0,              # 5. t2
            0.01,           # 6. extDim
            0.0,            # 7. extDim2
            False, False,   # 8-9. dchkpt1, dchkpt2
            False, False,   # 10-11. ddir1, ddir2
            0.0, 0.0,       # 12-13. dAng1, dAng2
            True,           # 14. merge
            False,          # 15. useFeatScope
            True,           # 16. useAutoSelect
            0.0,            # 17. startThickness
            0.0,            # 18. endThickness
            0.0,            # 19. midPlaneThickness
            False,          # 20. flipStartOffset
            0.0,            # 21. startOffset
        )
        print(f"  21参数: feat={feat}")
    except Exception as e:
        print(f"  21参数 失败: {e}")
    
    # 16 参数版本（最简形式）
    try:
        feat = fm.FeatureExtrusion2(
            True,           # 1. sd
            False,          # 2. flip
            False,          # 3. dir2
            0,              # 4. t1
            0,              # 5. t2
            0.01,           # 6. extDim
            0.0,            # 7. extDim2
            False, False,   # 8-9. dchkpt1, dchkpt2
            False, False,   # 10-11. ddir1, ddir2
            0.0, 0.0,       # 12-13. dAng1, dAng2
            True,           # 14. merge
            False,          # 15. useFeatScope
            True,           # 16. useAutoSelect
        )
        print(f"  16参数: feat={feat}")
    except Exception as e:
        print(f"  16参数 失败: {e}")

except Exception as e:
    print(f"8.x 草图创建失败: {e}")

# 关闭文档
try:
    session.close_document(doc, save_changes=False)
except Exception:
    pass
session.close()
print("\n诊断完成。")
