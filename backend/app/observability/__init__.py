"""可观测性模块（Task 16）。

封装 P2 阶段新增的可观测性能力：
- tracing：OpenTelemetry 全链路埋点（FastAPI / Celery / httpx / requests）
- queue_monitor：Celery 队列状态采集与阈值告警
- alerts：告警规则与通知渠道
- llm_metrics：LLM 推理成本与延迟监控

遵循"以复用现有为荣"原则：app/tracing.py 保留为兼容入口，
本包内 tracing.py 在其基础上扩展 httpx/requests 自动埋点与 span 工具。
OTEL_ENABLED=false 时所有 tracing 操作降级为空操作。
"""

from __future__ import annotations
