import api from "@/services/api";

export interface RecruiterCopilotResponse {
  answer: string;
  headline: string;
  recommendations: string[];
  focus_jobs: Array<Record<string, any>>;
  top_candidates: Array<Record<string, any>>;
  risks: string[];
  metrics: Record<string, any>;
  data_scope: string;
  snapshot: {
    metrics: Record<string, any>;
    jobs: Array<Record<string, any>>;
    data_scope: string;
  };
}

export async function askRecruiterCopilot(payload: {
  question: string;
  job_id?: string | null;
}): Promise<RecruiterCopilotResponse> {
  const response = await api.post("/recruiter-copilot/ask", payload, {
    timeout: 20_000,
  });
  return response.data;
}
