"""SolidWorks Worker 模块（Task 7）。

对外公共接口聚合：调用方优先从此包导入，避免直接依赖具体子模块。
所有 pywin32 / SolidWorks COM 的 import 都在 sw_session.py 内 try/except
优雅降级，本包 import 安全（Linux 部署时 is_solidworks_available() 返回 False）。

支持能力：
- SubTask 7.1（完成）：SolidWorksSession / SolidWorksWorkerPool / solidworks_task
- SubTask 7.2（完成）：read_sldprt / read_sldasm（结构化提取）
  - 特征树（含子特征递归）
  - 尺寸（含公差类型与上下偏差）
  - 形位公差（GB/T 1182 / ISO 1101）
  - 表面粗糙度（GB/T 131）
  - 技术要求（从自定义属性提取）
  - 装配体组件树 / 配合 / BOM 明细栏
  - 质量属性（质量/体积/表面积/重心）
- SubTask 7.3（完成）：generate_sldprt_from_cadquery /
  generate_sldprt_from_features / generate_sldasm_from_components
  - 路径 A: CadQuery 代码 → STEP → SolidWorks 导入 → SLDPRT
  - 路径 B: 特征描述 → FeatureManager API 重建 → SLDPRT
  - 路径 C: 组件列表 + 配合 → AddComponent5 + AddMate5 → SLDASM

- SubTask 7.4（完成）：Worker Pool 稳定性增强
  - 任务超时强制 kill SolidWorks 进程并重启（_kill_solidworks_process）
  - 健康检查分级（HealthStatus 枚举：healthy/degraded/unhealthy/restarting/stopped）
  - 自动重启增强（_restart_with_retry 指数退避 + on_restart 回调 + restart_count）
  - 进程隔离增强（max_concurrent_sessions + Semaphore + acquire_slot/release_slot）
  - is_busy / wait_for_idle 用于优雅关闭与并发控制
  - 任务注册表（_task_registry：task_id → thread/start_time/timeout）

- SubTask 7.5（完成）：Celery solidworks 队列 + 跨平台消息队列通信
  - 6 个 Celery 任务（read_sldprt/read_sldasm/generate_*/license_status）
  - 见 app/celery/tasks/solidworks.py
  - Linux AI 服务通过 Celery 投递任务到 solidworks 队列，Windows Worker 消费

- SubTask 7.6（完成）：SolidWorks 许可证管理与并发控制
  - SolidWorksLicenseManager：许可证状态检测 + 计数控制 + 线程安全
  - LicenseStatus 枚举（available/in_use/exhausted/unknown）
  - Worker Pool start/shutdown 集成许可证获取/释放
  - license_status / max_licenses / license_manager 属性暴露

部署约束（spec.md §3 部署约束）：
SolidWorks 原生文件（SLDPRT/SLDASM）的生成与编辑必须在装有 SolidWorks 许可证的
Windows 机器上通过 API 完成；不可绕过。
"""

from app.services.solidworks.exceptions import (
    SolidWorksLicenseError,
    SolidWorksNotAvailableError,
    SolidWorksSessionError,
    SolidWorksTaskError,
    SolidWorksTaskTimeout,
)
from app.services.solidworks.license import (
    LicenseStatus,
    SolidWorksLicenseManager,
    get_license_manager,
)
from app.services.solidworks.status import HealthStatus
from app.services.solidworks.sw_session import (
    SW_DOC_ASSEMBLY,
    SW_DOC_DRAWING,
    SW_DOC_PART,
    SolidWorksSession,
    get_session,
    is_solidworks_available,
)
from app.services.solidworks.worker_pool import (
    SolidWorksWorkerPool,
    get_worker_pool,
    solidworks_task,
)

# SubTask 7.2: SLDPRT/SLDASM 读取
# reader.py 通过 @solidworks_task 装饰，调用时自动管理 Worker Pool 生命周期
# 模块 import 安全（pywin32 在 sw_session.py 内 try/except 优雅降级）
from app.services.solidworks.reader import (
    read_sldasm,
    read_sldprt,
)

# SubTask 7.3: SLDPRT/SLDASM 生成
# writer.py 通过 @solidworks_task 装饰，调用时自动管理 Worker Pool 生命周期
# 三条生成路径：CadQuery→SLDPRT / 特征→SLDPRT / 组件→SLDASM
from app.services.solidworks.writer import (
    generate_sldasm_from_components,
    generate_sldprt_from_cadquery,
    generate_sldprt_from_features,
)

# SubTask P0-3: eDrawings CLI 渲染器（SLDPRT/SLDASM L3a 降级）
# edrawings_cli.py 提供 eDrawings 包装 + C# CLI subprocess 调用
from app.services.solidworks.edrawings_cli import (
    is_edrawings_available,
    render_sldprt_via_edrawings,
)

__all__ = [
    # 异常
    "SolidWorksLicenseError",
    "SolidWorksNotAvailableError",
    "SolidWorksSessionError",
    "SolidWorksTaskError",
    "SolidWorksTaskTimeout",
    # 状态（SubTask 7.4）
    "HealthStatus",
    # 许可证管理（SubTask 7.6）
    "LicenseStatus",
    "SolidWorksLicenseManager",
    "get_license_manager",
    # 会话
    "SW_DOC_ASSEMBLY",
    "SW_DOC_DRAWING",
    "SW_DOC_PART",
    "SolidWorksSession",
    "get_session",
    "is_solidworks_available",
    # Worker 池
    "SolidWorksWorkerPool",
    "get_worker_pool",
    "solidworks_task",
    # 读取（SubTask 7.2）
    "read_sldprt",
    "read_sldasm",
    # 生成（SubTask 7.3）
    "generate_sldprt_from_cadquery",
    "generate_sldprt_from_features",
    "generate_sldasm_from_components",
    # eDrawings CLI（P0-3）
    "is_edrawings_available",
    "render_sldprt_via_edrawings",
]
