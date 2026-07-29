"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  HelpCircle,
  History,
  Loader2,
  RotateCcw,
  Send,
  Sparkles,
  Wand2,
} from "lucide-react";
import { toast } from "sonner";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import { apiFetch } from "@/lib/api";
import { cancelTask, useTaskProgress } from "@/lib/ws";
import type {
  ExecuteCodeResponse,
  ExecutionResult,
  GenerationResult,
  GenerationTaskAccepted,
  GeometryValidation,
  TaskProgressMessage,
  UploadResponse,
} from "@/lib/types";
import { InputTabs } from "@/components/generate/InputTabs";
import {
  OutputFormatSelector,
  type OutputFormat,
} from "@/components/generate/OutputFormatSelector";
import { TaskProgress } from "@/components/shared/TaskProgress";
import { MetaRow } from "@/components/shared/MetaRow";
import { CodePanel } from "@/components/generate/CodePanel";
import { ExecutionResultCard } from "@/components/generate/ExecutionResultCard";
import { GeometryValidationCard } from "@/components/generate/GeometryValidationCard";
import { DownloadList } from "@/components/generate/DownloadList";
import { EmptyState } from "@/components/shared/States";
import { formatElapsed } from "@/lib/format";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "/api/v1";

type InputType = "text" | "sketch";
type Stage =
  | "idle"
  | "submitting"
  | "running"
  | "completed"
  | "failed";

const STAGE_LABEL: Record<Stage, string> = {
  idle: "就绪",
  submitting: "提交中",
  running: "生成中",
  completed: "已完成",
  failed: "已失败",
};

const MODE_LABEL: Record<string, string> = {
  llm: "LLM 生成",
  template: "模板生成",
};

/** 退避轮询延迟（ms）：WS 不可用时的兜底拉取 */
const GENERATE_POLL_DELAYS = [1000, 2000, 4000, 8000, 16000];

/** 把后端返回的 output_files（可能是绝对路径或相对 URL）转换为可下载 URL。 */
function buildDownloadUrl(file: string): string {
  if (!file) return "";
  // 已经是完整的相对 URL（来自 execute 响应）
  if (file.startsWith("/api/") || file.startsWith("http")) {
    return file;
  }
  // 视作服务端文件路径：剥掉首部斜杠后拼到下载端点
  const normalized = file.startsWith("/") ? file.slice(1) : file;
  return `${API_BASE}/generations/files/${normalized}`;
}

export default function GeneratePage() {
  // === 输入相关状态 ===
  const [inputType, setInputType] = useState<InputType>("text");
  const [prompt, setPrompt] = useState<string>("");
  const [sketch, setSketch] = useState<UploadResponse | null>(null);
  const [outputFormat, setOutputFormat] =
    useState<OutputFormat>("step");

  // === 任务状态 ===
  const [taskId, setTaskId] = useState<string | null>(null);
  const [stage, setStage] = useState<Stage>("idle");
  const [resultError, setResultError] = useState<string | null>(null);
  const [resultLoading, setResultLoading] = useState<boolean>(false);
  const [generationResult, setGenerationResult] =
    useState<GenerationResult | null>(null);

  // === 编辑模式 ===
  const [editMode, setEditMode] = useState<boolean>(false);
  const [executing, setExecuting] = useState<boolean>(false);
  const [executeResp, setExecuteResp] = useState<ExecuteCodeResponse | null>(
    null,
  );

  // === 多轮对话（P0 预留） ===
  const [modifyInstruction, setModifyInstruction] = useState<string>("");
  const [promptHistory, setPromptHistory] = useState<string[]>([]);

  const isBusy =
    stage === "submitting" || stage === "running" || resultLoading || executing;

  const canSubmit = (() => {
    if (isBusy) return false;
    if (inputType === "text") {
      return prompt.trim().length > 0;
    }
    return sketch !== null;
  })();

  const submitHint = isBusy
    ? "任务进行中..."
    : inputType === "text"
      ? prompt.trim().length > 0
        ? "已就绪，可提交生成"
        : "请输入自然语言描述"
      : sketch
        ? "已就绪，可提交生成"
        : "请上传草图文件";

  const handleCancelTask = useCallback(async () => {
    if (!taskId) return;
    try {
      await cancelTask(taskId);
      pollControllerRef.current?.abort();
      if (!doneRef.current) {
        doneRef.current = true;
        setResultLoading(false);
        setStage("failed");
        setResultError("任务已取消");
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`取消任务失败: ${msg}`);
    }
  }, [taskId]);

  // === 拉取生成结果（退避轮询，可被 WS 成功后取消） ===
  // 并发轮询控制器 + 完成标志（WS 成功后取消进行中的轮询，避免重复收尾）
  const pollControllerRef = useRef<AbortController | null>(null);
  const doneRef = useRef<boolean>(false);

  const fetchGenerationResult = useCallback(
    async (id: string, signal?: AbortSignal) => {
      setResultLoading(true);
      setResultError(null);
      for (let attempt = 0; attempt < GENERATE_POLL_DELAYS.length; attempt++) {
        if (signal?.aborted) {
          setResultLoading(false);
          return;
        }
        try {
          const data = await apiFetch<GenerationResult>(
            `/generations/${id}/result`,
            { signal },
          );
          if (doneRef.current) return;
          doneRef.current = true;
          setGenerationResult(data);
          setStage("completed");
          setResultLoading(false);
          toast.success("生成完成");
          return;
        } catch (e) {
          if (signal?.aborted) {
            setResultLoading(false);
            return;
          }
          // pending 返回 404 / running 返回 202 占位 / failed 返回 500
          const msg = e instanceof Error ? e.message : String(e);
          if (attempt === GENERATE_POLL_DELAYS.length - 1) {
            if (doneRef.current) return;
            doneRef.current = true;
            setStage("failed");
            setResultError(`获取生成结果失败: ${msg}`);
            setResultLoading(false);
            toast.error(`获取生成结果失败: ${msg}`);
            return;
          }
        }
        await new Promise((r) => setTimeout(r, GENERATE_POLL_DELAYS[attempt]));
      }
      if (!doneRef.current) {
        doneRef.current = true;
        setStage("failed");
        setResultError("获取生成结果超时，请稍后重试");
        setResultLoading(false);
        toast.error("获取生成结果超时");
      }
    },
    [],
  );

  // 任务提交后并发轮询结果（WS 的退避兜底），卸载或换任务时取消
  useEffect(() => {
    if (!taskId) return;
    doneRef.current = false;
    const controller = new AbortController();
    pollControllerRef.current = controller;
    void fetchGenerationResult(taskId, controller.signal);
    return () => {
      controller.abort();
      pollControllerRef.current = null;
    };
  }, [taskId, fetchGenerationResult]);

  // === WebSocket 进度订阅 ===
  const { status, progress, error: wsError, connected } = useTaskProgress(
    taskId,
    {
      onCompleted: (msg: TaskProgressMessage) => {
        if (msg.status === "succeeded") {
          // WS 确认成功：取消进行中的轮询，拉取最终结果
          // 注意：不在此处设置 doneRef，由 fetchGenerationResult 成功收尾时设置，
          // 否则 fetchGenerationResult 内部的 doneRef 守卫会提前返回导致结果永远不展示
          pollControllerRef.current?.abort();
          if (!doneRef.current) {
            void fetchGenerationResult(msg.task_id);
          }
        } else if (msg.status === "failed" || msg.status === "canceled") {
          pollControllerRef.current?.abort();
          if (!doneRef.current) {
            doneRef.current = true;
            setResultLoading(false);
            setStage("failed");
            setResultError(msg.error || "生成任务失败");
            toast.error(msg.error || "生成任务失败");
          }
        }
      },
    },
  );

  // === 提交生成任务（核心逻辑，接受显式参数避免闭包陷阱） ===
  const submitGeneration = useCallback(
    async (args: {
      inputType: InputType;
      prompt: string;
      sketch: UploadResponse | null;
    }) => {
      const { inputType: it, prompt: p, sketch: s } = args;
      // 校验
      if (it === "text" && !p.trim()) {
        toast.error("请输入自然语言描述");
        return;
      }
      if (it === "sketch" && !s) {
        toast.error("请上传草图文件");
        return;
      }

      setStage("submitting");
      setResultError(null);
      setGenerationResult(null);
      setExecuteResp(null);
      setEditMode(false);

      // 记录 prompt 历史
      const submittedPrompt =
        it === "text" ? p.trim() : `[草图] ${s?.file_name ?? ""}`;
      setPromptHistory((h) => [...h, submittedPrompt]);

      try {
        const body: Record<string, unknown> = {
          input_type: it,
          output_format: outputFormat,
        };
        if (it === "text") {
          body.prompt = p.trim();
        } else if (s) {
          body.sketch_key = s.file_key;
        }
        const accepted = await apiFetch<GenerationTaskAccepted>(
          `/generations`,
          {
            method: "POST",
            body: JSON.stringify(body),
          },
        );
        setTaskId(accepted.task_id);
        setStage("running");
        toast.success("生成任务已提交");
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        setStage("failed");
        setResultError(msg);
        toast.error(`提交生成失败: ${msg}`);
      }
    },
    [outputFormat],
  );

  // === 由当前输入状态触发的提交 ===
  const handleSubmit = useCallback(() => {
    if (!canSubmit) return;
    void submitGeneration({ inputType, prompt, sketch });
  }, [canSubmit, inputType, prompt, sketch, submitGeneration]);

  // Cmd/Ctrl+Enter 触发主提交（修改指令 textarea 内不触发，避免误提交）
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
        const target = e.target as HTMLElement | null;
        if (target?.dataset.modifyInstruction === "true") return;
        e.preventDefault();
        if (canSubmit && !isBusy) {
          handleSubmit();
        }
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [canSubmit, isBusy, handleSubmit]);

  // === 编辑后重新执行 ===
  const handleExecute = useCallback(
    async (code: string) => {
      setExecuting(true);
      try {
        const resp = await apiFetch<ExecuteCodeResponse>(
          `/generations/execute`,
          {
            method: "POST",
            body: JSON.stringify({
              code,
              output_format: outputFormat,
              timeout: 30,
            }),
          },
        );
        setExecuteResp(resp);
        if (resp.execution.success) {
          toast.success("代码执行成功");
        } else {
          toast.error("代码执行失败，请查看 stderr");
        }
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        toast.error(`执行失败: ${msg}`);
      } finally {
        setExecuting(false);
      }
    },
    [outputFormat],
  );

  // === 多轮：基于修改指令发起新一轮生成 ===
  const handleModifySubmit = useCallback(() => {
    const instruction = modifyInstruction.trim();
    if (!instruction) {
      toast.error("请输入修改指令");
      return;
    }
    // P0：把原 prompt + 修改指令拼接为新 prompt
    const basePrompt = generationResult?.input_prompt ?? prompt;
    const newPrompt = `${basePrompt}\n\n[修改指令] ${instruction}`;
    setPrompt(newPrompt);
    setInputType("text");
    setModifyInstruction("");
    // 直接以显式参数发起新一轮生成，避免依赖 state 更新时序
    void submitGeneration({
      inputType: "text",
      prompt: newPrompt,
      sketch: null,
    });
  }, [modifyInstruction, generationResult, prompt, submitGeneration]);

  // === 重置 ===
  const handleReset = useCallback(() => {
    setPrompt("");
    setSketch(null);
    setInputType("text");
    setOutputFormat("step");
    setTaskId(null);
    setStage("idle");
    setResultError(null);
    setResultLoading(false);
    setGenerationResult(null);
    setEditMode(false);
    setExecuting(false);
    setExecuteResp(null);
    setModifyInstruction("");
  }, []);

  const stageBadgeVariant =
    stage === "completed"
      ? "default"
      : stage === "failed"
        ? "destructive"
        : "secondary";

  // 当前展示的执行结果与几何校验（优先用 execute 响应，没有则用初次生成）
  const currentExecution: ExecutionResult | null =
    executeResp?.execution ?? generationResult?.execution ?? null;
  const currentValidation: GeometryValidation | null =
    executeResp?.geometry_validation ??
    generationResult?.geometry_validation ??
    null;
  const currentDownloadUrls: string[] = executeResp
    ? executeResp.download_urls
    : generationResult
      ? (generationResult.output_files ?? []).map(buildDownloadUrl)
      : [];
  const currentSourceLabel = executeResp ? "重新执行" : "初次生成";

  const modelName = generationResult?.metadata?.model_name ?? null;
  const generatedAt = generationResult?.metadata?.generated_at ?? null;

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6">
      <div className="flex items-center gap-2">
        <Wand2 className="h-6 w-6 text-muted-foreground" />
        <h1 className="text-2xl font-semibold tracking-tight">生成工作台</h1>
        <Badge variant={stageBadgeVariant}>{STAGE_LABEL[stage]}</Badge>
      </div>

      {/* 输入区 */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">输入与输出格式</CardTitle>
          <CardDescription>
            支持自然语言或草图两种输入模式，选择目标格式后提交异步生成任务。
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-6">
          <div className="flex flex-col gap-2">
            <span className="text-sm font-medium">输入</span>
            <InputTabs
              inputType={inputType}
              onInputTypeChange={setInputType}
              prompt={prompt}
              onPromptChange={setPrompt}
              sketch={sketch}
              onSketchUploaded={setSketch}
              onClearSketch={() => setSketch(null)}
              disabled={isBusy}
            />
          </div>
          <Separator />
          <div className="flex flex-col gap-2">
            <span className="text-sm font-medium">输出格式</span>
            <OutputFormatSelector
              value={outputFormat}
              onChange={setOutputFormat}
              disabled={isBusy}
            />
          </div>
        </CardContent>
        <CardFooter className="flex items-center justify-between gap-2">
          <span id="submit-hint" className="text-xs text-muted-foreground">
            {submitHint}
          </span>
          <Button
            onClick={handleSubmit}
            disabled={!canSubmit}
            aria-describedby="submit-hint"
          >
            {stage === "submitting" ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                提交中...
              </>
            ) : stage === "running" ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                生成中...
              </>
            ) : (
              <>
                <Sparkles className="h-4 w-4" />
                生成
              </>
            )}
          </Button>
        </CardFooter>
      </Card>

      {/* 空状态引导：未输入且 idle 时展示 3 步上手 */}
      {stage === "idle" && !prompt && !sketch && (
        <EmptyState
          icon={HelpCircle}
          title="快速上手"
          description={
            "1. 选择输入模式：自然语言描述或上传草图\n2. 填写工程图描述，或上传草图文件\n3. 选择输出格式并点击“生成”，AI 将产出 CadQuery 代码与可下载产物"
          }
        />
      )}

      {/* 任务进度 */}
      {(stage === "submitting" || stage === "running") && (
        <Card className="animate-in fade-in">
          <CardHeader>
            <CardTitle className="text-base">任务进度</CardTitle>
            <CardDescription>
              实时订阅任务状态，生成完成后自动加载结果。
            </CardDescription>
          </CardHeader>
          <CardContent>
            {stage === "submitting" || !taskId ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                正在提交生成任务...
              </div>
            ) : (
              <TaskProgress
                taskId={taskId}
                status={status}
                progress={progress}
                error={wsError}
                connected={connected}
                labels={{ running: "生成中..." }}
                onCancel={handleCancelTask}
              />
            )}
          </CardContent>
        </Card>
      )}

      {/* 失败提示 */}
      {stage === "failed" && (
        <Card className="animate-in fade-in">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base text-destructive">
              <AlertCircle className="h-4 w-4" />
              生成失败
            </CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            {resultError || "未知错误"}
          </CardContent>
          <CardFooter>
            <Button variant="outline" onClick={handleReset}>
              <RotateCcw className="h-4 w-4" />
              重新发起
            </Button>
          </CardFooter>
        </Card>
      )}

      {/* 结果展示 */}
      {stage === "completed" && generationResult && (
        <Card className="animate-in fade-in">
          <CardHeader>
            <CardTitle className="text-base">生成结果</CardTitle>
            <CardDescription>
              包含 CadQuery 代码、执行结果、几何校验与可下载产物。
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-6">
            {/* 元信息 */}
            <div className="grid gap-3 rounded-lg border p-4 md:grid-cols-3">
              <MetaRow
                label="生成模式"
                value={
                  <Badge variant="secondary">
                    {MODE_LABEL[generationResult.mode] ?? generationResult.mode}
                  </Badge>
                }
              />
              <MetaRow
                label="输入 Prompt"
                value={
                  <span className="line-clamp-2 text-xs">
                    {generationResult.input_prompt || "-"}
                  </span>
                }
              />
              <MetaRow
                label="任务 ID"
                value={
                  <code className="font-mono text-xs">
                    {generationResult.task_id}
                  </code>
                }
              />
              {modelName && (
                <MetaRow
                  label="模型"
                  value={<span className="text-xs">{modelName}</span>}
                />
              )}
              {generatedAt && (
                <MetaRow
                  label="生成时间"
                  value={<span className="text-xs">{generatedAt}</span>}
                />
              )}
              <MetaRow
                label="初次执行耗时"
                value={formatElapsed(
                  generationResult.execution?.elapsed_ms,
                )}
              />
            </div>

            {/* 代码面板 */}
            <CodePanel
              code={generationResult.generated_code}
              editMode={editMode}
              onEnterEdit={() => setEditMode(true)}
              onCancelEdit={() => setEditMode(false)}
              onExecute={handleExecute}
              executing={executing}
            />

            {/* 执行结果 */}
            {currentExecution && (
              <ExecutionResultCard
                execution={currentExecution}
                sourceLabel={currentSourceLabel}
              />
            )}

            {/* 几何校验 */}
            {currentValidation && (
              <GeometryValidationCard validation={currentValidation} />
            )}

            {/* 下载区 */}
            <div className="flex flex-col gap-2">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium">下载产物</span>
                <span className="text-xs text-muted-foreground">
                  共 {currentDownloadUrls.length} 个文件
                </span>
              </div>
              <DownloadList
                urls={currentDownloadUrls}
                emptyHint="本次执行未生成可下载文件"
              />
            </div>

            {/* 多轮对话 */}
            <Separator />
            <div className="flex flex-col gap-2">
              <div className="flex items-center gap-2">
                <Sparkles className="h-4 w-4 text-muted-foreground" />
                <span className="text-sm font-medium">修改指令</span>
                <span className="text-xs text-muted-foreground">
                  P0 预留：将原 prompt 与修改指令拼接送入新一轮生成
                </span>
              </div>
              <Textarea
                value={modifyInstruction}
                onChange={(e) => setModifyInstruction(e.target.value)}
                placeholder="例如：把直径改为 60mm，厚度增加到 12mm"
                disabled={isBusy}
                className="min-h-[80px] resize-y text-sm"
                data-modify-instruction="true"
              />
              <div className="flex justify-end">
                <Button
                  size="sm"
                  onClick={handleModifySubmit}
                  disabled={isBusy || !modifyInstruction.trim()}
                >
                  <Send className="h-4 w-4" />
                  发起新一轮生成
                </Button>
              </div>
            </div>

            {/* 历史 prompt */}
            {promptHistory.length > 0 && (
              <div className="flex flex-col gap-2">
                <div className="flex items-center gap-2">
                  <History className="h-4 w-4 text-muted-foreground" />
                  <span className="text-sm font-medium">Prompt 历史</span>
                  <span className="text-xs text-muted-foreground">
                    仅展示，不会重新加载
                  </span>
                </div>
                <ol className="list-decimal space-y-1 pl-5 text-xs text-muted-foreground">
                  {promptHistory.map((p, i) => (
                    <li key={i} className="break-words">
                      <span className="text-foreground">{p}</span>
                    </li>
                  ))}
                </ol>
              </div>
            )}
          </CardContent>
          <CardFooter>
            <Button variant="outline" onClick={handleReset}>
              <RotateCcw className="h-4 w-4" />
              发起新生成
            </Button>
          </CardFooter>
        </Card>
      )}
    </div>
  );
}
