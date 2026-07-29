"use client";

/**
 * 可复用的文件拖拽上传组件。
 *
 * 内部使用 useFileUpload hook 处理拖拽 / 校验 / 上传 / 错误。
 * 不同场景通过 accept / maxSize / icon / hint 配置：
 * - 审图图纸：accept=".pdf,.png,.jpg,.jpeg,.dwg,.dxf" maxSize=50 icon=FileSearch
 * - 生成草图：accept=SKETCH_ACCEPT maxSize=20 icon=PencilRuler
 */
import { useRef } from "react";
import type { LucideIcon } from "lucide-react";
import { Loader2, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { formatSize } from "@/lib/format";
import type { UploadResponse } from "@/lib/types";
import { useFileUpload } from "@/lib/useFileUpload";

export interface FileDropZoneProps {
  /** <input accept> 属性值。 */
  accept: string;
  /** 单文件最大体积（MB）。 */
  maxSize: number;
  /** 拖拽区与已上传卡片的图标。 */
  icon: LucideIcon;
  /** 拖拽区底部提示文案。 */
  hint?: string;
  /** 禁用交互。 */
  disabled?: boolean;
  /** 当前已上传文件（受控）。 */
  uploaded: UploadResponse | null;
  /** 上传成功回调。 */
  onUploaded: (resp: UploadResponse) => void;
  /** 清除回调。 */
  onClear: () => void;
  /** 上传端点路径，默认 "/uploads"。 */
  endpoint?: string;
  /** 上传成功 toast 文案。 */
  successMessage?: string;
}

export function FileDropZone({
  accept,
  maxSize,
  icon: Icon,
  hint,
  disabled,
  uploaded,
  onUploaded,
  onClear,
  endpoint,
  successMessage,
}: FileDropZoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);

  const { isDragging, uploading, error, upload, clear, dragProps } =
    useFileUpload({
      accept,
      maxSizeMB: maxSize,
      uploaded,
      onUploaded,
      onClear,
      disabled,
      endpoint,
      successMessage,
    });

  const isBusy = uploading;
  const showUploaded = uploaded !== null && !isBusy;

  const openPicker = () => {
    if (disabled || isBusy) return;
    inputRef.current?.click();
  };

  return (
    <div className="flex flex-col gap-3">
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        aria-label="文件上传"
        className="hidden"
        onChange={(e) => {
          if (e.target.files && e.target.files.length > 0) {
            void upload(e.target.files[0]);
          }
          e.target.value = "";
        }}
      />
      {!showUploaded ? (
        <div
          role="button"
          tabIndex={0}
          onClick={openPicker}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              openPicker();
            }
          }}
          {...dragProps}
          className={cn(
            "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-6 py-10 text-center transition-colors",
            isDragging
              ? "border-primary bg-primary/5"
              : "border-border hover:border-primary/50 hover:bg-accent/50",
            (disabled || isBusy) && "pointer-events-none opacity-60",
          )}
        >
          {isBusy ? (
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          ) : (
            <Icon className="h-8 w-8 text-muted-foreground" />
          )}
          <div className="text-sm font-medium">
            {isBusy ? "上传中..." : "拖拽文件到此处，或点击选择"}
          </div>
          {hint && (
            <div className="text-xs text-muted-foreground">{hint}</div>
          )}
        </div>
      ) : (
        <div className="flex items-start gap-3 rounded-lg border bg-muted/30 p-4">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-primary/10">
            <Icon className="h-5 w-5 text-primary" />
          </div>
          <div className="min-w-0 flex-1 space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="truncate text-sm font-medium">
                {uploaded.file_name}
              </span>
              <Badge variant="secondary" className="uppercase">
                {uploaded.file_type}
              </Badge>
            </div>
            <div className="text-xs text-muted-foreground">
              {formatSize(uploaded.size)} · file_key:{" "}
              <code className="font-mono">{uploaded.file_key}</code>
            </div>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={clear}
            disabled={disabled}
          >
            <X className="h-4 w-4" />
            清除
          </Button>
        </div>
      )}
      {error && <p className="text-sm text-destructive">{error}</p>}
    </div>
  );
}
