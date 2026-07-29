"""测试通过类型库模块直接包装 COM 对象。

策略：
  1. 用 Dispatch 获取 COM 对象（_oleobj_）
  2. 用生成的 ISldWorks 类包装 _oleobj_
  3. 通过强类型接口调用 FirstFeature / GetNextFeature 等
"""
import sys
sys.path.insert(0, r"d:\SynthDraft\backend")

import importlib.util
import pythoncom
from win32com.client import Dispatch, VARIANT


def load_typelib_module():
    """直接通过文件路径加载类型库模块。"""
    mod_path = (
        r"d:\SynthDraft\backend\.venv\Lib\site-packages\win32com\gen_py"
        r"\83A33D31-27C5-11CE-BFD4-00400513BB57x0x33x0.py"
    )
    spec = importlib.util.spec_from_file_location("sw_typelib", mod_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    sw_module = load_typelib_module()
    print(f"[OK] 类型库模块已加载")

    pythoncom.CoInitialize()
    try:
        # 1. 用 Dispatch 获取 COM 对象
        sw_app_dyn = Dispatch("SldWorks.Application")
        print(f"[OK] Dispatch 成功，版本={sw_app_dyn.RevisionNumber}")

        # 2. 用 ISldWorks 包装 _oleobj_
        oleobj = sw_app_dyn._oleobj_
        sw_strong = sw_module.ISldWorks(oleobj)
        print(f"[OK] ISldWorks 包装成功，类型={type(sw_strong).__name__}")

        # 3. 打开 bolt.sldprt
        # 强类型接口下 ByRef 参数传普通值即可（类型库自动处理）
        filepath = r"C:\Users\Public\Documents\SolidWorks\SOLIDWORKS 2025\samples\introsw\bolt.sldprt"

        # 用强类型接口打开文档（OpenDoc6 签名已通过类型库确认）
        # Errors/Warnings 是 ByRef out 参数，传 0 即可
        # 返回值是 tuple: (ModelDoc2, errors, warnings)
        open_result = sw_strong.OpenDoc6(filepath, 1, 2, "", 0, 0)
        if isinstance(open_result, tuple):
            doc = open_result[0]
            errors_val = open_result[1] if len(open_result) > 1 else None
            warnings_val = open_result[2] if len(open_result) > 2 else None
            print(f"[OK] OpenDoc6 成功，doc 类型={type(doc).__name__}, errors={errors_val}, warnings={warnings_val}")
        else:
            doc = open_result
            print(f"[OK] OpenDoc6 成功，doc 类型={type(doc).__name__}")

        if doc is None:
            print("[FAIL] OpenDoc6 返回 None")
            return 1

        # doc 可能是动态 Dispatch，需要包装为 IModelDoc2
        if not isinstance(doc, sw_module.IModelDoc2):
            if hasattr(doc, '_oleobj_'):
                doc_strong = sw_module.IModelDoc2(doc._oleobj_)
            else:
                doc_strong = doc
        else:
            doc_strong = doc
        print(f"[OK] IModelDoc2 包装，类型={type(doc_strong).__name__}")

        # 4. 测试特征树遍历
        print("\n--- 特征树遍历（强类型）---")
        feat = doc_strong.FirstFeature()
        print(f"FirstFeature: {feat} (type={type(feat).__name__ if feat else 'None'})")

        count = 0
        while feat is not None and count < 30:
            # 包装为 IFeature（动态 Dispatch 返回 CDispatch，需手动包装）
            if not isinstance(feat, sw_module.IFeature):
                if hasattr(feat, '_oleobj_'):
                    feat = sw_module.IFeature(feat._oleobj_)
                else:
                    print(f"  [{count}] 无法包装为 IFeature")
                    break

            try:
                name = feat.Name
                type_name = feat.GetTypeName2()
                print(f"  [{count}] {name}  (type={type_name})")
            except Exception as e:
                print(f"  [{count}] 读取失败: {e}")
                break

            count += 1
            try:
                feat = feat.GetNextFeature()
            except Exception as e:
                print(f"  GetNextFeature 失败: {e}")
                break

        print(f"\n共遍历 {count} 个顶层特征")

        # 5. 测试 Extension / CustomPropertyManager
        print("\n--- Extension / CustomPropertyManager ---")
        try:
            ext = doc_strong.Extension
            print(f"Extension: type={type(ext).__name__}")
            # 包装为 IModelDocExtension
            if hasattr(ext, '_oleobj_') and not hasattr(ext, 'GetMassProperties'):
                ext = sw_module.IModelDocExtension(ext._oleobj_)
            print(f"IModelDocExtension 包装后: type={type(ext).__name__}")

            # 获取质量属性
            try:
                # GetMassProperties(Accuracy, Status) - Status 是 ByRef out
                mass_props = ext.GetMassProperties(1.0, 0)
                if mass_props:
                    arr = list(mass_props) if hasattr(mass_props, '__iter__') else [mass_props]
                    print(f"GetMassProperties: {len(arr)} 个值, mass={arr[0] if arr else 'N/A'}")
            except Exception as e:
                print(f"GetMassProperties 失败: {e}")

            # 自定义属性
            try:
                cpm = ext.CustomPropertyManager("")
                if cpm is not None:
                    # 包装为 ICustomPropertyManager
                    if hasattr(cpm, '_oleobj_'):
                        cpm = sw_module.ICustomPropertyManager(cpm._oleobj_)
                    names = cpm.GetNames()
                    print(f"CustomPropertyManager.GetNames: {names}")
                    if names:
                        # 测试 Get5
                        for name in (names if hasattr(names, '__iter__') else [names]):
                            try:
                                val = cpm.Get5(str(name), False)
                                print(f"  Get5({name}): {val}")
                            except Exception as e:
                                print(f"  Get5({name}) 失败: {e}")
            except Exception as e:
                print(f"CustomPropertyManager 失败: {e}")

        except Exception as e:
            print(f"Extension 访问失败: {e}")

        # 6. 测试配置名
        print("\n--- 配置名 ---")
        try:
            configs = doc_strong.GetConfigurationNames()
            print(f"GetConfigurationNames: {configs}")
        except Exception as e:
            print(f"GetConfigurationNames 失败: {e}")

        # 7. 测试标题/类型
        print("\n--- 文档属性 ---")
        try:
            title = doc_strong.GetTitle()
            print(f"GetTitle: {title}")
        except Exception as e:
            print(f"GetTitle 失败: {e}")
        try:
            doc_type = doc_strong.GetType()
            print(f"GetType: {doc_type}")
        except Exception as e:
            print(f"GetType 失败: {e}")

        # 清理
        try:
            sw_app_dyn.CloseAllDocuments(True)
        except Exception:
            pass

    finally:
        try:
            sw_app_dyn.ExitApp()
        except Exception:
            pass
        pythoncom.CoUninitialize()

    return 0


if __name__ == "__main__":
    sys.exit(main())
