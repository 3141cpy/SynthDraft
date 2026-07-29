"use client";

import {
  AlertCircle,
  Loader2,
  RotateCcw,
  type LucideIcon,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

export interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  description?: string;
  action?: React.ReactNode;
}

/** 空状态：居中图标 + 标题 + 描述 + 可选动作。 */
export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
}: EmptyStateProps) {
  return (
    <Card>
      <CardContent className="flex flex-col items-center justify-center gap-3 py-12 text-center">
        <Icon className="h-10 w-10 text-muted-foreground" />
        <div className="space-y-1">
          <div className="text-sm font-medium">{title}</div>
          {description && (
            <div className="whitespace-pre-line text-sm text-muted-foreground">
              {description}
            </div>
          )}
        </div>
        {action}
      </CardContent>
    </Card>
  );
}

export interface LoadingStateProps {
  text?: string;
}

/** 加载状态：旋转 Loader2 + 文案，默认"加载中..."。 */
export function LoadingState({ text = "加载中..." }: LoadingStateProps) {
  return (
    <Card>
      <CardContent className="flex items-center justify-center gap-2 py-12 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        {text}
      </CardContent>
    </Card>
  );
}

export interface ErrorStateProps {
  title?: string;
  description: string;
  onRetry?: () => void;
}

/** 错误状态：AlertCircle + 标题 + 描述 + 可选重试按钮。 */
export function ErrorState({
  title = "加载失败",
  description,
  onRetry,
}: ErrorStateProps) {
  return (
    <Card>
      <CardContent className="flex flex-col items-center justify-center gap-3 py-12 text-center">
        <AlertCircle className="h-10 w-10 text-destructive" />
        <div className="space-y-1">
          <div className="text-sm font-medium text-destructive">{title}</div>
          <div className="text-sm text-muted-foreground">{description}</div>
        </div>
        {onRetry && (
          <Button variant="outline" size="sm" onClick={onRetry}>
            <RotateCcw className="h-4 w-4" />
            重试
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
