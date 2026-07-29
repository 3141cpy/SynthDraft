"""调试 SaveAs3 返回值结构（实测强类型 ISldWorks/IModelDoc2）。

目的：弄清 SaveAs3 在强类型接口下的实际返回值结构，
以便修正 sw_session.save_as 中对返回值的解析逻辑。
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.solidworks.sw_session import SolidWorksSession, SW_DOC_PART

OUT = BACKEND / "tmp_realtest" / "debug_saveas3.sldprt"
if OUT.exists():
    OUT.unlink()


def main() -> int:
    session = SolidWorksSession()
    session.start(visible=False)
    try:
        doc = session.new_document(doc_type=SW_DOC_PART)
        print(f"doc type: {type(doc).__name__}")

        # 创建草图+拉伸，确保文档非空
        import pythoncom
        from win32com.client import VARIANT
        nothing = VARIANT(pythoncom.VT_DISPATCH, None)
        ext = doc.Extension
        # 优先英文，回退中文
        try:
            ext.SelectByID2("Front Plane", "PLANE", 0.0, 0.0, 0.0,
                             False, 0, nothing, 0)
        except Exception:
            ext.SelectByID2("前视基准面", "PLANE", 0.0, 0.0, 0.0,
                             False, 0, nothing, 0)
        doc.SketchManager.InsertSketch(True)
        doc.SketchManager.CreateCenterRectangle(0.0, 0.0, 0.0,
                                                 0.01, 0.01, 0.0)
        doc.SketchManager.InsertSketch(True)
        feat = doc.FeatureManager.FeatureExtrusion2(
            True, False, False, 0, 0, 0.01, 0.0,
            False, False, False, False, 0.0, 0.0,
            False, False, False, False, True, False, True,
            0, 0.0, False,
        )
        print(f"extrusion feat: {feat}, type: {type(feat).__name__}")

        # ===== 关键：观察 SaveAs3 返回值 =====
        # 试法1：3 参数（当前实现）
        print("\n--- 试法1: SaveAs3(path, 0, 1) ---")
        try:
            ret = doc.SaveAs3(str(OUT), 0, 1)
            print(f"返回值: {ret!r}")
            print(f"类型: {type(ret).__name__}")
            if isinstance(ret, (tuple, list)):
                print(f"长度: {len(ret)}")
                for i, v in enumerate(ret):
                    print(f"  [{i}] = {v!r} ({type(v).__name__})")
            print(f"bool(ret): {bool(ret)}")
            print(f"文件存在: {OUT.is_file()}, 大小: {OUT.stat().st_size if OUT.is_file() else 0}")
        except Exception as e:
            print(f"异常: {type(e).__name__}: {e}")

        # 试法2：5 参数（强类型可能要求 errors/warnings）
        # 删除文件再试
        if OUT.exists():
            OUT.unlink()
        print("\n--- 试法2: SaveAs3(path, 0, 1, 0, 0) 带 ByRef ---")
        try:
            ret = doc.SaveAs3(str(OUT), 0, 1, 0, 0)
            print(f"返回值: {ret!r}")
            print(f"类型: {type(ret).__name__}")
            if isinstance(ret, (tuple, list)):
                print(f"长度: {len(ret)}")
                for i, v in enumerate(ret):
                    print(f"  [{i}] = {v!r} ({type(v).__name__})")
            print(f"文件存在: {OUT.is_file()}, 大小: {OUT.stat().st_size if OUT.is_file() else 0}")
        except Exception as e:
            print(f"异常: {type(e).__name__}: {e}")

        # 关闭文档
        session.close_document(doc, save_changes=False)
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
