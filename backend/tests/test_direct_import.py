"""测试直接导入生成的类型库模块。"""
import sys
sys.path.insert(0, r"d:\SynthDraft\backend")

import pythoncom
from win32com.client import Dispatch, CastTo, VARIANT


def main():
    # 直接导入生成的类型库模块
    # 文件名：83A33D31-27C5-11CE-BFD4-00400513BB57x0x33x0.py
    try:
        from win32com.gen_py import D83A33D31_27C5_11CE_BFD4_00400513BB57_0_51 as sw_module
        print(f"[OK] 直接导入类型库模块: {sw_module}")
        print(f"  模块属性: {[x for x in dir(sw_module) if not x.startswith('_')][:20]}")
    except ImportError as e:
        print(f"[FAIL] 直接导入失败: {e}")
        # 尝试其他导入方式
        try:
            import importlib.util
            mod_path = r"d:\SynthDraft\backend\.venv\Lib\site-packages\win32com\gen_py\83A33D31-27C5-11CE-BFD4-00400513BB57x0x33x0.py"
            spec = importlib.util.spec_from_file_location("sw_typelib", mod_path)
            sw_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(sw_module)
            print(f"[OK] importlib 导入成功: {sw_module}")
            print(f"  模块属性: {[x for x in dir(sw_module) if not x.startswith('_')][:20]}")
        except Exception as e2:
            print(f"[FAIL] importlib 导入失败: {e2}")
            return 1

    # 列出模块中的关键类
    print("\n--- 模块中的关键接口/类 ---")
    key_classes = ['ISldWorks', 'IModelDoc2', 'IPartDoc', 'IAssemblyDoc',
                   'IFeature', 'IModelDocExtension', 'ICustomPropertyManager',
                   'IFeatureManager', 'IComponent2', 'IMate2']
    for cls_name in key_classes:
        if hasattr(sw_module, cls_name):
            print(f"  [OK] {cls_name}: {getattr(sw_module, cls_name)}")
        else:
            # 查找相似的名称
            similar = [x for x in dir(sw_module) if cls_name.lower().replace('i', '') in x.lower()][:5]
            print(f"  [MISS] {cls_name}, 相似: {similar}")

    pythoncom.CoInitialize()
    try:
        sw_app = Dispatch("SldWorks.Application")
        print(f"\n[OK] Dispatch 成功，版本={sw_app.RevisionNumber}")

        # 尝试 CastTo
        print("\n--- CastTo 测试 ---")
        for iface in ['ISldWorks', 'ISldWorks1']:
            try:
                sw_strong = CastTo(sw_app, iface)
                print(f"[OK] CastTo {iface} 成功")
                break
            except Exception as e:
                print(f"  [FAIL] CastTo {iface}: {e}")

    finally:
        try:
            sw_app.ExitApp()
        except Exception:
            pass
        pythoncom.CoUninitialize()

    return 0


if __name__ == "__main__":
    sys.exit(main())
