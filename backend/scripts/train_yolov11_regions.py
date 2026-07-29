"""YOLOv11 工程图区域检测训练脚本（Task 9.3 占位）。

用途：
- P1 阶段收集标注数据后，用本脚本训练 YOLOv11 区域检测模型
- 训练完成后将权重路径通过环境变量 SYNTHDRAFT_YOLO_REGION_WEIGHTS 指定，
  region_detector.py 即自动启用 YOLOv11 推理路径

数据集要求（YOLO 格式）：
- 数据集根目录下含 images/ 与 labels/（同名 .txt，每行 "cls cx cy w h" 归一化）
- 提供一个 data.yaml 描述 train/val 路径与类别名，类别名须与
  app.schemas.region_detection.RegionType 枚举值一致：
    0: title_block
    1: dimension_area
    2: view_area
    3: parts_list
    4: revision_block
    5: technical_requirements
    6: other

ultralytics 训练 API（官方文档核实：
  https://docs.ultralytics.com/zh/modes/train/）：
    from ultralytics import YOLO
    model = YOLO("yolo11n.pt")          # 加载预训练权重
    model.train(data="data.yaml", epochs=100, imgsz=640)

运行方式：
    python scripts/train_yolov11_regions.py --data dataset.yaml
    python scripts/train_yolov11_regions.py --data dataset.yaml --epochs 200 --imgsz 640 --weights yolo11s.pt

实测结论（本环境）：
- ultralytics 未安装 → 打印安装指引并退出（exit code 2）
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


# 类别名须与 app.schemas.region_detection.RegionType 一致
EXPECTED_CLASSES = [
    "title_block",
    "dimension_area",
    "view_area",
    "parts_list",
    "revision_block",
    "technical_requirements",
    "other",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="YOLOv11 工程图区域检测训练脚本（Task 9.3）"
    )
    parser.add_argument(
        "--data",
        type=str,
        required=True,
        help="数据集 YAML 文件路径（YOLO 格式，含 train/val/names）",
    )
    parser.add_argument(
        "--weights",
        type=str,
        default="yolo11n.pt",
        help="预训练权重（默认 yolo11n.pt；可选 yolo11s/m/l/x）",
    )
    parser.add_argument(
        "--epochs",
        type=int,
        default=100,
        help="训练轮数（默认 100）",
    )
    parser.add_argument(
        "--imgsz",
        type=int,
        default=640,
        help="训练图像尺寸（默认 640）",
    )
    parser.add_argument(
        "--batch",
        type=int,
        default=16,
        help="批大小（默认 16）",
    )
    parser.add_argument(
        "--device",
        type=str,
        default="cpu",
        help="训练设备（cpu / 0 / 0,1；默认 cpu）",
    )
    parser.add_argument(
        "--project",
        type=str,
        default="runs/region_detect",
        help="训练输出目录（默认 runs/region_detect）",
    )
    parser.add_argument(
        "--name",
        type=str,
        default="yolo11_regions",
        help="实验名（默认 yolo11_regions）",
    )
    return parser.parse_args()


def check_ultralytics() -> bool:
    """检查 ultralytics 是否安装。未安装时打印指引并返回 False。"""
    try:
        import ultralytics  # type: ignore[import-not-found]

        print(f"[OK] ultralytics 已安装：{ultralytics.__version__}")
        return True
    except ImportError:
        print("[FAIL] ultralytics 未安装。")
        print("\n安装方式（任选其一）：")
        print("  pip install ultralytics>=8.3          # CPU 版（含 torch CPU）")
        print("  pip install ultralytics torch torchvision --index-url https://download.pytorch.org/whl/cu121")
        print("                                       # GPU 版（CUDA 12.1）")
        print("\n训练完成后，将权重路径设置为环境变量：")
        print("  $env:SYNTHDRAFT_YOLO_REGION_WEIGHTS = '<权重绝对路径>'  # PowerShell")
        print("  export SYNTHDRAFT_YOLO_REGION_WEIGHTS='<权重绝对路径>'  # bash")
        print("region_detector.py 会自动启用 YOLOv11 推理路径。")
        return False


def validate_data_yaml(yaml_path: Path) -> bool:
    """校验 data.yaml 的类别名与 RegionType 一致。

    实测：ultralytics 未安装时跳过 pyyaml 依赖也行，但 data.yaml 校验需要 yaml。
    """
    if not yaml_path.is_file():
        print(f"[FAIL] 数据集 YAML 不存在：{yaml_path}")
        return False
    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError:
        print("[WARN] pyyaml 未安装，跳过 YAML 校验")
        return True

    try:
        with open(yaml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception as e:
        print(f"[FAIL] 解析 YAML 失败：{e}")
        return False

    names = data.get("names")
    if not names:
        print("[WARN] data.yaml 缺少 names 字段，跳过类别校验")
        return True

    # names 可能是 list 或 dict
    if isinstance(names, dict):
        name_list = list(names.values())
    elif isinstance(names, list):
        name_list = names
    else:
        print(f"[WARN] names 字段类型异常：{type(names)}")
        return True

    print(f"[INFO] data.yaml 类别：{name_list}")
    missing = [c for c in EXPECTED_CLASSES if c not in name_list]
    extra = [c for c in name_list if c not in EXPECTED_CLASSES]
    if missing:
        print(f"[WARN] 缺少预期类别（RegionType）：{missing}")
    if extra:
        print(f"[WARN] 存在非预期类别：{extra}")
    if not missing and not extra:
        print(f"[OK] 类别名与 RegionType 完全一致（{len(name_list)} 类）")
    return True


def main() -> int:
    args = parse_args()
    data_path = Path(args.data).resolve()

    print("=" * 60)
    print("YOLOv11 工程图区域检测训练（Task 9.3）")
    print("=" * 60)
    print(f"数据集 YAML : {data_path}")
    print(f"预训练权重  : {args.weights}")
    print(f"轮数        : {args.epochs}")
    print(f"图像尺寸    : {args.imgsz}")
    print(f"批大小      : {args.batch}")
    print(f"设备        : {args.device}")
    print(f"输出目录    : {args.project}/{args.name}")
    print(f"预期类别    : {EXPECTED_CLASSES}")
    print("=" * 60)

    # 1. 检查 ultralytics
    if not check_ultralytics():
        return 2

    # 2. 校验 data.yaml
    if not validate_data_yaml(data_path):
        return 3

    # 3. 训练（ultralytics API 官方文档核实）
    try:
        from ultralytics import YOLO  # type: ignore[import-not-found]
    except ImportError:
        print("[FAIL] ultralytics 导入失败")
        return 2

    print(f"\n[INFO] 加载预训练权重：{args.weights}")
    model = YOLO(args.weights)

    print("[INFO] 开始训练...")
    results = model.train(
        data=str(data_path),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        project=args.project,
        name=args.name,
        exist_ok=True,
    )

    # 训练结果
    print("\n" + "=" * 60)
    print("训练完成")
    print("=" * 60)
    save_dir = getattr(results, "save_dir", "(未知)")
    print(f"输出目录: {save_dir}")
    best_weights = Path(str(save_dir)) / "weights" / "best.pt"
    print(f"最佳权重: {best_weights}")
    if best_weights.is_file():
        print(f"\n[OK] 权重已生成。启用方式：")
        print(f'  $env:SYNTHDRAFT_YOLO_REGION_WEIGHTS = "{best_weights}"')
    else:
        print(f"[WARN] 未找到 best.pt，请检查 {Path(str(save_dir)) / 'weights'}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
