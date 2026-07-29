"""预置规范库（SubTask 15.1 / 15.2）。

管理工程制图领域常见规范的元数据清单，覆盖：
- 国家标准（GB/T 4458 系列、GB/T 14665 等）
- 国际标准（ISO 128 系列、ISO 1101 等）
- 行业标准（JB/T 8836、JB/T 5996、HG/T 20668、QC/T 265 等）

仅维护规范的"元数据"（编号 / 标题 / 发布机构 / 年份 / 类别 / 状态 / 引用关系），
不存储规范原文（受版权保护）。元数据可作为"种子"用于：
- 前端规范库浏览页面
- 后续规范导入工具的"已知规范列表"参考
- 版本管理器（``version_manager.py``）初始化版本记录
- 规范冲突检测（``conflict_detector.py``）的引用关系溯源

遵循"八荣八耻"原则：
- 以复用现有为荣：复用 ``app.schemas.kb.PresetStandard`` schema；不重复造元数据结构。
- 以最小修改为荣：纯只读元数据 + 查询接口，不修改已有 indexer / retriever。
- 以实事求是为荣：``create_seed_metadata`` 仅生成"占位种子条款"，明确标注
  ``is_sample=True``，不假装拥有规范原文。需要真实条款时仍需通过
  ``enterprise_import`` 或 ``kb/tools/extract_clauses.py`` 从企业正版 PDF 提取。
"""

from __future__ import annotations

import re

from app.logging import get_logger
from app.schemas.kb import (
    ClauseRecord,
    PresetStandard,
    StandardCategory,
)

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# 预置规范元数据清单
# ---------------------------------------------------------------------------

# 国家标准（GB/T 系列）
_PRESET_NATIONAL: list[PresetStandard] = [
    PresetStandard(
        standard_id="GB/T 4458.1-2002",
        title="机械制图 图样画法 视图",
        publisher="国家标准化管理委员会",
        year="2002",
        category="national",
        status="active",
        scope="规定机件视图（基本视图、向视图、局部视图等）的画法。",
        references=["GB/T 17452-1998", "GB/T 4457.4-2002"],
    ),
    PresetStandard(
        standard_id="GB/T 4458.2-2003",
        title="机械制图 装配图中零、部件序号及其编排方法",
        publisher="国家标准化管理委员会",
        year="2003",
        category="national",
        status="active",
        scope="规定装配图中零、部件序号的编排与标注方法。",
        references=["GB/T 4458.1-2002"],
    ),
    PresetStandard(
        standard_id="GB/T 4458.3-2013",
        title="机械制图 轴测图",
        publisher="国家标准化管理委员会",
        year="2013",
        category="national",
        status="active",
        scope="规定轴测图（正等测、斜二测等）的画法。",
        references=[],
    ),
    PresetStandard(
        standard_id="GB/T 4458.4-2003",
        title="机械制图 尺寸注法",
        publisher="国家标准化管理委员会",
        year="2003",
        category="national",
        status="active",
        scope="规定图样中尺寸标注的基本规则与方法。"
        "注意：与 GB/T 4457.4-2002《图样画法 指引线和引出线》区分。",
        references=["GB/T 4457.4-2002", "GB/T 16675.2-2012"],
    ),
    PresetStandard(
        standard_id="GB/T 4458.5-2003",
        title="机械制图 尺寸公差与配合注法",
        publisher="国家标准化管理委员会",
        year="2003",
        category="national",
        status="active",
        scope="规定图样中尺寸公差与配合的标注方法。",
        references=["GB/T 1800.1-2009", "GB/T 4458.4-2003"],
    ),
    PresetStandard(
        standard_id="GB/T 4458.6-2002",
        title="机械制图 圆锥的尺寸和公差注法",
        publisher="国家标准化管理委员会",
        year="2002",
        category="national",
        status="active",
        scope="规定圆锥的尺寸与公差标注方法。",
        references=["GB/T 4458.4-2003", "GB/T 157-2001"],
    ),
    PresetStandard(
        standard_id="GB/T 14665-2012",
        title="机械工程 CAD 制图规则",
        publisher="国家标准化管理委员会",
        year="2012",
        category="national",
        status="active",
        scope="规定机械工程领域使用 CAD 进行制图的图层、线型、字体等规则。",
        references=["GB/T 17450-1998", "GB/T 18229-2023", "GB/T 4457.4-2002"],
    ),
]


# 国际标准（ISO 系列）
_PRESET_INTERNATIONAL: list[PresetStandard] = [
    PresetStandard(
        standard_id="ISO 128-1:2003",
        title=(
            "Technical drawings — General principles of presentation — "
            "Part 1: Introduction and index"
        ),
        publisher="ISO（国际标准化组织）",
        year="2003",
        category="international",
        status="active",
        scope="技术制图通用表示规则的引言与索引。",
        references=["ISO 128-24:2014"],
    ),
    PresetStandard(
        standard_id="ISO 128-24:2014",
        title=(
            "Technical drawings — General principles of presentation — "
            "Part 24: Lines on mechanical engineering drawings"
        ),
        publisher="ISO（国际标准化组织）",
        year="2014",
        category="international",
        status="active",
        scope="机械工程图样中图线的画法规则。",
        references=["ISO 128-1:2003", "GB/T 17450-1998"],
    ),
    PresetStandard(
        standard_id="ISO 1101:2017",
        title=(
            "Geometrical product specifications (GPS) — "
            "Geometrical tolerancing — Tolerances of form, orientation, "
            "location and run-out"
        ),
        publisher="ISO（国际标准化组织）",
        year="2017",
        category="international",
        status="active",
        scope="GPS 几何公差：形状、方向、位置与跳动公差的标注方法。",
        references=["GB/T 1182-2018"],
    ),
]


# 行业标准（JB/T、HG/T、QC/T 等）
_PRESET_INDUSTRY: list[PresetStandard] = [
    PresetStandard(
        standard_id="JB/T 8836-2023",
        title="机械加工工艺文件 编号方法",
        publisher="国家发展和改革委员会 / 机械工业联合会",
        year="2023",
        category="industry",
        status="active",
        scope="规定机械加工工艺文件（工艺过程卡、工序卡等）的编号方法。",
        references=[],
    ),
    PresetStandard(
        standard_id="JB/T 5996-2023",
        title="机械产品图样及设计文件 编号原则",
        publisher="国家发展和改革委员会 / 机械工业联合会",
        year="2023",
        category="industry",
        status="active",
        scope="规定机械产品图样及设计文件的编号原则。",
        references=["JB/T 5054-2023"],
    ),
    PresetStandard(
        standard_id="JB/T 5054-2023",
        title="产品图样及设计文件 完整性",
        publisher="国家发展和改革委员会 / 机械工业联合会",
        year="2023",
        category="industry",
        status="active",
        scope="规定产品图样及设计文件的完整性要求。",
        references=["JB/T 5996-2023"],
    ),
    PresetStandard(
        standard_id="HG/T 20668-2000",
        title="化工设备设计文件编制规定",
        publisher="国家石油和化学工业局",
        year="2000",
        category="industry",
        status="active",
        scope="规定化工设备设计文件的编制规范。",
        references=[],
    ),
    PresetStandard(
        standard_id="QC/T 265-2023",
        title="汽车产品图样及设计文件 编号原则",
        publisher="工业和信息化部",
        year="2023",
        category="industry",
        status="active",
        scope="规定汽车产品图样及设计文件的编号原则。",
        references=["JB/T 5996-2023"],
    ),
]


# ---------------------------------------------------------------------------
# 标准库服务
# ---------------------------------------------------------------------------


class StandardLibrary:
    """预置规范库（只读）。

    用法：
        lib = StandardLibrary()
        for std in lib.list_preset_standards():
            print(std.standard_id, std.title)
        for std in lib.list_standards_by_category("industry"):
            ...
    """

    def __init__(self) -> None:
        self._presets: list[PresetStandard] = (
            list(_PRESET_NATIONAL)
            + list(_PRESET_INTERNATIONAL)
            + list(_PRESET_INDUSTRY)
        )

    # ===== 查询接口 =====

    def list_preset_standards(
        self, category: StandardCategory | None = None
    ) -> list[PresetStandard]:
        """列出预置规范。可选按类别过滤。"""
        if category is None:
            return list(self._presets)
        return [s for s in self._presets if s.category == category]

    def list_standards_by_category(
        self, category: StandardCategory
    ) -> list[PresetStandard]:
        """按类别列出预置规范。

        Args:
            category: ``national`` / ``industry`` / ``international`` / ``enterprise``

        Returns:
            该类别下的预置规范列表（按编号排序）。
        """
        valid: set[str] = {
            "national",
            "industry",
            "international",
            "enterprise",
        }
        if category not in valid:
            raise ValueError(
                f"非法 category={category!r}，合法值：{sorted(valid)}"
            )
        items = [s for s in self._presets if s.category == category]
        items.sort(key=lambda s: s.standard_id)
        return items

    def get_preset_standard(self, standard_id: str) -> PresetStandard | None:
        """按规范编号查询单个预置规范。未找到返回 None。"""
        sid = self._normalize_id(standard_id)
        for s in self._presets:
            if self._normalize_id(s.standard_id) == sid:
                return s
        return None

    def count(self) -> int:
        """预置规范总数。"""
        return len(self._presets)

    # ===== 种子元数据生成 =====

    def create_seed_metadata(
        self, standard_id: str
    ) -> list[ClauseRecord]:
        """生成某规范的"种子条款"列表（占位用，非规范原文）。

        种子条款仅用于：
        - 让 Qdrant 索引在规范正式导入前就具备"该规范已纳入"的占位
        - 让 RAG 检索能命中"该规范已收录"的提示信息
        - 让版本管理 / 通知系统能引用一个稳定的 ClauseRecord

        遵循"以实事求是为荣"原则：种子条款的 ``original_text`` 明确标注
        "占位元数据，非规范原文"，``is_sample=True``。
        若需真实条款，请通过 ``enterprise_import`` 从企业正版 PDF 提取。
        """
        std = self.get_preset_standard(standard_id)
        if std is None:
            log.warning(
                "kb.standard_library.seed_not_found", standard_id=standard_id
            )
            return []

        seed = ClauseRecord(
            standard=std.standard_id,
            clause_id="0",
            title=f"{std.standard_id} {std.title}",
            category="general",
            keywords=self._auto_keywords(std.title),
            references=list(std.references),
            version=std.year,
            is_sample=True,
            original_text=(
                f"[占位元数据] {std.standard_id}《{std.title}》"
                f"（{std.publisher}，{std.year}）已纳入规范库。"
                f"适用范围：{std.scope} "
                f"本条目为种子元数据，非规范原文；"
                f"如需检索具体条款，请通过企业正版 PDF 导入。"
            ),
            source_file=f"preset_library:{std.standard_id}",
        )
        log.info(
            "kb.standard_library.seed_created",
            standard_id=std.standard_id,
            references_count=len(seed.references),
        )
        return [seed]

    # ===== 内部辅助 =====

    @staticmethod
    def _normalize_id(sid: str) -> str:
        """规范化编号：去多余空白、统一连字符。"""
        return re.sub(r"\s+", " ", sid.strip()).replace("—", "-")

    @staticmethod
    def _auto_keywords(title: str) -> list[str]:
        """从标题提取关键词（复用 enterprise_import._auto_keywords 的语义）。"""
        parts = re.split(r"[\s、，,。/（）()【】]+", title)
        return [p for p in parts if len(p) >= 2 and not p.replace(".", "").isdigit()][:5]


# ---------------------------------------------------------------------------
# 模块级便捷函数
# ---------------------------------------------------------------------------


_DEFAULT_LIBRARY: StandardLibrary | None = None


def get_library() -> StandardLibrary:
    """获取全局 StandardLibrary 单例。"""
    global _DEFAULT_LIBRARY
    if _DEFAULT_LIBRARY is None:
        _DEFAULT_LIBRARY = StandardLibrary()
    return _DEFAULT_LIBRARY


def list_preset_standards(
    category: StandardCategory | None = None,
) -> list[PresetStandard]:
    """便捷函数：列出预置规范。"""
    return get_library().list_preset_standards(category=category)


def get_preset_standard(standard_id: str) -> PresetStandard | None:
    """便捷函数：按编号查询预置规范。"""
    return get_library().get_preset_standard(standard_id)


def create_seed_metadata(standard_id: str) -> list[ClauseRecord]:
    """便捷函数：生成种子条款元数据。"""
    return get_library().create_seed_metadata(standard_id)
