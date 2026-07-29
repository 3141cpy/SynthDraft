# 验证与修整 Task 13 私有化部署完善 Spec

## Why
Task 13（私有化部署完善）的四个 SubTask 实现已落地（vLLM Provider、离线安装包、商业 API 脱敏、合规加固+审计日志），但尚未执行端到端自测以确认所有代码路径真实可用。运行 `backend/tests/verify_task13.py` 首轮实测发现 90/91 PASS、1 FAIL，需要修复失败项并完成第二轮回归，确保 Task 13 真正交付可用。

## What Changes
- 修复 `backend/tests/verify_task13.py` 中 SubTask 13.2 测试用例的 `importlib` 动态加载逻辑：在 `spec.loader.exec_module(build_module)` 之前将 `build_module` 注册到 `sys.modules`，解决 Python 3.13 下 `@dataclass` 装饰器通过 `sys.modules.get(cls.__module__).__dict__` 查找命名空间时返回 None 导致的 `AttributeError`。
- 不修改 `infra/offline_install/build_offline_package.py`（脚本本身逻辑正确，直接 `python build_offline_package.py --dry-run` 可正常运行；问题仅出在测试用例的动态加载方式）。
- 修复后重新运行 `verify_task13.py`，确认 91/91 PASS（环境限制项不计入失败）。
- 直接执行 `python infra/offline_install/build_offline_package.py --dry-run` 真实验证打包脚本可用（脱离 importlib 路径）。

## Impact
- Affected specs: 无（本 spec 仅覆盖 Task 13 已实现代码的验证与单点修复）
- Affected code:
  - `d:\SynthDraft\backend\tests\verify_task13.py`（仅修改 `test_offline_package` 函数中的模块加载片段，约 2 行新增）
- 不影响其他 Task，不修改生产代码

## ADDED Requirements

### Requirement: 离线打包脚本动态加载兼容 Python 3.13
测试用例通过 `importlib.util.spec_from_file_location` 动态加载 `build_offline_package.py` 时，必须在 `exec_module` 之前将模块注册到 `sys.modules`，以兼容 Python 3.13+ 中 `@dataclass` 装饰器对模块命名空间的查找行为。

#### Scenario: 测试用例动态加载打包脚本成功
- **WHEN** `verify_task13.py` 的 `test_offline_package` 通过 importlib 加载 `build_offline_package.py`
- **THEN** 加载过程不抛出 `AttributeError: 'NoneType' object has no attribute '__dict__'`
- **AND** `build_module.build_package` 可正常调用并返回 `PackageManifest` 实例

### Requirement: verify_task13.py 全量回归通过
修复后重新运行 `verify_task13.py`，所有非环境限制检查必须通过。

#### Scenario: 全量回归
- **WHEN** 执行 `.venv\Scripts\python.exe tests\verify_task13.py`
- **THEN** 退出码为 0
- **AND** 通过数 / 总数 = 91/91（环境限制项不计入失败）
- **AND** 失败明细为空

### Requirement: 打包脚本直接执行可用
脱离 importlib 路径，直接通过 `python build_offline_package.py --dry-run` 执行打包脚本，验证脚本本身真实可用。

#### Scenario: 直接执行 dry-run
- **WHEN** 执行 `python infra/offline_install/build_offline_package.py --dry-run`
- **THEN** 退出码为 0
- **AND** 输出含 "DRY-RUN" 标识
- **AND** 输出含 "预计总大小: X.XX GB"

## MODIFIED Requirements
（无）

## REMOVED Requirements
（无）
