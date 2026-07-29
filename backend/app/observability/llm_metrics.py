"""LLM 推理成本与延迟监控（SubTask 16.4）。

设计：
- 在 LLM 调用前后记录：模型名 / 输入 tokens / 输出 tokens / 耗时 / 成本估算
- 复用 ``app/services/ai`` provider 的调用点：
  通过 ``instrument_provider(provider)`` 在 provider 实例的
  ``chat`` / ``chat_with_image`` 方法周围加 hook（monkey-patch，
  不修改既有函数签名）
- 成本估算表：按模型每 1K token 价格（USD）
- 指标持久化：JSONL 写入 ``settings.OBS_LLM_METRICS_PATH``

遵循"以谨慎重构为荣"原则：仅新增 hook，不修改 provider 既有方法签名。
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app.config import settings
from app.logging import get_logger

log = get_logger(__name__)

_WRITE_LOCK = threading.Lock()

# ===== 成本估算表（USD per 1K tokens）=====
# 数据来源：各厂商官方定价页（2026-07-25 查询）
# - Ollama 本地模型：0 成本（仅算力）
# - OpenAI: https://openai.com/api/pricing/
# - Anthropic: https://www.anthropic.com/pricing
# - DeepSeek: https://api-docs.deepseek.com/quick_start/pricing
# 输入价 / 输出价 分别记录；未知模型按 0 估算
MODEL_PRICING_USD_PER_1K: dict[str, tuple[float, float]] = {
    # (input_per_1k, output_per_1k)
    # Ollama 本地
    "qwen2.5-coder:7b": (0.0, 0.0),
    "qwen2.5-coder:14b": (0.0, 0.0),
    "qwen2.5-vl:7b": (0.0, 0.0),
    "llava:7b": (0.0, 0.0),
    "minicpm-v": (0.0, 0.0),
    # OpenAI
    "gpt-4o": (0.0025, 0.01),
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-4-turbo": (0.01, 0.03),
    "gpt-3.5-turbo": (0.0005, 0.0015),
    # Anthropic
    "claude-3-5-sonnet-latest": (0.003, 0.015),
    "claude-3-5-haiku-latest": (0.001, 0.005),
    "claude-3-opus-latest": (0.015, 0.075),
    # DeepSeek
    "deepseek-chat": (0.00014, 0.00028),
    "deepseek-coder": (0.00014, 0.00028),
    "deepseek-reasoner": (0.00055, 0.00219),
    # 通义千问（vLLM 部署可能用）
    "qwen2.5-72b-instruct": (0.004, 0.012),
    # 智谱 GLM
    "glm-4": (0.001, 0.001),
    "glm-4v": (0.001, 0.001),
}


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """估算单次调用成本（USD）。

    未知模型按 0 返回（保守估算，避免虚高）。
    """
    if not model:
        return 0.0
    pricing = MODEL_PRICING_USD_PER_1K.get(model)
    if pricing is None:
        # 尝试前缀匹配（如 qwen2.5-coder:7b-instruct-fp16）
        for k, v in MODEL_PRICING_USD_PER_1K.items():
            if model.startswith(k) or k.startswith(model.split(":")[0]):
                pricing = v
                break
    if pricing is None:
        return 0.0
    in_price, out_price = pricing
    return round(input_tokens / 1000.0 * in_price + output_tokens / 1000.0 * out_price, 6)


def _extract_tokens(usage: dict[str, Any] | None) -> tuple[int, int]:
    """从 provider ChatResponse.usage 提取 (input_tokens, output_tokens)。

    兼容 OpenAI / Anthropic / Ollama 的字段命名差异：
    - OpenAI: prompt_tokens / completion_tokens
    - Anthropic: input_tokens / output_tokens
    - Ollama: prompt_eval_count / eval_count
    """
    if not usage:
        return 0, 0
    input_tokens = (
        usage.get("prompt_tokens")
        or usage.get("input_tokens")
        or usage.get("prompt_eval_count")
        or 0
    )
    output_tokens = (
        usage.get("completion_tokens")
        or usage.get("output_tokens")
        or usage.get("eval_count")
        or 0
    )
    return int(input_tokens), int(output_tokens)


def _metrics_path() -> Path:
    return Path(settings.OBS_LLM_METRICS_PATH)


def _ensure_metrics_dir() -> None:
    p = _metrics_path()
    p.parent.mkdir(parents=True, exist_ok=True)


def record_llm_call(
    *,
    model: str,
    input_tokens: int,
    output_tokens: int,
    elapsed_ms: float,
    operation: str = "chat",
    cost_usd: float | None = None,
    success: bool = True,
    error: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """记录一次 LLM 推理指标到 JSONL 文件。

    Args:
        model: 模型名
        input_tokens: 输入 token 数
        output_tokens: 输出 token 数
        elapsed_ms: 耗时（毫秒）
        operation: "chat" / "chat_with_image"
        cost_usd: 预估成本；None 时按 MODEL_PRICING 表估算
        success: 是否成功
        error: 失败时的错误信息
        extra: 附加元数据

    Returns:
        实际写入的指标字典。
    """
    if cost_usd is None:
        cost_usd = estimate_cost_usd(model, input_tokens, output_tokens)

    record: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "operation": operation,
        "input_tokens": int(input_tokens),
        "output_tokens": int(output_tokens),
        "total_tokens": int(input_tokens) + int(output_tokens),
        "elapsed_ms": round(float(elapsed_ms), 3),
        "cost_usd": float(cost_usd),
        "success": bool(success),
        "error": error,
    }
    if extra:
        record["extra"] = extra

    _ensure_metrics_dir()
    with _WRITE_LOCK:
        with _metrics_path().open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def load_all_metrics() -> list[dict[str, Any]]:
    """加载全部 LLM 指标记录。"""
    p = _metrics_path()
    if not p.is_file():
        return []
    records: list[dict[str, Any]] = []
    with p.open("r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except Exception as e:  # noqa: BLE001
                log.warning(
                    "llm_metrics.load.line_skipped",
                    lineno=lineno,
                    error=str(e),
                )
    return records


def compute_cost_summary(records: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """按模型汇总成本。

    Returns:
        dict 含 total_calls / total_cost_usd / by_model 列表
    """
    if records is None:
        records = load_all_metrics()
    by_model: dict[str, dict[str, Any]] = defaultdict_dict()
    total_cost = 0.0
    total_calls = 0
    total_input = 0
    total_output = 0
    for r in records:
        m = r.get("model", "unknown")
        agg = by_model[m]
        agg["model"] = m
        agg["calls"] += 1
        agg["input_tokens"] += int(r.get("input_tokens", 0))
        agg["output_tokens"] += int(r.get("output_tokens", 0))
        agg["total_tokens"] += int(r.get("total_tokens", 0))
        agg["cost_usd"] += float(r.get("cost_usd", 0.0))
        agg["elapsed_ms_total"] += float(r.get("elapsed_ms", 0.0))
        agg["failures"] += 0 if r.get("success") else 1
        total_cost += float(r.get("cost_usd", 0.0))
        total_calls += 1
        total_input += int(r.get("input_tokens", 0))
        total_output += int(r.get("output_tokens", 0))

    by_model_list = []
    for agg in by_model.values():
        calls = agg["calls"]
        agg["avg_latency_ms"] = round(agg["elapsed_ms_total"] / calls, 2) if calls else 0.0
        agg["cost_usd"] = round(agg["cost_usd"], 6)
        agg["failure_rate"] = round(agg["failures"] * 100.0 / calls, 2) if calls else 0.0
        by_model_list.append(agg)
    by_model_list.sort(key=lambda x: x["cost_usd"], reverse=True)

    return {
        "total_calls": total_calls,
        "total_cost_usd": round(total_cost, 6),
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "by_model": by_model_list,
    }


def compute_latency_distribution(records: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """计算延迟分布（p50 / p95 / p99 + 平均 + 最大）。

    Returns:
        dict 含 overall 与 by_model 两个维度。
    """
    if records is None:
        records = load_all_metrics()

    def _percentile(sorted_vals: list[float], p: float) -> float:
        if not sorted_vals:
            return 0.0
        k = (len(sorted_vals) - 1) * p / 100.0
        lo = int(k)
        hi = min(lo + 1, len(sorted_vals) - 1)
        frac = k - lo
        return round(sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac, 3)

    by_model_lat: dict[str, list[float]] = defaultdict_list()
    all_lat: list[float] = []
    for r in records:
        lat = float(r.get("elapsed_ms", 0.0))
        all_lat.append(lat)
        by_model_lat[r.get("model", "unknown")].append(lat)

    all_lat_sorted = sorted(all_lat)
    overall = {
        "count": len(all_lat_sorted),
        "avg_ms": round(sum(all_lat_sorted) / len(all_lat_sorted), 3) if all_lat_sorted else 0.0,
        "p50_ms": _percentile(all_lat_sorted, 50),
        "p95_ms": _percentile(all_lat_sorted, 95),
        "p99_ms": _percentile(all_lat_sorted, 99),
        "max_ms": all_lat_sorted[-1] if all_lat_sorted else 0.0,
    }

    by_model = {}
    for m, lats in by_model_lat.items():
        lats_sorted = sorted(lats)
        by_model[m] = {
            "count": len(lats_sorted),
            "avg_ms": round(sum(lats_sorted) / len(lats_sorted), 3) if lats_sorted else 0.0,
            "p50_ms": _percentile(lats_sorted, 50),
            "p95_ms": _percentile(lats_sorted, 95),
            "p99_ms": _percentile(lats_sorted, 99),
            "max_ms": lats_sorted[-1] if lats_sorted else 0.0,
        }

    return {"overall": overall, "by_model": by_model}


# ===== defaultdict 工厂（避免 lambda 在闭包中的可变默认陷阱）=====


def defaultdict_dict() -> dict[str, dict[str, Any]]:
    """返回一个 defaultdict，默认值为可写 dict。"""
    from collections import defaultdict

    def _new_agg() -> dict[str, Any]:
        return {
            "model": "",
            "calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "cost_usd": 0.0,
            "elapsed_ms_total": 0.0,
            "failures": 0,
        }

    return defaultdict(_new_agg)


def defaultdict_list() -> dict[str, list[float]]:
    from collections import defaultdict

    return defaultdict(list)


# ===== Provider Hook =====


def instrument_provider(provider: Any) -> bool:
    """对 provider 实例的 chat / chat_with_image 方法加 metrics hook。

    通过 monkey-patch 包裹原方法，不修改既有函数签名。
    幂等：重复调用不会重复包裹。

    Args:
        provider: ``BaseLLMProvider`` 实例

    Returns:
        True 表示已埋点（或已埋过点）；False 表示无法埋点。
    """
    if provider is None:
        return False
    if getattr(provider, "_llm_metrics_instrumented", False):
        return True

    original_chat = getattr(provider, "chat", None)
    original_chat_with_image = getattr(provider, "chat_with_image", None)

    if original_chat is None or original_chat_with_image is None:
        log.warning(
            "llm_metrics.instrument.skip",
            reason="provider_missing_methods",
            has_chat=original_chat is not None,
            has_chat_with_image=original_chat_with_image is not None,
        )
        return False

    def _wrap(method_name: str, original: Callable) -> Callable:
        def _wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            success = True
            err_msg = ""
            resp = None
            try:
                resp = original(*args, **kwargs)
                return resp
            except Exception as e:  # noqa: BLE001
                success = False
                err_msg = str(e)
                raise
            finally:
                elapsed_ms = (time.perf_counter() - start) * 1000.0
                model = ""
                input_tokens = 0
                output_tokens = 0
                if resp is not None:
                    model = getattr(resp, "model", "") or ""
                    usage = getattr(resp, "usage", None)
                    input_tokens, output_tokens = _extract_tokens(usage)
                try:
                    record_llm_call(
                        model=model,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        elapsed_ms=elapsed_ms,
                        operation=method_name,
                        success=success,
                        error=err_msg,
                    )
                except Exception as hook_err:  # noqa: BLE001
                    log.warning(
                        "llm_metrics.hook.record_failed",
                        method=method_name,
                        error=str(hook_err),
                    )

        return _wrapper

    try:
        provider.chat = _wrap("chat", original_chat)  # type: ignore[method-assign]
        provider.chat_with_image = _wrap(  # type: ignore[method-assign]
            "chat_with_image", original_chat_with_image
        )
        provider._llm_metrics_instrumented = True  # type:[attr-defined]
        log.info("llm_metrics.provider_instrumented", provider=type(provider).__name__)
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("llm_metrics.instrument.failed", error=str(e))
        return False


def self_test() -> dict[str, Any]:
    """self_test：写入 2 条测试指标 + 验证成本估算 + hook。"""
    import tempfile

    orig = settings.OBS_LLM_METRICS_PATH
    tmpdir = tempfile.mkdtemp(prefix="llm_metrics_selftest_")
    test_path = str(Path(tmpdir) / "llm_metrics.jsonl")
    settings.OBS_LLM_METRICS_PATH = test_path  # type: ignore[assignment]
    try:
        # 1) 成本估算
        cost_gpt4o = estimate_cost_usd("gpt-4o", 1000, 500)
        cost_ollama = estimate_cost_usd("qwen2.5-coder:7b", 1000, 500)
        cost_unknown = estimate_cost_usd("nonexistent-model", 1000, 500)

        # 2) 写入 2 条测试记录
        r1 = record_llm_call(
            model="gpt-4o",
            input_tokens=100,
            output_tokens=50,
            elapsed_ms=1234.5,
            operation="chat",
        )
        r2 = record_llm_call(
            model="qwen2.5-coder:7b",
            input_tokens=200,
            output_tokens=80,
            elapsed_ms=5678.9,
            operation="chat_with_image",
        )

        # 3) 加载并汇总
        loaded = load_all_metrics()
        summary = compute_cost_summary(loaded)
        latency = compute_latency_distribution(loaded)

        # 4) hook 测试：用 fake provider
        class _FakeResp:
            def __init__(self) -> None:
                self.model = "gpt-4o-mini"
                self.usage = {"prompt_tokens": 50, "completion_tokens": 30}

        class _FakeProvider:
            def __init__(self) -> None:
                self.model = "fake"

            def chat(self, messages: list, temperature: float = 0.2, max_tokens: int = 2048):
                return _FakeResp()

            def chat_with_image(
                self, messages: list, image_b64: str, temperature: float = 0.2, max_tokens: int = 2048
            ):
                return _FakeResp()

        fp = _FakeProvider()
        hooked = instrument_provider(fp)
        fp.chat([])
        fp.chat_with_image([], "img")
        loaded_after_hook = load_all_metrics()

        return {
            "cost_gpt4o_1k_in_0.5k_out": cost_gpt4o,
            "cost_ollama_zero": cost_ollama,
            "cost_unknown_zero": cost_unknown,
            "wrote_count": 2,
            "loaded_count": len(loaded),
            "summary_total_calls": summary["total_calls"],
            "summary_total_cost": summary["total_cost_usd"],
            "summary_model_count": len(summary["by_model"]),
            "latency_p50": latency["overall"]["p50_ms"],
            "latency_p95": latency["overall"]["p95_ms"],
            "hook_applied": hooked,
            "after_hook_records": len(loaded_after_hook),
            "metrics_path": test_path,
            "ok": (
                cost_gpt4o > 0
                and cost_ollama == 0.0
                and cost_unknown == 0.0
                and len(loaded) == 2
                and summary["total_calls"] == 2
                and len(summary["by_model"]) == 2
                and hooked is True
                and len(loaded_after_hook) == 4  # 2 + 2 from hook
            ),
        }
    finally:
        settings.OBS_LLM_METRICS_PATH = orig  # type: ignore[assignment]


if __name__ == "__main__":
    print(json.dumps(self_test(), indent=2, ensure_ascii=False, default=str))
