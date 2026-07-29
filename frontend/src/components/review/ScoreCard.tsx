"use client";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

interface ScoreCardProps {
  score: number;
  defectCount: number;
}

interface ScoreStyle {
  text: string;
  border: string;
  bg: string;
  label: string;
  variant: "success" | "warning" | "destructive";
}

function scoreStyle(score: number): ScoreStyle {
  if (score >= 85) {
    return {
      text: "text-success",
      border: "border-success/30",
      bg: "bg-success/15",
      label: "良好",
      variant: "success",
    };
  }
  if (score >= 70) {
    return {
      text: "text-warning",
      border: "border-warning/30",
      bg: "bg-warning/15",
      label: "一般",
      variant: "warning",
    };
  }
  return {
    text: "text-destructive",
    border: "border-destructive/30",
    bg: "bg-destructive/15",
    label: "不合格",
    variant: "destructive",
  };
}

export function ScoreCard({ score, defectCount }: ScoreCardProps) {
  const clamped = Number.isFinite(score) ? Math.max(0, Math.min(100, score)) : 0;
  const s = scoreStyle(clamped);
  return (
    <div
      role="meter"
      aria-valuenow={clamped}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label="合规分数"
      className={cn(
        "flex flex-col items-center justify-center gap-1 rounded-lg border-2 p-6",
        s.border,
        s.bg,
      )}
    >
      <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        合规性评分
      </div>
      <div className={cn("text-6xl font-bold tabular-nums", s.text)}>
        {Math.round(clamped)}
      </div>
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <span>/ 100 ·</span>
        <Badge variant={s.variant}>{s.label}</Badge>
      </div>
      <div className="mt-2 text-xs text-muted-foreground">
        共 {defectCount} 项缺陷
      </div>
    </div>
  );
}
