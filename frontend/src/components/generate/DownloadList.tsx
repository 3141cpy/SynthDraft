"use client";

import { useState } from "react";
import { Download, File, FileBox, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { toast } from "@/components/ui/sonner";

interface DownloadListProps {
  /** 已构造好的可访问 URL 列表（相对路径或绝对 URL 均可） */
  urls: string[];
  /** 列表为空时显示的提示文案 */
  emptyHint?: string;
}

function getFileName(url: string): string {
  // 去掉 query 与 hash
  const cleaned = url.split("?")[0]?.split("#")[0] ?? url;
  const slashIdx = cleaned.lastIndexOf("/");
  return slashIdx >= 0 ? cleaned.slice(slashIdx + 1) : cleaned;
}

function getFormat(url: string): string {
  const name = getFileName(url).toLowerCase();
  const idx = name.lastIndexOf(".");
  return idx >= 0 ? name.slice(idx + 1) : "";
}

function isMeshFormat(fmt: string): boolean {
  return fmt === "stl" || fmt === "obj" || fmt === "ply";
}

export function DownloadList({ urls, emptyHint }: DownloadListProps) {
  const [loadingMap, setLoadingMap] = useState<Record<string, boolean>>({});

  if (urls.length === 0) {
    return (
      <div className="rounded-md border border-dashed p-4 text-center text-xs text-muted-foreground">
        {emptyHint ?? "暂无可下载的产物文件"}
      </div>
    );
  }

  const handleDownload = (url: string, name: string) => {
    setLoadingMap((m) => ({ ...m, [url]: true }));
    // 触发原生下载
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    a.target = "_blank";
    a.rel = "noreferrer";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => {
      setLoadingMap((m) => ({ ...m, [url]: false }));
      toast.success("下载已开始");
    }, 2000);
  };

  return (
    <div className="flex flex-col gap-2">
      {urls.map((url, idx) => {
        const name = getFileName(url);
        const fmt = getFormat(url);
        const Icon = isMeshFormat(fmt) ? FileBox : File;
        const loading = !!loadingMap[url];
        return (
          <div
            key={`${url}-${idx}`}
            className="flex items-center justify-between gap-3 rounded-md border bg-muted/30 p-3"
          >
            <div className="flex min-w-0 items-center gap-2">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-primary/10">
                <Icon className="h-4 w-4 text-primary" />
              </div>
              <div className="flex min-w-0 flex-col">
                <span className="truncate font-mono text-xs">{name}</span>
                <span className="text-xs text-muted-foreground">
                  {fmt.toUpperCase() || "未知格式"}
                </span>
              </div>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => handleDownload(url, name)}
              disabled={loading}
            >
              {loading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Download className="h-4 w-4" />
              )}
              {loading ? "下载中…" : "下载"}
            </Button>
          </div>
        );
      })}
    </div>
  );
}
