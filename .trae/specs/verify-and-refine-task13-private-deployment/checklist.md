# Checklist

## SubTask 13.2 动态加载修复

- [ ] `backend/tests/verify_task13.py` 的 `test_offline_package` 函数中，在 `spec.loader.exec_module(build_module)` 之前存在 `sys.modules["build_offline_package"] = build_module` 注册语句
- [ ] 修复后运行 `verify_task13.py`，`test_offline_package` 中"打包脚本导入成功"检查项 PASS（不再出现 `'NoneType' object has no attribute '__dict__'` 错误）
- [ ] 修复后 `test_offline_package` 中 dry-run 执行检查项全部 PASS（dry_run 标志正确、HF 模型清单非空、Ollama 模型清单非空、预期大小 > 0、include_images=False 时无 Docker 镜像清单、include_images=True 时含 Docker 镜像清单）
- [ ] `test_offline_package` 中 OFFLINE_MODE / is_offline / README_OFFLINE.md 检查项 PASS

## 打包脚本直接执行验证

- [ ] 执行 `python infra/offline_install/build_offline_package.py --dry-run` 退出码为 0
- [ ] 输出含 "DRY-RUN" 标识
- [ ] 输出含 "预计总大小: X.XX GB" 且数值 > 0
- [ ] 输出含 5 个收集阶段标题（[1/5] Python wheels / [2/5] HuggingFace 模型 / [3/5] Ollama 模型 / [4/5] 规范库 / [5/5] 后端代码归档）
- [ ] 输出记录已写入 `tmp_audit_logs/35_task13_offline_script_direct.md`

## 全量回归验证

- [ ] 执行 `verify_task13.py` 退出码为 0
- [ ] 通过数 = 91、失败数 = 0
- [ ] 环境限制数 = 1（vLLM GPU 限制，符合预期，非失败）
- [ ] 失败明细为空
- [ ] SubTask 13.1（vLLM Provider）所有检查项 PASS
- [ ] SubTask 13.2（离线安装包）所有检查项 PASS
- [ ] SubTask 13.3（脱敏工具）所有检查项 PASS
- [ ] SubTask 13.4（合规检查+审计日志）所有检查项 PASS
- [ ] 第二轮回归输出已记录到 `tmp_audit_logs/36_task13_verify_regression.md`

## 八荣八耻原则自评

- [ ] 以复用现有为荣：仅修改测试用例 1 行，未改动生产代码 `build_offline_package.py`
- [ ] 以瞎猜接口为耻：已通过直接执行脚本 + 重复 importlib 加载确认根因（Python 3.13 dataclass + importlib 交互问题）
- [ ] 以覆盖测试为荣：修复后全量回归 91/91 PASS，并补充直接执行脚本的真实验证
- [ ] 以实事求是为荣：vLLM GPU 环境限制如实标注，未假装通过
- [ ] 以最小修改为荣：仅 1 行新增，不破坏现有稳定代码
