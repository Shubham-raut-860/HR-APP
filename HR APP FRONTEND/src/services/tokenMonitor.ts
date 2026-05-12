import api from '@/services/api';

export interface TokenSummary {
  window_minutes: number;
  enabled: boolean;
  calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  total_cost_usd: number;
  avg_latency_ms: number;
  over_budget_calls: number;
  cost_alert_calls: number;
  top_tasks_by_calls: Array<[string, number]>;
  top_tasks_by_tokens: Array<[string, number]>;
  top_models_by_calls: Array<[string, number]>;
}

export interface TokenHotspot {
  task_name: string;
  calls: number;
  total_tokens: number;
  avg_tokens_per_call: number;
  total_cost_usd: number;
  over_budget_calls: number;
  over_budget_rate_pct: number;
  budget_tokens: number;
}

interface HotspotsResponse {
  hotspots: TokenHotspot[];
}

export interface TokenBudgets {
  default_token_budget: number;
  warn_multiplier: number;
  max_cost_usd_per_call: number;
  task_budgets: Record<string, number>;
}

export interface ModelEfficiencyRow {
  model: string;
  calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  avg_tokens_per_call: number;
  total_cost_usd: number;
  avg_cost_per_call_usd: number;
  cost_per_1k_tokens_usd: number;
  avg_latency_ms: number;
  over_budget_calls: number;
  over_budget_rate_pct: number;
  cost_alert_calls: number;
}

interface ModelsResponse {
  models: ModelEfficiencyRow[];
}

export interface ModelRecommendation {
  task_name: string;
  current_model: string;
  suggested_model: string;
  estimated_savings_per_call_usd: number;
  estimated_savings_pct: number;
  token_ratio_vs_current: number;
  latency_ratio_vs_current: number;
  current_calls: number;
  suggested_calls: number;
  confidence: 'low' | 'medium' | 'high';
  note: string;
}

export interface RecommendationResponse {
  window_minutes: number;
  min_calls: number;
  opportunities: ModelRecommendation[];
  model_efficiency: ModelEfficiencyRow[];
}

export async function getTokenSummary(windowMinutes = 30, signal?: AbortSignal): Promise<TokenSummary> {
  const response = await api.get<TokenSummary>('/monitoring/tokens/summary', {
    params: { window_minutes: windowMinutes },
    signal,
  });
  return response.data;
}

export async function getTokenHotspots(topN = 5, windowMinutes = 30, signal?: AbortSignal): Promise<TokenHotspot[]> {
  const response = await api.get<HotspotsResponse>('/monitoring/tokens/hotspots', {
    params: { top_n: topN, window_minutes: windowMinutes },
    signal,
  });
  return response.data.hotspots || [];
}

export async function getTokenBudgets(signal?: AbortSignal): Promise<TokenBudgets> {
  const response = await api.get<TokenBudgets>('/monitoring/tokens/budgets', { signal });
  return response.data;
}

export async function getModelEfficiency(windowMinutes = 30, signal?: AbortSignal): Promise<ModelEfficiencyRow[]> {
  const response = await api.get<ModelsResponse>('/monitoring/tokens/models', {
    params: { window_minutes: windowMinutes },
    signal,
  });
  return response.data.models || [];
}

export async function getModelRecommendations(windowMinutes = 30, minCalls = 8, signal?: AbortSignal): Promise<RecommendationResponse> {
  const response = await api.get<RecommendationResponse>('/monitoring/tokens/recommendations', {
    params: { window_minutes: windowMinutes, min_calls: minCalls },
    signal,
  });
  return response.data;
}
