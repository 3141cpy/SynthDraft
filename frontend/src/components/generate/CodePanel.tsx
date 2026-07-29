"use client";

import { useEffect, useState } from "react";
import { Check, Copy, Loader2, Pencil, Play, RotateCcw } from "lucide-react";
import { toast } from "@/components/ui/sonner";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";

interface CodePanelProps {
  /** 原始生成代码（只读展示） */
  code: string;
  /** 是否处于编辑模式 */
  editMode: boolean;
  /** 切换到编辑模式 */
  onEnterEdit: () => void;
  /** 退出编辑模式（取消） */
  onCancelEdit: () => void;
  /** 提交编辑后的代码进行执行 */
  onExecute: (code: string) => void;
  /** 是否正在执行 */
  executing: boolean;
  /** 是否禁用全部操作（如任务进行中） */
  disabled?: boolean;
}

export function CodePanel({
  code,
  editMode,
  onEnterEdit,
  onCancelEdit,
  onExecute,
  executing,
  disabled,
}: CodePanelProps) {
  const [editedCode, setEditedCode] = useState<string>(code);
  const [copied, setCopied] = useState<boolean>(false);

  // 当原始代码变化或进入编辑模式时，重置编辑缓冲
  useEffect(() => {
    if (!editMode) {
      setEditedCode(code);
    }
  }, [code, editMode]);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      toast.success("代码已复制");
      setTimeout(() => setCopied(false), 2000);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`复制失败: ${msg}`);
    }
  };

  const handleExecute = () => {
    if (!editedCode.trim()) {
      toast.error("代码不能为空");
      return;
    }
    onExecute(editedCode);
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium">生成代码</span>
          <Badge variant="outline" className="font-mono text-xs">
            Python / CadQuery
          </Badge>
          {editMode && (
            <Badge variant="secondary" className="text-xs">
              编辑中
            </Badge>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          {!editMode ? (
            <>
              <Button
                variant="outline"
                size="sm"
                onClick={handleCopy}
                disabled={disabled}
              >
                {copied ? (
                  <Check className="h-4 w-4" />
                ) : (
                  <Copy className="h-4 w-4" />
                )}
                {copied ? "已复制" : "复制代码"}
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={onEnterEdit}
                disabled={disabled || executing}
              >
                <Pencil className="h-4 w-4" />
                编辑并重新执行
              </Button>
            </>
          ) : (
            <>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setEditedCode(code);
                  onCancelEdit();
                }}
                disabled={executing}
              >
                <RotateCcw className="h-4 w-4" />
                取消
              </Button>
              <Button
                size="sm"
                onClick={handleExecute}
                disabled={executing || disabled}
              >
                {executing ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Play className="h-4 w-4" />
                )}
                {executing ? "执行中..." : "执行"}
              </Button>
            </>
          )}
        </div>
      </div>
      <Textarea
        id="generate-code"
        aria-label="生成代码"
        aria-readonly={!editMode}
        value={editMode ? editedCode : code}
        onChange={(e) => setEditedCode(e.target.value)}
        readOnly={!editMode}
        spellCheck={false}
        className={editMode ? "min-h-[360px] resize-y font-mono text-xs" : "min-h-[360px] resize-y bg-muted/30 font-mono text-xs"}
      />
      {editMode && (
        <p className="text-xs text-muted-foreground">
          编辑后点击「执行」将调用 POST /api/v1/generations/execute
          同步运行 CadQuery 代码并返回几何校验与下载链接。
        </p>
      )}
    </div>
  );
}
