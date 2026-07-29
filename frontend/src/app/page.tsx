"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  Activity,
  ArrowRight,
  BookOpen,
  FileSearch,
  Wand2,
} from "lucide-react";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { apiFetch } from "@/lib/api";
import { CardSkeleton } from "@/components/shared/Skeleton";
import { ErrorState } from "@/components/shared/States";

/** 工作台入口：图标与 sidebar 保持一致，描述聚焦功能价值。 */
const workbenches = [
  {
    href: "/review",
    title: "审图工作台",
    value: "上传图纸，AI 自动审查合规性",
    description:
      "上传工程图纸，AI 自动审查尺寸标注、形位公差、表面结构等是否符合国标规范，生成结构化审图报告。",
    icon: FileSearch,
  },
  {
    href: "/generate",
    title: "生成工作台",
    value: "描述需求，AI 生成规范工程图元",
    description:
      "基于自然语言描述或参数输入，AI 辅助生成符合规范的工程图元、CAD 中间表达与设计草稿。",
    icon: Wand2,
  },
  {
    href: "/kb",
    title: "知识库",
    value: "检索国标条款，秒级定位依据",
    description:
      "浏览与检索工程设计国家标准（GB/T）知识库，包含制图规则、公差标准、标注方法等结构化条款。",
    icon: BookOpen,
  },
];

type HealthState =
  | { kind: "loading" }
  | { kind: "online" }
  | { kind: "offline"; message: string };

export default function Home() {
  const [health, setHealth] = useState<HealthState>({ kind: "loading" });

  const checkHealth = useCallback(async () => {
    setHealth({ kind: "loading" });
    try {
      await apiFetch<{ status: string }>("/healthz");
      setHealth({ kind: "online" });
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setHealth({ kind: "offline", message: msg });
    }
  }, []);

  useEffect(() => {
    void checkHealth();
  }, [checkHealth]);

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-8">
      <section className="flex flex-col gap-2">
        <h1 className="text-2xl font-semibold tracking-tight">
          SynthDraft 控制台
        </h1>
        <p className="text-muted-foreground">
          AI 驱动工程设计辅助系统，提供工程图纸智能审查、规范合规生成与国家标准知识检索能力。
          后端服务运行于本地 8000 端口，通过 Next.js API 代理访问。
        </p>
      </section>

      {/* 系统状态卡片 */}
      <section>
        {health.kind === "loading" ? (
          <CardSkeleton />
        ) : health.kind === "offline" ? (
          <ErrorState
            title="后端离线"
            description={health.message || "无法连接到后端服务"}
            onRetry={checkHealth}
          />
        ) : (
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <Activity className="h-5 w-5 text-muted-foreground" />
                  <CardTitle className="text-base">系统状态</CardTitle>
                </div>
                <Badge variant="success">后端在线</Badge>
              </div>
              <CardDescription>
                后端服务连通正常，可正常使用审图、生成与知识检索能力。
              </CardDescription>
            </CardHeader>
          </Card>
        )}
      </section>

      <section className="grid gap-4 md:grid-cols-3">
        {workbenches.map((wb) => (
          <Card key={wb.href} className="flex flex-col">
            <CardHeader>
              <div className="flex items-center gap-2">
                <wb.icon className="h-5 w-5 text-muted-foreground" />
                <CardTitle className="text-base">{wb.title}</CardTitle>
              </div>
              <CardDescription className="font-medium text-foreground">
                {wb.value}
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-1 flex-col gap-4">
              <p className="flex-1 text-sm text-muted-foreground">
                {wb.description}
              </p>
              <Button asChild variant="outline" size="sm" className="w-fit">
                <Link href={wb.href}>
                  进入
                  <ArrowRight className="h-3.5 w-3.5" />
                </Link>
              </Button>
            </CardContent>
          </Card>
        ))}
      </section>

      {/* 离线状态额外提示：保留入口但提示后端不可用 */}
      {health.kind === "offline" && (
        <Card>
          <CardContent className="py-4 text-xs text-muted-foreground">
            后端服务暂不可用，部分功能（审图、生成、知识检索）将无法正常响应。请确认本地 8000 端口服务已启动后重试。
          </CardContent>
        </Card>
      )}
    </div>
  );
}
