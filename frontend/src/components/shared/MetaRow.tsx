import type { ReactNode } from "react";

export interface MetaRowProps {
  label: string;
  value: ReactNode;
}

/** 标签 + 值的纵向紧凑行，消除 review/generate 页面内的重复定义。 */
export function MetaRow({ label, value }: MetaRowProps) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-sm">{value}</span>
    </div>
  );
}
