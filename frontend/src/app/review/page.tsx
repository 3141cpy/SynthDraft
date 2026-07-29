"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  Download,
  FileSearch,
  FileText,
  HelpCircle,
  Loader2,
  RotateCcw,
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
import { apiFetch } from "@/lib/api";
import { cancelTask, useTaskProgress } from "@/lib/ws";
import type {
  ReviewResult,
  ReviewTaskAccepted,
  TaskProgressMessage,
  UploadResponse,
} from "@/lib/types";
import { FileUploader } from "@/components/review/FileUploader";
import { StandardsSelector } from "@/components/review/StandardsSelector";
import { TaskProgress } from "@/components/shared/TaskProgress";
import { MetaRow } from "@/components/shared/MetaRow";
import { ScoreCard } from "@/components/review/ScoreCard";
import { DefectsTable } from "@/components/review/DefectsTable";
import { EmptyState } from "@/components/shared/States";
import { formatElapsedFromMeta } from "@/lib/format";
import { DEFAULT_STANDARD_IDS } from "@/lib/constants";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "/api/v1";

const REVIEW_MODE_LABELS: Record<string, string> = {
  vlm: "VLM 视觉审图",
  vector_only: "向量审图",
  rule_engine: "规则引擎",
};

/** 退避轮询延迟（ms）：WS 不可用时的兜底拉取 */
const REVIEW_POLL_DELAYS = [800, 1600, 3200, 6400];
/** 轮询墙钟超时（ms）：超过此时间仍未拿到结果则放弃兜底轮询 */
const REVIEW_POLL_TIMEOUT_MS = 120_000;

type Stage = "idle" | "submitting" | "running" | "completed" | "failed";

const STAGE_LABEL: Record<Stage, string> = {
  idle: "就绪",
  submitting: "提交中",
  running: "审图中",
  completed: "已完成",
  failed: "已失败",
};

export default function ReviewPage() {
  const [uploadResp, setUploadResp] = useState<UploadResponse | null>(null);
  const [standards, setStandards] = useState<string[]>(DEFAULT_STANDARD_IDS);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [stage, setStage] = useState<Stage>("idle");
  const [resultError, setResultError] = useState<string | null>(null);
  const [resultLoading, setResultLoading] = useState(false);
  const [reviewResult, setReviewResult] = useState<ReviewResult | null>(null);

  const isBusy =
    stage === "submitting" || stage === "running" || resultLoading;

  // 并发轮询控制器 + 完成标志（WS 成功后取消进行中的轮询，避免重复收尾）
  const pollControllerRef = useRef<AbortController | null>(null);
  const doneRef = useRef<boolean>(false);
  // WS 连接状态镜像（供 fetchReviewResult 读取，避免闭包陷阱）
  const connectedRef = useRef<boolean>(false);

  const fetchReviewResult = useCallback(
    async (id: string, signal?: AbortSignal) => {
      setResultLoading(true);
      setResultError(null);
      const startedAt = Date.now();
      let attempt = 0;
      while (Date.now() - startedAt < REVIEW_POLL_TIMEOUT_MS) {
        if (signal?.aborted) {
          setResultLoading(false);
          return;
        }
        try {
          const data = await apiFetch<ReviewResult>(
            `/reviews/${id}/result`,
            { signal },
          );
          if (data.status === "completed") {
            if (doneRef.current) return;
            doneRef.current = true;
            setReviewResult(data);
            setStage("completed");
            setResultLoading(false);
            toast.success("审图完成");
            return;
          }
          if (data.status === "failed") {
            if (doneRef.current) return;
            doneRef.current = true;
            setStage("failed");
            setResultError(data.error || "审图任务失败");
            setResultLoading(false);
            toast.error(data.error || "审图任务失败");
            return;
          }
          // pending / running — 退避后重试
        } catch {
          if (signal?.aborted) {
            setResultLoading(false);
            return;
          }
          // 非最终超时：继续退避重试
        }
        // 退避：超出数组范围后复用最后一个延迟
        const delay =
          REVIEW_POLL_DELAYS[
            Math.min(attempt, REVIEW_POLL_DELAYS.length - 1)
          ];
        attempt++;
        // 剩余时间不足以再等一轮则跳出
        if (Date.now() - startedAt + delay >= REVIEW_POLL_TIMEOUT_MS) {
          break;
        }
        await new Promise((r) => setTimeout(r, delay));
      }
      // 超时处理：WS 仍连接则不标记失败（等 WS 收尾），否则标记失败
      if (!doneRef.current) {
        if (connectedRef.current) {
          setResultLoading(false);
          return;
        }
        doneRef.current = true;
        setStage("failed");
        setResultError("获取审图结果超时，请稍后重试");
        setResultLoading(false);
        toast.error("获取审图结果超时");
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
    void fetchReviewResult(taskId, controller.signal);
    return () => {
      controller.abort();
      pollControllerRef.current = null;
    };
  }, [taskId, fetchReviewResult]);

  const { status, progress, error: wsError, connected } = useTaskProgress(
    taskId,
    {
      onCompleted: (msg: TaskProgressMessage) => {
        if (msg.status === "succeeded") {
          // WS 确认成功：取消进行中的轮询，拉取最终结果
          // 注意：不在此处设置 doneRef，由 fetchReviewResult 成功收尾时设置，
          // 否则 fetchReviewResult 内部的 doneRef 守卫会提前返回导致结果永远不展示
          pollControllerRef.current?.abort();
          if (!doneRef.current) {
            void fetchReviewResult(msg.task_id);
          }
        } else if (msg.status === "failed" || msg.status === "canceled") {
          pollControllerRef.current?.abort();
          if (!doneRef.current) {
            doneRef.current = true;
            setResultLoading(false);
            setStage("failed");
            setResultError(msg.error || "审图任务失败");
            toast.error(msg.error || "审图任务失败");
          }
        }
      },
    },
  );

  // 镜像 WS 连接状态到 ref，供 fetchReviewResult 超时时判断是否仍等待 WS
  useEffect(() => {
    connectedRef.current = connected;
  }, [connected]);

  const handleUpload = useCallback((resp: UploadResponse) => {
    setUploadResp(resp);
  }, []);

  const handleClearFile = useCallback(() => {
    setUploadResp(null);
  }, []);

  const handleSubmit = useCallback(async () => {
    if (!uploadResp) return;
    if (standards.length === 0) {
      toast.error("请至少选择一项规范");
      return;
    }
    setStage("submitting");
    setResultError(null);
    setReviewResult(null);
    try {
      const accepted = await apiFetch<ReviewTaskAccepted>(`/reviews`, {
        method: "POST",
        body: JSON.stringify({
          file_key: uploadResp.file_key,
          file_type: uploadResp.file_type,
          standard_set: standards,
        }),
      });
      setTaskId(accepted.task_id);
      setStage("running");
      toast.success("审图任务已提交");
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setStage("failed");
      setResultError(msg);
      toast.error(`提交审图失败: ${msg}`);
    }
  }, [uploadResp, standards]);

  const handleReset = useCallback(() => {
    setUploadResp(null);
    setStandards(DEFAULT_STANDARD_IDS);
    setTaskId(null);
    setStage("idle");
    setResultError(null);
    setResultLoading(false);
    setReviewResult(null);
  }, []);

  const canSubmit =
    uploadResp !== null && standards.length > 0 && !isBusy;

  const submitHint = isBusy
    ? "任务进行中..."
    : !uploadResp
      ? "请先上传图纸文件"
      : standards.length === 0
        ? "请至少选择一项规范"
        : "已上传文件，可提交审图";

  // Cmd/Ctrl+Enter 触发主提交
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        if (canSubmit && !isBusy) {
          void handleSubmit();
        }
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [canSubmit, isBusy, handleSubmit]);

  const handleCancelTask = useCallback(async () => {
    if (!taskId) return;
    try {
      await cancelTask(taskId);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`取消任务失败: ${msg}`);
    }
  }, [taskId]);

  const reportHtmlUrl = taskId
    ? `${API_BASE}/reviews/${taskId}/report?format=html`
    : null;
  const reportPdfUrl = taskId
    ? `${API_BASE}/reviews/${taskId}/report?format=pdf`
    : null;
  const hasPdf = Boolean(reviewResult?.pdf_report_path);

  const stageBadgeVariant =
    stage === "completed"
      ? "default"
      : stage === "failed"
        ? "destructive"
        : "secondary";

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6">
      <div className="flex items-center gap-2">
        <FileSearch className="h-6 w-6 text-muted-foreground" />
        <h1 className="text-2xl font-semibold tracking-tight">审图工作台</h1>
        <Badge variant={stageBadgeVariant}>{STAGE_LABEL[stage]}</Badge>
      </div>

      {/* 上传 + 规范选择 + 提交 */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">上传图纸与选择规范</CardTitle>
          <CardDescription>
            上传工程图文件并选择适用的国家标准，提交后由 AI 自动审查合规性。
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-6">
          <div className="flex flex-col gap-2">
            <span className="text-sm font-medium">图纸文件</span>
            <FileUploader
              uploaded={uploadResp}
              onUploaded={handleUpload}
              onClear={handleClearFile}
              disabled={isBusy}
            />
          </div>
          <Separator />
          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium">
               适用规范
                <span className="ml-2 text-xs text-muted-foreground">
                  已选 {standards.length} 项
                </span>
              </span>
            </div>
            <StandardsSelector
              value={standards}
              onChange={setStandards}
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
              "审图中..."
            ) : (
              "提交审图"
            )}
          </Button>
        </CardFooter>
      </Card>

      {/* 空状态引导：未上传且 idle 时展示 3 步上手 */}
      {stage === "idle" && !uploadResp && (
        <EmptyState
          icon={HelpCircle}
          title="快速上手"
          description={
            "1. 上传工程图纸文件（DWG/DXF/PDF/图片）\n2. 选择适用的国家标准规范\n3. 提交后由 AI 自动审查合规性并生成报告"
          }
        />
      )}

      {/* 任务进度 */}
      {(stage === "submitting" || stage === "running") && (
        <Card className="animate-in fade-in">
          <CardHeader>
            <CardTitle className="text-base">任务进度</CardTitle>
            <CardDescription>
              实时订阅任务状态，审图完成后自动加载结果。
            </CardDescription>
          </CardHeader>
          <CardContent>
            {stage === "submitting" || !taskId ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                正在提交审图任务...
              </div>
            ) : (
              <TaskProgress
                taskId={taskId}
                status={status}
                progress={progress}
                error={wsError}
                connected={connected}
                labels={{ running: "审图中..." }}
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
              审图失败
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
      {stage === "completed" && reviewResult && (
        <Card className="animate-in fade-in">
          <CardHeader>
            <CardTitle className="text-base">审图结果</CardTitle>
            <CardDescription>
              基于所选规范的结构化审查报告，可下载完整版。
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-6">
            <div className="grid gap-4 md:grid-cols-3">
              <ScoreCard
                score={reviewResult.compliance_score}
                defectCount={reviewResult.defects.length}
              />
              <div className="flex flex-col gap-3 rounded-lg border p-4 md:col-span-2">
                <div className="grid grid-cols-2 gap-3">
                  <MetaRow
                    label="审图模式"
                    value={
                      REVIEW_MODE_LABELS[reviewResult.review_mode] ??
                      reviewResult.review_mode
                    }
                  />
                  <MetaRow
                    label="图纸类型"
                    value={
                      <Badge variant="outline" className="uppercase">
                        {reviewResult.file_type}
                      </Badge>
                    }
                  />
                  <MetaRow
                    label="耗时"
                    value={formatElapsedFromMeta(reviewResult.metadata)}
                  />
                  <MetaRow
                    label="缺陷数量"
                    value={`${reviewResult.defects.length} 项`}
                  />
                </div>
                <Separator />
                <MetaRow
                  label="应用规范"
                  value={
                    reviewResult.standards_applied.length > 0 ? (
                      <div className="flex flex-wrap gap-1">
                        {reviewResult.standards_applied.map((s) => (
                          <Badge
                            key={s}
                            variant="secondary"
                            className="font-normal"
                          >
                            {s}
                          </Badge>
                        ))}
                      </div>
                    ) : (
                      "-"
                    )
                  }
                />
              </div>
            </div>

            <Separator />

            <div className="flex flex-col gap-2">
              <h3 className="text-sm font-medium">
                缺陷列表
                <span className="ml-2 text-xs text-muted-foreground">
                  点击行展开查看完整证据与建议
                </span>
              </h3>
              <DefectsTable defects={reviewResult.defects} />
            </div>

            <Separator />

            <div className="flex flex-wrap gap-2">
              <Button
                variant="outline"
                onClick={() =>
                  reportHtmlUrl && window.open(reportHtmlUrl, "_blank")
                }
                disabled={!reportHtmlUrl}
              >
                <FileText className="h-4 w-4" />
                下载 HTML 报告
              </Button>
              <Button
                variant="outline"
                onClick={() =>
                  reportPdfUrl && window.open(reportPdfUrl, "_blank")
                }
                disabled={!hasPdf || !reportPdfUrl}
              >
                <Download className="h-4 w-4" />
                下载 PDF 报告
              </Button>
              {!hasPdf && (
                <span className="self-center text-xs text-muted-foreground">
                  该任务暂无 PDF 报告
                </span>
              )}
            </div>
          </CardContent>
          <CardFooter>
            <Button variant="outline" onClick={handleReset}>
              <RotateCcw className="h-4 w-4" />
              重新发起审图
            </Button>
          </CardFooter>
        </Card>
      )}
    </div>
  );
}
