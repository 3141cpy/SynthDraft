"use client";

import { useEffect, useState } from "react";
import {
  CheckCircle2,
  Clock,
  Loader2,
  X,
  XCircle,
} from "lucide-react";
import { toast } from "@/components/ui/sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import type { TaskStatus } from "@/lib/types";

/**
 * 合并自 review/TaskProgress 与 generate/TaskProgress。
 *
 * - 默认 STATUS_LABEL 可被 `labels` 覆写（running 默认"运行中"，
 *   审图场景传 { running: "审图中..." }，生成场景传 { running: "生成中..." }）。
 * - `connected` 由 generate 版继承：传入时展示 WS 连接状态徽章。
 * - `onCancel` 提供时在运行中展示"取消"按钮，点击弹 AlertDialog 二次确认，
 *   确认后调用 onCancel 并 toast.warning("任务已取消")。
 * - `connected === false` 时顶部显示 warning Badge "连接中断，重试中…"；
 *   重连成功后切换为 success Badge "已重连"并 2s 后淡出。
 * - `status` 为 null 时回退到 Clock + "等待中"（保留 review 版行为）。
 */
export interface TaskProgressProps {
  taskId: string;
  status: TaskStatus | string | null;
  progress: number;
  error: string | null;
  connected?: boolean;
  labels?: Partial<Record<string, string>>;
  /** 运行中取消任务回调，提供时展示"取消"按钮 */
  onCancel?: () => Promise<void> | void;
}

const DEFAULT_STATUS_LABEL: Record<string, string> = {
  queued: "排队中",
  running: "运行中",
  pending: "排队中",
  succeeded: "已完成",
  failed: "已失败",
  canceled: "已取消",
  unknown: "等待中",
};

export function TaskProgress({
  taskId,
  status,
  progress,
  error,
  connected,
  labels,
  onCancel,
}: TaskProgressProps) {
  const STATUS_LABEL = { ...DEFAULT_STATUS_LABEL, ...labels };

  const isRunning =
    status === "queued" || status === "running" || status === "pending";
  const isFailed = status === "failed" || status === "canceled";
  const isDone = status === "succeeded";

  // === 取消任务 AlertDialog 状态 ===
  const [cancelDialogOpen, setCancelDialogOpen] = useState(false);
  const [canceling, setCanceling] = useState(false);

  const handleCancelClick = () => {
    setCancelDialogOpen(true);
  };

  const handleCancelConfirm = async () => {
    if (!onCancel) return;
    setCanceling(true);
    try {
      await onCancel();
      toast.warning("任务已取消");
      setCancelDialogOpen(false);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`取消任务失败: ${msg}`);
    } finally {
      setCanceling(false);
    }
  };

  // === 重连徽章状态：跟踪 connected 变化 ===
  // disconnected: 连接中断，显示 warning "连接中断，重试中…"
  // reconnected: 刚重连成功，显示 success "已重连" 2s 后淡出
  const [reconnected, setReconnected] = useState(false);
  const [prevConnected, setPrevConnected] = useState<boolean | undefined>(
    connected,
  );

  useEffect(() => {
    if (prevConnected === false && connected === true) {
      // 从断开到连接：显示"已重连"
      setReconnected(true);
      const timer = setTimeout(() => setReconnected(false), 2000);
      return () => clearTimeout(timer);
    }
    setPrevConnected(connected);
  }, [connected, prevConnected]);

  const showDisconnectedBadge = connected === false;
  const showReconnectedBadge = connected === true && reconnected;

  return (
    <div className="flex flex-col gap-3">
      {/* 重连状态徽章 */}
      {showDisconnectedBadge && (
        <Badge variant="warning" className="w-fit animate-in fade-in">
          连接中断，重试中…
        </Badge>
      )}
      {showReconnectedBadge && (
        <Badge
          variant="success"
          className="w-fit animate-in fade-in"
        >
          已重连
        </Badge>
      )}

      <div className="flex items-center justify-between gap-2 text-sm">
        <div className="flex items-center gap-2">
          {isRunning && (
            <Loader2 className="h-4 w-4 animate-spin text-primary" />
          )}
          {isDone && (
            <CheckCircle2 className="h-4 w-4 text-success" />
          )}
          {isFailed && (
            <XCircle className="h-4 w-4 text-destructive" />
          )}
          {!status && (
            <Clock className="h-4 w-4 text-muted-foreground" />
          )}
          <span className="font-medium">
            {STATUS_LABEL[status ?? "unknown"] ?? "等待中"}
          </span>
          {connected !== undefined && !showDisconnectedBadge && !showReconnectedBadge && (
            <Badge variant="outline" className="text-xs">
              {connected ? "WS 已连接" : "WS 未连接"}
            </Badge>
          )}
        </div>
        <div className="flex items-center gap-2">
          {isRunning && onCancel && (
            <Button
              variant="ghost"
              size="sm"
              onClick={handleCancelClick}
              disabled={canceling}
              className="h-7 px-2 text-xs text-muted-foreground"
            >
              <X className="h-3 w-3" />
              取消
            </Button>
          )}
          <Badge variant="outline" className="font-mono text-xs">
            任务 ID: {taskId}
          </Badge>
        </div>
      </div>
      {isRunning && (
        <div className="flex flex-col gap-1">
          <Progress value={progress} />
          <div className="flex justify-between text-xs text-muted-foreground">
            <span>{STATUS_LABEL[status ?? "unknown"]}</span>
            <span className="tabular-nums">{progress}%</span>
          </div>
        </div>
      )}
      {isFailed && error && (
        <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
          {error}
        </div>
      )}

      {/* 取消任务二次确认 */}
      <AlertDialog
        open={cancelDialogOpen}
        onOpenChange={setCancelDialogOpen}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>确认取消任务？</AlertDialogTitle>
            <AlertDialogDescription>
              取消后正在进行的任务将终止，且无法恢复。此操作不可撤销。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={canceling}>继续等待</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleCancelConfirm}
              disabled={canceling}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {canceling ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  取消中...
                </>
              ) : (
                "确认取消"
              )}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
