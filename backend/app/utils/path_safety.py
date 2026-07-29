"""Path safety utilities for resolving user-supplied file keys within allowed roots.

防范路径穿越攻击（Finding 6/8/Part 3）：
- 拒绝绝对路径
- 拒绝通过 ``..`` 逃逸根目录的相对路径
- 仅在显式声明的根目录内查找文件
"""

from __future__ import annotations

from pathlib import Path


def resolve_within_roots(file_key: str, roots: list[Path]) -> Path:
    """Resolve file_key within allowed roots, rejecting absolute paths and traversal.

    Args:
        file_key: User-supplied relative path or filename
        roots: List of allowed root directories (will be resolved to absolute)

    Returns:
        Resolved path within one of the roots

    Raises:
        ValueError: If file_key is absolute or escapes roots
        FileNotFoundError: If file not found in any root
    """
    p = Path(file_key)
    if p.is_absolute():
        raise ValueError(f"absolute path not allowed: {file_key}")
    for root in roots:
        root_resolved = root.resolve()
        candidate = (root_resolved / file_key).resolve()
        try:
            candidate.relative_to(root_resolved)
        except ValueError:
            continue  # escapes this root, try next
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"file not found in allowed roots: {file_key}")
