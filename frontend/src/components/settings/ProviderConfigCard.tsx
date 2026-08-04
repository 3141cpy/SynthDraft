"use client";

import { useCallback, useState } from "react";
import {
  Box,
  Cloud,
  Loader2,
  type LucideIcon,
  Server,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
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
import { MetaRow } from "@/components/shared/MetaRow";
import { activateAIConfig, deleteAIConfig, testAIConfig } from "@/lib/api";
import type {
  AIConfigTestResult,
  AIProviderConfig,
  ConfigRole,
  ProviderType,
} from "@/lib/types";

/** Provider 类型显示标签。 */
const PROVIDER_LABELS: Record<ProviderType, string> = {
  ollama: "Ollama",
  openai_compatible: "OpenAI 兼容",
  anthropic: "Anthropic",
};

/** Provider 类型图标。 */
const PROVIDER_ICONS: Record<ProviderType, LucideIcon> = {
  ollama: Server,
  openai_compatible: Cloud,
  anthropic: Box,
};

/** 按 role 渲染差异化文案与视觉标识。
 *
 * - 色条：LLM 用 primary（蓝），VLM 用 amber（橙），让用户一眼区分两类配置
 * - 徽章：标注"文本模型"/"视觉模型"
 * - 模型字段标签：LLM 显示"文本模型"，VLM 显示"视觉模型"
 */
const ROLE_META: Record<
  ConfigRole,
  {
    badge: string;
    badgeVariant: "default" | "secondary";
    /** 左侧色条 Tailwind class（仅活跃时生效）。 */
    activeBorder: string;
    /** 模型字段标签。 */
    modelLabel: string;
    /** 从 config 中取对应模型字段值。 */
    modelField: "model" | "vlm_model";
    /** 空值时的占位提示。 */
    emptyHint: string;
  }
> = {
  llm: {
    badge: "文本模型",
    badgeVariant: "default",
    activeBorder: "border-l-primary",
    modelLabel: "文本模型",
    modelField: "model",
    emptyHint: "未配置",
  },
  vlm: {
    badge: "视觉模型",
    badgeVariant: "secondary",
    activeBorder: "border-l-amber-500",
    modelLabel: "视觉模型",
    modelField: "vlm_model",
    emptyHint: "未配置",
  },
};

interface ProviderConfigCardProps {
  config: AIProviderConfig;
  onEdit: (config: AIProviderConfig) => void;
  /** 操作完成后的刷新回调（激活/删除）。 */
  onChanged: () => void;
}

export function ProviderConfigCard({
  config,
  onEdit,
  onChanged,
}: ProviderConfigCardProps) {
  const [activating, setActivating] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<AIConfigTestResult | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const handleActivate = useCallback(async () => {
    setActivating(true);
    try {
      await activateAIConfig(config.id);
      toast.success(`已激活配置：${config.name}`);
      onChanged();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`激活失败: ${msg}`);
    } finally {
      setActivating(false);
    }
  }, [config.id, config.name, onChanged]);

  const handleTest = useCallback(async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const result = await testAIConfig(config.id);
      setTestResult(result);
      if (result.available) {
        toast.success(`连接成功（${result.latency_ms}ms）`);
      } else {
        toast.error(`连接失败: ${result.error || "未知错误"}`);
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`测试连接失败: ${msg}`);
    } finally {
      setTesting(false);
    }
  }, [config.id]);

  const handleDelete = useCallback(async () => {
    setDeleting(true);
    try {
      await deleteAIConfig(config.id);
      toast.success(`已删除配置：${config.name}`);
      setDeleteOpen(false);
      onChanged();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`删除失败: ${msg}`);
    } finally {
      setDeleting(false);
    }
  }, [config.id, config.name, onChanged]);

  const hasApiKey = config.api_key === "***";
  const ProviderIcon = PROVIDER_ICONS[config.provider_type] ?? Server;
  const providerLabel =
    PROVIDER_LABELS[config.provider_type] ?? config.provider_type;
  const roleMeta = ROLE_META[config.role];
  const modelValue = config[roleMeta.modelField];

  // 活跃色条：按 role 区分颜色，让用户在双列表中快速识别
  const activeBorderClass = config.is_active ? roleMeta.activeBorder : undefined;

  return (
    <Card className={activeBorderClass ? `border-l-4 ${activeBorderClass}` : undefined}>
      <CardHeader>
        <div className="flex items-start gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
            <ProviderIcon className="h-5 w-5" />
          </div>
          <div className="flex flex-col gap-1">
            <CardTitle className="flex flex-wrap items-center gap-2 text-base">
              {config.name}
              <Badge variant={roleMeta.badgeVariant} className="text-[10px]">
                {roleMeta.badge}
              </Badge>
              {config.is_active && (
                <span className="text-xs font-medium text-primary">活跃</span>
              )}
            </CardTitle>
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
              <span>{providerLabel}</span>
              <span aria-hidden className="text-muted-foreground/40">
                ·
              </span>
              <span>{hasApiKey ? "已配置 Key" : "无需 Key"}</span>
            </div>
          </div>
        </div>
      </CardHeader>

      <CardContent className="flex flex-col gap-3">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <MetaRow label="Base URL" value={config.base_url} />
          <MetaRow
            label={roleMeta.modelLabel}
            value={modelValue || roleMeta.emptyHint}
          />
        </div>

        {/* 测试连接结果 —— 按 role 展示对应模型可用性
            split-llm-vlm-config 后 VLM 状态由独立配置决定，
            本卡片只展示当前 role 配置的探测结果，不再混展 LLM/VLM 两栏 */}
        {testResult && (
          <div
            className={
              "flex flex-col gap-1 rounded-md border-l-2 bg-muted/40 p-2.5 text-xs " +
              (testResult.available
                ? "border-l-green-500"
                : "border-l-red-500")
            }
          >
            {testResult.available ? (
              <div className="flex items-center gap-2">
                <span className="font-medium text-green-600 dark:text-green-500">
                  连接成功
                </span>
                <span className="text-muted-foreground">
                  延迟 {testResult.latency_ms}ms
                </span>
              </div>
            ) : (
              <>
                <div className="font-medium text-red-600 dark:text-red-500">
                  连接失败
                </div>
                <div className="text-destructive break-all">
                  {testResult.error || "未知错误"}
                </div>
              </>
            )}
          </div>
        )}
      </CardContent>

      <Separator />

      <CardFooter className="flex flex-wrap items-center gap-2">
        <Button
          variant={config.is_active ? "secondary" : "default"}
          size="sm"
          onClick={handleActivate}
          disabled={config.is_active || activating || deleting}
        >
          {activating ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              激活中...
            </>
          ) : config.is_active ? (
            "当前活跃"
          ) : (
            "激活"
          )}
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={handleTest}
          disabled={testing || activating || deleting}
        >
          {testing ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              测试中...
            </>
          ) : (
            "测试连接"
          )}
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={() => onEdit(config)}
          disabled={testing || activating || deleting}
        >
          编辑
        </Button>
        <Button
          variant="destructive"
          size="sm"
          className="ml-auto"
          onClick={() => setDeleteOpen(true)}
          disabled={testing || activating || deleting}
        >
          <Trash2 className="h-4 w-4" />
          删除
        </Button>
      </CardFooter>

      {/* 删除确认 */}
      <AlertDialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>确认删除配置</AlertDialogTitle>
            <AlertDialogDescription>
              将删除配置「{config.name}」，此操作不可撤销。{config.is_active && "该配置当前为活跃状态，删除后将无活跃配置。"}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>取消</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDelete}
              disabled={deleting}
              className="bg-destructive text-destructive-foreground shadow-sm hover:bg-destructive/90"
            >
              {deleting ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  删除中...
                </>
              ) : (
                "确认删除"
              )}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  );
}
