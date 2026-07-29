"use client";

import { useCallback, useState } from "react";
import {
  Database,
  Loader2,
  RefreshCw,
  RotateCcw,
} from "lucide-react";
import { toast } from "sonner";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { apiFetch } from "@/lib/api";
import type { ReindexResponse } from "@/lib/types";
import {
  EmptyState,
  ErrorState,
  LoadingState,
} from "@/components/shared/States";

interface StandardsListProps {
  standards: string[];
  loading: boolean;
  error: string | null;
  onRetry: () => void;
}

export function StandardsList({
  standards,
  loading,
  error,
  onRetry,
}: StandardsListProps) {
  const [reindexing, setReindexing] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const handleReindex = useCallback(async () => {
    setConfirmOpen(false);
    setReindexing(true);
    try {
      const res = await apiFetch<ReindexResponse>(`/kb/reindex`, {
        method: "POST",
      });
      toast.success(
        `索引重建完成：已索引 ${res.indexed_count} 条条款`,
      );
      onRetry();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`重建索引失败: ${msg}`);
    } finally {
      setReindexing(false);
    }
  }, [onRetry]);

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-2">
          <div className="space-y-1.5">
            <CardTitle className="flex items-center gap-2 text-base">
              <Database className="h-4 w-4 text-muted-foreground" />
              已索引规范
            </CardTitle>
            <CardDescription>
              知识库中已建立向量索引的工程设计国家标准。
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={onRetry}
              disabled={loading || reindexing}
            >
              <RefreshCw className="h-4 w-4" />
              刷新
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setConfirmOpen(true)}
              disabled={reindexing}
            >
              {reindexing ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  重建中...
                </>
              ) : (
                <>
                  <RotateCcw className="h-4 w-4" />
                  重建索引
                </>
              )}
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {loading ? (
          <LoadingState text="正在加载规范列表..." />
        ) : error ? (
          <ErrorState description={error} onRetry={onRetry} />
        ) : standards.length === 0 ? (
          <EmptyState
            icon={Database}
            title="暂无已索引规范"
            description='请点击"重建索引"'
          />
        ) : (
          <>
            <div className="text-sm text-muted-foreground">
              共 <span className="font-medium text-foreground">{standards.length}</span> 项规范
            </div>
            <div className="flex flex-wrap gap-2">
              {standards.map((s) => (
                <Badge key={s} variant="secondary" className="font-normal">
                  {s}
                </Badge>
              ))}
            </div>
          </>
        )}
        {reindexing && (
          <div className="flex items-center gap-2 rounded-md border border-border bg-muted/40 p-2 text-xs text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            正在重建向量索引，可能需要 5-30 秒，请勿离开页面...
          </div>
        )}
      </CardContent>

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>确认重建索引</DialogTitle>
            <DialogDescription>
              将从 kb/standards/ 目录重新构建向量索引，会删除并重建 Qdrant collection。这是一个耗时操作（约 5-30 秒），期间检索功能可能不可用。确认继续？
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setConfirmOpen(false)}
              disabled={reindexing}
            >
              取消
            </Button>
            <Button onClick={handleReindex} disabled={reindexing}>
              确认重建
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
