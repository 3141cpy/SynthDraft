"""诊断 SolidWorks API：验证属性 vs 方法访问模式。

背景：
  EnsureDispatch 失败（makepy 不支持），只能用动态 Dispatch。
  动态 Dispatch 下 GetFirstFeature() 报错，但 FirstFeature 属性可访问。
  需要确认其他 API 是否也遵循此模式。
"""
import sys
sys.path.insert(0, r"d:\SynthDraft\backend")

from pathlib import Path
from app.services.solidworks.sw_session import SolidWorksSession, SW_DOC_PART
from win32com.client import VARIANT
import pythoncom


def safe_call(label: str, fn):
    """安全调用，捕获异常并打印结果。"""
    try:
        result = fn()
        type_name = type(result).__name__ if result is not None else "None"
        # 截断长结果
        result_str = str(result)
        if len(result_str) > 100:
            result_str = result_str[:100] + "..."
        print(f"  [OK]   {label}: {result_str} (type={type_name})")
        return result
    except Exception as e:
        print(f"  [FAIL] {label}: {type(e).__name__}: {e}")
        return None


def main():
    session = SolidWorksSession()
    session.start(visible=False)
    print(f"\nSolidWorks 版本: {session.revision}")

    filepath = r"C:\Users\Public\Documents\SolidWorks\SOLIDWORKS 2025\samples\introsw\bolt.sldprt"
    errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    warnings = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    doc = session._sw_app.OpenDoc6(filepath, 1, 2, "", errors, warnings)
    print(f"OpenDoc6: type={type(doc).__name__}")

    print("\n=== 1. 特征树访问：属性 vs 方法 ===")
    feat_method = safe_call("GetFirstFeature() 方法", lambda: doc.GetFirstFeature())
    feat_prop = safe_call("FirstFeature 属性", lambda: doc.FirstFeature)

    if feat_prop is not None:
        print("\n=== 2. Feature 对象属性访问 ===")
        safe_call("feat.Name", lambda: feat_prop.Name)
        safe_call("feat.GetTypeName2()", lambda: feat_prop.GetTypeName2())
        safe_call("feat.GetTypeName", lambda: feat_prop.GetTypeName)
        safe_call("feat.TypeName", lambda: feat_prop.TypeName)
        safe_call("feat.GetNextFeature() 方法", lambda: feat_prop.GetNextFeature())
        safe_call("feat.NextFeature 属性", lambda: feat_prop.NextFeature)
        safe_call("feat.GetFirstChildFeature() 方法", lambda: feat_prop.GetFirstChildFeature())
        safe_call("feat.FirstChildFeature 属性", lambda: feat_prop.FirstChildFeature)
        safe_call("feat.GetFirstDisplayDimension() 方法", lambda: feat_prop.GetFirstDisplayDimension())
        safe_call("feat.FirstDisplayDimension 属性", lambda: feat_prop.FirstDisplayDimension)
        safe_call("feat.IsSuppressed()", lambda: feat_prop.IsSuppressed())
        safe_call("feat.IsSuppressed 属性", lambda: feat_prop.IsSuppressed)
        safe_call("feat.GetSpecificFeature2()", lambda: feat_prop.GetSpecificFeature2())
        safe_call("feat.GetDefinition()", lambda: feat_prop.GetDefinition())

    print("\n=== 3. Extension / CustomPropertyManager ===")
    ext = safe_call("doc.Extension", lambda: doc.Extension)
    if ext is not None:
        safe_call("ext.GetAnnotations()", lambda: ext.GetAnnotations())
        safe_call("ext.GetMassProperties(1.0)", lambda: ext.GetMassProperties(1.0))
        cpm = safe_call("ext.CustomPropertyManager('')", lambda: ext.CustomPropertyManager(""))
        if cpm is not None:
            safe_call("cpm.GetNames()", lambda: cpm.GetNames())
            safe_call("cpm.GetNames 属性", lambda: cpm.Names)

    print("\n=== 4. 文档级属性 ===")
    safe_call("doc.GetConfigurationNames()", lambda: doc.GetConfigurationNames())
    safe_call("doc.ConfigurationNames 属性", lambda: doc.ConfigurationNames)
    safe_call("doc.GetNameForSelection", lambda: doc.GetNameForSelection)
    safe_call("doc.GetTitle()", lambda: doc.GetTitle())
    safe_call("doc.Title 属性", lambda: doc.Title)
    safe_call("doc.GetType()", lambda: doc.GetType())
    safe_call("doc.Type 属性", lambda: doc.Type)
    safe_call("doc.GetUserPreferenceIntegerValue(13)",
              lambda: doc.GetUserPreferenceIntegerValue(13))

    print("\n=== 5. 遍历特征树（属性访问模式）===")
    feat = feat_prop
    count = 0
    while feat is not None and count < 20:
        try:
            name = str(feat.Name)
        except Exception as e:
            print(f"  [{count}] Name 读取失败: {e}")
            break
        type_name = None
        try:
            type_name = str(feat.GetTypeName2())
        except Exception:
            try:
                type_name = str(feat.TypeName)
            except Exception:
                type_name = "<unknown>"
        print(f"  [{count}] {name}  (type={type_name})")
        count += 1
        try:
            feat = feat.NextFeature
        except Exception as e:
            print(f"  NextFeature 失败: {e}")
            break

    print(f"\n共遍历 {count} 个顶层特征")

    # 清理
    try:
        session._sw_app.CloseAllDocuments(True)
    except Exception:
        pass
    session.close()
    print("\n诊断完成。")


if __name__ == "__main__":
    main()
