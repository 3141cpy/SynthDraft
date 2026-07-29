"""智能生成模块（Task 5）。

自然语言 → CadQuery 代码 → 沙箱执行 → STEP/STL 输出 → 几何校验。

公共接口聚合：调用方优先从此包导入，避免直接依赖具体子模块。

子模块：
- prompts:           LLM Prompt 模板（SubTask 5.1）
- code_generator:    LLM 生成 CadQuery 代码 + 多轮修改（SubTask 5.2 / 5.6）
- templates:         模板匹配降级路径（SubTask 5.2 降级）
- sandbox:           静态扫描 + subprocess 沙箱执行（SubTask 5.2 / 5.4）
- geometry_validator: STEP 几何校验（SubTask 5.3）
"""

from app.services.generation.code_generator import (
    apply_multi_turn_edit,
    generate_cadquery_code,
    is_llm_available,
    template_match_generate,
)
from app.services.generation.geometry_validator import validate_step_file
from app.services.generation.sandbox import (
    STATIC_VIOLATIONS,
    execute_cadquery_code,
    static_scan_code,
)

__all__ = [
    # 代码生成
    "generate_cadquery_code",
    "apply_multi_turn_edit",
    "is_llm_available",
    "template_match_generate",
    # 沙箱
    "execute_cadquery_code",
    "static_scan_code",
    "STATIC_VIOLATIONS",
    # 几何校验
    "validate_step_file",
]
