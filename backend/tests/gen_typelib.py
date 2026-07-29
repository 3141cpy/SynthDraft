"""手动生成 SolidWorks 类型库缓存（makepy）。

背景：
  win32com.client.gencache.EnsureDispatch("SldWorks.Application") 失败：
  "This COM object can not automate the makepy process"
  原因：自动 makepy 无法从 ProgID 解析类型库，需手动指定 .tlb 路径。

  通过 makepy.main() 处理 sldworks.tlb + swconst.tlb，生成 GenPy 缓存。
  缓存路径：%TEMP%\gen_py\3.x\（PyWin32 版本相关）
"""
import sys
import os

# SolidWorks 类型库路径（已通过注册表确认）
TLB_PATHS = [
    r"D:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\sldworks.tlb",
    r"D:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\swconst.tlb",
]

# 设置环境变量，强制 makepy 生成缓存
os.environ["GEN_PY"] = r"d:\SynthDraft\backend\.venv\Lib\site-packages\win32com\gen_py"


def main():
    try:
        from win32com.client import gencache, makepy
        import pythoncom
    except ImportError as e:
        print(f"[FAIL] pywin32 未安装: {e}")
        return 1

    # 检查 gen_py 目录
    gen_py_dir = os.environ["GEN_PY"]
    print(f"gen_py 目录: {gen_py_dir}")
    os.makedirs(gen_py_dir, exist_ok=True)

    for tlb_path in TLB_PATHS:
        if not os.path.isfile(tlb_path):
            print(f"[FAIL] 类型库不存在: {tlb_path}")
            continue
        print(f"\n--- 处理 {os.path.basename(tlb_path)} ---")
        try:
            # 加载类型库
            tlb = pythoncom.LoadTypeLib(tlb_path)
            print(f"  类型库已加载，包含 {tlb.GetTypeInfoCount()} 个类型")

            # 遍历并打印前几个类型名
            for i in range(min(5, tlb.GetTypeInfoCount())):
                try:
                    info = tlb.GetTypeInfo(i)
                    name = tlb.GetDocumentation(i)[0]
                    print(f"    [{i}] {name}")
                except Exception as e:
                    print(f"    [{i}] 读取失败: {e}")

            # 使用 gencache 生成缓存
            from win32com.client.gencache import EnsureModule
            # 获取类型库的 GUID/版本
            attr = tlb.GetLibAttr()
            guid = str(attr.guid)
            major = attr.wMajorVerNum
            minor = attr.wMinorVerNum
            lcid = attr.lcid
            print(f"  GUID={guid}, Major={major}, Minor={minor}, LCID={lcid}")

            module = EnsureModule(guid, lcid, major, minor)
            if module is not None:
                print(f"  [OK] 缓存已生成: {module}")
            else:
                print(f"  [WARN] EnsureModule 返回 None")

        except Exception as e:
            print(f"  [FAIL] {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()

    # 验证：尝试 EnsureDispatch
    print("\n--- 验证 EnsureDispatch ---")
    try:
        sw = gencache.EnsureDispatch("SldWorks.Application")
        if sw is not None:
            rev = sw.RevisionNumber
            print(f"  [OK] EnsureDispatch 成功，版本={rev}")
            try:
                sw.ExitApp()
            except Exception:
                pass
        else:
            print(f"  [FAIL] EnsureDispatch 返回 None")
    except Exception as e:
        print(f"  [FAIL] EnsureDispatch 失败: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

    return 0


if __name__ == "__main__":
    sys.exit(main())
