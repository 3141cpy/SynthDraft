"""辅助脚本：通过 ollama Python 客户端拉取 qwen2.5-coder:7b。

仅在 Task 5 自检阶段使用；不属于正式产物。
"""

from __future__ import annotations

import sys
import time

import ollama


def main() -> int:
    model = "qwen2.5-coder:7b"
    t0 = time.time()
    print(f"[pull] start {model}", flush=True)
    try:
        for progress in ollama.pull(model=model, stream=True):
            status = progress.get("status", "")
            completed = progress.get("completed")
            total = progress.get("total")
            if completed is not None and total is not None and total > 0:
                pct = completed / total * 100
                print(f"[pull] {status} {pct:5.1f}% ({completed}/{total})", flush=True)
            else:
                print(f"[pull] {status}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[pull] FAILED: {type(e).__name__}: {e}", flush=True)
        return 1
    print(f"[pull] done in {time.time() - t0:.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
