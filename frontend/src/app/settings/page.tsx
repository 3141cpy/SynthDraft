"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Plus,
  Settings as SettingsIcon,
  Type,
  Eye,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  EmptyState,
  ErrorState,
  LoadingState,
} from "@/components/shared/States";
import { ProviderConfigCard } from "@/components/settings/ProviderConfigCard";
import { ProviderConfigForm } from "@/components/settings/ProviderConfigForm";
import { getAIConfigs } from "@/lib/api";
import type { AIProviderConfig, ConfigRole } from "@/lib/types";

/** 每个 role 的展示元数据：标签、图标、空状态文案。 */
const ROLE_TAB_META: Record<
  ConfigRole,
  {
    label: string;
    icon: typeof Type;
    emptyTitle: string;
    emptyDescription: string;
  }
> = {
  llm: {
    label: "文本模型",
    icon: Type,
    emptyTitle: "暂无文本模型配置",
    emptyDescription:
      "点击「新增配置」添加第一个文本模型。\n支持 Ollama / OpenAI 兼容 / Anthropic Claude。",
  },
  vlm: {
    label: "视觉模型",
    icon: Eye,
    emptyTitle: "暂无视觉模型配置",
    emptyDescription:
      "点击「新增配置」添加第一个视觉模型。\n支持 Ollama / OpenAI 兼容 / Anthropic Claude。",
  },
};

export default function SettingsPage() {
  const [configs, setConfigs] = useState<AIProviderConfig[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 当前激活的 Tab：决定新增配置时默认的 role
  const [activeRole, setActiveRole] = useState<ConfigRole>("llm");

  // 新增/编辑对话框状态
  const [formOpen, setFormOpen] = useState(false);
  const [editingConfig, setEditingConfig] = useState<AIProviderConfig | null>(
    null,
  );

  const fetchConfigs = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // 一次性拉取全部配置，前端按 role 过滤分到两个 Tab 展示，
      // 避免切换 Tab 时重复请求，也便于顶部统计一致
      const data = await getAIConfigs();
      setConfigs(data);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      setConfigs([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchConfigs();
  }, [fetchConfigs]);

  const handleOpenCreate = useCallback(() => {
    setEditingConfig(null);
    setFormOpen(true);
  }, []);

  const handleOpenEdit = useCallback((config: AIProviderConfig) => {
    setEditingConfig(config);
    setFormOpen(true);
  }, []);

  // 按 role 拆分配置列表
  const llmConfigs = useMemo(
    () => configs.filter((c) => c.role === "llm"),
    [configs],
  );
  const vlmConfigs = useMemo(
    () => configs.filter((c) => c.role === "vlm"),
    [configs],
  );
  const llmActiveCount = llmConfigs.filter((c) => c.is_active).length;
  const vlmActiveCount = vlmConfigs.filter((c) => c.is_active).length;

  /** 渲染单个 Tab 内的配置列表。 */
  const renderTabList = useCallback(
    (role: ConfigRole) => {
      const meta = ROLE_TAB_META[role];
      const list = role === "llm" ? llmConfigs : vlmConfigs;
      const activeCount = role === "llm" ? llmActiveCount : vlmActiveCount;

      if (loading) {
        return <LoadingState text={`正在加载${meta.label}配置...`} />;
      }
      if (error) {
        return <ErrorState description={error} onRetry={fetchConfigs} />;
      }
      if (list.length === 0) {
        return (
          <EmptyState
            icon={meta.icon}
            title={meta.emptyTitle}
            description={meta.emptyDescription}
            action={
              <Button
                onClick={handleOpenCreate}
                disabled={loading || error !== null}
              >
                <Plus className="h-4 w-4" />
                新增{meta.label}配置
              </Button>
            }
          />
        );
      }
      return (
        <div className="flex flex-col gap-3">
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>
              共 <span className="font-medium text-foreground">{list.length}</span> 项
              {activeCount > 0 && (
                <>
                  {" · "}
                  <span className="font-medium text-foreground">{activeCount}</span> 项活跃
                </>
              )}
            </span>
          </div>
          <div className="flex flex-col gap-4">
            {list.map((config) => (
              <ProviderConfigCard
                key={config.id}
                config={config}
                onEdit={handleOpenEdit}
                onChanged={fetchConfigs}
              />
            ))}
          </div>
        </div>
      );
    },
    [
      llmConfigs,
      vlmConfigs,
      llmActiveCount,
      vlmActiveCount,
      loading,
      error,
      fetchConfigs,
      handleOpenCreate,
      handleOpenEdit,
    ],
  );

  // 顶部统计：仅在非空时展示总数
  const totalActive = llmActiveCount + vlmActiveCount;

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <SettingsIcon className="h-6 w-6 text-muted-foreground" />
          <h1 className="text-2xl font-semibold tracking-tight">设置</h1>
        </div>
        {configs.length > 0 && (
          <div className="text-sm text-muted-foreground">
            共 <span className="font-medium text-foreground">{configs.length}</span> 项
            {totalActive > 0 && (
              <>
                {" · "}
                <span className="font-medium text-foreground">{totalActive}</span> 项活跃
              </>
            )}
          </div>
        )}
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="space-y-1.5">
              <CardTitle className="text-base">AI Provider 配置</CardTitle>
              <CardDescription>
                分别配置文本模型与视觉模型，激活后立即生效。两类配置相互独立，互不影响。
              </CardDescription>
            </div>
            <Button
              variant="default"
              onClick={handleOpenCreate}
              disabled={loading}
            >
              <Plus className="h-4 w-4" />
              新增{ROLE_TAB_META[activeRole].label}配置
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <Tabs
            value={activeRole}
            onValueChange={(v) => setActiveRole(v as ConfigRole)}
            className="w-full"
          >
            <TabsList className="grid w-full max-w-md grid-cols-2">
              <TabsTrigger value="llm" className="gap-1.5">
                <Type className="h-3.5 w-3.5" />
                文本模型
              </TabsTrigger>
              <TabsTrigger value="vlm" className="gap-1.5">
                <Eye className="h-3.5 w-3.5" />
                视觉模型
              </TabsTrigger>
            </TabsList>
            <TabsContent value="llm" className="mt-4">
              {renderTabList("llm")}
            </TabsContent>
            <TabsContent value="vlm" className="mt-4">
              {renderTabList("vlm")}
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>

      <ProviderConfigForm
        open={formOpen}
        onOpenChange={setFormOpen}
        editingConfig={editingConfig}
        defaultRole={activeRole}
        onSaved={fetchConfigs}
      />
    </div>
  );
}
