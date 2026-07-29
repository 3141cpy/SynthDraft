"""工程规范知识库（KB）相关 schema。

定义条款（Clause）与检索结果（ClauseSearchResult）的数据结构，
供 Qdrant 存储层、LlamaIndex 检索层、API 端点共用。

遵循"以强制引用原文为荣"原则：
ClauseSearchResult 必含 original_text 与 source_file，
若缺失则 completeness=incomplete（SubTask 3.5）。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ClauseRecord(BaseModel):
    """单条结构化条款记录。用于写入 Qdrant 的 payload + vector。"""

    standard: str = Field(..., description="规范编号，如 GB/T 1182-2018")
    clause_id: str = Field(..., description="条款号，如 5.2")
    title: str = Field(..., description="条款标题")
    category: str = Field(default="general", description="分类")
    keywords: list[str] = Field(default_factory=list, description="关键词")
    references: list[str] = Field(default_factory=list, description="引用关系")
    version: str = Field(default="", description="规范版本年份")
    is_sample: bool = Field(default=False, description="是否为开发样本数据")
    original_text: str = Field(..., description="条款原文片段（强制引用原文）")
    source_file: str = Field(default="", description="来源文件名")

    @property
    def point_id(self) -> str:
        """Qdrant point 的稳定 ID：standard|clause_id。"""
        return f"{self.standard}|{self.clause_id}"

    def to_payload(self) -> dict:
        """转换为 Qdrant payload（不含 vector）。"""
        return self.model_dump()


class ClauseSearchResult(BaseModel):
    """检索结果项。每条必须包含原文出处。"""

    standard: str = Field(..., description="规范编号")
    clause_id: str = Field(..., description="条款号")
    title: str = Field(..., description="条款标题")
    original_text: str = Field(default="", description="条款原文片段")
    score: float = Field(default=0.0, description="相似度得分")
    source_file: str = Field(default="", description="来源文件名")
    category: str = Field(default="general", description="分类")
    keywords: list[str] = Field(default_factory=list, description="关键词")
    completeness: Literal["complete", "incomplete"] = Field(
        default="complete",
        description="完整性标记；任一必填字段缺失则为 incomplete",
    )

    @classmethod
    def from_record(
        cls, record: ClauseRecord, score: float = 0.0
    ) -> "ClauseSearchResult":
        """从 ClauseRecord 构造检索结果，并做完整性校验。

        强制引用原文机制（SubTask 3.5）：
        若 original_text 或 source_file 缺失，标记 completeness=incomplete。
        """
        missing = []
        if not record.original_text or not record.original_text.strip():
            missing.append("original_text")
        if not record.source_file or not record.source_file.strip():
            missing.append("source_file")

        completeness: Literal["complete", "incomplete"] = (
            "incomplete" if missing else "complete"
        )
        return cls(
            standard=record.standard,
            clause_id=record.clause_id,
            title=record.title,
            original_text=record.original_text,
            score=float(score),
            source_file=record.source_file,
            category=record.category,
            keywords=record.keywords,
            completeness=completeness,
        )


class ReindexResponse(BaseModel):
    """重建索引响应。"""

    indexed_count: int = Field(..., description="已索引条款数")
    collection: str = Field(..., description="Qdrant collection 名称")
    message: str = Field(default="", description="附加消息")


class StandardsListResponse(BaseModel):
    """已索引规范列表响应。"""

    standards: list[str] = Field(default_factory=list, description="规范编号列表")
    count: int = Field(default=0, description="规范数量")


class ClausesQueryResponse(BaseModel):
    """条款检索响应。"""

    query: str = Field(..., description="查询文本")
    top_k: int = Field(..., description="返回条数")
    results: list[ClauseSearchResult] = Field(default_factory=list)
    total: int = Field(default=0, description="实际返回条数")


# ===========================================================================
# Task 14：企业规范自定义
# ===========================================================================


class EnterpriseImportResponse(BaseModel):
    """企业规范导入响应（SubTask 14.1）。"""

    standard: str = Field(..., description="规范编号/名称")
    version: str = Field(default="", description="规范版本年份")
    source_file: str = Field(default="", description="来源文件名")
    format: str = Field(..., description="文件格式：pdf/docx/xlsx")
    clauses_count: int = Field(default=0, description="已提取条款数")
    clauses: list[ClauseRecord] = Field(default_factory=list, description="提取的条款列表")
    message: str = Field(default="", description="附加消息")


ConflictType = Literal["contradiction", "duplicate", "missing", "enhancement"]
"""冲突类型：
- contradiction：矛盾（同一要求不同规定）
- duplicate：重复（同一要求重复定义）
- missing：缺失（国标有企业无）
- enhancement：增强（企业标准严于国标）
"""

ConflictSeverity = Literal["critical", "major", "minor", "info"]
"""严重等级：
- critical：矛盾且影响合规
- major：缺失关键要求或重大矛盾
- minor：次要差异
- info：增强或重复，无风险
"""


class ConflictItem(BaseModel):
    """单条规范冲突（SubTask 14.2）。"""

    conflict_type: ConflictType = Field(..., description="冲突类型")
    severity: ConflictSeverity = Field(default="info", description="严重等级")
    standard_a: str = Field(..., description="规范集 A 编号")
    standard_b: str = Field(..., description="规范集 B 编号")
    clause_a_id: str = Field(default="", description="A 集中冲突条款号")
    clause_b_id: str = Field(default="", description="B 集中冲突条款号")
    title_a: str = Field(default="", description="A 集中冲突条款标题")
    title_b: str = Field(default="", description="B 集中冲突条款标题")
    text_a: str = Field(default="", description="A 集中条款原文片段")
    text_b: str = Field(default="", description="B 集中条款原文片段")
    description: str = Field(default="", description="冲突说明")
    detection_method: Literal["llm", "keyword", "both"] = Field(
        default="keyword",
        description="检测方法：llm/keyword/both",
    )


class ConflictReport(BaseModel):
    """规范冲突检测报告。"""

    standard_a: str = Field(..., description="规范集 A 编号")
    standard_b: str = Field(..., description="规范集 B 编号")
    conflicts: list[ConflictItem] = Field(default_factory=list)
    total: int = Field(default=0, description="冲突总数")
    by_type: dict[str, int] = Field(
        default_factory=dict, description="按冲突类型分组的数量"
    )
    by_severity: dict[str, int] = Field(
        default_factory=dict, description="按严重等级分组的数量"
    )
    llm_used: bool = Field(default=False, description="是否使用了 LLM 检测")


class StandardProfile(BaseModel):
    """单套规范配置（SubTask 14.3）。"""

    name: str = Field(..., description="配置名称，唯一标识")
    description: str = Field(default="", description="配置描述")
    standards: list[str] = Field(
        default_factory=list, description="包含的规范编号列表"
    )
    priority: int = Field(default=0, description="优先级（数字越大越优先）")
    created_at: str = Field(default="", description="创建时间 ISO 格式")
    is_active: bool = Field(default=False, description="是否为当前活跃配置")


class ProfileListResponse(BaseModel):
    """规范配置列表响应。"""

    profiles: list[StandardProfile] = Field(default_factory=list)
    active_profile: str = Field(default="", description="当前活跃配置名")
    total: int = Field(default=0, description="配置总数")


class ProfileCreateRequest(BaseModel):
    """创建规范配置请求。"""

    name: str = Field(..., min_length=1, description="配置名称")
    description: str = Field(default="", description="配置描述")
    standards: list[str] = Field(default_factory=list, description="规范编号列表")
    priority: int = Field(default=0, ge=0, description="优先级")


class ProfileSetActiveRequest(BaseModel):
    """切换活跃配置请求。"""

    name: str = Field(..., min_length=1, description="要激活的配置名")


# ===========================================================================
# Task 15：规范知识库扩展（预置规范库 + 版本管理 + 更新通知）
# ===========================================================================


StandardCategory = Literal["national", "industry", "international", "enterprise"]
"""规范类别：
- national：国家标准（GB/T）
- industry：行业标准（JB/T、HG/T、QC/T 等）
- international：国际标准（ISO、IEC 等）
- enterprise：企业标准（Q/XX）
"""

StandardStatus = Literal["active", "deprecated", "superseded", "draft"]
"""规范状态：
- active：现行有效
- deprecated：已废弃
- superseded：已被替代
- draft：草案
"""


class PresetStandard(BaseModel):
    """预置规范元数据（SubTask 15.1 / 15.2）。"""

    standard_id: str = Field(..., description="规范编号，如 GB/T 4458.4-2003")
    title: str = Field(..., description="规范标题")
    publisher: str = Field(default="", description="发布机构，如 国家标准化管理委员会")
    year: str = Field(default="", description="发布年份")
    category: StandardCategory = Field(
        default="national", description="规范类别"
    )
    status: StandardStatus = Field(default="active", description="规范状态")
    scope: str = Field(default="", description="适用范围简述")
    references: list[str] = Field(
        default_factory=list, description="引用的其他规范编号"
    )


class StandardVersion(BaseModel):
    """规范版本记录（SubTask 15.3）。"""

    standard_id: str = Field(..., description="规范编号（不含年份），如 GB/T 4458.4")
    version: str = Field(..., description="版本年份，如 2003")
    release_date: str = Field(default="", description="发布日期 ISO 格式")
    status: StandardStatus = Field(default="active", description="版本状态")
    notes: str = Field(default="", description="版本备注")
    registered_at: str = Field(default="", description="注册时间 ISO 格式")


class VersionDiff(BaseModel):
    """两版本对比差异（SubTask 15.3）。"""

    standard_id: str = Field(..., description="规范编号")
    version_a: str = Field(..., description="版本 A 年份")
    version_b: str = Field(..., description="版本 B 年份")
    added: list[str] = Field(
        default_factory=list, description="B 版本相对 A 版本新增条款号"
    )
    removed: list[str] = Field(
        default_factory=list, description="B 版本相对 A 版本删除条款号"
    )
    modified: list[str] = Field(
        default_factory=list, description="B 版本相对 A 版本修改条款号"
    )
    note: str = Field(default="", description="对比说明")


class StandardNotification(BaseModel):
    """规范更新通知（SubTask 15.3）。"""

    notification_id: str = Field(..., description="通知 ID")
    standard_id: str = Field(..., description="规范编号")
    new_version: str = Field(..., description="新版本年份")
    old_version: str = Field(default="", description="旧版本年份")
    message: str = Field(default="", description="通知内容")
    created_at: str = Field(default="", description="创建时间 ISO 格式")
    is_read: bool = Field(default=False, description="是否已读")


class VersionRegisterRequest(BaseModel):
    """注册新版本请求。"""

    version: str = Field(..., min_length=1, description="版本年份，如 2024")
    release_date: str = Field(default="", description="发布日期 ISO 格式")
    status: StandardStatus = Field(default="active", description="版本状态")
    notes: str = Field(default="", description="版本备注")
