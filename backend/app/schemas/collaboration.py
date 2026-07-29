"""协同闭环 schema（Task 11）。

定义"审图→生成→复审"协同闭环的数据结构：
- OptimizeFromReviewRequest：基于审图缺陷优化图纸的请求
- CollaborativeWorkflowResult：协同闭环工作流结果
- DefectDiffItem：单条缺陷的对比结果
- DiffReport：修订前后对比报告
- FeedbackRecord：用户反馈记录

设计原则：
- 复用现有 ReviewResult / GenerationResult schema
- 不引入数据库表（P0 阶段使用文件系统 + Celery result backend）
- 缺陷对比基于 category + standard_ref + suggestion 模糊匹配
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.review_detail import DefectItem, Severity, DefectCategory


# ===== SubTask 11.1：基于缺陷优化图纸 =====


class OptimizeFromReviewRequest(BaseModel):
    """基于审图缺陷优化图纸的请求。

    用户在拿到审图结果后，可基于缺陷列表自动生成修订版图纸。
    """

    review_task_id: str = Field(..., description="原审图任务 ID（Celery task_id）")
    user_id: str = Field(default="anonymous", description="提交用户 ID")
    output_format: Literal["dxf", "step", "stl", "iges"] = Field(
        default="dxf",
        description="期望输出格式（默认 DXF，便于复审闭环）",
    )
    auto_re_review: bool = Field(
        default=True,
        description="是否自动触发修订后复审（SubTask 11.2）",
    )


class CollaborativeWorkflowResult(BaseModel):
    """协同闭环工作流结果。

    记录一次"审图→生成→复审"完整闭环的所有关联任务 ID。
    """

    original_review_task_id: str = Field(..., description="原审图任务 ID")
    generation_task_id: str = Field(..., description="生成任务 ID")
    new_review_task_id: str | None = Field(
        default=None,
        description="修订后审图任务 ID（auto_re_review=False 时为 None）",
    )
    status: Literal["dispatched", "partial", "failed"] = Field(
        default="dispatched",
        description="闭环状态：dispatched=全部派发；partial=部分派发；failed=派发失败",
    )
    defects_count: int = Field(default=0, description="原审图缺陷数量")
    optimized_prompt: str = Field(
        default="", description="基于缺陷生成的 LLM prompt（截断前 500 字符）"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="附加元信息"
    )


# ===== SubTask 11.3：修订前后对比报告 =====


# 缺陷闭环状态
DiffStatus = Literal["resolved", "unresolved", "new"]


class DefectDiffItem(BaseModel):
    """单条缺陷的对比结果。

    - resolved：原审图缺陷在修订后已修复
    - unresolved：原审图缺陷在修订后仍存在
    - new：修订后新增的缺陷
    """

    diff_status: DiffStatus = Field(..., description="缺陷闭环状态")
    defect: DefectItem = Field(..., description="缺陷条目")
    matched_defect_index: int | None = Field(
        default=None,
        description=(
            "匹配的原缺陷索引（仅 resolved/unresolved 时有值，"
            "指向 old_defects 列表的位置；new 缺陷为 None）"
        ),
    )
    similarity_score: float | None = Field(
        default=None,
        description="匹配相似度（0-1，基于 category + standard_ref + suggestion）",
    )


class DiffReport(BaseModel):
    """修订前后对比报告。"""

    original_review_task_id: str = Field(..., description="原审图任务 ID")
    new_review_task_id: str = Field(..., description="修订后审图任务 ID")
    generation_task_id: str | None = Field(
        default=None, description="关联的生成任务 ID"
    )

    old_defects_count: int = Field(default=0, description="原缺陷总数")
    new_defects_count: int = Field(default=0, description="修订后缺陷总数")

    resolved_count: int = Field(default=0, description="已修复缺陷数")
    unresolved_count: int = Field(default=0, description="未修复缺陷数")
    new_count: int = Field(default=0, description="新增缺陷数")

    old_compliance_score: float | None = Field(
        default=None, description="原合规性评分"
    )
    new_compliance_score: float | None = Field(
        default=None, description="修订后合规性评分"
    )
    score_improvement: float | None = Field(
        default=None, description="评分提升（new - old）"
    )

    diffs: list[DefectDiffItem] = Field(
        default_factory=list, description="缺陷对比详情列表"
    )

    closure_rate: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="缺陷闭环率（resolved_count / old_defects_count）",
    )

    generated_at: str = Field(default="", description="报告生成时间 ISO 字符串")
    metadata: dict[str, Any] = Field(default_factory=dict)


# ===== SubTask 11.4：用户反馈 =====


FeedbackAction = Literal["accept", "reject_as_false_positive", "modify_suggestion"]


class FeedbackRecord(BaseModel):
    """用户反馈记录。

    用户对审图缺陷的反馈：
    - accept：采纳该缺陷
    - reject_as_false_positive：误报，拒绝该缺陷
    - modify_suggestion：修改建议（comment 中提供新建议）
    """

    review_task_id: str = Field(..., description="审图任务 ID")
    defect_index: int = Field(
        ..., ge=0, description="缺陷在 ReviewResult.defects 列表中的索引"
    )
    action: FeedbackAction = Field(..., description="反馈动作")
    comment: str = Field(default="", description="用户备注/新建议")
    user_id: str = Field(default="anonymous", description="反馈用户 ID")

    # 缺陷快照（便于反馈检索时无需再查 Celery result）
    defect_snapshot: DefectItem | None = Field(
        default=None, description="被反馈的缺陷快照"
    )

    created_at: str = Field(default="", description="反馈时间 ISO 字符串")
