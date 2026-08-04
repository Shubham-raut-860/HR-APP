import api from './api';
import { assertBlobResponseSuccess, throwBlobRequestError } from './blobError';

export interface SkillFeedback {
  skill: string;
  required: boolean;
  candidate_has: boolean;
  importance: string;
  suggestion?: string;
}

export interface CandidateOut {
  id: string;
  job_id: string;
  tag: string;
  resume_score: number;
  quiz_score: number | null;
  final_score: number | null;
  passed: boolean | null;
  created_at: string;
  /** @deprecated use created_at — backwards-compat alias returned by /candidate/results */
  applied_at?: string;
  job_title?: string;
  job_role?: string;
  quiz_status?: "pending" | "in_progress" | "submitted" | "timed_out" | null;
}

export interface CandidatePortalOut {
  candidate_id: string;
  job_id: string;
  job_title: string;
  job_role: string;
  resume_score: number;
  skill_match_pct: number;
  experience_match_pct: number;
  project_relevance_pct: number;
  education_match_pct: number;
  tag: string;
  quiz_score: number | null;
  // BUG-F1 FIX: was typed as number but backend returns null when no quiz exists.
  // Rendering "Score: X / null" before a quiz is assigned is now prevented at the
  // type level — every consumer must handle the null case explicitly.
  quiz_max_score: number | null;
  final_score: number | null;
  passed: boolean | null;
  rank: number | null;
  skill_feedback: SkillFeedback[];
  quiz_status: "pending" | "in_progress" | "submitted" | "timed_out" | null;
  quiz_token?: string;
}

export interface CandidateResultOut {
  candidate_id: string;
  job_id: string;
  job_title: string;
  application_status?: 'active' | 'withdrawn';
  created_at: string;
  applied_at?: string;
  tag: string | null;
  resume_score: number;
  quiz_score: number | null;
  quiz_max_score: number | null;
  final_score: number | null;
  passed: boolean | null;
  rank: number | null;
  quiz_status: "pending" | "in_progress" | "submitted" | "timed_out" | null;
}

export interface CandidateCoachResponse {
  answer: string;
  headline: string;
  recommendations: string[];
  applications: Array<Record<string, any>>;
  resumes: Array<Record<string, any>>;
  risks: string[];
  metrics: Record<string, number | string | null>;
  data_scope: string;
  snapshot: Record<string, any>;
}

const normalizeCandidateResult = (item: any): CandidateResultOut => {
  const createdAt = item?.created_at ?? item?.applied_at ?? "";
  return {
    ...item,
    created_at: createdAt,
    // Keep legacy alias so old UI fallbacks continue to work.
    applied_at: item?.applied_at ?? createdAt,
  };
};

const requireJobId = (jobId: string, action: string): string => {
  const normalized = jobId?.trim();
  if (!normalized) {
    throw new Error(`${action}: job_id is required`);
  }
  return normalized;
};

// GET /candidate/jobs
export const getPublicJobs = async () => {
  const response = await api.get('/candidate/jobs');
  return response.data;
};

// GET /candidate/jobs/:id
export const getPublicJob = async (id: string) => {
  const response = await api.get(`/candidate/jobs/${id}`);
  return response.data;
};

// POST /candidate/apply/:job_id
export const applyToJob = async (jobId: string, file: File, careerBreaks?: any[]) => {
  const safeJobId = requireJobId(jobId, 'applyToJob');
  const formData = new FormData();
  formData.append('file', file);
  if (careerBreaks && careerBreaks.length > 0) {
    formData.append('career_breaks', JSON.stringify(careerBreaks));
  }
  const response = await api.post(`/candidate/apply/${safeJobId}`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return response.data;
};

// GET /candidate/my-applications
export const getMyApplications = async () => {
  const response = await api.get('/candidate/my-applications');
  return response.data;
};

// GET /candidate/feedback/:candidate_id
export const getMyFeedback = async (candidateId: string) => {
  const response = await api.get(`/candidate/feedback/${candidateId}`);
  return response.data;
};

// GET /candidate/quiz
export const getMyPendingQuiz = async (signal?: AbortSignal) => {
  const response = await api.get('/candidate/quiz', { signal });
  return response.data;
};

// GET /candidate/results
export const getMyResults = async (signal?: AbortSignal) => {
  const response = await api.get('/candidate/results', { signal });
  const rows = Array.isArray(response.data) ? response.data : [];
  return rows.map(normalizeCandidateResult);
};

export const askCandidateCoach = async (payload: {
  question: string;
  candidate_id?: string;
}): Promise<CandidateCoachResponse> => {
  const response = await api.post('/candidate/coach', payload);
  return response.data;
};

export const withdrawApplication = async (candidateId: string): Promise<{
  message: string;
  candidate_id: string;
  application_status: 'withdrawn';
  already_withdrawn?: boolean;
}> => {
  const response = await api.post(`/candidate/applications/${candidateId}/withdraw`);
  return response.data;
};

// GET /candidate/mock-test
export const generateMockTest = async (resumeContext?: string) => {
  const response = await api.get('/candidate/mock-test', {
    params: resumeContext ? { context: resumeContext } : undefined,
  });
  return response.data;
};

// ─── Resume Vault ─────────────────────────────────────────────────────────────

export interface StoredResume {
  id: string;
  label: string;
  original_filename: string;
  file_size_kb: number;
  is_default: boolean;
  uploaded_at: string;
  parsed_name?: string | null;
  parsed_email?: string | null;
  experience_years?: number | null;
  normalized_skills?: string[] | null;
  summary?: string | null;
  is_parsed?: boolean;
}

export type KycDocType =
  | 'aadhaar'
  | 'pan'
  | 'employment_proof'
  | 'passport'
  | 'driving_license'
  | 'salary_slip'
  | 'offer_letter';
export type KycDocStatus = 'uploaded' | 'verified' | 'rejected';

export interface CandidateKycDocument {
  id: string;
  doc_type: KycDocType;
  original_filename: string;
  file_size_kb: number;
  status: KycDocStatus;
  review_note?: string | null;
  uploaded_at: string;
  updated_at: string;
}

export interface CandidateKycChecklistItem {
  doc_type: KycDocType;
  label: string;
  mandatory: boolean;
  uploaded: boolean;
  status?: KycDocStatus | null;
  updated_at?: string | null;
}

export interface CandidateKycChecklist {
  all_mandatory_uploaded: boolean;
  items: CandidateKycChecklistItem[];
}

export interface CandidateKycConsent {
  candidate_id: string;
  recruiter_user_id: string;
  job_id: string;
  granted: boolean;
  granted_at?: string | null;
  revoked_at?: string | null;
  updated_at: string;
}

export interface CandidateKycMagicContext {
  valid: boolean;
  invite_id: string;
  candidate_id: string;
  job_id: string;
  expires_at: string;
  purpose: string;
  access_scope: string;
  retention_days: number;
  require_masked_aadhaar: boolean;
  legal_hold_required: boolean;
  allowed_doc_types: KycDocType[];
  mandatory_doc_types: KycDocType[];
}

export interface CandidateKycMagicUploadResult {
  message: string;
  uploaded_count: number;
  retention_days: number;
  invite_consumed: boolean;
  documents: CandidateKycDocument[];
}

export const getStoredResumes = async (signal?: AbortSignal): Promise<StoredResume[]> => {
  const res = await api.get('/candidate/my-resumes', { signal });
  return res.data;
};

export const uploadStoredResume = async (
  file: File,
  label: string,
  setAsDefault: boolean,
): Promise<StoredResume> => {
  const formData = new FormData();
  formData.append('file', file);
  const res = await api.post('/candidate/my-resumes', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    params: { label, set_as_default: setAsDefault },
  });
  return res.data;
};

export const updateStoredResume = async (
  id: string,
  data: { label?: string; is_default?: boolean },
): Promise<StoredResume> => {
  const res = await api.patch(`/candidate/my-resumes/${id}`, data);
  return res.data;
};

export const deleteStoredResume = async (id: string): Promise<void> => {
  await api.delete(`/candidate/my-resumes/${id}`);
};

export const getKycChecklist = async (): Promise<CandidateKycChecklist> => {
  const res = await api.get('/candidate/my-kyc-checklist');
  return res.data;
};

export const getKycDocuments = async (): Promise<CandidateKycDocument[]> => {
  const res = await api.get('/candidate/my-kyc-documents');
  return res.data;
};

export const uploadKycDocument = async (
  docType: KycDocType,
  file: File,
): Promise<CandidateKycDocument> => {
  const formData = new FormData();
  formData.append('file', file);
  const res = await api.post(`/candidate/my-kyc-documents/${docType}`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return res.data;
};

export const downloadKycDocument = async (docType: KycDocType): Promise<Blob> => {
  try {
    const res = await api.get(`/candidate/my-kyc-documents/${docType}/download`, {
      responseType: 'blob',
    });
    const blob: Blob = res.data;
    await assertBlobResponseSuccess(blob, 'KYC document download failed.');
    return blob;
  } catch (error) {
    return throwBlobRequestError(error, 'KYC document download failed.');
  }
};

export const listKycConsents = async (): Promise<CandidateKycConsent[]> => {
  const res = await api.get('/candidate/kyc-consents');
  return res.data;
};

export const setKycConsent = async (
  candidateId: string,
  granted: boolean,
): Promise<CandidateKycConsent> => {
  const res = await api.post(`/candidate/kyc-consent/${candidateId}`, { granted });
  return res.data;
};

export const getKycMagicContext = async (token: string): Promise<CandidateKycMagicContext> => {
  const res = await api.get('/candidate/kyc-magic/context', {
    params: { token },
  });
  return res.data;
};

export const uploadKycWithMagicLink = async (payload: {
  token: string;
  consentGiven: boolean;
  consentPurposeAck: string;
  consentAccessAck: string;
  consentRetentionAckDays: number;
  aadhaarMaskedConfirmed: boolean;
  docTypes: KycDocType[];
  files: File[];
}): Promise<CandidateKycMagicUploadResult> => {
  const formData = new FormData();
  formData.append('token', payload.token);
  formData.append('consent_given', String(payload.consentGiven));
  formData.append('consent_purpose_ack', payload.consentPurposeAck);
  formData.append('consent_access_ack', payload.consentAccessAck);
  formData.append('consent_retention_ack_days', String(payload.consentRetentionAckDays));
  formData.append('aadhaar_masked_confirmed', String(payload.aadhaarMaskedConfirmed));
  payload.docTypes.forEach((docType) => formData.append('doc_types', docType));
  payload.files.forEach((file) => formData.append('files', file));
  const res = await api.post('/candidate/kyc-magic/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return res.data;
};

export const applyWithVaultResume = async (jobId: string, resumeId: string): Promise<any> => {
  const safeJobId = requireJobId(jobId, 'applyWithVaultResume');
  const res = await api.post(`/candidate/apply-with-vault/${safeJobId}`, null, {
    params: { resume_id: resumeId },
  });
  return res.data;
};

export interface ResumeFitScore {
  resume_score: number;
  skill_match_pct: number;
  experience_match_pct: number;
  project_relevance_pct: number;
  education_match_pct: number;
  tag: 'strong' | 'medium' | 'reject';
  job_title: string;
  resume_label: string;
}

const normalizeResumeTag = (tag: string): 'strong' | 'medium' | 'reject' => {
  const normalized = tag?.trim().toLowerCase();
  if (normalized === 'strong' || normalized === 'medium' || normalized === 'reject') {
    return normalized;
  }
  // Safe fallback: keep UI logic deterministic even if backend adds/changes labels.
  return 'reject';
};

export const getResumeFitScore = async (jobId: string, resumeId: string): Promise<ResumeFitScore> => {
  const safeJobId = requireJobId(jobId, 'getResumeFitScore');
  const res = await api.get(`/candidate/resume-fit/${safeJobId}`, {
    params: { resume_id: resumeId },
  });
  return {
    ...res.data,
    tag: normalizeResumeTag(res.data?.tag),
  };
};

/**
 * @deprecated Use `downloadStoredResume` instead. This returns a bare relative
 * path without the API base URL or auth token.
 */
export const getStoredResumeDownloadUrl = (id: string): string => {
  return `/candidate/my-resumes/${id}/download`;
};

export const downloadStoredResume = async (id: string): Promise<Blob> => {
  try {
    const res = await api.get(`/candidate/my-resumes/${id}/download`, {
      responseType: 'blob',
    });
    const blob: Blob = res.data;
    await assertBlobResponseSuccess(blob, 'Resume download failed.');
    return blob;
  } catch (error) {
    return throwBlobRequestError(error, 'Resume download failed.');
  }
};

export const uploadProfileResume = async (file: File): Promise<StoredResume> => {
  return uploadStoredResume(file, file.name, true);
};

export const getProfileResume = async () => {
  try {
    const resumes = await getStoredResumes();
    const defaultResume = resumes.find(r => r.is_default) ?? resumes[0];
    if (defaultResume) {
      return { name: defaultResume.original_filename };
    }
    const apps = (await api.get('/candidate/my-applications')).data;
    if (apps?.length > 0) {
      const topSkills = apps[0].skills?.slice(0, 4).join(", ") || "General Skills";
      return { name: `AI Profile Database (${topSkills})` };
    }
  } catch (e) {
    console.error(e);
  }
  return null;
};

// ─── Career Tools (AI Generative) ─────────────────────────────────────────────

export const evaluateResumePrecheck = async (jobId: string, file: File) => {
  const safeJobId = requireJobId(jobId, 'evaluateResumePrecheck');
  const formData = new FormData();
  formData.append('file', file);
  const response = await api.post(`/candidate/evaluate-resume/${safeJobId}`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return response.data;
};

/**
 * Enhance a resume against a specific JD.
 * Supply either resume_id (vault) or resume_text (pasted text).
 *
 * Matches the merged backend endpoint — both paths now hit the same route
 * and the vault path traversal guard is active for resume_id requests.
 */
export const enhanceCandidateResume = async (
  jobId: string,
  opts: { resumeId: string } | { resumeText: string },
) => {
  const safeJobId = requireJobId(jobId, 'enhanceCandidateResume');
  const body: Record<string, string> = { job_id: safeJobId };
  if ('resumeId' in opts) {
    body.resume_id = opts.resumeId;
  } else {
    body.resume_text = opts.resumeText;
  }
  const res = await api.post('/candidate/resume/enhance', body);
  return res.data;
};

export const buildCandidateResume = async (data: {
  target_role?: string;
  // Structured
  personal_info?: Record<string, string>;
  work_experience?: object[];
  education?: object[];
  skills?: string[];
  projects?: object[];
  certifications?: string[];
  summary?: string;
  // Quick text form
  experience_summary?: string;
  skills_list?: string;
  education_summary?: string;
}) => {
  const res = await api.post('/candidate/resume/build', data);
  return res.data;
};

export const generateCoverLetter = async (jobId: string, resumeId?: string) => {
  const safeJobId = requireJobId(jobId, 'generateCoverLetter');
  const res = await api.post(`/candidate/cover-letter/${safeJobId}`, null, {
    params: resumeId ? { resume_id: resumeId } : undefined,
  });
  return res.data;
};

export const getCareerAnalysis = async (targetRole?: string, resumeId?: string) => {
  const params: Record<string, string> = {};
  if (targetRole) params.target_role = targetRole;
  if (resumeId) params.resume_id = resumeId;
  const res = await api.get('/candidate/career-analysis', { params });
  return res.data;
};

// ─── Resume Builder Advanced Tools ────────────────────────────────────────────

/** Upload an existing resume/doc/image and extract structured data to pre-fill the builder form. */
export const parseResumeForBuilder = async (file: File): Promise<any> => {
  const formData = new FormData();
  formData.append('file', file);
  const res = await api.post('/candidate/resume/parse-for-builder', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return res.data;
};

/** Convert a structured resume JSON object into a downloadable professional PDF via RenderCV. */
export const generateResumePDF = async (
  resume: Record<string, any>,
  theme: 'classic' | 'engineering' | 'sb2nov' | 'moderncv' = 'classic',
): Promise<Blob> => {
  try {
    const res = await api.post(
      '/candidate/resume/generate-pdf',
      { resume, theme },
      { responseType: 'blob' },
    );
    const blob: Blob = res.data;
    await assertBlobResponseSuccess(blob, 'Resume PDF generation failed.');
    return blob;
  } catch (error) {
    return throwBlobRequestError(error, 'Resume PDF generation failed.');
  }
};

/** Enhance a single bullet point using AI against a specific job title context. */
export const enhanceBulletPoint = async (
  bullet: string,
  jobId: string,
  jobTitle: string,
  context?: string,
): Promise<string> => {
  const safeJobId = requireJobId(jobId, 'enhanceBulletPoint');
  const body = {
    job_id: safeJobId,
    resume_text: `Role context: ${jobTitle}. ${context || ''}\n\nBullet to enhance:\n${bullet}`,
  };
  const res = await api.post('/candidate/resume/enhance', body);
  const rewrites = res.data?.bullet_rewrites || res.data?.enhanced_work_experience;
  if (Array.isArray(rewrites) && rewrites.length > 0) {
    return rewrites[0]?.improved || rewrites[0]?.enhanced_bullets?.[0] || bullet;
  }
  return bullet;
};
