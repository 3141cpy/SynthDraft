"""STEP/IGES 3D 模型渲染为 PNG（降级方案）。

当 OCCT 离屏渲染不可用时，通过 OCC BRepMesh 网格化 → StlAPI 导出 STL
→ trimesh 加载 → pyrender 离屏渲染。

使用 scikit-robot-pyrender（pyrender 的 fork）作为优先后端：自动从 OpenGL 4.1
→ 4.0 → 3.3 降级并启用软件渲染，在无 GPU / WSL2 / headless 服务器上稳定性
显著优于原版 pyrender（原版在 OpenGL 上下文创建失败时直接崩溃）。
scikit-robot-pyrender 安装后模块名仍为 pyrender（fork 包名相同），通过 PyPI
包名区分；缺失时回退原版 pyrender。pyrender API 在 fork 中完全兼容，无需修改
Scene/Mesh/Camera/OffscreenRenderer 调用。
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from app.logging import get_logger

log = get_logger(__name__)

# 检测实际使用的 pyrender 后端：
# scikit-robot-pyrender（fork，自动 OpenGL 降级 + 软件渲染）或原版 pyrender。
# 两者模块名均为 pyrender，且 fork 安装路径也直接是 pyrender/（不含 scikit_robot
# 字样），因此不能靠文件路径区分。改用 importlib.metadata 按 PyPI 包名可靠识别：
# fork 包名为 "scikit-robot-pyrender"，原版为 "pyrender"。
import importlib.metadata as _metadata

try:
    import pyrender as _pyrender_mod
    try:
        _metadata.distribution("scikit-robot-pyrender")
        _PYRENDER_BACKEND = "scikit-robot-pyrender"
    except _metadata.PackageNotFoundError:
        _PYRENDER_BACKEND = "pyrender"
except ImportError:
    _pyrender_mod = None
    _PYRENDER_BACKEND = None


def render_via_trimesh(
    shape: Any,
    output_path: str | Path,
    width: int = 1024,
    height: int = 768,
) -> str:
    """用 trimesh + pyrender 渲染 OCC shape 为 PNG。

    Args:
        shape: OCC TopoDS_Shape 对象
        output_path: 输出 PNG 路径
        width: 图片宽度
        height: 图片高度

    Returns:
        输出 PNG 路径

    Raises:
        DependencyMissingError: trimesh 或 pyrender 未安装
        RuntimeError: 渲染失败
    """
    from app.services.review.dependency_check import (
        DependencyMissingError,
        is_trimesh_pyrender_available,
    )

    if not is_trimesh_pyrender_available():
        raise DependencyMissingError(
            dependency_name="trimesh + pyrender",
            install_hint="pip install trimesh scikit-robot-pyrender  # 推荐（自动 OpenGL 降级 + 软件渲染）\n或 pip install trimesh pyrender  # 原版（headless 环境可能失败）",
            file_type="step/iges",
        )

    import numpy as np
    import pyrender
    import trimesh

    # 记录实际使用的 pyrender 后端（scikit-robot-pyrender / pyrender）
    log.info("review.step_renderer.backend", backend=_PYRENDER_BACKEND)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # OCC shape → STL（通过 BRepMesh 网格化 + StlAPI 导出）
    stl_path: str | None = None
    try:
        try:
            from OCP.BRepMesh import BRepMesh_IncrementalMesh  # type: ignore[import-not-found]
            from OCP.StlAPI import StlAPI_Writer  # type: ignore[import-not-found]
        except ImportError:
            from OCC.Core.BRepMesh import BRepMesh_IncrementalMesh  # type: ignore[import-not-found]
            from OCC.Core.StlAPI import StlAPI_Writer  # type: ignore[import-not-found]

        # 网格化（修改 shape 本身，附加三角剖分数据）
        mesh = BRepMesh_IncrementalMesh(shape, 0.1)
        mesh.Perform()

        # 导出 STL 到临时文件
        writer = StlAPI_Writer()
        # OCP 7.9.x: ASCIIMode 是属性而非 SetASCIIMode 方法
        writer.ASCIIMode = False
        with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as f:
            stl_path = f.name
        writer.Write(shape, stl_path)

        # trimesh 加载
        tri_mesh = trimesh.load(stl_path)
    except Exception as e:
        raise RuntimeError(f"OCC shape 转 STL 失败: {e}") from e
    finally:
        # 清理临时 STL（无论成功或异常）
        if stl_path is not None:
            Path(stl_path).unlink(missing_ok=True)

    # pyrender 离屏渲染
    r = None
    try:
        scene = pyrender.Scene(bg_color=[255, 255, 255, 1.0])
        scene.add(pyrender.Mesh.from_trimesh(tri_mesh))

        # 根据 mesh bounding box 自动计算相机位姿，避免相机在物体内部
        bounds = tri_mesh.bounds  # (2, 3): [min, max]
        center = (bounds[0] + bounds[1]) / 2.0
        size = bounds[1] - bounds[0]
        # 相机距离 = 物体对角线 / (2 * tan(yfov/2))，留 1.5 倍余量
        diagonal = float(np.linalg.norm(size))
        yfov = np.pi / 3.0
        cam_dist = max(diagonal * 1.5, (max(size) / 2.0) / np.tan(yfov / 2.0) * 1.2)

        # 等轴侧视角：相机看向物体中心，沿 (1, -1, 1) 方向偏移
        direction = np.array([1.0, -1.0, 1.0])
        direction = direction / np.linalg.norm(direction)
        cam_pos = center + direction * cam_dist

        # 构造 look-at 矩阵（pyrender 相机 -Z 朝前）
        up = np.array([0.0, 0.0, 1.0])
        forward = center - cam_pos
        forward = forward / np.linalg.norm(forward)
        right = np.cross(forward, up)
        right = right / np.linalg.norm(right)
        up_vec = np.cross(right, forward)

        camera_pose = np.eye(4)
        camera_pose[:3, 0] = right
        camera_pose[:3, 1] = up_vec
        camera_pose[:3, 2] = -forward  # pyrender 相机 -Z 朝前
        camera_pose[:3, 3] = cam_pos

        camera = pyrender.PerspectiveCamera(yfov=yfov)
        scene.add(camera, pose=camera_pose)

        # 光源（与相机同位）
        light = pyrender.DirectionalLight(color=[1.0, 1.0, 1.0], intensity=3.0)
        scene.add(light, pose=camera_pose)

        r = pyrender.OffscreenRenderer(width, height)
        color, _ = r.render(scene)

        # 保存 PNG
        from PIL import Image

        Image.fromarray(color).save(str(output_path))
        return str(output_path)
    except Exception as e:
        raise RuntimeError(f"pyrender 渲染失败: {e}") from e
    finally:
        # 确保 OffscreenRenderer 资源释放（即使渲染异常）
        if r is not None:
            try:
                r.delete()
            except Exception:  # noqa: BLE001
                pass
