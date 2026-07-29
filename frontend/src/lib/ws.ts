/** WebSocket 任务进度订阅 hook。
 *
 * 对接后端 GET /api/v1/ws/tasks/{task_id}（见 backend/app/api/v1/endpoints/ws.py）。
 * 后端每秒推送一次 {task_id, status, progress, result?, error?}，
 * 在 succeeded/failed/canceled 时关闭连接。
 *
 * 遵循"以瞎猜接口为耻"原则：消息格式严格对照 ws.py 的 send_json payload。
 */

"use client";

import { useEffect, useRef, useState } from "react";
import type { TaskProgressMessage, TaskStatus } from "./types";
import { apiFetch } from "./api";

/** 指数退避重连延迟（ms），达到上限后停止重连并 setError。 */
const RECONNECT_DELAYS = [1000, 2000, 4000, 8000, 16000];
const MAX_RECONNECT_ATTEMPTS = RECONNECT_DELAYS.length;

/**
 * 推导 WS 基址，与 API 同源：
 * 1. `NEXT_PUBLIC_WS_BASE_URL` 显式覆盖；
 * 2. `NEXT_PUBLIC_API_BASE_URL` 为绝对 URL 时转换协议（http→ws / https→wss）；
 * 3. 相对路径（如 `/api/v1`）：开发环境（localhost/127.0.0.1）指向 `ws://localhost:8000`，
 *    生产环境用 `wss://${window.location.host}`，与页面同源。
 */
function resolveWsBase(): string {
  const explicit = process.env.NEXT_PUBLIC_WS_BASE_URL;
  if (explicit) return explicit;

  const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL || "/api/v1";

  if (apiBase.startsWith("http://") || apiBase.startsWith("https://")) {
    return apiBase.replace(/^http/, "ws");
  }

  if (typeof window !== "undefined") {
    const host = window.location.host;
    const isLocalDev =
      host.startsWith("localhost") || host.startsWith("127.0.0.1");
    const scheme = isLocalDev ? "ws" : "wss";
    // 开发环境后端运行在 8000 端口；生产环境与前端同源
    const wsHost = isLocalDev ? "localhost:8000" : host;
    return `${scheme}://${wsHost}${apiBase}`;
  }

  // SSR fallback
  return "ws://localhost:8000/api/v1";
}

interface UseTaskProgressOptions {
  /** 任务结束时的回调（succeeded/failed/canceled） */
  onCompleted?: (msg: TaskProgressMessage) => void;
  /** 收到消息时的回调（每次都触发） */
  onMessage?: (msg: TaskProgressMessage) => void;
}

interface UseTaskProgressResult {
  /** 当前任务状态，未连接时为 null */
  status: TaskStatus | null;
  /** 进度（0-100，后端当前固定 0，保留扩展） */
  progress: number;
  /** 错误信息（连接异常或任务失败时） */
  error: string | null;
  /** 是否已连接 */
  connected: boolean;
  /** 当前重连次数（重连成功后归零） */
  reconnectCount: number;
}

/**
 * 订阅指定 task_id 的进度更新。
 *
 * 用法：
 *   const { status, error, connected, reconnectCount } = useTaskProgress(taskId, {
 *     onCompleted: (msg) => toast.success("任务完成"),
 *   });
 *
 * 实现要点：
 * - 用 `errorRef` / `closedRef` 替代在 `onclose` 内直接读取 `error` state，
 *   规避闭包陷阱导致的"非正常关闭"误判。
 * - 非正常关闭时按指数退避自动重连（最多 `MAX_RECONNECT_ATTEMPTS` 次）。
 * - 卸载时清理重连定时器并关闭连接。
 */
export function useTaskProgress(
  taskId: string | null,
  options: UseTaskProgressOptions = {},
): UseTaskProgressResult {
  const [status, setStatus] = useState<TaskStatus | null>(null);
  const [progress, setProgress] = useState<number>(0);
  const [error, setError] = useState<string | null>(null);
  const [connected, setConnected] = useState<boolean>(false);
  const [reconnectCount, setReconnectCount] = useState<number>(0);

  const wsRef = useRef<WebSocket | null>(null);
  const optionsRef = useRef(options);
  optionsRef.current = options;

  // 用 ref 替代在 WS 事件回调内直接读取 state，规避闭包陷阱
  const errorRef = useRef<string | null>(null);
  const closedRef = useRef<boolean>(false);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const attemptRef = useRef<number>(0);

  useEffect(() => {
    if (!taskId) {
      return;
    }

    // 重置状态
    setStatus(null);
    setProgress(0);
    setError(null);
    setConnected(false);
    setReconnectCount(0);
    errorRef.current = null;
    closedRef.current = false;
    attemptRef.current = 0;

    const url = `${resolveWsBase()}/ws/tasks/${taskId}`;
    let disposed = false;

    const connect = () => {
      if (disposed || closedRef.current) return;

      let ws: WebSocket;
      try {
        ws = new WebSocket(url);
        wsRef.current = ws;
      } catch (e) {
        const msg = `WebSocket 创建失败: ${e instanceof Error ? e.message : String(e)}`;
        setError(msg);
        errorRef.current = msg;
        return;
      }

      ws.onopen = () => {
        if (disposed) return;
        setConnected(true);
        // 重连成功，重置退避计数
        attemptRef.current = 0;
        setReconnectCount(0);
      };

      ws.onmessage = (event) => {
        if (disposed) return;
        try {
          const msg: TaskProgressMessage = JSON.parse(event.data);
          setStatus(msg.status);
          setProgress(msg.progress);
          if (msg.error) {
            setError(msg.error);
            errorRef.current = msg.error;
          }
          optionsRef.current.onMessage?.(msg);
          if (
            msg.status === "succeeded" ||
            msg.status === "failed" ||
            msg.status === "canceled"
          ) {
            // 正常结束：先标记关闭，避免 onclose 误判为非正常关闭而触发重连
            closedRef.current = true;
            optionsRef.current.onCompleted?.(msg);
            ws.close();
          }
        } catch (e) {
          const msg = `消息解析失败: ${e instanceof Error ? e.message : String(e)}`;
          setError(msg);
          errorRef.current = msg;
        }
      };

      ws.onerror = () => {
        // 不在此处 setError；onerror 通常紧随 onclose，由 onclose 决定是否重连
      };

      ws.onclose = () => {
        if (disposed) return;
        setConnected(false);
        // 正常关闭（任务结束主动 close）——不重连
        if (closedRef.current) return;

        // 非正常关闭：指数退避重连
        const attempt = attemptRef.current;
        if (attempt >= MAX_RECONNECT_ATTEMPTS) {
          const msg = `WebSocket 重连已达上限（${MAX_RECONNECT_ATTEMPTS} 次），停止重连`;
          setError(msg);
          errorRef.current = msg;
          return;
        }
        const delay = RECONNECT_DELAYS[attempt];
        attemptRef.current = attempt + 1;
        setReconnectCount(attempt + 1);
        reconnectTimerRef.current = setTimeout(() => {
          reconnectTimerRef.current = null;
          connect();
        }, delay);
      };
    };

    connect();

    return () => {
      disposed = true;
      closedRef.current = true;
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      const ws = wsRef.current;
      if (ws) {
        ws.onopen = null;
        ws.onmessage = null;
        ws.onerror = null;
        ws.onclose = null;
        try {
          ws.close();
        } catch {
          // ignore
        }
        wsRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskId]);

  return { status, progress, error, connected, reconnectCount };
}

/** 取消任务（POST /api/v1/tasks/{task_id}/cancel），走统一 apiFetch 入口。 */
export async function cancelTask(taskId: string): Promise<void> {
  await apiFetch<void>(`/tasks/${taskId}/cancel`, { method: "POST" });
}
