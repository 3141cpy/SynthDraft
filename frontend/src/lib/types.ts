/** 共享类型定义：与后端 schemas 对齐。
 *
 * 来源对照：
 * - ReviewResult / DefectItem: backend/app/schemas/review_detail.py
 * - GenerationResult / ExecutionResult / GeometryValidation: backend/app/schemas/generation_detail.py
 * - ClauseSearchResult / ClausesQueryResponse: backend/app/schemas/kb.py
 * - UploadResponse: backend/app/schemas/upload.py
 * - TaskStatusResponse: backend/app/schemas/task.py
 *
 * 遵循"以瞎猜接口为耻"原则：所有字段名与后端 pydantic 模型严格一致。
 */

// ===== 任务状态 =====
export type TaskStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "canceled"
  | "pending"
  | "unknown";

export interface TaskStatusResponse {
  task_id: string;
  status: TaskStatus;
  progress: number;
  result?: Record<string, unknown> | null;
  error?: string | null;
}

// ===== 文件上传 =====
export type UploadFileType =
  | "sldprt"
  | "sldasm"
  | "dwg"
  | "dxf"
  | "pdf"
  | "image"
  | "step"
  | "iges";

export interface UploadResponse {
  file_key: string;
  file_name: string;
  file_type: UploadFileType;
  size: number;
  content_type: string;
}

// ===== 审图 =====
export type ReviewMode = "vlm" | "vector_only" | "rule_engine";

export type DefectCategory =
  | "title_block"
  | "layer_naming"
  | "dimensioning"
  | "tolerance"
  | "surface_roughness"
  | "line_type"
  | "view_layout"
  | "text_annotation"
  | "other";

export type Severity = "critical" | "major" | "minor" | "warning";

export interface DefectItem {
  category: DefectCategory;
  severity: Severity;
  coordinate: { x: number; y: number } | null;
  standard_ref: string;
  standard_clause_id?: string | null;
  suggestion: string;
  evidence: string;
}

/**
 * 审图结果 metadata。
 *
 * 后端在 pending/running 时也会返回 200，可能附带 error 字段；
 * elapsed_ms 用于耗时展示。
 */
export interface ReviewMetadata {
  elapsed_ms?: number;
  [k: string]: unknown;
}

export interface ReviewResult {
  task_id: string;
  file_key: string;
  file_type: UploadFileType;
  status: "completed" | "failed" | "pending" | "running";
  compliance_score: number;
  defects: DefectItem[];
  standards_applied: string[];
  review_mode: ReviewMode;
  report_path?: string | null;
  pdf_report_path?: string | null;
  metadata: ReviewMetadata;
  /** 失败时由后端附带的可读错误信息。 */
  error?: string | null;
}

export interface ReviewTaskAccepted {
  task_id: string;
  status: "queued";
  websocket_url: string;
}

// ===== 生成 =====
export interface ExecutionResult {
  success: boolean;
  stdout: string;
  stderr: string;
  output_files: string[];
  elapsed_ms: number;
  exit_code: number | null;
  violations: string[];
}

export interface GeometryValidation {
  is_valid: boolean;
  volume: number;
  bounding_box: [number, number, number, number, number, number] | null;
  surface_area: number;
  errors: string[];
  backend: string | null;
}

/**
 * 生成结果 metadata。
 *
 * model_name / generated_at 用于结果卡片展示；
 * elapsed_ms 用于耗时统计。
 */
export interface GenerationMetadata {
  model_name?: string;
  generated_at?: string;
  elapsed_ms?: number;
  [k: string]: unknown;
}

export interface GenerationResult {
  task_id: string;
  input_prompt: string;
  generated_code: string;
  execution: ExecutionResult;
  geometry_validation: GeometryValidation | null;
  output_files: string[];
  mode: "llm" | "template";
  metadata: GenerationMetadata;
}

export interface GenerationTaskAccepted {
  task_id: string;
  status: "queued";
  websocket_url: string;
}

export interface ExecuteCodeResponse {
  execution: ExecutionResult;
  geometry_validation: GeometryValidation | null;
  download_urls: string[];
}

// ===== 知识库 =====
export interface ClauseSearchResult {
  standard: string;
  clause_id: string;
  title: string;
  original_text: string;
  score: number;
  source_file: string;
  category: string;
  keywords: string[];
  completeness: "complete" | "incomplete";
}

export interface ClausesQueryResponse {
  query: string;
  top_k: number;
  results: ClauseSearchResult[];
  total: number;
}

export interface StandardsListResponse {
  standards: string[];
  count: number;
}

/** 重建知识库索引响应。 */
export interface ReindexResponse {
  indexed_count: number;
  collection: string;
  message: string;
}

// ===== WebSocket =====
export interface TaskProgressMessage {
  task_id: string;
  status: TaskStatus;
  progress: number;
  result?: Record<string, unknown> | null;
  error?: string;
}

// ===== AI Provider 配置 =====
// 来源对照：backend/app/schemas/ai_config.py
// 统一 5 字段结构，所有 provider（本地/远程）一视同仁。
// split-llm-vlm-config：新增 role 字段区分文本模型与视觉模型配置。

export type ProviderType = "ollama" | "openai_compatible" | "anthropic";

/** 配置角色：llm=文本模型 / vlm=视觉模型。 */
export type ConfigRole = "llm" | "vlm";

/** Provider 配置响应（api_key 脱敏：有 key 返回 "***"，无 key 返回 ""）。 */
export interface AIProviderConfig {
  id: number;
  name: string;
  provider_type: ProviderType;
  base_url: string;
  api_key: string;
  model: string;
  vlm_model: string;
  /** 配置角色：llm=文本模型 / vlm=视觉模型。 */
  role: ConfigRole;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

/** 新增 provider 配置请求体。
 *
 * split-llm-vlm-config：``role`` 决定必填字段：
 * - role="llm"：``model`` 必填，``vlm_model`` 留空
 * - role="vlm"：``vlm_model`` 必填，``model`` 留空
 */
export interface AIProviderConfigCreate {
  name: string;
  provider_type: ProviderType;
  base_url: string;
  api_key?: string;
  model: string;
  vlm_model?: string;
  role: ConfigRole;
}

/** 更新 provider 配置请求体（所有字段可选）。
 *
 * api_key: undefined 表示不修改，传值（含空串）表示更新。
 * role 一般不修改（创建后即固定）。
 */
export interface AIProviderConfigUpdate {
  name?: string;
  provider_type?: ProviderType;
  base_url?: string;
  api_key?: string;
  model?: string;
  vlm_model?: string;
  role?: ConfigRole;
}

/** 测试连接结果。 */
export interface AIConfigTestResult {
  available: boolean;
  vlm_available: boolean;
  latency_ms: number;
  error: string;
}
