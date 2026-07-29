/**
 * 共享格式化函数：消除前端各页面重复实现。
 *
 * 替代的历史本地实现：
 * - review/page.tsx 的 formatElapsed(meta)
 * - generate/page.tsx 的 formatElapsed(ms)
 * - ExecutionResultCard.tsx 的 formatElapsed(ms)
 * - FileUploader.tsx / InputTabs.tsx 的 formatSize / getExtension
 * - GeometryValidationCard.tsx 的 formatNumber / formatBoundingBox
 */

/**
 * 格式化耗时（毫秒）。
 *
 * - number: <1000 显示 "X ms"，≥1000 显示 "X.XX s"
 * - string: 非空字符串原样返回，空字符串返回 "-"
 * - undefined/null/其他类型: 返回 "-"
 */
export function formatElapsed(ms: number | unknown): string {
  if (typeof ms === "number") {
    if (ms < 1000) return `${ms} ms`;
    return `${(ms / 1000).toFixed(2)} s`;
  }
  if (typeof ms === "string" && ms) return ms;
  return "-";
}

/**
 * 从 metadata 对象读取耗时并格式化。
 *
 * 优先取 elapsed_ms，其次 elapsed，最后回退到 "-"。
 * 保留 review/page.tsx 历史行为。
 */
export function formatElapsedFromMeta(
  meta: Record<string, unknown>,
): string {
  const v = meta?.elapsed_ms ?? meta?.elapsed;
  return formatElapsed(v);
}

/**
 * 格式化字节数为人类可读字符串。
 *
 * - <1024: "X B"
 * - <1024*1024: "X.X KB"
 * - <1024*1024*1024: "X.XX MB"
 * - 否则: "X.XX GB"
 */
export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024)
    return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

/**
 * 格式化数字为固定小数位字符串。
 *
 * NaN/Infinity 返回 "-"。
 *
 * @param digits 小数位数，默认 2
 */
export function formatNumber(n: number, digits = 2): string {
  if (!Number.isFinite(n)) return "-";
  return n.toFixed(digits);
}

/**
 * 格式化包围盒为 "DX × DY × DZ mm" 字符串。
 *
 * 支持两种输入形态：
 * - 6-tuple `[xmin, ymin, zmin, xmax, ymax, zmax]`（与后端 GeometryValidation.bounding_box 对齐）
 * - `{ min: [x,y,z]; max: [x,y,z] }`（spec 描述的形态）
 *
 * 非法/空输入返回 "-"。
 */
export function formatBoundingBox(
  bb:
    | { min: [number, number, number]; max: [number, number, number] }
    | [number, number, number, number, number, number]
    | unknown,
): string {
  if (!bb) return "-";

  // 6-tuple 形态（与后端 GeometryValidation.bounding_box 对齐）
  if (Array.isArray(bb) && bb.length === 6) {
    const [xmin, ymin, zmin, xmax, ymax, zmax] = bb as number[];
    if (
      [xmin, ymin, zmin, xmax, ymax, zmax].every(
        (v) => typeof v === "number" && Number.isFinite(v),
      )
    ) {
      const dx = xmax - xmin;
      const dy = ymax - ymin;
      const dz = zmax - zmin;
      return `${formatNumber(dx, 3)} × ${formatNumber(dy, 3)} × ${formatNumber(dz, 3)} mm`;
    }
    return "-";
  }

  // min/max 形态（spec 描述）
  if (typeof bb === "object" && bb !== null && "min" in bb && "max" in bb) {
    const o = bb as { min: unknown; max: unknown };
    if (
      Array.isArray(o.min) &&
      o.min.length === 3 &&
      Array.isArray(o.max) &&
      o.max.length === 3 &&
      [...o.min, ...o.max].every(
        (v) => typeof v === "number" && Number.isFinite(v),
      )
    ) {
      const [xmin, ymin, zmin] = o.min as number[];
      const [xmax, ymax, zmax] = o.max as number[];
      const dx = xmax - xmin;
      const dy = ymax - ymin;
      const dz = zmax - zmin;
      return `${formatNumber(dx, 3)} × ${formatNumber(dy, 3)} × ${formatNumber(dz, 3)} mm`;
    }
  }

  return "-";
}

/**
 * 取文件名的小写扩展名（不含点）。无扩展名返回空字符串。
 *
 * 例：
 * - "file.png" → "png"
 * - "archive.tar.gz" → "gz"
 * - "Makefile" → ""
 * - ".bashrc" → ""（隐藏文件无扩展名）
 */
export function getExtension(name: string): string {
  if (typeof name !== "string") return "";
  const idx = name.lastIndexOf(".");
  if (idx < 0 || idx === 0 || idx === name.length - 1) return "";
  return name.slice(idx + 1).toLowerCase();
}
