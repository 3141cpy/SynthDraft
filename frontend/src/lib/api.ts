import type { UploadResponse } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "/api/v1";

/** 统一 API 错误：携带 HTTP 状态码与解析后的响应体（detail）。
 *
 * 组件层可 `catch (e)` 后通过 `e instanceof ApiError` 读取 `status` / `detail`，
 * 例如根据 401 跳登录、根据 422 detail 展示字段级校验信息。
 */
export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown, message?: string) {
    super(message ?? `API ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

/** 解析非 2xx 响应并构造 ApiError。
 *
 * 优先按 `Content-Type: application/json` 解析响应体：FastAPI 错误格式为
 * `{"detail": "..."}`，此时把 detail 字符串作为 message；其余情况保留原始文本。
 */
async function buildApiError(res: Response): Promise<ApiError> {
  let detail: unknown = null;
  let message = `API ${res.status}`;
  try {
    const contentType = res.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      const body = await res.json();
      detail = body;
      if (body && typeof body === "object" && "detail" in body) {
        const d = (body as { detail: unknown }).detail;
        message =
          typeof d === "string"
            ? d
            : `API ${res.status}: ${JSON.stringify(d)}`;
      }
    } else {
      const text = await res.text();
      detail = text;
      if (text) message = `API ${res.status}: ${text}`;
    }
  } catch {
    // 响应体解析失败时仅保留 status
  }
  return new ApiError(res.status, detail, message);
}

/** 默认请求超时（ms）：防止后端无响应时前端无限等待 */
const DEFAULT_TIMEOUT_MS = 30_000;
/** 文件上传超时（ms）：大文件需要更长窗口 */
const UPLOAD_TIMEOUT_MS = 120_000;

/** 创建带超时的 AbortController，与调用方 signal 合并。
 *
 * 返回的 signal 同时受超时和外部 signal 控制；cleanup 需在请求完成后调用
 * 以清除定时器并移除事件监听。
 */
function createTimeoutSignal(
  timeoutMs: number,
  externalSignal?: AbortSignal,
): { signal: AbortSignal; cleanup: () => void } {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const onAbort = () => controller.abort();
  if (externalSignal) {
    if (externalSignal.aborted) {
      controller.abort();
    } else {
      externalSignal.addEventListener("abort", onAbort, { once: true });
    }
  }
  return {
    signal: controller.signal,
    cleanup: () => {
      clearTimeout(timer);
      if (externalSignal) {
        externalSignal.removeEventListener("abort", onAbort);
      }
    },
  };
}

/** 统一 fetch 入口：注入 JSON Content-Type，透传 `init.signal`，解析错误为 ApiError。
 *
 * 通过 Headers API 合并请求头（兼容 Headers 实例、元组数组与普通对象），
 * 并施加默认超时防止请求无限挂起。对 204 No Content 或空响应体返回 `undefined`。
 */
export async function apiFetch<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const { signal, cleanup } = createTimeoutSignal(
    DEFAULT_TIMEOUT_MS,
    init?.signal ?? undefined,
  );
  try {
    const headers = new Headers({ "Content-Type": "application/json" });
    if (init?.headers) {
      new Headers(init.headers).forEach((value, key) =>
        headers.set(key, value),
      );
    }
    const res = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers,
      signal,
    });
    if (!res.ok) {
      throw await buildApiError(res);
    }
    if (res.status === 204) {
      return undefined as T;
    }
    const text = await res.text();
    if (!text) {
      return undefined as T;
    }
    return JSON.parse(text) as T;
  } finally {
    cleanup();
  }
}

/** 文件上传：走 FormData，不强制 Content-Type（由浏览器设置 multipart boundary）。
 *
 * 失败时同样抛出 ApiError，便于上层统一处理。施加上传超时并合并调用方 signal。
 */
export async function apiUpload(
  file: File,
  endpoint: string,
  signal?: AbortSignal,
): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append("file", file);
  const { signal: timeoutSignal, cleanup } = createTimeoutSignal(
    UPLOAD_TIMEOUT_MS,
    signal,
  );
  try {
    const res = await fetch(`${API_BASE}${endpoint}`, {
      method: "POST",
      body: formData,
      signal: timeoutSignal,
    });
    if (!res.ok) {
      throw await buildApiError(res);
    }
    return res.json();
  } finally {
    cleanup();
  }
}
