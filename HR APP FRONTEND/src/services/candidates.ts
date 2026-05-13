import api from './api';
import { assertBlobResponseSuccess, throwBlobRequestError } from './blobError';

export const getCandidates = async (jobId?: string, limit?: number, signal?: AbortSignal) => {
  const params: Record<string, unknown> = {};
  if (jobId) params.job_id = jobId;
  if (limit !== undefined) params.limit = limit;
  const response = await api.get('/resumes/', { params, signal });
  return response.data;
};

export const getCandidate = async (id: string, signal?: AbortSignal) => {
  const response = await api.get(`/resumes/${id}`, { signal });
  return response.data;
};

export const uploadResume = async (jobId: string, file: File) => {
  const formData = new FormData();
  formData.append('job_id', jobId);
  formData.append('file', file);
  const response = await api.post('/resumes/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return response.data;
};

export const uploadBulkResumes = async (jobId: string, files: File[]) => {
  const formData = new FormData();
  formData.append('job_id', jobId);
  for (let i = 0; i < files.length; i++) {
    formData.append('files', files[i]);
  }
  const response = await api.post('/resumes/upload-bulk', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 300_000, // 5 min — concurrent AI processing still takes time for large batches
  });
  return response.data;
};

export interface BulkUploadAsyncStart {
  run_id: string;
  job_id: string;
  status: 'started' | 'queued' | 'running' | 'completed' | 'failed';
  accepted_count: number;
  rejected_count: number;
  poll_url: string;
}

export interface BulkUploadAsyncStatus {
  id: string;
  status: 'queued' | 'running' | 'completed' | 'failed';
  job_id: string;
  requested_count: number;
  accepted_count: number;
  rejected_count: number;
  progress?: {
    processed: number;
    total: number;
    success_count: number;
    failed_count: number;
    duplicate_count: number;
  };
  result?: {
    http_status: number;
    summary: {
      success?: Array<{ filename: string; file_id: string; candidate_id: string }>;
      failed?: Array<{ filename: string; file_id: string; error: string }>;
      skipped_duplicates?: Array<{ filename: string; file_id: string; reason: string; email?: string }>;
      success_count?: number;
      failed_count?: number;
      duplicate_count?: number;
    };
  };
  error?: string | null;
}

export const uploadBulkResumesAsync = async (jobId: string, files: File[], fileIds?: string[]) => {
  const formData = new FormData();
  formData.append('job_id', jobId);
  for (let i = 0; i < files.length; i++) {
    formData.append('files', files[i]);
    formData.append('file_ids', fileIds?.[i] ?? `${files[i].name}_${i}`);
  }
  const response = await api.post<BulkUploadAsyncStart>('/resumes/upload-bulk-async', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120_000,
  });
  return response.data;
};

export const getBulkUploadAsyncStatus = async (runId: string) => {
  const response = await api.get<BulkUploadAsyncStatus>(`/resumes/upload-bulk-async/${runId}`);
  return response.data;
};

export const uploadSingleResumeForJob = async (jobId: string, file: File) => {
  const formData = new FormData();
  formData.append('job_id', jobId);
  formData.append('files', file);
  const response = await api.post('/resumes/upload-bulk', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 60_000,
  });
  return response.data;
};

export const updateCandidate = async (id: string, data: any) => {
  const response = await api.patch(`/resumes/${id}`, data);
  return response.data;
};

export const shortlistCandidates = async (
  jobId: string,
  strongThreshold = 75,
  // Must match backend MEDIUM_THRESHOLD in app/constants/scoring.py
  mediumThreshold = 55
) => {
  const response = await api.post('/resumes/shortlist', null, {
    params: {
      job_id: jobId,
      strong_threshold: strongThreshold,
      medium_threshold: mediumThreshold,
    },
  });
  return response.data;
};

export const downloadResume = async (id: string) => {
  try {
    const response = await api.get(`/resumes/${id}/resume-file`, {
      responseType: 'blob', // Crucial for downloading binary PDF files
    });
    const blob: Blob = response.data;
    await assertBlobResponseSuccess(blob, 'Resume download failed.');
    return blob;
  } catch (error) {
    return throwBlobRequestError(error, 'Resume download failed.');
  }
};

export const draftCandidateEmail = async (id: string, emailType: string) => {
  const response = await api.post(`/resumes/${id}/draft-email`, { email_type: emailType });
  return response.data;
};

export const sendCandidateEmail = async (id: string, subject: string, body: string) => {
  const response = await api.post(`/resumes/${id}/send-email`, { subject, body });
  return response.data;
};

export const uploadBulkResumesToPool = async (files: File[]) => {
  const formData = new FormData();
  for (let i = 0; i < files.length; i++) {
    formData.append('files', files[i]);
  }
  const response = await api.post('/resumes/upload-bulk-pool', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 300_000, // 5 min timeout for large pool uploads
  });
  return response.data;
};

export const uploadSingleToPool = async (file: File) => {
  const formData = new FormData();
  formData.append('file', file);
  const response = await api.post('/resumes/upload-pool', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120_000,
  });
  return response.data;
};


export const getPoolMatches = async (jobId: string, minScore = 0): Promise<any[]> => {
  const response = await api.get('/resumes/pool-matches', {
    params: { job_id: jobId, min_score: minScore },
  });
  return response.data;
};

export const importFromPool = async (jobId: string, candidateIds: string[]) => {
  const response = await api.post('/resumes/import-from-pool', {
    job_id: jobId,
    candidate_ids: candidateIds,
  });
  return response.data;
};

export const getAllCandidatesData = async (search?: string, skip = 0, limit = 500) => {
  const params: any = { skip, limit };
  if (search) params.search = search;
  const response = await api.get('/resumes/all-data', { params });
  return response.data;
};

export const deleteCandidates = async (candidateIds: string[]) => {
  const response = await api.post('/resumes/bulk-delete', { candidate_ids: candidateIds });
  return response.data;
};

/**
 * Soft-remove candidates from the active pipeline (sets is_archived=True).
 * Records remain visible in the All Data master archive modal.
 * This is what "Clear Displayed" calls — it does NOT permanently delete.
 */
export const archiveCandidates = async (candidateIds: string[]) => {
  const response = await api.post('/resumes/bulk-archive', { candidate_ids: candidateIds });
  return response.data;
};

/**
 * Restore archived candidates back to the active pipeline (sets is_archived=False).
 * Called from the All Data modal "Restore" action.
 */
export const restoreCandidates = async (candidateIds: string[]) => {
  const response = await api.post('/resumes/bulk-restore', { candidate_ids: candidateIds });
  return response.data;
};

export interface PipelineStats {
  total_candidates: number;
  shortlisted: number;
  hired: number;
  tested: number;
  final_ranked: number;
  avg_quiz_score: number | null;
}

/**
 * Lightweight aggregate counts for the Dashboard summary cards and hiring funnel.
 * Returns only numbers — no candidate rows — so it's fast regardless of pipeline size.
 */
export const getPipelineStats = async (signal?: AbortSignal): Promise<PipelineStats> => {
  const response = await api.get<PipelineStats>('/resumes/stats', { signal });
  return response.data;
};

export interface QuizSkillBreakdown {
  score: number;
  max: number;
  pct: number;
}

export interface CandidateQuizResult {
  attempt_id: string;
  candidate_id: string;
  candidate_name: string | null;
  quiz_title: string;
  status: string;
  raw_score: number;
  max_score: number;
  percentage: number;
  passed: boolean | null;
  tab_switches: number;
  started_at: string | null;
  submitted_at: string | null;
  skill_breakdown: Record<string, QuizSkillBreakdown>;
  difficulty_breakdown: Record<string, QuizSkillBreakdown>;
}

/**
 * Fetch the detailed quiz result for a candidate (HR use only).
 * Returns 404 if the candidate has not yet submitted a quiz.
 */
export const getCandidateQuizResult = async (candidateId: string): Promise<CandidateQuizResult> => {
  const response = await api.get<CandidateQuizResult>(`/resumes/${candidateId}/quiz-result`);
  return response.data;
};

export interface RefreshJDSimilarityResult {
  message: string;
  job_id: string;
  processed: number;
  updated: number;
  skipped_no_text: number;
  failed: number;
  failed_candidates?: Array<{ candidate_id: string; reason: string }>;
}

export const refreshJobJDSimilarity = async (
  jobId: string,
  opts?: { limit?: number; includeArchived?: boolean },
): Promise<RefreshJDSimilarityResult> => {
  const response = await api.post<RefreshJDSimilarityResult>(
    `/resumes/jobs/${jobId}/refresh-jd-similarity`,
    null,
    {
      params: {
        limit: opts?.limit ?? 500,
        include_archived: opts?.includeArchived ?? false,
      },
      timeout: 300_000,
    }
  );
  return response.data;
};
