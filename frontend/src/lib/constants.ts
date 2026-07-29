/**
 * 全局共享常量：消除各组件本地散落的魔法数与预设列表。
 *
 * 替代的历史本地定义：
 * - components/review/StandardsSelector.tsx 的 PRESET_STANDARDS / DEFAULT_STANDARD_IDS / StandardOption
 * - components/kb/SearchPanel.tsx 的 CATEGORY_OPTIONS
 * - components/generate/InputTabs.tsx 的 SKETCH_ACCEPT / ACCEPTED_SKETCH_EXT
 * - app/kb/page.tsx 的 DEFAULT_TOP_K
 */

/** 预设规范条目的结构。 */
export interface StandardOption {
  id: string;
  label: string;
}

/** P0 预设规范（与后端 default 对齐）。 */
export const PRESET_STANDARDS: StandardOption[] = [
  { id: "GB/T 1182-2018", label: "GB/T 1182-2018 形位公差" },
  { id: "GB/T 4457.4-2002", label: "GB/T 4457.4-2002 尺寸注法" },
  { id: "GB/T 17450-1998", label: "GB/T 17450-1998 技术制图图线" },
  { id: "GB/T 1804-2000", label: "GB/T 1804-2000 一般公差" },
  { id: "GB/T 131-2006", label: "GB/T 131-2006 表面结构表示法" },
  { id: "GB/T 18229-2023", label: "GB/T 18229-2023 CAD工程制图规则" },
];

/** 默认勾选前两项（与后端 default 一致）。 */
export const DEFAULT_STANDARD_IDS = PRESET_STANDARDS.slice(0, 2).map(
  (s) => s.id,
);

/** 知识库分类过滤选项。保持 `as const` 以支持值类型收窄。 */
export const CATEGORY_OPTIONS = [
  { value: "general", label: "通用" },
  { value: "dimensioning", label: "尺寸标注" },
  { value: "tolerance", label: "形位公差" },
  { value: "surface", label: "表面结构" },
  { value: "layer", label: "图层" },
  { value: "view", label: "视图" },
  { value: "other", label: "其他" },
] as const;

/** 草图上传 <input accept> 属性。 */
export const SKETCH_ACCEPT = ".png,.jpg,.jpeg,image/png,image/jpeg";

/** 草图允许的扩展名（不含点，与 getExtension 输出对齐）。 */
export const ACCEPTED_SKETCH_EXT = ["png", "jpg", "jpeg"];

/** 知识库检索默认 top_k。 */
export const DEFAULT_TOP_K = 5;
