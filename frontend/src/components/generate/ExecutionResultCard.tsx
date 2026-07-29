"use client";

import { useState } from "react";
import { AlertCircle, CheckCircle2, ChevronDown, ChevronUp } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import type { ExecutionResult } from "@/lib/types";
import { formatElapsed } from "@/lib/format";

interface ExecutionResultCardProps {
  execution: ExecutionResult;
  /** 来源标签，如 "初次生成" / "重新执行" */
  sourceLabel?: string;
}

const STDOUT_PREVIEW_LIMIT = 500;

export function ExecutionResultCard({
  execution,
  sourceLabel,
}: ExecutionResultCardProps) {
  const [expanded, setExpanded] = useState<boolean>(false);

  const success = execution.success;
  const hasStdout = execution.stdout.length > 0;
  const hasStderr = execution.stderr.length > 0;
  const stdoutLong = execution.stdout.length > STDOUT_PREVIEW_LIMIT;
  const stdoutPreview = stdoutLong
    ? execution.stdout.slice(0, STDOUT_PREVIEW_LIMIT)
    : execution.stdout;
  const stdoutShown = expanded ? execution.stdout : stdoutPreview;

  return (
    <div className="flex flex-col gap-3 rounded-lg border p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          {success ? (
            <CheckCircle2 className="h-4 w-4 text-success" />
          ) : (
            <AlertCircle className="h-4 w-4 text-destructive" />
          )}
          <span className="text-sm font-medium">
            {sourceLabel ? `${sourceLabel} · ` : ""}执行结果
          </span>
          <Badge variant={success ? "default" : "destructive"}>
            {success ? "成功" : "失败"}
          </Badge>
          {execution.exit_code !== null && (
            <Badge variant="outline" className="font-mono text-xs">
              exit={execution.exit_code}
            </Badge>
          )}
        </div>
        <div className="text-xs text-muted-foreground">
          耗时 {formatElapsed(execution.elapsed_ms)}
        </div>
      </div>

      {execution.violations.length > 0 && (
        <div className="rounded-md border border-warning/40 bg-warning/10 p-3 text-sm">
          <div className="mb-1 font-medium text-warning">
            规则违规（{execution.violations.length} 项）
          </div>
          <ul className="list-disc space-y-0.5 pl-5 text-xs text-warning">
            {execution.violations.map((v, i) => (
              <li key={i}>{v}</li>
            ))}
          </ul>
        </div>
      )}

      {hasStdout && (
        <div className="flex flex-col gap-1">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-muted-foreground">
              stdout
            </span>
            {stdoutLong && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setExpanded((v) => !v)}
              >
                {expanded ? (
                  <ChevronUp className="h-3 w-3" />
                ) : (
                  <ChevronDown className="h-3 w-3" />
                )}
                {expanded ? "收起" : `展开全部 (${execution.stdout.length} 字符)`}
              </Button>
            )}
          </div>
          <pre className="max-h-72 overflow-auto rounded-md bg-muted/50 p-3 font-mono text-xs leading-relaxed">
            {stdoutShown}
            {stdoutLong && !expanded && (
              <span className="text-muted-foreground">{"\n...（已截断）"}</span>
            )}
          </pre>
        </div>
      )}

      {hasStderr && (
        <div className="flex flex-col gap-1">
          <span className="text-xs font-medium text-muted-foreground">
            stderr
          </span>
          <pre className="max-h-72 overflow-auto rounded-md border border-destructive/30 bg-destructive/5 p-3 font-mono text-xs leading-relaxed text-destructive">
            {execution.stderr}
          </pre>
        </div>
      )}

      {!hasStdout && !hasStderr && (
        <div className="text-xs text-muted-foreground">无 stdout / stderr 输出</div>
      )}

      <Separator />
      <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
        <span>
          产物文件数:{" "}
          <span className="font-mono text-foreground">
            {execution.output_files.length}
          </span>
        </span>
        <Separator orientation="vertical" className="h-4" />
        <span>
          违规项:{" "}
          <span className="font-mono text-foreground">
            {execution.violations.length}
          </span>
        </span>
      </div>
    </div>
  );
}
