"""诊断 SolidWorks API：检查 GetFirstFeature 返回 None 的原因。"""
import sys
sys.path.insert(0, r"d:\SynthDraft\backend")

from pathlib import Path
from app.services.solidworks.sw_session import SolidWorksSession, SW_DOC_PART
from win32com.client import VARIANT
import pythoncom

session = SolidWorksSession()
session.start(visible=False)
print(f"SolidWorks 版本: {session.revision}")

# 打开 bolt.sldprt
errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
warnings = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
filepath = r"C:\Users\Public\Documents\SolidWorks\SOLIDWORKS 2025\samples\introsw\bolt.sldprt"
doc = session._sw_app.OpenDoc6(filepath, 1, 2, "", errors, warnings)
print(f"OpenDoc6 返回: type={type(doc).__name__}")

# 尝试各种特征树访问方式
print("\n--- 特征树访问方式测试 ---")

# 1. GetFirstFeature() 方法
try:
    feat = doc.GetFirstFeature()
    print(f"1. GetFirstFeature(): {feat} (type={type(feat).__name__})")
except Exception as e:
    print(f"1. GetFirstFeature() ERROR: {e}")

# 2. FirstFeature 属性
try:
    feat = doc.FirstFeature
    print(f"2. FirstFeature: {feat} (type={type(feat).__name__})")
except Exception as e:
    print(f"2. FirstFeature ERROR: {e}")

# 3. GetFirstFeature2
try:
    feat = doc.GetFirstFeature2()
    print(f"3. GetFirstFeature2(): {feat}")
except Exception as e:
    print(f"3. GetFirstFeature2() ERROR: {e}")

# 4. 尝试激活文档
try:
    activated = session._sw_app.ActivateDoc3(filepath, False, 0)
    print(f"4. ActivateDoc3: {activated}")
except Exception as e:
    print(f"4. ActivateDoc3 ERROR: {e}")

# 5. 激活后重试 GetFirstFeature
try:
    feat = doc.GetFirstFeature()
    print(f"5. 激活后 GetFirstFeature(): {feat}")
except Exception as e:
    print(f"5. 激活后 GetFirstFeature() ERROR: {e}")

# 6. 检查 doc 的 Feature 相关属性
print("\n--- doc 中含 Feature/First 的属性 ---")
for attr in sorted(dir(doc)):
    if not attr.startswith('_') and ('Feature' in attr or 'First' in attr or 'feature' in attr):
        print(f"  {attr}")

# 7. 检查 doc 的 Get 方法
print("\n--- doc 中 Get 开头的方法 ---")
for attr in sorted(dir(doc)):
    if not attr.startswith('_') and attr.startswith('Get'):
        print(f"  {attr}")

# 8. 检查 Extension
try:
    ext = doc.Extension
    print(f"\nExtension: {type(ext).__name__}")
    for attr in sorted(dir(ext)):
        if not attr.startswith('_') and ('Annotation' in attr or 'Custom' in attr or 'Mass' in attr):
            print(f"  ext.{attr}")
except Exception as e:
    print(f"Extension ERROR: {e}")

# 9. 检查自定义属性
try:
    cpm = ext.CustomPropertyManager("")
    print(f"\nCustomPropertyManager: {type(cpm).__name__}")
    names = cpm.GetNames()
    print(f"GetNames: {names}")
except Exception as e:
    print(f"CustomPropertyManager ERROR: {e}")

# 10. 检查质量属性
try:
    mass = ext.GetMassProperties(2)
    print(f"\nGetMassProperties: {mass}")
except Exception as e:
    print(f"GetMassProperties ERROR: {e}")

session.close()
print("\n诊断完成。")
