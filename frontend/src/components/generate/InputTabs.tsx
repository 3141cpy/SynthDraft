"use client";

import { PencilRuler } from "lucide-react";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { FileDropZone } from "@/components/shared/FileDropZone";
import type { UploadResponse } from "@/lib/types";
import { SKETCH_ACCEPT } from "@/lib/constants";

const SKETCH_MAX_SIZE_MB = 20;
const SKETCH_HINT = "支持 PNG / JPG，单文件 ≤ 20 MB";
const NL_PLACEHOLDER =
  "例如：生成一个直径 50mm、厚度 10mm 的法兰盘，中心孔直径 20mm，4 个均布螺栓孔";

type InputType = "text" | "sketch";

interface InputTabsProps {
  inputType: InputType;
  onInputTypeChange: (v: InputType) => void;
  prompt: string;
  onPromptChange: (v: string) => void;
  sketch: UploadResponse | null;
  onSketchUploaded: (resp: UploadResponse) => void;
  onClearSketch: () => void;
  disabled?: boolean;
}

export function InputTabs({
  inputType,
  onInputTypeChange,
  prompt,
  onPromptChange,
  sketch,
  onSketchUploaded,
  onClearSketch,
  disabled,
}: InputTabsProps) {
  return (
    <Tabs
      value={inputType}
      onValueChange={(v) => onInputTypeChange(v as InputType)}
    >
      <TabsList>
        <TabsTrigger value="text" disabled={disabled}>
          自然语言描述
        </TabsTrigger>
        <TabsTrigger value="sketch" disabled={disabled}>
          草图上传
        </TabsTrigger>
      </TabsList>
      <TabsContent value="text">
        <Textarea
          aria-label="自然语言描述"
          value={prompt}
          onChange={(e) => onPromptChange(e.target.value)}
          placeholder={NL_PLACEHOLDER}
          disabled={disabled}
          className="min-h-[140px] resize-y font-mono text-sm"
        />
        <p className="mt-2 text-xs text-muted-foreground">
          支持中文描述零件的几何参数、特征与尺寸。提交后将由 LLM 生成 CadQuery
          代码并执行。
        </p>
      </TabsContent>
      <TabsContent value="sketch">
        <div className="flex flex-col gap-3">
          <FileDropZone
            accept={SKETCH_ACCEPT}
            maxSize={SKETCH_MAX_SIZE_MB}
            icon={PencilRuler}
            hint={SKETCH_HINT}
            uploaded={sketch}
            onUploaded={onSketchUploaded}
            onClear={onClearSketch}
            disabled={disabled}
            successMessage="草图上传成功"
          />
          {!sketch && (
            <p className="text-xs text-muted-foreground">
              上传草图后系统将基于图像内容生成对应 CadQuery 代码。
            </p>
          )}
        </div>
      </TabsContent>
    </Tabs>
  );
}
