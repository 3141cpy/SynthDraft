"""测试直接使用类型库模块（绕过 EnsureDispatch）。

策略：
  1. 用 Dispatch 获取 SldWorks.Application COM 对象
  2. 用 CastTo 将其转换为类型库中的 ISldWorks 接口
  3. 通过强类型接口访问 Feature API
"""
import sys
sys.path.insert(0, r"d:\SynthDraft\backend")

from pathlib import Path
import pythoncom
from win32com.client import Dispatch, gencache, CastTo
from win32com.client import VARIANT


def main():
    # 确保类型库模块已加载
    # GUID 来自 makepy 输出：83A33D31-27C5-11CE-BFD4-00400513BB57
    try:
        sw_module = gencache.EnsureModule(
            "{83A33D31-27C5-11CE-BFD4-00400513BB57}", 0, 0, 51
        )
        print(f"[OK] 加载 sldworks 类型库模块: {sw_module}")
    except Exception as e:
        print(f"[FAIL] 加载类型库失败: {e}")
        return 1

    # 用 Dispatch 获取 COM 对象
    pythoncom.CoInitialize()
    try:
        sw_app = Dispatch("SldWorks.Application")
        print(f"[OK] Dispatch 成功，版本={sw_app.RevisionNumber}")

        # 尝试 CastTo 转换为 ISldWorks
        try:
            sw_strong = CastTo(sw_app, "ISldWorks")
            print(f"[OK] CastTo ISldWorks 成功，类型={type(sw_strong).__name__}")
        except Exception as e:
            print(f"[FAIL] CastTo ISldWorks 失败: {e}")
            # 尝试其他接口名
            for iface in ("ISldWorks", "SldWorks", "ISldWorks1"):
                try:
                    sw_strong = CastTo(sw_app, iface)
                    print(f"[OK] CastTo {iface} 成功")
                    break
                except Exception as e2:
                    print(f"  [FAIL] CastTo {iface}: {e2}")
            return 1

        # 打开 bolt.sldprt
        errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        warnings = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        filepath = r"C:\Users\Public\Documents\SolidWorks\SOLIDWORKS 2025\samples\introsw\bolt.sldprt"

        # 用强类型接口打开文档
        try:
            doc = sw_strong.OpenDoc6(filepath, 1, 2, "", errors, warnings)
            print(f"[OK] OpenDoc6 成功，type={type(doc).__name__}")
        except Exception as e:
            print(f"[FAIL] OpenDoc6 失败: {e}")
            return 1

        if doc is None:
            print("[FAIL] OpenDoc6 返回 None")
            return 1

        # 尝试 CastTo IModelDoc2
        print("\n--- 尝试 CastTo 文档接口 ---")
        doc_strong = None
        for iface in ("IModelDoc2", "IModelDoc", "IPartDoc", "ModelDoc2", "PartDoc"):
            try:
                doc_strong = CastTo(doc, iface)
                print(f"[OK] CastTo {iface} 成功，类型={type(doc_strong).__name__}")
                break
            except Exception as e:
                print(f"  [FAIL] CastTo {iface}: {e}")

        if doc_strong is None:
            print("[FAIL] 无法转换到任何文档接口")
            return 1

        # 测试特征树访问
        print("\n--- 特征树访问（强类型）---")
        try:
            # IModelDoc2.FirstFeature 是属性
            feat = doc_strong.FirstFeature
            print(f"[OK] FirstFeature: {feat} (type={type(feat).__name__})")
        except Exception as e:
            print(f"[FAIL] FirstFeature 属性: {e}")

        # 尝试 GetFirstFeature 方法
        try:
            feat = doc_strong.GetFirstFeature()
            print(f"[OK] GetFirstFeature(): {feat}")
        except Exception as e:
            print(f"[FAIL] GetFirstFeature(): {e}")

        # 如果 FirstFeature 返回了对象，尝试遍历
        try:
            feat = doc_strong.FirstFeature
            count = 0
            while feat is not None and count < 20:
                try:
                    name = feat.Name
                    type_name = feat.GetTypeName2()
                    print(f"  [{count}] {name} (type={type_name})")
                except Exception as e:
                    print(f"  [{count}] 读取失败: {e}")
                    break
                count += 1
                try:
                    feat = feat.GetNextFeature()
                except Exception as e:
                    print(f"  GetNextFeature 失败: {e}")
                    break
            print(f"\n共遍历 {count} 个特征")
        except Exception as e:
            print(f"特征遍历失败: {e}")

        # 清理
        try:
            sw_app.CloseAllDocuments(True)
        except Exception:
            pass
        try:
            sw_app.ExitApp()
        except Exception:
            pass

    finally:
        pythoncom.CoUninitialize()

    return 0


if __name__ == "__main__":
    sys.exit(main())
