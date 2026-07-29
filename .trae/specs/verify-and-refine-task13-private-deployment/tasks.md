# Tasks

## 阶段一: 修复 verify_task13.py 动态加载失败

- [ ] Task 1: 修复 verify_task13.py 中 test_offline_package 的 importlib 动态加载逻辑
  - 依赖: 无（独立）
  - SubTask 1.1: 定位 `backend/tests/verify_task13.py` 中 `test_offline_package` 函数的模块加载片段
    - 当前代码（约 199-211 行）：
      ```
      spec = importlib.util.spec_from_file_location("build_offline_package", script_path)
      if spec is None or spec.loader is None:
          check(False, "无法加载打包脚本 spec")
          return
      build_module = importlib.util.module_from_spec(spec)
      spec.loader.exec_module(build_module)
      ```
    - 问题：Python 3.13+ 下 `@dataclass` 装饰器通过 `sys.modules.get(cls.__module__).__dict__` 查找模块命名空间，未注册到 `sys.modules` 时返回 None 导致 `AttributeError: 'NoneType' object has no attribute '__dict__'`
  - SubTask 1.2: 在 `module_from_spec` 与 `exec_module` 之间插入一行 `sys.modules["build_offline_package"] = build_module`
    - 这是 Python 官方文档推荐的动态加载模式（参考 importlib.util.module_from_spec 文档）
    - 仅新增 1 行，不改动其他逻辑
  - SubTask 1.3: 保留原有 try/except 与错误处理，不扩大修改范围
  - 验证标准: 修改后 `test_offline_package` 函数中"打包脚本导入成功"检查项 PASS

## 阶段二: 真实执行打包脚本

- [ ] Task 2: 直接执行 build_offline_package.py --dry-run 真实验证
  - 依赖: 无（独立，可与 Task 1 并行）
  - SubTask 2.1: 在项目根目录执行 `.venv\Scripts\python.exe infra\offline_install\build_offline_package.py --dry-run`
  - SubTask 2.2: 验证退出码为 0
  - SubTask 2.3: 验证输出含 "DRY-RUN" 标识与 "预计总大小: X.XX GB"
  - SubTask 2.4: 验证输出含 5 个收集阶段（Python wheels / HF 模型 / Ollama 模型 / 规范库 / 后端代码归档）
  - SubTask 2.5: 记录输出到 `tmp_audit_logs/35_task13_offline_script_direct.md`（若 tmp_audit_logs 目录不存在则创建）
  - 验证标准: 必须真实执行脚本（非 mock），输出完整且退出码 0

## 阶段三: 全量回归

- [ ] Task 3: 重新运行 verify_task13.py 全量回归
  - 依赖: Task 1 完成（Task 2 可并行）
  - SubTask 3.1: 执行 `.venv\Scripts\python.exe tests\verify_task13.py`
  - SubTask 3.2: 验证退出码为 0
  - SubTask 3.3: 验证通过数 = 91、失败数 = 0、环境限制数 = 1（vLLM GPU 限制，符合预期）
  - SubTask 3.4: 验证失败明细为空
  - SubTask 3.5: 记录第二轮回归输出到 `tmp_audit_logs/36_task13_verify_regression.md`
  - 验证标准: 91/91 PASS（环境限制不计入失败），退出码 0

## Task Dependencies
- Task 1 独立（可并行）
- Task 2 独立（可并行）
- Task 3 依赖 Task 1 完成

## 并行执行建议
Task 1 与 Task 2 可并行启动 2 个 sub-agent：
- Sub-Agent A: Task 1（修复 verify_task13.py）
- Sub-Agent B: Task 2（直接执行打包脚本 dry-run）
Task 3 必须在 Task 1 完成后串行执行。
