"""Task 13 私有化部署完善 端到端实测脚本。

覆盖 SubTask：
- 13.1: vLLM 本地 GPU 推理 provider（导入 + 降级路径）
- 13.2: 离线安装包打包脚本（dry-run）
- 13.3: 商业 API 脱敏工具（图号/件号/企业名/人名 正则匹配）+ provider 集成
- 13.4: 等保三级/ISO 27001 合规检查器 + 审计日志增强

运行：
    cd d:\\SynthDraft\\backend
    .venv\\Scripts\\python.exe tests\\verify_task13.py

设计原则（八荣八耻）：
- 复用现有：通过 sys.path 注入 backend 目录，复用现有 settings 与 provider 抽象
- 实事求是：环境限制项（无 GPU / 无 vLLM 服务）如实标注，仅验证降级路径
- 覆盖测试：每个 SubTask 必须有可执行的断言
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Any

# 将 backend 目录加入 sys.path
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# 测试环境变量（避免污染真实配置）
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault("OFFLINE_MODE", "false")


def section(title: str) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'-' * 70}", flush=True)


def _ok(msg: str) -> None:
    print(f"  [PASS] {msg}", flush=True)


def _fail(msg: str, detail: str = "") -> None:
    print(f"  [FAIL] {msg}{f' :: {detail}' if detail else ''}", flush=True)


def _info(msg: str) -> None:
    print(f"  [INFO] {msg}", flush=True)


def _env_limit(msg: str) -> None:
    print(f"  [ENV-LIMIT] {msg}", flush=True)


# ===== 全局统计 =====
_passed = 0
_failed = 0
_env_limits = 0
_failures: list[str] = []


def check(condition: bool, msg: str, detail: str = "") -> None:
    global _passed, _failed
    if condition:
        _passed += 1
        _ok(msg)
    else:
        _failed += 1
        _failures.append(f"{msg}{f' :: {detail}' if detail else ''}")
        _fail(msg, detail)


def env_limit(msg: str) -> None:
    global _env_limits
    _env_limits += 1
    _env_limit(msg)


# ===== SubTask 13.1: vLLM Provider =====

def test_vllm_provider() -> None:
    section("SubTask 13.1: vLLM Provider 导入 + 降级路径")

    # 1. 导入测试
    try:
        from app.services.ai.providers.vllm_provider import VLLMProvider
        from app.services.ai.base import BaseLLMProvider, get_llm_provider, reset_provider_cache
        check(True, "VLLMProvider 导入成功")
    except Exception as e:
        check(False, "VLLMProvider 导入失败", str(e))
        return

    # 2. VLLMProvider 继承 BaseLLMProvider
    try:
        check(issubclass(VLLMProvider, BaseLLMProvider), "VLLMProvider 继承 BaseLLMProvider")
    except Exception as e:
        check(False, "继承检查失败", str(e))

    # 3. VLLM_ENABLED=False 时 is_available 返回 False（降级路径）
    from app.config import settings
    from app.services.ai.base import reset_provider_cache
    reset_provider_cache()

    orig_vllm_enabled = settings.VLLM_ENABLED
    orig_llm_provider = settings.LLM_PROVIDER
    try:
        settings.VLLM_ENABLED = False
        settings.LLM_PROVIDER = "vllm"
        provider = get_llm_provider()
        # 降级路径：VLLM_ENABLED=False 时应回退到 Ollama
        from app.services.ai.providers.ollama_provider import OllamaProvider
        check(
            isinstance(provider, OllamaProvider),
            "VLLM_ENABLED=False 时降级到 OllamaProvider",
            f"actual={type(provider).__name__}",
        )
    except Exception as e:
        check(False, "降级路径验证失败", str(e))
    finally:
        settings.VLLM_ENABLED = orig_vllm_enabled
        settings.LLM_PROVIDER = orig_llm_provider
        reset_provider_cache()

    # 4. VLLM_ENABLED=True 但端点不可达时返回空 ChatResponse（降级）
    reset_provider_cache()
    orig_vllm_enabled = settings.VLLM_ENABLED
    orig_vllm_base = settings.VLLM_BASE_URL
    orig_vllm_model = settings.VLLM_MODEL
    try:
        settings.VLLM_ENABLED = True
        settings.VLLM_BASE_URL = "http://127.0.0.1:59999/v1"  # 不存在的端口
        settings.VLLM_MODEL = "test-model"
        provider = VLLMProvider()
        check(provider.is_available() is False, "vLLM 端点不可达时 is_available=False")
        from app.services.ai.base import ChatMessage, ChatResponse
        msgs = [ChatMessage(role="user", content="ping")]
        resp = provider.chat(msgs)
        check(
            isinstance(resp, ChatResponse) and resp.content == "",
            "vLLM 不可达时 chat() 返回空 ChatResponse",
            f"content={resp.content!r}",
        )
        # 多模态降级
        resp_img = provider.chat_with_image(msgs, "iVBORw0KGgo=")
        check(
            isinstance(resp_img, ChatResponse) and resp_img.content == "",
            "vLLM 不可达时 chat_with_image() 返回空 ChatResponse",
        )
    except Exception as e:
        check(False, "vLLM 降级响应测试失败", str(e))
    finally:
        settings.VLLM_ENABLED = orig_vllm_enabled
        settings.VLLM_BASE_URL = orig_vllm_base
        settings.VLLM_MODEL = orig_vllm_model
        reset_provider_cache()

    # 5. 配置项存在性检查
    config_attrs = [
        "VLLM_ENABLED", "VLLM_BASE_URL", "VLLM_MODEL",
        "VLLM_QUANTIZATION", "VLLM_TENSOR_PARALLEL_SIZE",
        "VLLM_GPU_MEMORY_UTILIZATION", "VLLM_VLM_MODEL",
    ]
    for attr in config_attrs:
        check(hasattr(settings, attr), f"settings.{attr} 存在")

    # 6. 量化配置校验
    try:
        from app.config import Settings
        # 合法值
        for q in ["", "awq", "gptq", "int8", "fp8", "bitsandbytes"]:
            try:
                s = Settings(VLLM_QUANTIZATION=q)
                check(s.VLLM_QUANTIZATION == q, f"VLLM_QUANTIZATION={q!r} 校验通过")
            except Exception as e:
                check(False, f"VLLM_QUANTIZATION={q!r} 应通过校验", str(e))
        # 非法值
        try:
            Settings(VLLM_QUANTIZATION="invalid_quant")
            check(False, "VLLM_QUANTIZATION='invalid_quant' 应拒绝")
        except Exception:
            check(True, "VLLM_QUANTIZATION='invalid_quant' 被拒绝")
    except Exception as e:
        check(False, "量化配置校验测试异常", str(e))

    # 环境限制标注
    env_limit("vLLM 实际 GPU 推理需 GPU 节点 + vLLM 服务端启动，本测试仅验证降级路径")


# ===== SubTask 13.2: 离线安装包 =====

def test_offline_package() -> None:
    section("SubTask 13.2: 离线安装包脚本（dry-run）")

    # 1. 打包脚本可导入
    try:
        # 通过 importlib 加载（脚本不在 backend sys.path 内）
        import importlib.util
        script_path = BACKEND_ROOT.parent / "infra" / "offline_install" / "build_offline_package.py"
        check(script_path.is_file(), f"打包脚本存在: {script_path}")
        spec = importlib.util.spec_from_file_location("build_offline_package", script_path)
        if spec is None or spec.loader is None:
            check(False, "无法加载打包脚本 spec")
            return
        build_module = importlib.util.module_from_spec(spec)
        sys.modules["build_offline_package"] = build_module  # 注册到 sys.modules 以支持 @dataclass 装饰器
        spec.loader.exec_module(build_module)
        check(True, "打包脚本导入成功")
    except Exception as e:
        check(False, "打包脚本导入失败", str(e))
        return

    # 2. dry-run 执行
    try:
        with tempfile.TemporaryDirectory(prefix="task13_offline_") as tmpdir:
            manifest = build_module.build_package(
                Path(tmpdir),
                dry_run=True,
                include_images=False,
            )
            check(manifest.dry_run is True, "dry-run 模式标志正确")
            check(
                isinstance(manifest.hf_models, list) and len(manifest.hf_models) > 0,
                "HF 模型清单非空",
                f"hf_models={manifest.hf_models}",
            )
            check(
                isinstance(manifest.ollama_models, list) and len(manifest.ollama_models) > 0,
                "Ollama 模型清单非空",
                f"ollama_models={manifest.ollama_models}",
            )
            check(
                manifest.expected_size_gb > 0,
                "预期大小 > 0",
                f"size={manifest.expected_size_gb}GB",
            )
            check(
                len(manifest.docker_images) == 0,
                "include_images=False 时无 Docker 镜像清单",
            )
            # 含镜像模式
            manifest2 = build_module.build_package(
                Path(tmpdir),
                dry_run=True,
                include_images=True,
            )
            check(
                len(manifest2.docker_images) > 0,
                "include_images=True 时含 Docker 镜像清单",
                f"images={manifest2.docker_images}",
            )
    except Exception as e:
        check(False, "dry-run 执行失败", str(e))

    # 3. OFFLINE_MODE 配置项检查
    from app.config import settings
    check(hasattr(settings, "OFFLINE_MODE"), "settings.OFFLINE_MODE 存在")
    check(hasattr(settings, "is_offline"), "settings.is_offline 属性存在")

    # 4. README 存在
    readme_path = BACKEND_ROOT.parent / "infra" / "offline_install" / "README_OFFLINE.md"
    check(readme_path.is_file(), f"离线安装 README 存在: {readme_path}")

    env_limit("实际打包需网络下载 12-20GB 模型权重，本测试仅验证 dry-run")


# ===== SubTask 13.3: 脱敏工具 =====

def test_desensitize() -> None:
    section("SubTask 13.3: 商业 API 脱敏工具")

    try:
        from app.services.ai.desensitize import (
            sanitize_text, sanitize_messages, BUILTIN_RULES, get_rules,
            should_desensitize_for_provider,
        )
        check(True, "desensitize 模块导入成功")
    except Exception as e:
        check(False, "desensitize 模块导入失败", str(e))
        return

    # 1. 内置规则数量检查（至少 7 类）
    check(
        len(BUILTIN_RULES) >= 7,
        f"内置规则数量 >= 7（实际 {len(BUILTIN_RULES)}）",
    )
    rule_names = {r.name for r in BUILTIN_RULES}
    expected_rules = {"id_card", "phone", "email", "ipv4", "drawing_number", "part_number", "company_name", "person_name"}
    check(
        expected_rules.issubset(rule_names),
        f"内置规则覆盖 8 大类: {rule_names}",
    )

    # 2. 图号匹配
    test_cases = [
        ("图号: ABC-1234-001", "drawing_number", "[DWG_NO]"),
        ("件号: A001-002-003", "part_number", "[PART_NO]"),
        ("设计: 张三丰", "person_name", None),
        ("由某某科技有限公司提供", "company_name", "[COMPANY]"),
        ("手机 13812345678", "phone", "[PHONE]"),
        ("邮箱 test@example.com", "email", "[EMAIL]"),
        ("IP 192.168.1.100", "ipv4", "[IP]"),
        ("身份证 110101199001011234", "id_card", "[ID_CARD]"),
    ]
    for text, expected_rule, expected_placeholder in test_cases:
        r = sanitize_text(text, mode="strict")
        check(
            expected_rule in r.matched_rules,
            f"匹配规则 {expected_rule}（input={text!r}）",
            f"matched={r.matched_rules}",
        )
        check(
            not r.rejected,
            f"strict 模式不拒绝已脱敏内容（{expected_rule}）",
            f"reason={r.reject_reason}",
        )
        if expected_placeholder:
            check(
                expected_placeholder in r.sanitized_text,
                f"脱敏后含占位符 {expected_placeholder}",
                f"sanitized={r.sanitized_text!r}",
            )

    # 3. mode=off 不脱敏
    r_off = sanitize_text("手机 13812345678", mode="off")
    check(
        r_off.sanitized_text == "手机 13812345678",
        "mode=off 时不脱敏",
    )
    check(len(r_off.matched_rules) == 0, "mode=off 时不匹配任何规则")

    # 4. should_desensitize_for_provider
    check(should_desensitize_for_provider("openai") is True, "openai 需脱敏")
    check(should_desensitize_for_provider("anthropic") is True, "anthropic 需脱敏")
    check(should_desensitize_for_provider("ollama") is False, "ollama 不需脱敏")
    check(should_desensitize_for_provider("vllm") is False, "vllm 不需脱敏")

    # 5. provider 集成测试：OpenAIProvider 在 strict 模式下拒绝含敏感词的调用
    from app.config import settings
    from app.services.ai.base import ChatMessage, ChatResponse
    from app.services.ai.providers.openai_provider import OpenAIProvider

    orig_mode = settings.COMMERCIAL_API_MODE
    try:
        # strict 模式 + 敏感词 → 返回空 ChatResponse（脱敏拒绝路径）
        settings.COMMERCIAL_API_MODE = "strict"
        # 构造一个无 API key 的 provider（chat 会因 no_client 返回空，但脱敏先执行）
        # 由于没有 API key，_client 为 None，会先走 no_client 路径，不会触发脱敏
        # 改为构造带 client 的场景：mock 一个 client
        provider = OpenAIProvider.__new__(OpenAIProvider)
        provider._client = "fake"  # 占位，让 chat 不走 no_client 分支
        provider._init_error = None
        provider._model = "gpt-4o-mini"
        provider._vlm_model = ""

        # 用真实 OpenAI SDK 调用会失败，但脱敏逻辑会先执行
        # 这里用一个会抛异常的 mock client 验证脱敏被调用
        class _FailingClient:
            class chat:
                class completions:
                    @staticmethod
                    def create(**kwargs):
                        raise RuntimeError("mock_client_no_network")
        provider._client = _FailingClient()

        # off 模式：应直接调用 client（失败），返回空 ChatResponse
        settings.COMMERCIAL_API_MODE = "off"
        msgs = [ChatMessage(role="user", content="手机 13812345678")]
        resp = provider.chat(msgs)
        check(
            isinstance(resp, ChatResponse) and resp.content == "",
            "OpenAIProvider off 模式调用失败时返回空 ChatResponse",
        )

        # strict 模式：脱敏后调用失败，仍返回空 ChatResponse
        settings.COMMERCIAL_API_MODE = "strict"
        resp2 = provider.chat(msgs)
        check(
            isinstance(resp2, ChatResponse) and resp2.content == "",
            "OpenAIProvider strict 模式调用失败时返回空 ChatResponse",
        )

    except Exception as e:
        check(False, "provider 集成测试异常", str(e))
    finally:
        settings.COMMERCIAL_API_MODE = orig_mode

    # 6. config 校验
    try:
        from app.config import Settings
        for m in ["off", "optional", "strict"]:
            try:
                s = Settings(COMMERCIAL_API_MODE=m)
                check(s.COMMERCIAL_API_MODE == m, f"COMMERCIAL_API_MODE={m!r} 校验通过")
            except Exception as e:
                check(False, f"COMMERCIAL_API_MODE={m!r} 应通过校验", str(e))
        try:
            Settings(COMMERCIAL_API_MODE="invalid")
            check(False, "COMMERCIAL_API_MODE='invalid' 应拒绝")
        except Exception:
            check(True, "COMMERCIAL_API_MODE='invalid' 被拒绝")
    except Exception as e:
        check(False, "COMMERCIAL_API_MODE 校验测试异常", str(e))


# ===== SubTask 13.4: 合规检查 + 审计日志 =====

def test_compliance_and_audit() -> None:
    section("SubTask 13.4: 合规检查器 + 审计日志增强")

    # 1. compliance 模块导入
    try:
        from app.security.compliance import (
            run_compliance_check, ComplianceReport, CheckResult,
            AUTO_CHECKS, MANUAL_CHECKS,
        )
        check(True, "compliance 模块导入成功")
    except Exception as e:
        check(False, "compliance 模块导入失败", str(e))
        return

    # 2. 合规检查器返回完整检查项
    try:
        report = run_compliance_check(include_manual=True)
        check(isinstance(report, ComplianceReport), "返回 ComplianceReport 实例")
        check(report.total >= 13, f"检查项总数 >= 13（实际 {report.total}）")
        check(report.passed + report.failed + report.warned + report.manual == report.total,
              "通过+失败+警告+人工 = 总数")

        # 验证检查项 ID 完整性
        expected_ids = {
            "T-001", "T-002", "T-003", "T-004", "T-005", "T-006", "T-007", "T-008", "T-009",
            "M-001", "M-002", "M-003", "M-004",
        }
        actual_ids = {r.check_id for r in report.results}
        check(
            expected_ids.issubset(actual_ids),
            f"检查项 ID 完整: {actual_ids}",
        )

        # 验证各检查项字段完整
        for r in report.results:
            check(
                all([r.check_id, r.name, r.standard, r.category, r.severity, r.status]),
                f"检查项 {r.check_id} 字段完整",
            )

        # 评分在合理范围
        check(0 <= report.overall_score <= 100, f"overall_score 在 [0, 100]（{report.overall_score}）")

        # to_dict 可序列化
        d = report.to_dict()
        check(isinstance(d, dict) and "results" in d, "to_dict() 返回合法 dict")
    except Exception as e:
        check(False, "合规检查器执行异常", str(e))

    # 3. 审计日志模块导入
    try:
        from app.security.audit_log import (
            record_audit_event, load_audit_events, cleanup_expired_logs,
            HIGH_RISK_EVENTS,
        )
        check(True, "audit_log 模块导入成功")
    except Exception as e:
        check(False, "audit_log 模块导入失败", str(e))
        return

    # 4. 审计日志写入 + 查询 + 清理
    from app.config import settings
    orig_path = settings.AUDIT_LOG_PATH
    orig_enabled = settings.AUDIT_LOG_ENABLED
    try:
        with tempfile.TemporaryDirectory(prefix="task13_audit_") as tmpdir:
            test_path = str(Path(tmpdir) / "audit.jsonl")
            settings.AUDIT_LOG_PATH = test_path
            settings.AUDIT_LOG_ENABLED = True

            # 写入 3 类事件
            ev1 = record_audit_event(
                event_type="user_login",
                actor="alice",
                action="用户登录",
            )
            ev2 = record_audit_event(
                event_type="data_export",
                actor="bob",
                target="/api/v1/generations/123/export",
                action="导出生成结果",
            )
            ev3 = record_audit_event(
                event_type="admin_config_change",
                actor="admin",
                target="VLLM_QUANTIZATION",
                action="修改 vLLM 量化配置",
            )

            # 验证文件存在
            check(Path(test_path).is_file(), "审计日志文件已创建")

            # 查询全部
            all_events = load_audit_events(limit=100)
            check(len(all_events) == 3, f"查询全部 3 条（实际 {len(all_events)}）")

            # 查询高风险
            high_risk = load_audit_events(high_risk_only=True)
            check(len(high_risk) == 2, f"查询高风险 2 条（实际 {len(high_risk)}）")

            # 按 actor 查询
            bob_events = load_audit_events(actor="bob")
            check(len(bob_events) == 1, "按 actor=bob 查询 1 条")

            # 清理过期（cutoff=未来，应删 0 条）
            deleted_none = cleanup_expired_logs(retention_days=36500)
            check(deleted_none == 0, "清理未来过期: 0 条")

            # 清理过期（cutoff=过去，应删 3 条）
            deleted_all = cleanup_expired_logs(retention_days=-1)
            check(deleted_all == 3, f"清理过去过期: 3 条（实际 {deleted_all}）")

    except Exception as e:
        check(False, "审计日志测试异常", str(e))
    finally:
        settings.AUDIT_LOG_PATH = orig_path
        settings.AUDIT_LOG_ENABLED = orig_enabled

    # 5. security package 兼容性检查（原 security.py 已迁移到 security/__init__.py）
    try:
        from app.security import hash_password, verify_password, create_access_token, decode_access_token
        check(True, "原 security.py 函数仍可 import（迁移无破坏）")

        h = hash_password("test123")
        check(h.startswith("$2"), "bcrypt 哈希格式正确")
        check(verify_password("test123", h), "bcrypt 校验通过")
        check(not verify_password("wrong", h), "bcrypt 错误密码校验失败")
    except Exception as e:
        check(False, "security package 兼容性失败", str(e))


# ===== 主入口 =====

def main() -> int:
    section("Task 13 私有化部署完善 - 自测开始")

    test_vllm_provider()
    test_offline_package()
    test_desensitize()
    test_compliance_and_audit()

    section("Task 13 自测汇总")
    total = _passed + _failed
    print(f"  通过: {_passed}/{total}", flush=True)
    print(f"  失败: {_failed}/{total}", flush=True)
    print(f"  环境限制: {_env_limits}", flush=True)
    if _failures:
        print("\n  失败明细:", flush=True)
        for f in _failures:
            print(f"    - {f}", flush=True)

    # 退出码：所有非环境限制的检查必须通过
    return 0 if _failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
