/**
 * 文件上传 hook：封装拖拽、onChange、大小/类型校验、上传请求与错误处理。
 *
 * 抽离自原 components/review/FileUploader.tsx 与 components/generate/InputTabs.tsx
 * 中重复的内联拖拽 + 上传逻辑。`uploaded` 为受控值（来自父组件），上传成功
 * 通过 onUploaded 回调通知父组件，清除通过 onClear 回调。
 *
 * 返回 dragProps 可直接展开到拖拽容器上。
 */
import { useCallback, useMemo, useRef, useState } from "react";
import type { DragEvent } from "react";
import { toast } from "sonner";
import { apiUpload } from "@/lib/api";
import { formatSize, getExtension } from "@/lib/format";
import type { UploadResponse } from "@/lib/types";

export interface UseFileUploadOptions {
  /** <input accept> 属性值，如 ".pdf,.png,.jpg,.jpeg,.dwg,.dxf"。 */
  accept: string;
  /** 单文件最大体积（MB）。 */
  maxSizeMB: number;
  /** 上传端点路径，默认 "/uploads"（与原 FileUploader/SketchUploader 对齐）。 */
  endpoint?: string;
  /** 当前已上传文件（受控值，来自父组件）。 */
  uploaded: UploadResponse | null;
  /** 上传成功回调。 */
  onUploaded: (resp: UploadResponse) => void;
  /** 清除回调。 */
  onClear: () => void;
  /** 禁用交互。 */
  disabled?: boolean;
  /** 上传成功 toast 文案。 */
  successMessage?: string;
}

export interface DragProps {
  onDrop: (e: DragEvent<HTMLDivElement>) => void;
  onDragOver: (e: DragEvent<HTMLDivElement>) => void;
  onDragLeave: (e: DragEvent<HTMLDivElement>) => void;
}

export interface UseFileUploadReturn {
  isDragging: boolean;
  uploading: boolean;
  error: string | null;
  uploaded: UploadResponse | null;
  upload: (file: File) => Promise<void>;
  clear: () => void;
  dragProps: DragProps;
}

/**
 * 从 accept 属性解析允许的扩展名列表（小写、无点）。
 *
 * 仅取点前缀 token（如 ".pdf" → "pdf"），忽略 MIME 类型 token（如 "image/png"）。
 * SKETCH_ACCEPT 中的 image/png 与 .png 重复，去重后得到 ["png","jpg","jpeg"]。
 */
function parseAllowedExtensions(accept: string): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const raw of accept.split(",")) {
    const token = raw.trim().toLowerCase();
    if (!token.startsWith(".")) continue;
    const ext = token.slice(1);
    if (!ext || seen.has(ext)) continue;
    seen.add(ext);
    result.push(ext);
  }
  return result;
}

export function useFileUpload(
  options: UseFileUploadOptions,
): UseFileUploadReturn {
  const {
    accept,
    maxSizeMB,
    endpoint = "/uploads",
    uploaded,
    onUploaded,
    onClear,
    disabled = false,
    successMessage = "文件上传成功",
  } = options;

  const [isDragging, setIsDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const uploadControllerRef = useRef<AbortController | null>(null);

  const allowedExtensions = useMemo(
    () => parseAllowedExtensions(accept),
    [accept],
  );

  const upload = useCallback(
    async (file: File) => {
      const ext = getExtension(file.name);
      if (!allowedExtensions.includes(ext)) {
        const msg = `不支持的文件格式 ${ext || "(无后缀)"}，仅支持 ${allowedExtensions
          .join(" / ")
          .toUpperCase()}`;
        setError(msg);
        toast.error(msg);
        return;
      }
      if (file.size > maxSizeMB * 1024 * 1024) {
        const msg = `文件过大（${formatSize(file.size)}），上限 ${maxSizeMB} MB`;
        setError(msg);
        toast.error(msg);
        return;
      }
      setError(null);
      setUploading(true);
      const controller = new AbortController();
      uploadControllerRef.current = controller;
      try {
        const data = await apiUpload(file, endpoint, controller.signal);
        if (controller.signal.aborted) return;
        toast.success(successMessage);
        onUploaded(data);
      } catch (e) {
        if (controller.signal.aborted) return;
        const msg = e instanceof Error ? e.message : String(e);
        setError(msg);
        toast.error(msg);
      } finally {
        setUploading(false);
        uploadControllerRef.current = null;
      }
    },
    [allowedExtensions, maxSizeMB, endpoint, onUploaded, successMessage],
  );

  const clear = useCallback(() => {
    uploadControllerRef.current?.abort();
    uploadControllerRef.current = null;
    setError(null);
    onClear();
  }, [onClear]);

  const onDrop = useCallback(
    (e: DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragging(false);
      if (disabled || uploading) return;
      const files = e.dataTransfer.files;
      if (!files || files.length === 0) return;
      void upload(files[0]);
    },
    [disabled, uploading, upload],
  );

  const onDragOver = useCallback(
    (e: DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      e.stopPropagation();
      if (disabled || uploading) return;
      setIsDragging(true);
    },
    [disabled, uploading],
  );

  const onDragLeave = useCallback(
    (e: DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragging(false);
    },
    [],
  );

  const dragProps: DragProps = { onDrop, onDragOver, onDragLeave };

  return {
    isDragging,
    uploading,
    error,
    uploaded,
    upload,
    clear,
    dragProps,
  };
}
