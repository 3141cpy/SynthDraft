"use client";

import { useCallback, useRef, useState } from "react";
import {
  File as FileIcon,
  Loader2,
  RotateCcw,
  UploadCloud,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { UploadResponse } from "@/lib/types";
import { formatSize, getExtension } from "@/lib/format";
import { apiUpload } from "@/lib/api";

const ACCEPTED_EXTENSIONS = [
  "dxf",
  "dwg",
  "pdf",
  "png",
  "jpg",
  "jpeg",
  "sldprt",
  "sldasm",
  "step",
  "stp",
  "iges",
  "igs",
];
const ACCEPT_ATTR = ACCEPTED_EXTENSIONS.map((ext) => `.${ext}`).join(",");
const MAX_SIZE_MB = 100;

interface FileUploaderProps {
  uploaded: UploadResponse | null;
  onUploaded: (resp: UploadResponse) => void;
  onClear: () => void;
  disabled?: boolean;
}

export function FileUploader({
  uploaded,
  onUploaded,
  onClear,
  disabled,
}: FileUploaderProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  const upload = useCallback(
    async (file: File) => {
      const ext = getExtension(file.name);
      if (!ACCEPTED_EXTENSIONS.includes(ext)) {
        const msg = `不支持的文件格式 ${ext || "(无后缀)"}，仅支持 DXF/DWG/PDF/PNG/JPG/SLDPRT/SLDASM/STEP/IGES`;
        setLocalError(msg);
        toast.error(msg);
        return;
      }
      if (file.size > MAX_SIZE_MB * 1024 * 1024) {
        const msg = `文件过大（${formatSize(file.size)}），上限 ${MAX_SIZE_MB} MB`;
        setLocalError(msg);
        toast.error(msg);
        return;
      }
      setLocalError(null);
      setIsUploading(true);
      try {
        const data = await apiUpload(file, "/uploads");
        toast.success("文件上传成功");
        onUploaded(data);
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        setLocalError(msg);
        toast.error(msg);
      } finally {
        setIsUploading(false);
      }
    },
    [onUploaded],
  );

  const handleFiles = useCallback(
    (files: FileList | null) => {
      if (!files || files.length === 0) return;
      void upload(files[0]);
    },
    [upload],
  );

  const onDrop = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragging(false);
      if (disabled || isUploading) return;
      handleFiles(e.dataTransfer.files);
    },
    [disabled, isUploading, handleFiles],
  );

  const onDragOver = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      e.stopPropagation();
      if (disabled || isUploading) return;
      setIsDragging(true);
    },
    [disabled, isUploading],
  );

  const onDragLeave = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragging(false);
    },
    [],
  );

  const openPicker = () => {
    if (disabled || isUploading) return;
    inputRef.current?.click();
  };

  const isBusy = isUploading;
  const showUploaded = uploaded !== null && !isBusy;

  return (
    <div className="flex flex-col gap-3">
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPT_ATTR}
        aria-label="上传图纸文件"
        className="hidden"
        onChange={(e) => {
          handleFiles(e.target.files);
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
          onDrop={onDrop}
          onDragOver={onDragOver}
          onDragLeave={onDragLeave}
          className={cn(
            "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-6 py-10 text-center transition-colors",
            isDragging
              ? "border-primary bg-accent"
              : "border-border hover:border-primary/50 hover:bg-accent/50",
            (disabled || isBusy) && "pointer-events-none opacity-60",
          )}
        >
          {isBusy ? (
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          ) : (
            <UploadCloud className="h-8 w-8 text-muted-foreground" />
          )}
          <div className="text-sm font-medium">
            {isBusy ? "上传中..." : "拖拽文件到此处，或点击选择"}
          </div>
          <div className="text-xs text-muted-foreground">
            支持 DXF / DWG / PDF / PNG / JPG / SLDPRT / SLDASM / STEP / IGES，单文件 ≤{" "}
            {MAX_SIZE_MB} MB
          </div>
        </div>
      ) : (
        <div className="flex items-start gap-3 rounded-lg border bg-muted/30 p-4">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-primary/10">
            <FileIcon className="h-5 w-5 text-primary" />
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
            onClick={onClear}
            disabled={disabled}
          >
            <RotateCcw className="h-4 w-4" />
            重新选择
          </Button>
        </div>
      )}
      {localError && (
        <p className="text-xs text-destructive">{localError}</p>
      )}
    </div>
  );
}
