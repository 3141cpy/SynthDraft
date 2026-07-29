"""等保三级 + ISO 27001 合规自评检查器（SubTask 13.4）。

参考标准：
- GB/T 22239-2019《信息安全技术 网络安全等级保护基本要求》三级要求
- ISO/IEC 27001:2022 信息安全管理体系

设计原则（八荣八耻）：
- 实事求是：检查项标注"自动检测"或"人工确认"，不假装高精度
- 复用现有：基于 settings 与已实现的安全功能（JWT/审计日志/沙箱）评估
- 不引入额外依赖：仅用 Python 标准库

检查项分类：
1. **技术要求**（等保三级技术要求 + ISO 27001 A.8-A.10）
   - 身份鉴别 / 访问控制 / 安全审计 / 入侵防范 / 恶意代码防范
   - 数据完整性 / 数据保密性 / 数据可用性
2. **管理要求**（等保三级管理要求 + ISO 27001 A.5-A.7）
   - 安全策略 / 组织安全 / 资产管理 / 人员安全 / 物理环境
3. **SubTask 13.x 新增**：脱敏模式 / 审计日志保留 / 离线模式 / vLLM 量化
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from app.config import settings


@dataclass
class CheckResult:
    """单项检查结果。"""
    check_id: str
    name: str
    standard: str  # "等保三级" / "ISO 27001" / "SubTask13"
    category: str  # 技术要求 / 管理要求
    severity: str  # high / medium / low
    status: str  # pass / fail / warn / manual
    description: str = ""
    evidence: str = ""
    remediation: str = ""
    auto_detect: bool = True  # False 表示需人工确认


@dataclass
class ComplianceReport:
    """合规自评报告。"""
    timestamp: str = ""
    total: int = 0
    passed: int = 0
    failed: int = 0
    warned: int = 0
    manual: int = 0
    results: list[CheckResult] = field(default_factory=list)
    overall_score: float = 0.0  # 0-100

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "warned": self.warned,
            "manual": self.manual,
            "overall_score": round(self.overall_score, 2),
            "results": [
                {
                    "check_id": r.check_id,
                    "name": r.name,
                    "standard": r.standard,
                    "category": r.category,
                    "severity": r.severity,
                    "status": r.status,
                    "description": r.description,
                    "evidence": r.evidence,
                    "remediation": r.remediation,
                    "auto_detect": r.auto_detect,
                }
                for r in self.results
            ],
        }


# ===== 检查项定义 =====

def _check_jwt_secret() -> CheckResult:
    """检查 JWT_SECRET_KEY 是否已修改默认值。"""
    default_secret = "change-this-in-production-use-a-strong-random-secret"
    is_strong = settings.JWT_SECRET_KEY != default_secret and len(settings.JWT_SECRET_KEY) >= 32
    return CheckResult(
        check_id="T-001",
        name="JWT 密钥强度",
        standard="等保三级 8.1.4 / ISO 27001 A.9.4",
        category="技术要求",
        severity="high",
        status="pass" if is_strong else "fail",
        description="JWT 签发密钥应非默认且长度>=32",
        evidence=f"secret_length={len(settings.JWT_SECRET_KEY)}, is_default={settings.JWT_SECRET_KEY == default_secret}",
        remediation="在 .env 中设置 JWT_SECRET_KEY 为 32+ 字符随机字符串",
    )


def _check_token_expiry() -> CheckResult:
    """检查 JWT token 过期时间是否合理（<=24h）。"""
    minutes = settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
    is_reasonable = minutes <= 1440  # 24h
    return CheckResult(
        check_id="T-002",
        name="Token 过期策略",
        standard="等保三级 8.1.4 / ISO 27001 A.9.4.6",
        category="技术要求",
        severity="medium",
        status="pass" if is_reasonable else "warn",
        description="Access token 过期时间应 <= 24h",
        evidence=f"expire_minutes={minutes}",
        remediation="调低 JWT_ACCESS_TOKEN_EXPIRE_MINUTES 至 1440 以下",
    )


def _check_cors() -> CheckResult:
    """检查 CORS 配置是否非通配。"""
    origins = settings.cors_origins_list
    is_safe = "*" not in origins and len(origins) > 0
    return CheckResult(
        check_id="T-003",
        name="CORS 来源限制",
        standard="等保三级 8.1.3 / ISO 27001 A.13.1",
        category="技术要求",
        severity="high",
        status="pass" if is_safe else "fail",
        description="CORS 不应使用通配 *，应限制为前端域名",
        evidence=f"origins={origins}",
        remediation="在 .env 中设置 CORS_ORIGINS 为具体域名列表（逗号分隔）",
    )


def _check_offline_mode() -> CheckResult:
    """检查离线模式开关（SubTask 13.2）。"""
    return CheckResult(
        check_id="T-004",
        name="离线模式（私有化部署）",
        standard="SubTask13.2 / ISO 27001 A.13.7",
        category="技术要求",
        severity="medium",
        status="pass" if settings.is_offline else "warn",
        description="私有化部署应启用 OFFLINE_MODE=true 禁用外部网络调用",
        evidence=f"OFFLINE_MODE={settings.OFFLINE_MODE}",
        remediation="在 .env 中设置 OFFLINE_MODE=true",
    )


def _check_commercial_api_desensitize() -> CheckResult:
    """检查商业 API 脱敏模式（SubTask 13.3）。"""
    mode = settings.COMMERCIAL_API_MODE
    # strict / optional 都算启用；off 在使用商业 API 时为不合规
    is_enabled = mode in {"strict", "optional"}
    return CheckResult(
        check_id="T-005",
        name="商业 API 脱敏模式",
        standard="SubTask13.3 / ISO 27001 A.8.12",
        category="技术要求",
        severity="high",
        status="pass" if is_enabled else "warn",
        description="使用商业 LLM API 时应启用 strict 脱敏模式",
        evidence=f"COMMERCIAL_API_MODE={mode}",
        remediation="在 .env 中设置 COMMERCIAL_API_MODE=strict",
    )


def _check_audit_log() -> CheckResult:
    """检查审计日志开关与保留期（SubTask 13.4）。"""
    enabled = settings.AUDIT_LOG_ENABLED
    retention = settings.AUDIT_LOG_RETENTION_DAYS
    # 等保三级要求日志保留 >= 6 个月（180 天）
    is_compliant = enabled and retention >= 180
    return CheckResult(
        check_id="T-006",
        name="审计日志保留",
        standard="等保三级 8.1.4.3 / ISO 27001 A.8.15",
        category="技术要求",
        severity="high",
        status="pass" if is_compliant else "fail",
        description="审计日志应启用且保留 >= 180 天（等保三级要求 6 个月）",
        evidence=f"enabled={enabled}, retention_days={retention}",
        remediation="在 .env 中设置 AUDIT_LOG_ENABLED=true, AUDIT_LOG_RETENTION_DAYS=180",
    )


def _check_sandbox_static_scan() -> CheckResult:
    """检查 CadQuery 沙箱静态扫描是否启用。"""
    try:
        from app.services.generation.sandbox import STATIC_VIOLATIONS

        return CheckResult(
            check_id="T-007",
            name="代码沙箱静态扫描",
            standard="等保三级 8.1.4 / ISO 27001 A.14.2",
            category="技术要求",
            severity="high",
            status="pass",
            description="CadQuery 代码执行前应做静态扫描（危险 import 黑名单）",
            evidence=f"STATIC_VIOLATIONS count={len(STATIC_VIOLATIONS)}",
            remediation="",
        )
    except Exception as e:  # noqa: BLE001
        return CheckResult(
            check_id="T-007",
            name="代码沙箱静态扫描",
            standard="等保三级 8.1.4 / ISO 27001 A.14.2",
            category="技术要求",
            severity="high",
            status="fail",
            description="CadQuery 沙箱静态扫描模块加载失败",
            evidence=f"error={e}",
            remediation="检查 app.services.generation.sandbox 模块完整性",
        )


def _check_password_hash() -> CheckResult:
    """检查密码哈希算法（bcrypt）。"""
    try:
        from app.security import hash_password, verify_password

        h = hash_password("test")
        is_bcrypt = h.startswith("$2") and verify_password("test", h)
        return CheckResult(
            check_id="T-008",
            name="密码哈希算法",
            standard="等保三级 8.1.4.1 / ISO 27001 A.9.4.3",
            category="技术要求",
            severity="high",
            status="pass" if is_bcrypt else "fail",
            description="密码应使用 bcrypt 哈希存储",
            evidence=f"hash_prefix={h[:3]}",
            remediation="使用 app.security.hash_password 替代明文存储",
        )
    except Exception as e:  # noqa: BLE001
        return CheckResult(
            check_id="T-008",
            name="密码哈希算法",
            standard="等保三级 8.1.4.1 / ISO 27001 A.9.4.3",
            category="技术要求",
            severity="high",
            status="fail",
            description="密码哈希模块加载失败",
            evidence=f"error={e}",
            remediation="检查 passlib / bcrypt 安装",
        )


def _check_vllm_quantization() -> CheckResult:
    """检查 vLLM 量化配置（SubTask 13.1，GPU 部署时建议）。"""
    if not settings.VLLM_ENABLED:
        return CheckResult(
            check_id="T-009",
            name="vLLM GPU 量化（可选）",
            standard="SubTask13.1",
            category="技术要求",
            severity="low",
            status="manual",
            description="VLLM_ENABLED=false，未启用 vLLM GPU 推理",
            evidence=f"VLLM_ENABLED={settings.VLLM_ENABLED}",
            remediation="GPU 节点可启用 VLLM_ENABLED=true 并配置 VLLM_QUANTIZATION=awq",
            auto_detect=False,
        )
    quant = settings.VLLM_QUANTIZATION
    return CheckResult(
        check_id="T-009",
        name="vLLM GPU 量化",
        standard="SubTask13.1",
        category="技术要求",
        severity="medium",
        status="pass" if quant else "warn",
        description="vLLM 启用时应配置量化（awq/gptq/int8）以降低显存占用",
        evidence=f"VLLM_QUANTIZATION={quant or 'none'}",
        remediation="在 .env 中设置 VLLM_QUANTIZATION=awq 或 gptq",
    )


# 人工确认项（管理要求）
def _check_security_policy() -> CheckResult:
    """安全策略文档（人工确认）。"""
    return CheckResult(
        check_id="M-001",
        name="信息安全策略文档",
        standard="等保三级 7.1 / ISO 27001 A.5.1",
        category="管理要求",
        severity="high",
        status="manual",
        description="应制定并发布信息安全策略文档，覆盖安全目标/范围/责任",
        evidence="需人工确认",
        remediation="编写《SynthDraft 信息安全策略》文档，由管理层签发",
        auto_detect=False,
    )


def _check_asset_management() -> CheckResult:
    """资产管理（人工确认）。"""
    return CheckResult(
        check_id="M-002",
        name="资产清单与责任",
        standard="等保三级 7.2 / ISO 27001 A.5.9",
        category="管理要求",
        severity="medium",
        status="manual",
        description="应维护信息资产清单，明确所有者与责任人",
        evidence="需人工确认",
        remediation="建立资产清单表格，标注每项资产（服务器/模型/数据）的负责人",
        auto_detect=False,
    )


def _check_physical_security() -> CheckResult:
    """物理环境安全（人工确认）。"""
    return CheckResult(
        check_id="M-003",
        name="物理环境安全",
        standard="等保三级 8.1 / ISO 27001 A.7.1",
        category="管理要求",
        severity="medium",
        status="manual",
        description="服务器应部署在具备门禁/消防/温湿度控制的机房",
        evidence="需人工确认",
        remediation="确认部署机房符合 GB/T 9361 B 类以上要求",
        auto_detect=False,
    )


def _check_personnel_security() -> CheckResult:
    """人员安全（人工确认）。"""
    return CheckResult(
        check_id="M-004",
        name="人员安全管控",
        standard="等保三级 7.4 / ISO 27001 A.6.1",
        category="管理要求",
        severity="medium",
        status="manual",
        description="关键岗位人员应签署保密协议，定期开展安全培训",
        evidence="需人工确认",
        remediation="建立人员安全管控流程（入职保密协议 + 年度培训）",
        auto_detect=False,
    )


# 检查项注册表
AUTO_CHECKS: list[Callable[[], CheckResult]] = [
    _check_jwt_secret,
    _check_token_expiry,
    _check_cors,
    _check_offline_mode,
    _check_commercial_api_desensitize,
    _check_audit_log,
    _check_sandbox_static_scan,
    _check_password_hash,
    _check_vllm_quantization,
]

MANUAL_CHECKS: list[Callable[[], CheckResult]] = [
    _check_security_policy,
    _check_asset_management,
    _check_physical_security,
    _check_personnel_security,
]


def run_compliance_check(*, include_manual: bool = True) -> ComplianceReport:
    """运行合规自评。

    Args:
        include_manual: 是否包含人工确认项（True 时一并返回 manual 状态项）

    Returns:
        ComplianceReport
    """
    report = ComplianceReport(timestamp=datetime.now(timezone.utc).isoformat())
    for check_fn in AUTO_CHECKS:
        try:
            r = check_fn()
        except Exception as e:  # noqa: BLE001
            r = CheckResult(
                check_id="ERROR",
                name=check_fn.__name__,
                standard="",
                category="技术要求",
                severity="high",
                status="fail",
                description=f"检查项执行异常: {e}",
                evidence="",
                remediation="",
            )
        report.results.append(r)

    if include_manual:
        for check_fn in MANUAL_CHECKS:
            r = check_fn()
            report.results.append(r)

    # 统计
    report.total = len(report.results)
    report.passed = sum(1 for r in report.results if r.status == "pass")
    report.failed = sum(1 for r in report.results if r.status == "fail")
    report.warned = sum(1 for r in report.results if r.status == "warn")
    report.manual = sum(1 for r in report.results if r.status == "manual")

    # 评分：pass=1, warn=0.5, manual=0.5, fail=0
    if report.total > 0:
        score = sum(
            1.0 if r.status == "pass"
            else 0.5 if r.status in {"warn", "manual"}
            else 0.0
            for r in report.results
        )
        report.overall_score = score / report.total * 100.0

    return report


def self_test() -> dict[str, Any]:
    """self_test：验证合规检查器返回完整检查项。"""
    report = run_compliance_check(include_manual=True)
    expected_ids = {
        "T-001", "T-002", "T-003", "T-004", "T-005", "T-006", "T-007", "T-008", "T-009",
        "M-001", "M-002", "M-003", "M-004",
    }
    actual_ids = {r.check_id for r in report.results}
    return {
        "total": report.total,
        "passed": report.passed,
        "failed": report.failed,
        "warned": report.warned,
        "manual": report.manual,
        "overall_score": round(report.overall_score, 2),
        "expected_ids_count": len(expected_ids),
        "actual_ids_count": len(actual_ids),
        "all_ids_present": expected_ids.issubset(actual_ids),
        "ok": (
            report.total >= 13
            and expected_ids.issubset(actual_ids)
            and 0 <= report.overall_score <= 100
        ),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(run_compliance_check().to_dict(), indent=2, ensure_ascii=False, default=str))
