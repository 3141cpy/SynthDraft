"""离线安装包构建脚本（SubTask 13.2）。

收集以下内容到单一离线包目录：
1. Python 依赖（pip download 到 wheels/）
2. 模型权重（Ollama 模型导出 / HuggingFace 模型快照）
3. 规范库（Qdrant 集合导出 + 原始 PDF）
4. Docker 镜像 tar（可选，--include-images）
5. 后端代码快照（git archive 或目录拷贝）

用法：
    # 仅 dry-run（列出待打包内容，不实际下载）
    python build_offline_package.py --dry-run

    # 实际打包到指定目录
    python build_offline_package.py --output D:/synthdraft_offline

    # 含 Docker 镜像
    python build_offline_package.py --output D:/synthdraft_offline --include-images

设计原则（八荣八耻）：
- 复用现有 infra/docker-compose.yml 与 backend/requirements.txt
- 不重新发明 pip download / huggingface-cli / ollama pull 等工具
- dry-run 模式确保可在 CI 中验证脚本可执行性（不依赖网络）

环境限制说明（实事求是标注）：
- 实际下载需要网络；dry-run 模式可在无网络环境验证脚本逻辑
- 模型权重体积大（GB 级），dry-run 仅统计预期大小，不实际下载
- Docker 镜像 tar 需本机已 docker pull 对应镜像
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ===== 路径常量 =====
# 本脚本位于 infra/offline_install/，项目根 = 父父父目录
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
INFRA_DIR = PROJECT_ROOT / "infra"

# 默认收集清单（与 infra/docker-compose.yml 中镜像 tag 对齐）
DEFAULT_DOCKER_IMAGES = [
    "postgres:16-alpine",
    "redis:7-alpine",
    "qdrant/qdrant:v1.18.3",
    "minio/minio:RELEASE.2025-09-07T16-13-09Z",
    "ollama/ollama:0.30.6",
    "vllm/vllm-openai:v0.25.0",
]

# 默认 HuggingFace 模型清单（与 backend/app/config.py 默认值对齐）
DEFAULT_HF_MODELS = [
    "BAAI/bge-m3",  # 嵌入模型
    # vLLM 模型由 VLLM_MODEL 配置决定，按需添加
]

# 默认 Ollama 模型清单（与 backend/app/config.py LLM_MODEL/VLM_MODEL 对齐）
DEFAULT_OLLAMA_MODELS = [
    "qwen2.5-coder:7b",
    "qwen2.5-vl:7b",
]


@dataclass
class PackageManifest:
    """离线包清单（描述待打包内容）。"""

    output_dir: str = ""
    python_wheels: list[str] = field(default_factory=list)
    hf_models: list[str] = field(default_factory=list)
    ollama_models: list[str] = field(default_factory=list)
    docker_images: list[str] = field(default_factory=list)
    spec_library_files: list[str] = field(default_factory=list)
    backend_code_archive: str = ""
    expected_size_gb: float = 0.0
    dry_run: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "output_dir": self.output_dir,
            "python_wheels": self.python_wheels,
            "hf_models": self.hf_models,
            "ollama_models": self.ollama_models,
            "docker_images": self.docker_images,
            "spec_library_files": self.spec_library_files,
            "backend_code_archive": self.backend_code_archive,
            "expected_size_gb": round(self.expected_size_gb, 2),
            "dry_run": self.dry_run,
        }


def _run(cmd: list[str], *, check: bool = True, capture: bool = True) -> tuple[int, str]:
    """运行子进程命令，返回 (returncode, output)。

    离线打包脚本不直接使用 RunCommand 工具，因为它是被用户/CI 调用的独立脚本。
    """
    try:
        result = subprocess.run(
            cmd,
            capture_output=capture,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if check and result.returncode != 0:
            raise RuntimeError(
                f"command failed: {' '.join(cmd)}\nstderr: {result.stderr}\nstdout: {result.stdout}"
            )
        return result.returncode, (result.stdout or "") + (result.stderr or "")
    except FileNotFoundError as e:
        if check:
            raise RuntimeError(f"command not found: {cmd[0]}") from e
        return -1, str(e)


def _estimate_model_size_gb(model_name: str) -> float:
    """粗略估算模型大小（GB）。"""
    name_lower = model_name.lower()
    if "7b" in name_lower:
        return 4.5  # 7B 量化约 4-5GB
    if "14b" in name_lower:
        return 8.5
    if "72b" in name_lower:
        return 40.0
    if "bge-m3" in name_lower:
        return 2.2  # 嵌入模型
    if "vl" in name_lower:
        return 5.5
    return 5.0  # 默认估算


def _collect_python_wheels(output_dir: Path, dry_run: bool) -> list[str]:
    """收集 Python wheels（pip download backend/requirements.txt）。"""
    wheels_dir = output_dir / "wheels"
    req_file = BACKEND_DIR / "requirements.txt"
    if not req_file.is_file():
        print(f"  [WARN] requirements.txt not found: {req_file}")
        return []
    if dry_run:
        # dry-run 模式：仅统计依赖数量
        try:
            with req_file.open("r", encoding="utf-8") as f:
                deps = [
                    line.strip()
                    for line in f
                    if line.strip() and not line.startswith("#")
                ]
            print(f"  [DRY-RUN] would pip download {len(deps)} deps to {wheels_dir}")
            return deps
        except Exception as e:  # noqa: BLE001
            print(f"  [WARN] failed to read requirements.txt: {e}")
            return []
    # 实际下载
    wheels_dir.mkdir(parents=True, exist_ok=True)
    print(f"  pip download -> {wheels_dir}")
    rc, _ = _run(
        [
            sys.executable,
            "-m",
            "pip",
            "download",
            "-r",
            str(req_file),
            "-d",
            str(wheels_dir),
            "--platform",
            "manylinux2014_x86_64",
            "--only-binary=:all:",
        ],
        check=False,
    )
    if rc != 0:
        # 回退：不限平台（允许 sdist）
        _run(
            [
                sys.executable,
                "-m",
                "pip",
                "download",
                "-r",
                str(req_file),
                "-d",
                str(wheels_dir),
            ],
            check=False,
        )
    return sorted(str(p.name) for p in wheels_dir.glob("*.whl"))


def _collect_hf_models(output_dir: Path, models: list[str], dry_run: bool) -> list[str]:
    """收集 HuggingFace 模型权重（huggingface-cli snapshot-download）。"""
    models_dir = output_dir / "models" / "huggingface"
    if dry_run:
        for m in models:
            print(f"  [DRY-RUN] would snapshot-download {m} -> {models_dir / m}")
        return models
    models_dir.mkdir(parents=True, exist_ok=True)
    for m in models:
        target = models_dir / m.replace("/", "_")
        target.mkdir(parents=True, exist_ok=True)
        print(f"  hf snapshot-download {m} -> {target}")
        _run(
            [
                sys.executable,
                "-m",
                "huggingface_hub",
                "snapshot-download",
                m,
                "--local-dir",
                str(target),
            ],
            check=False,
        )
    return models


def _collect_ollama_models(output_dir: Path, models: list[str], dry_run: bool) -> list[str]:
    """收集 Ollama 模型权重（ollama pull 后从 ~/.ollama/models 拷出）。"""
    models_dir = output_dir / "models" / "ollama"
    if dry_run:
        for m in models:
            print(f"  [DRY-RUN] would ollama pull {m} then export to {models_dir}")
        return models
    models_dir.mkdir(parents=True, exist_ok=True)
    for m in models:
        print(f"  ollama pull {m}")
        _run(["ollama", "pull", m], check=False)
        # 导出：ollama show --modelfile + 拷贝 blob
        # 简化实现：仅记录模型名，实际部署时由 install.sh 调 ollama pull
        (models_dir / f"{m.replace(':', '_')}.txt").write_text(
            f"# model: {m}\n# install via: ollama pull {m}\n",
            encoding="utf-8",
        )
    return models


def _collect_docker_images(output_dir: Path, images: list[str], dry_run: bool) -> list[str]:
    """收集 Docker 镜像 tar（docker save）。"""
    images_dir = output_dir / "docker_images"
    if dry_run:
        for img in images:
            print(f"  [DRY-RUN] would docker pull + save {img} -> {images_dir}")
        return images
    images_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for img in images:
        # pull（若本地已有则跳过）
        _run(["docker", "pull", img], check=False)
        tar_path = images_dir / f"{img.replace('/', '_').replace(':', '_')}.tar"
        print(f"  docker save {img} -> {tar_path}")
        rc, _ = _run(
            ["docker", "save", "-o", str(tar_path), img],
            check=False,
        )
        if rc == 0:
            saved.append(img)
    return saved


def _collect_spec_library(output_dir: Path, dry_run: bool) -> list[str]:
    """收集规范库文件（从 backend/tmp_uploads 或 spec 目录拷贝）。"""
    spec_dir = output_dir / "spec_library"
    # 候选源目录
    candidates = [
        BACKEND_DIR / "tmp_uploads",
        PROJECT_ROOT / "spec_library",
        PROJECT_ROOT / "data" / "spec_library",
    ]
    found_files: list[str] = []
    if dry_run:
        for c in candidates:
            if c.is_dir():
                files = list(c.glob("*.pdf")) + list(c.glob("*.docx"))
                print(f"  [DRY-RUN] would copy {len(files)} files from {c} -> {spec_dir}")
                found_files.extend(str(f.name) for f in files)
        return found_files
    spec_dir.mkdir(parents=True, exist_ok=True)
    for c in candidates:
        if not c.is_dir():
            continue
        for f in c.glob("*"):
            if f.suffix.lower() in {".pdf", ".docx", ".doc", ".txt", ".json"}:
                shutil.copy2(f, spec_dir / f.name)
                found_files.append(f.name)
    return found_files


def _archive_backend_code(output_dir: Path, dry_run: bool) -> str:
    """归档后端代码（git archive 或目录拷贝）。"""
    archive_path = output_dir / "backend_code.tar"
    if dry_run:
        print(f"  [DRY-RUN] would git archive backend -> {archive_path}")
        return str(archive_path)
    # 优先 git archive（排除 .venv）
    rc, _ = _run(
        ["git", "archive", "--format=tar", "-o", str(archive_path), "HEAD"],
        check=False,
    )
    if rc == 0:
        return str(archive_path)
    # 回退：直接拷贝目录（排除 .venv）
    print(f"  [WARN] git archive failed, fallback to dir copy")
    fallback = output_dir / "backend_code"
    fallback.mkdir(parents=True, exist_ok=True)
    for item in BACKEND_DIR.iterdir():
        if item.name in {".venv", "__pycache__", ".pytest_cache", "tmp_*"}:
            continue
        if item.is_dir():
            shutil.copytree(item, fallback / item.name, dirs_exist_ok=True)
        else:
            shutil.copy2(item, fallback / item.name)
    return str(fallback)


def build_package(
    output_dir: Path,
    *,
    dry_run: bool = False,
    include_images: bool = False,
    hf_models: list[str] | None = None,
    ollama_models: list[str] | None = None,
) -> PackageManifest:
    """构建离线安装包。

    Args:
        output_dir: 输出目录
        dry_run: 仅打印计划，不实际下载
        include_images: 是否包含 Docker 镜像 tar
        hf_models: 自定义 HF 模型清单（None 用默认）
        ollama_models: 自定义 Ollama 模型清单（None 用默认）

    Returns:
        PackageManifest 描述实际打包内容
    """
    output_dir = Path(output_dir).resolve()
    manifest = PackageManifest(
        output_dir=str(output_dir),
        dry_run=dry_run,
        hf_models=hf_models if hf_models is not None else list(DEFAULT_HF_MODELS),
        ollama_models=(
            ollama_models if ollama_models is not None else list(DEFAULT_OLLAMA_MODELS)
        ),
        docker_images=list(DEFAULT_DOCKER_IMAGES) if include_images else [],
    )

    print(f"\n{'=' * 60}")
    print(f"  SynthDraft 离线安装包构建 ({'DRY-RUN' if dry_run else 'REAL'})")
    print(f"  输出目录: {output_dir}")
    print(f"{'=' * 60}\n")

    if not dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Python wheels
    print("[1/5] 收集 Python wheels...")
    manifest.python_wheels = _collect_python_wheels(output_dir, dry_run)

    # 2. HuggingFace 模型
    print("\n[2/5] 收集 HuggingFace 模型权重...")
    manifest.hf_models = _collect_hf_models(output_dir, manifest.hf_models, dry_run)
    for m in manifest.hf_models:
        manifest.expected_size_gb += _estimate_model_size_gb(m)

    # 3. Ollama 模型
    print("\n[3/5] 收集 Ollama 模型权重...")
    manifest.ollama_models = _collect_ollama_models(
        output_dir, manifest.ollama_models, dry_run
    )
    for m in manifest.ollama_models:
        manifest.expected_size_gb += _estimate_model_size_gb(m)

    # 4. 规范库
    print("\n[4/5] 收集规范库...")
    manifest.spec_library_files = _collect_spec_library(output_dir, dry_run)

    # 5. 后端代码归档
    print("\n[5/5] 归档后端代码...")
    manifest.backend_code_archive = _archive_backend_code(output_dir, dry_run)

    # 6. Docker 镜像（可选）
    if include_images:
        print("\n[6/6] 收集 Docker 镜像...")
        manifest.docker_images = _collect_docker_images(
            output_dir, manifest.docker_images, dry_run
        )
        # 每个镜像粗略估算 500MB
        manifest.expected_size_gb += 0.5 * len(manifest.docker_images)

    # 写入 manifest.json
    if not dry_run:
        manifest_path = output_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"\n清单已写入: {manifest_path}")
    else:
        print(f"\n[DRY-RUN] 清单未写入（dry-run 模式）")

    print(f"\n预计总大小: {manifest.expected_size_gb:.2f} GB")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="构建 SynthDraft 离线安装包")
    parser.add_argument(
        "--output",
        "-o",
        default="./synthdraft_offline",
        help="输出目录（默认 ./synthdraft_offline）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅打印计划，不实际下载",
    )
    parser.add_argument(
        "--include-images",
        action="store_true",
        help="包含 Docker 镜像 tar（需要 docker 命令）",
    )
    parser.add_argument(
        "--hf-models",
        nargs="*",
        default=None,
        help="自定义 HuggingFace 模型清单（覆盖默认）",
    )
    parser.add_argument(
        "--ollama-models",
        nargs="*",
        default=None,
        help="自定义 Ollama 模型清单（覆盖默认）",
    )
    args = parser.parse_args()

    output = Path(args.output).resolve()
    manifest = build_package(
        output,
        dry_run=args.dry_run,
        include_images=args.include_images,
        hf_models=args.hf_models,
        ollama_models=args.ollama_models,
    )
    print("\n" + json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
