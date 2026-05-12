/**
 * TypeScript interfaces mirroring the backend Pydantic schemas.
 *
 * Field names use snake_case to match the API response exactly — the old
 * version used camelCase which conflicted with every actual API call and
 * caused no component to import from here (they fell back to `any[]` instead).
 *
 * Mirrors: backend/app/schemas.py  (UserOut, JDOut, CandidateListOut, CandidateOut)
 */

// ─── Auth ─────────────────────────────────────────────────────────────────────

export type UserRole = 'admin' | 'hr' | 'candidate';

export interface UserOut {
  id: string;
  email: string;
  full_name: string;
  role: UserRole;
  is_active: boolean;
  bio?: string | null;
  preferences?: Record<string, unknown> | null;
  created_at: string;
}

// ─── Job Description ──────────────────────────────────────────────────────────

export interface JDOut {
  id: string;
  title: string;
  role: string;
  location?: string | null;
  employment_type?: string | null;
  experience_min: number;
  experience_max: number;
  must_have_skills: string[];
  good_to_have_skills: string[];
  description?: string | null;
  salary_range?: string | null;
  education_requirement?: string | null;
  resume_weight: number;
  quiz_weight: number;
  pass_threshold: number;
  is_active: boolean;
  created_at: string;
}

// ─── Candidate ────────────────────────────────────────────────────────────────

export type CandidateTag = 'Strong' | 'Medium' | 'Reject';
export type CandidateTier = 'fresher' | 'mid' | 'senior';

export interface ScoreBreakdown {
  ai_score_used: boolean;
  ai_skill_score?: number | null;
  ai_experience_score?: number | null;
  ai_project_score?: number | null;
  matched_must_have: string[];
  missing_must_have: string[];
  matched_good_to_have: string[];
  reasoning: string;
  domain_fit: string;
  seniority_match: string;
  hire_recommendation: string;
  red_flags: string[];
  standout_factors: string[];
  confidence: string;
  candidate_tier?: CandidateTier;
  from_cache?: boolean;
  rule_based?: {
    skill_pct: number;
    exp_pct: number;
    proj_pct: number;
  };
}

export interface EducationItem {
  degree?: string | null;
  institute?: string | null;
  year?: string | null;
  gpa?: string | null;
}

export interface ProjectItem {
  title?: string | null;
  description?: string | null;
  skills: string[];
}

/** Lightweight shape returned by list endpoints — no embeddings or raw blobs. */
export interface CandidateListOut {
  id: string;
  job_id?: string | null;
  user_id?: string | null;
  name?: string | null;
  email?: string | null;
  phone?: string | null;
  skills: string[];
  normalized_skills: string[];
  experience_years?: number | null;
  education: EducationItem[];
  projects: ProjectItem[];
  skill_match_pct: number;
  experience_match_pct: number;
  project_relevance_pct: number;
  education_match_pct: number;
  location_match_pct?: number | null;
  candidate_tier?: CandidateTier | null;
  vector_similarity: number;
  resume_score: number;
  score_breakdown?: ScoreBreakdown | null;
  career_breaks?: Record<string, unknown>[] | null;
  tag?: CandidateTag | null;
  quiz_score?: number | null;
  quiz_max?: number | null;
  quiz_pct?: number | null;
  final_score?: number | null;
  rank?: number | null;
  passed?: boolean | null;
  is_archived: boolean;
  created_at: string;
}

/** Full shape returned by single-candidate detail endpoints (includes work_experience). */
export interface CandidateOut extends CandidateListOut {
  work_experience?: Record<string, unknown>[] | null;
  skill_years?: Record<string, number> | null;
}

// ─── Notifications ────────────────────────────────────────────────────────────

export type NotificationType =
  | 'job_posted'
  | 'email_sent'
  | 'quiz_link'
  | 'shortlisted'
  | 'tag_updated'
  | 'quiz_result'
  | 'system';

export interface AppNotification {
  id: string;
  title: string;
  message: string;
  type: NotificationType;
  is_read: boolean;
  is_dismissed: boolean;
  related_id?: string | null;
  created_at: string;
}

// ─── Analytics ────────────────────────────────────────────────────────────────

export interface AnalyticsSummary {
  total_applicants: number;
  shortlisted_count: number;
  shortlisted_pct: number;
  quiz_taken_count: number;
  ranked_count: number;
  strong_count: number;
  medium_count: number;
  reject_count: number;
  avg_resume_score: number;
  avg_quiz_score?: number | null;
  avg_quiz_pct?: number | null;
  avg_final_score?: number | null;
  pass_count: number;
  fail_count: number;
}
