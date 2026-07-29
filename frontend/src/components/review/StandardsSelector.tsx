"use client";

import { cn } from "@/lib/utils";
import {
  DEFAULT_STANDARD_IDS,
  PRESET_STANDARDS,
  type StandardOption,
} from "@/lib/constants";

/** 向后兼容：调用方仍可从本模块导入这些常量与类型。 */
export { DEFAULT_STANDARD_IDS, PRESET_STANDARDS, type StandardOption };

interface StandardsSelectorProps {
  value: string[];
  onChange: (value: string[]) => void;
  disabled?: boolean;
}

export function StandardsSelector({
  value,
  onChange,
  disabled,
}: StandardsSelectorProps) {
  const toggle = (id: string) => {
    if (disabled) return;
    if (value.includes(id)) {
      onChange(value.filter((v) => v !== id));
    } else {
      onChange([...value, id]);
    }
  };

  return (
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
      {PRESET_STANDARDS.map((opt) => {
        const checked = value.includes(opt.id);
        return (
          <label
            key={opt.id}
            className={cn(
              "flex cursor-pointer items-start gap-2 rounded-md border p-2.5 text-sm transition-colors",
              checked
                ? "border-primary bg-accent/50"
                : "border-border hover:bg-accent/40",
              disabled && "pointer-events-none opacity-60",
            )}
          >
            <input
              type="checkbox"
              checked={checked}
              onChange={() => toggle(opt.id)}
              disabled={disabled}
              className="mt-0.5 h-4 w-4 shrink-0 cursor-pointer rounded border-input accent-primary"
            />
            <span className="leading-tight">{opt.label}</span>
          </label>
        );
      })}
    </div>
  );
}
