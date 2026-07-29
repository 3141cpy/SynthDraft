"use client";

import { Inbox, Search } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import type { ClauseSearchResult } from "@/lib/types";
import { ClauseCard } from "@/components/kb/ClauseCard";
import { CardSkeleton } from "@/components/shared/Skeleton";
import { EmptyState, ErrorState } from "@/components/shared/States";

/** 推荐查询示例：未搜索时展示，点击填入查询框。 */
const EXAMPLE_QUERIES = [
  "螺栓标记方法",
  "尺寸公差选用",
  "表面粗糙度标注",
  "螺纹画法",
  "形位公差等级",
];

interface ResultsListProps {
  results: ClauseSearchResult[];
  total: number;
  loading: boolean;
  error: string | null;
  hasSearched: boolean;
  /** 推荐查询点击回调：由父组件把示例填入查询框。 */
  onExampleClick?: (query: string) => void;
}

export function ResultsList({
  results,
  total,
  loading,
  error,
  hasSearched,
  onExampleClick,
}: ResultsListProps) {
  if (loading) {
    return (
      <div className="flex flex-col gap-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <CardSkeleton key={i} />
        ))}
      </div>
    );
  }

  if (error) {
    return <ErrorState description={error} />;
  }

  if (!hasSearched) {
    return (
      <EmptyState
        icon={Search}
        title="开始检索"
        description='输入查询文本并点击"检索"开始，或试试以下推荐查询'
        action={
          onExampleClick ? (
            <div className="flex flex-wrap items-center justify-center gap-2 pt-1">
              {EXAMPLE_QUERIES.map((q) => (
                <Button
                  key={q}
                  variant="outline"
                  size="sm"
                  className="h-7 rounded-full px-3 text-xs font-normal"
                  onClick={() => onExampleClick(q)}
                >
                  {q}
                </Button>
              ))}
            </div>
          ) : null
        }
      />
    );
  }

  if (results.length === 0) {
    return (
      <EmptyState
        icon={Inbox}
        title="未找到匹配条款"
        description="请尝试调整查询文本或过滤条件"
      />
    );
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-2">
          <div className="space-y-1.5">
            <CardTitle className="text-base">检索结果</CardTitle>
            <CardDescription>共 {total} 条匹配条款</CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <div className="flex flex-col gap-3">
          {results.map((r, idx) => (
            <ClauseCard
              key={`${r.standard}-${r.clause_id}-${idx}`}
              result={r}
            />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
