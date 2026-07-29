"use client";

import { FileText, HelpCircle } from "lucide-react";
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { ClauseSearchResult } from "@/lib/types";
import { categoryLabel } from "@/components/kb/SearchPanel";

interface ClauseCardProps {
  result: ClauseSearchResult;
}

function formatScore(score: number): string {
  if (!Number.isFinite(score)) return "-";
  const pct = Math.round(score * 100);
  return `${pct}%`;
}

export function ClauseCard({ result }: ClauseCardProps) {
  const isIncomplete = result.completeness === "incomplete";
  return (
    <Card>
      <CardHeader className="gap-2 pb-3">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="secondary" className="font-normal">
            {result.standard}
          </Badge>
          <Badge variant="outline" className="font-normal">
            条款 {result.clause_id}
          </Badge>
          {isIncomplete ? (
            <TooltipProvider delayDuration={200}>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Badge variant="warning">
                    不完整
                    <HelpCircle className="ml-1 h-3 w-3" />
                  </Badge>
                </TooltipTrigger>
                <TooltipContent>
                  原文或来源缺失
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          ) : (
            <Badge variant="success">
              完整
            </Badge>
          )}
        </div>
        <div className="text-sm font-medium leading-snug">
          {result.title || "（无标题）"}
        </div>
      </CardHeader>
      <CardContent className="pb-3">
        <blockquote className="border-l-2 border-border pl-3 text-sm leading-relaxed text-muted-foreground">
          {result.original_text || "（无原文）"}
        </blockquote>
      </CardContent>
      <CardFooter className="flex flex-col items-start gap-3 pt-0">
        <div className="flex w-full flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
          <span>
            相似度：
            <span className="font-medium text-foreground">
              {formatScore(result.score)}
            </span>
          </span>
          <span className="inline-flex items-center gap-1">
            <FileText className="h-3 w-3" />
            {result.source_file || "未知来源"}
          </span>
          {result.category && (
            <span>
              分类：
              <span className="font-medium text-foreground">
                {categoryLabel(result.category)}
              </span>
            </span>
          )}
        </div>
        {result.keywords && result.keywords.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {result.keywords.map((kw) => (
              <Badge
                key={kw}
                variant="outline"
                className="font-normal text-muted-foreground"
              >
                {kw}
              </Badge>
            ))}
          </div>
        )}
      </CardFooter>
    </Card>
  );
}
