"use client";

import { Check } from "lucide-react";
import { cn } from "@/lib/utils";

export type OutputFormat = "step" | "iges" | "stl" | "dxf";

export const OUTPUT_FORMATS: {
  value: OutputFormat;
  label: string;
  description: string;
}[] = [
  { value: "step", label: "STEP", description: "通用 CAD 交换格式" },
  { value: "iges", label: "IGES", description: "老牌曲面交换格式" },
  { value: "stl", label: "STL", description: "三角网格 / 3D 打印" },
  { value: "dxf", label: "DXF", description: "二维工程图" },
];

interface OutputFormatSelectorProps {
  value: OutputFormat;
  onChange: (v: OutputFormat) => void;
  disabled?: boolean;
}

export function OutputFormatSelector({
  value,
  onChange,
  disabled,
}: OutputFormatSelectorProps) {
  return (
    <div
      role="radiogroup"
      aria-label="输出格式"
      className="grid grid-cols-2 gap-2 sm:grid-cols-4"
    >
      {OUTPUT_FORMATS.map((opt) => {
        const checked = value === opt.value;
        return (
          <label
            key={opt.value}
            className={cn(
              "flex cursor-pointer flex-col items-start gap-0.5 rounded-md border p-3 text-sm transition-colors",
              checked
                ? "border-primary bg-accent/50"
                : "border-border hover:bg-accent/40",
              disabled && "pointer-events-none opacity-60",
            )}
          >
            <input
              type="radio"
              name="output-format"
              value={opt.value}
              checked={checked}
              onChange={() => onChange(opt.value)}
              disabled={disabled}
              className="sr-only"
            />
            <div className="flex w-full items-center justify-between">
              <span className="font-medium uppercase">{opt.label}</span>
              {checked ? (
                <Check
                  aria-hidden="true"
                  className="h-4 w-4 text-primary"
                />
              ) : (
                <span
                  aria-hidden="true"
                  className="h-2 w-2 rounded-full bg-muted-foreground/30"
                />
              )}
            </div>
            <span className="text-xs text-muted-foreground">
              {opt.description}
            </span>
          </label>
        );
      })}
    </div>
  );
}
