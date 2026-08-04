import api from "@/services/api";

export type A2ATaskStatus = "queued" | "running" | "completed" | "failed" | "canceled";

export interface A2ACapability {
  name: string;
  description: string;
  input_modes: string[];
  output_modes: string[];
  streaming: boolean;
  side_effects: boolean;
}

export interface A2ASkill {
  id: string;
  name: string;
  description: string;
  tags: string[];
  examples: string[];
}

export interface A2AAgentCard {
  id: string;
  name: string;
  description: string;
  protocol_version: string;
  version: string;
  url: string;
  provider: string;
  visibility: "public" | "hr" | "internal";
  enabled: boolean;
  capabilities: A2ACapability[];
  skills: A2ASkill[];
  default_input_modes: string[];
  default_output_modes: string[];
  auth_schemes: string[];
  metadata: Record<string, unknown>;
}

export interface A2AAgentMessage {
  role: "user" | "agent" | "system";
  content: string;
  context: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  task_id?: string | null;
  trace_id?: string | null;
}

export interface A2AExecutionMetadata {
  agent_id: string;
  runtime: "hr_multi_agent_runtime";
  started_at: string | null;
  completed_at: string | null;
  latency_ms: number | null;
  model_used: string | null;
  token_usage: Record<string, unknown>;
  status_code: string | null;
}

export interface A2ATraceMetadata {
  trace_id: string;
  request_id: string | null;
  run_id: string | null;
  correlation_id: string | null;
  agent_trace: Array<Record<string, unknown>>;
}

export interface A2AArtifact {
  id: string;
  task_id: string;
  name: string;
  artifact_type: "json" | "text" | "trace" | "error";
  mime_type: string;
  data: unknown;
  redacted: boolean;
  created_at: string;
  metadata: Record<string, unknown>;
}

export interface A2AAuditEvent {
  id: string;
  actor_id: string;
  actor_type: "technical_admin" | "service_token";
  action: string;
  resource: string;
  resource_id: string | null;
  detail: Record<string, unknown>;
  created_at: string;
}

export interface A2ATask {
  id: string;
  agent_id: string;
  status: A2ATaskStatus;
  owner_id: string;
  message: A2AAgentMessage;
  result: {
    summary: string;
    output: Record<string, unknown>;
    artifact_ids: string[];
  } | null;
  error: string | null;
  trace: A2ATraceMetadata;
  execution: A2AExecutionMetadata;
  artifact_ids: string[];
  created_at: string;
  updated_at: string;
}

export interface ADKShadowSummary {
  enabled: boolean;
  execution_mode: string;
  events: number;
  completed: number;
  failed: number;
  compared: number;
  matched: number;
  match_rate_pct: number | null;
}

export interface ADKShadowEvent {
  workflow: string;
  status: string;
  started_at: string;
  latency_ms: number;
  production_hash: string | null;
  shadow_hash: string | null;
  match: boolean | null;
  execution_mode: string;
  entity_id: string | null;
  actor_id: string | null;
  error: string | null;
  metadata: Record<string, unknown>;
}

export interface ADKPromotionStatus {
  enabled: boolean;
  allowlist: string[];
  effective_workflows: Record<string, boolean>;
  timeout_seconds: number;
  fallback_to_legacy: boolean;
  min_quiz_quality_score: number;
  recent: ADKShadowEvent[];
  recent_counts: {
    completed: number;
    fallback: number;
    failed: number;
  };
}

export async function getA2AAgents(includeInternal = false): Promise<A2AAgentCard[]> {
  const res = await api.get("/a2a/agents", { params: { include_internal: includeInternal } });
  return res.data.agents || [];
}

export async function getA2AAgentCard(agentId: string): Promise<A2AAgentCard> {
  const res = await api.get(`/a2a/agents/${encodeURIComponent(agentId)}/card`);
  return res.data;
}

export async function sendA2AMessage(agentId: string, message: A2AAgentMessage): Promise<A2ATask> {
  const res = await api.post(`/a2a/agents/${encodeURIComponent(agentId)}/message`, message);
  return res.data;
}

export async function createA2ATask(
  agentId: string,
  message: A2AAgentMessage,
  executionMode: "sync" | "async" = "async",
): Promise<A2ATask> {
  const res = await api.post("/a2a/tasks", {
    agent_id: agentId,
    message,
    execution_mode: executionMode,
  });
  return res.data;
}

export async function getA2ATask(taskId: string): Promise<A2ATask> {
  const res = await api.get(`/a2a/tasks/${encodeURIComponent(taskId)}`);
  return res.data;
}

export async function getA2ATaskArtifacts(taskId: string): Promise<A2AArtifact[]> {
  const res = await api.get(`/a2a/tasks/${encodeURIComponent(taskId)}/artifacts`);
  return res.data || [];
}

export async function downloadA2AArtifact(taskId: string, artifactId: string): Promise<void> {
  const res = await api.get(
    `/a2a/tasks/${encodeURIComponent(taskId)}/artifacts/${encodeURIComponent(artifactId)}/download`,
    { responseType: "blob" },
  );
  const disposition = String(res.headers["content-disposition"] || "");
  const match = disposition.match(/filename="([^"]+)"/);
  const filename = match?.[1] || `${artifactId}.json`;
  const url = URL.createObjectURL(res.data);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export async function runA2AResumeScreeningEvaluation(payload: {
  resume_text: string;
  jd_text: string;
  label?: string;
  execution_mode?: "sync" | "async";
}): Promise<A2ATask> {
  const res = await api.post("/a2a/evaluations/resume-screening", {
    label: "Resume screening evaluation",
    execution_mode: "async",
    ...payload,
  });
  return res.data;
}

export async function getA2AAudit(limit = 100): Promise<A2AAuditEvent[]> {
  const res = await api.get("/a2a/audit", { params: { limit } });
  return res.data.events || [];
}

export async function getADKShadowSummary(): Promise<ADKShadowSummary> {
  const res = await api.get("/a2a/adk-shadow/summary");
  return res.data;
}

export async function getADKShadowRecent(limit = 50): Promise<ADKShadowEvent[]> {
  const res = await api.get("/a2a/adk-shadow/recent", { params: { limit } });
  return res.data.events || [];
}

export async function getADKPromotionStatus(limit = 25): Promise<ADKPromotionStatus> {
  const res = await api.get("/a2a/adk-promotion/status", { params: { limit } });
  return res.data;
}
