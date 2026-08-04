import api from "@/services/api";

export interface InspectorOverview {
  generated_at: string;
  window_minutes: number;
  readiness: {
    verdict: "production_ready" | "watch" | "not_ready";
    infrastructure_score: number;
    checks: Record<string, boolean>;
    notes: string[];
  };
  harness: {
    status: string;
    redis_reachable: boolean;
    run_count: number;
    recent_runs: Array<{
      run_id: string;
      agent_type: string;
      status: string;
      created_at: string | null;
      started_at: string | null;
      completed_at: string | null;
      success: boolean;
      steps: number;
      tokens: number;
      cost_usd: number;
      elapsed_seconds: number;
      failure_class?: string | null;
      error_message?: string | null;
    }>;
    trace_summaries: Array<{
      run_id: string;
      status: string;
      span_count: number;
      duration_ms: number;
      total_input_tokens: number;
      total_output_tokens: number;
      total_cost_usd: number;
    }>;
    metrics: {
      completed: number;
      failed: number;
      cancelled: number;
      inflight: number;
      success_rate: number;
      avg_elapsed_seconds: number;
      avg_steps: number;
      avg_tokens: number;
      avg_cost_usd: number;
    };
    detail?: string;
  };
  model_fit?: {
    recommendations?: {
      opportunities?: Array<{
        task_name: string;
        current_model: string;
        suggested_model: string;
        estimated_savings_pct: number;
        confidence: string;
      }>;
    };
  };
  prompt_quality?: {
    status?: string;
    overall_avg_score?: number;
    overall_pass_rate?: number;
  };
  ocr_quality?: {
    status?: string;
    valid_text_ratio?: number;
  };
}

export async function getHrInspectorOverview(
  windowMinutes = 1440,
  runLimit = 20,
  traceLimit = 8,
  signal?: AbortSignal,
): Promise<InspectorOverview> {
  const response = await api.get<InspectorOverview>("/evals/hr-inspector", {
    params: {
      window_minutes: windowMinutes,
      run_limit: runLimit,
      trace_limit: traceLimit,
    },
    signal,
  });
  return response.data;
}

