"use client";

import { useCallback, useEffect, useState } from "react";
import { Eye, EyeOff, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { createAIConfig, updateAIConfig } from "@/lib/api";
import type {
  AIProviderConfig,
  AIProviderConfigCreate,
  AIProviderConfigUpdate,
  ConfigRole,
  ProviderType,
} from "@/lib/types";

/** Provider 类型选项：label + 选中后自动填充的默认 base_url。 */
const PROVIDER_OPTIONS: Record<
  ProviderType,
  { label: string; baseUrl: string }
> = {
  ollama: {
    label: "Ollama（本地）",
    baseUrl: "http://localhost:11434",
  },
  openai_compatible: {
    label: "OpenAI 兼容（OpenAI/DeepSeek/通义千问/vLLM 等）",
    baseUrl: "https://api.openai.com/v1",
  },
  anthropic: {
    label: "Anthropic Claude",
    baseUrl: "https://api.anthropic.com",
  },
};

/** 按 role 渲染差异化文案，保持两端标签 / 占位符 / 标题一致。 */
const ROLE_COPY: Record<
  ConfigRole,
  {
    /** 对话框标题用。 */
    titleNoun: string;
    /** 顶部说明。 */
    description: string;
    /** 模型字段标签。 */
    modelLabel: string;
    /** 模型字段占位符。 */
    modelPlaceholder: string;
    /** 模型字段为空时的校验提示。 */
    modelRequired: string;
    /** 模型字段下方的辅助说明。 */
    modelHint: string;
  }
> = {
  llm: {
    titleNoun: "文本模型",
    description: "配置文本模型（LLM），用于规范审查与代码生成",
    modelLabel: "文本模型名称",
    modelPlaceholder: "如：qwen2.5-coder:7b / gpt-4o-mini / claude-3-5-sonnet",
    modelRequired: "请填写文本模型名称",
    modelHint: "用于工程图审查的规范匹配与缺陷判定",
  },
  vlm: {
    titleNoun: "视觉模型",
    description: "配置视觉模型（VLM），用于图纸区域识别与 OCR 提取",
    modelLabel: "视觉模型名称",
    modelPlaceholder: "如：qwen2.5-vl:7b / gpt-4o / llama3.2-vision:11b",
    modelRequired: "请填写视觉模型名称",
    modelHint: "用于识别工程图标题栏 / 标注区 / 视图区并提取文字信息",
  },
};

interface ProviderConfigFormProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** 编辑模式传入原配置；新增模式传 null。 */
  editingConfig: AIProviderConfig | null;
  /** 新增模式下的目标 role。编辑模式下以 ``editingConfig.role`` 为准并忽略此值。 */
  defaultRole?: ConfigRole;
  /** 保存成功后回调（通常为刷新列表）。 */
  onSaved: () => void;
}

interface FormState {
  name: string;
  provider_type: ProviderType;
  base_url: string;
  api_key: string;
  model: string;
  vlm_model: string;
}

interface FormErrors {
  name?: string;
  base_url?: string;
  model?: string;
}

const EMPTY_FORM: FormState = {
  name: "",
  provider_type: "ollama",
  base_url: PROVIDER_OPTIONS.ollama.baseUrl,
  api_key: "",
  model: "",
  vlm_model: "",
};

/** 校验 URL 是否合法（仅接受 http/https）。 */
function isValidUrl(value: string): boolean {
  try {
    const u = new URL(value);
    return u.protocol === "http:" || u.protocol === "https:";
  } catch {
    return false;
  }
}

export function ProviderConfigForm({
  open,
  onOpenChange,
  editingConfig,
  defaultRole = "llm",
  onSaved,
}: ProviderConfigFormProps) {
  const isEditing = editingConfig !== null;
  // role 在编辑模式下固定为 editingConfig.role；新增模式下用 defaultRole
  const role: ConfigRole = editingConfig?.role ?? defaultRole;
  const copy = ROLE_COPY[role];
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [errors, setErrors] = useState<FormErrors>({});
  const [showApiKey, setShowApiKey] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  // 对话框打开或编辑目标变化时重置表单
  useEffect(() => {
    if (!open) return;
    if (editingConfig) {
      setForm({
        name: editingConfig.name,
        provider_type: editingConfig.provider_type,
        base_url: editingConfig.base_url,
        // api_key 脱敏返回 "***" 或 ""，编辑时不回填，留空表示不修改
        api_key: "",
        // 按 role 只回填对应字段，另一字段留空（避免展示无关脏数据）
        model: editingConfig.role === "llm" ? editingConfig.model : "",
        vlm_model: editingConfig.role === "vlm" ? editingConfig.vlm_model : "",
      });
    } else {
      setForm(EMPTY_FORM);
    }
    setErrors({});
    setShowApiKey(false);
  }, [open, editingConfig]);

  const validate = useCallback((): FormErrors => {
    const next: FormErrors = {};
    if (form.name.trim().length < 1) {
      next.name = "请填写配置名称";
    }
    if (form.base_url.trim().length < 1) {
      next.base_url = "请填写 Base URL";
    } else if (!isValidUrl(form.base_url.trim())) {
      next.base_url = "请填写合法的 URL（需以 http:// 或 https:// 开头）";
    }
    // 按 role 校验对应模型字段必填
    const modelValue = role === "llm" ? form.model : form.vlm_model;
    if (modelValue.trim().length < 1) {
      next.model = copy.modelRequired;
    }
    return next;
  }, [form, role, copy]);

  const handleProviderTypeChange = useCallback((value: ProviderType) => {
    // provider 类型切换时自动填充默认 base_url，减少手动输入
    setForm((prev) => ({
      ...prev,
      provider_type: value,
      base_url: PROVIDER_OPTIONS[value].baseUrl,
    }));
  }, []);

  const handleSubmit = useCallback(async () => {
    const nextErrors = validate();
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) return;

    setSubmitting(true);
    try {
      if (isEditing && editingConfig) {
        const payload: AIProviderConfigUpdate = {
          name: form.name.trim(),
          provider_type: form.provider_type,
          base_url: form.base_url.trim(),
        };
        // 按 role 只回传对应模型字段，另一字段传空串清空（保持 DB 一致性）
        if (role === "llm") {
          payload.model = form.model.trim();
          payload.vlm_model = "";
        } else {
          payload.vlm_model = form.vlm_model.trim();
          payload.model = "";
        }
        // api_key 留空表示不修改；有输入则更新（含清空）
        if (form.api_key.length > 0) {
          payload.api_key = form.api_key;
        }
        await updateAIConfig(editingConfig.id, payload);
        toast.success("配置已更新");
      } else {
        const payload: AIProviderConfigCreate = {
          name: form.name.trim(),
          provider_type: form.provider_type,
          base_url: form.base_url.trim(),
          api_key: form.api_key,
          role,
          // 按 role 填充对应模型字段，另一字段传空串
          model: role === "llm" ? form.model.trim() : "",
          vlm_model: role === "vlm" ? form.vlm_model.trim() : "",
        };
        await createAIConfig(payload);
        toast.success("配置已新增");
      }
      onSaved();
      onOpenChange(false);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`保存配置失败: ${msg}`);
    } finally {
      setSubmitting(false);
    }
  }, [validate, isEditing, editingConfig, form, role, onSaved, onOpenChange]);

  const apiKeyPlaceholder = isEditing
    ? "留空表示不修改"
    : "本地模型无需填写";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {isEditing
              ? `编辑${copy.titleNoun}配置`
              : `新增${copy.titleNoun}配置`}
          </DialogTitle>
          <DialogDescription>{copy.description}</DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-4">
          {/* 基础信息 */}
          <div className="flex flex-col gap-4">
            <div className="text-sm font-medium text-foreground">基础信息</div>
            {/* 配置名称 */}
            <div className="flex flex-col gap-2">
              <Label htmlFor="ai-config-name">配置名称</Label>
              <Input
                id="ai-config-name"
                placeholder="如：本地 Ollama"
                value={form.name}
                onChange={(e) =>
                  setForm((prev) => ({ ...prev, name: e.target.value }))
                }
                disabled={submitting}
                aria-invalid={Boolean(errors.name)}
                aria-describedby={errors.name ? "ai-config-name-error" : undefined}
              />
              {errors.name && (
                <span
                  id="ai-config-name-error"
                  className="text-xs text-destructive"
                  role="alert"
                >
                  {errors.name}
                </span>
              )}
            </div>

            {/* Provider 类型 */}
            <div className="flex flex-col gap-2">
              <Label htmlFor="ai-config-provider">Provider 类型</Label>
              <Select
                value={form.provider_type}
                onValueChange={(v) =>
                  handleProviderTypeChange(v as ProviderType)
                }
                disabled={submitting}
              >
                <SelectTrigger id="ai-config-provider" aria-label="Provider 类型">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(Object.keys(PROVIDER_OPTIONS) as ProviderType[]).map((pt) => (
                    <SelectItem key={pt} value={pt}>
                      {PROVIDER_OPTIONS[pt].label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Base URL */}
            <div className="flex flex-col gap-2">
              <Label htmlFor="ai-config-base-url">Base URL</Label>
              <Input
                id="ai-config-base-url"
                placeholder="https://api.example.com/v1"
                value={form.base_url}
                onChange={(e) =>
                  setForm((prev) => ({ ...prev, base_url: e.target.value }))
                }
                disabled={submitting}
                aria-invalid={Boolean(errors.base_url)}
                aria-describedby={
                  errors.base_url ? "ai-config-base-url-error" : undefined
                }
              />
              {errors.base_url && (
                <span
                  id="ai-config-base-url-error"
                  className="text-xs text-destructive"
                  role="alert"
                >
                  {errors.base_url}
                </span>
              )}
            </div>
          </div>

          {/* 认证 */}
          <div className="flex flex-col gap-4 border-t border-border pt-4">
            <div className="text-sm font-medium text-foreground">认证</div>
            {/* API Key */}
            <div className="flex flex-col gap-2">
              <Label htmlFor="ai-config-api-key">API Key</Label>
              <div className="flex gap-2">
                <Input
                  id="ai-config-api-key"
                  type={showApiKey ? "text" : "password"}
                  placeholder={apiKeyPlaceholder}
                  value={form.api_key}
                  onChange={(e) =>
                    setForm((prev) => ({ ...prev, api_key: e.target.value }))
                  }
                  disabled={submitting}
                  autoComplete="off"
                />
                <Button
                  type="button"
                  variant="outline"
                  size="icon"
                  onClick={() => setShowApiKey((v) => !v)}
                  disabled={submitting}
                  aria-label={showApiKey ? "隐藏 API Key" : "显示 API Key"}
                  title={showApiKey ? "隐藏" : "显示"}
                >
                  {showApiKey ? (
                    <EyeOff className="h-4 w-4" />
                  ) : (
                    <Eye className="h-4 w-4" />
                  )}
                </Button>
              </div>
              <span className="text-xs text-muted-foreground">
                本地模型（如 Ollama）无需填写
              </span>
            </div>
          </div>

          {/* 模型配置 —— 按 role 只展示对应字段 */}
          <div className="flex flex-col gap-4 border-t border-border pt-4">
            <div className="text-sm font-medium text-foreground">模型配置</div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="ai-config-model">{copy.modelLabel}</Label>
              <Input
                id="ai-config-model"
                placeholder={copy.modelPlaceholder}
                value={role === "llm" ? form.model : form.vlm_model}
                onChange={(e) =>
                  setForm((prev) =>
                    role === "llm"
                      ? { ...prev, model: e.target.value }
                      : { ...prev, vlm_model: e.target.value },
                  )
                }
                disabled={submitting}
                aria-invalid={Boolean(errors.model)}
                aria-describedby={
                  errors.model ? "ai-config-model-error" : undefined
                }
              />
              {errors.model && (
                <span
                  id="ai-config-model-error"
                  className="text-xs text-destructive"
                  role="alert"
                >
                  {errors.model}
                </span>
              )}
              <span className="text-xs text-muted-foreground">
                {copy.modelHint}
              </span>
            </div>
          </div>
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={submitting}
          >
            取消
          </Button>
          <Button onClick={handleSubmit} disabled={submitting}>
            {submitting ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                保存中...
              </>
            ) : isEditing ? (
              "保存修改"
            ) : (
              "新增配置"
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
