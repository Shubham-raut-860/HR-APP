import api from './api';

export interface Quiz {
  id: string;
  job_id: string;
  title: string;
  duration_minutes: number;
  is_active: boolean;
  question_count: number;
  created_at: string;
}

export interface Question {
  id: string;
  question_text: string;
  options: string[];
  difficulty: 'easy' | 'medium' | 'hard';
  skill_tag: string;
  weight: number;
}

export interface QuizStartResponse {
  attempt_id: string;
  quiz_id: string;
  duration_minutes: number;
  // FIX (Bug #2): backend now computes exact remaining time so a resumed quiz
  // doesn't reset the countdown to the full duration.
  time_remaining_seconds: number;
  started_at: string;
  questions: Question[];
}

export interface QuizResult {
  attempt_id: string;
  candidate_id: string;
  status: string;
  raw_score: number;
  max_score: number;
  percentage: number;
  skill_breakdown: Record<string, any>;
  difficulty_breakdown: Record<string, any>;
  passed?: boolean | null;
}

export interface QuizAnswerItem {
  question_id: string;
  question_type: "mcq" | "coding" | string;
  question_text: string;
  skill_tag?: string | null;
  difficulty?: "easy" | "medium" | "hard" | string | null;
  selected_answer?: unknown;
  selected_option_index?: number | null;
  selected_option_text?: string | null;
  correct_option_index?: number | null;
  correct_option_text?: string | null;
  is_correct?: boolean | null;
  score_awarded?: number | null;
  max_score?: number | null;
}

export interface CandidateAnswerSheet {
  attempt_id: string;
  candidate_id: string;
  candidate_name?: string | null;
  candidate_email?: string | null;
  status: string;
  raw_score: number;
  max_score: number;
  percentage: number;
  passed?: boolean | null;
  submitted_at?: string | null;
  answers: QuizAnswerItem[];
}

export interface QuizMasterAnswerSheet {
  quiz_id: string;
  quiz_title: string;
  generated_at: string;
  passed_only: boolean;
  total_candidates: number;
  candidates: CandidateAnswerSheet[];
}

export interface QuestionWithAnswer {
  id: string;
  question_text: string;
  options: string[];
  difficulty: 'easy' | 'medium' | 'hard';
  skill_tag: string;
  weight: number;
  correct_answer: number;
}

export interface QuizMagicLinkContext {
  job_title: string | null;
  quiz_title: string;
  has_existing_account: boolean;
  status: 'pending' | 'started' | 'completed';
}

export const getQuestions = async (quizId: string, signal?: AbortSignal): Promise<QuestionWithAnswer[]> => {
  const response = await api.get<QuestionWithAnswer[]>(`/quiz/${quizId}/questions`, { signal });
  return response.data;
};

export const generateQuiz = async (jobId: string, customTitle?: string, durationMinutes?: number) => {
  const response = await api.post<Quiz>(
    '/quiz/generate',
    { job_id: jobId, custom_title: customTitle, duration_minutes: durationMinutes },
    { timeout: 180_000 }
  );
  return response.data;
};

export const getQuizzes = async (jobId?: string, signal?: AbortSignal) => {
  const response = await api.get<Quiz[]>('/quiz/', { params: { job_id: jobId }, signal });
  return response.data;
};

export const getQuizResults = async (quizId: string) => {
  const response = await api.get<QuizResult[]>(`/quiz/${quizId}/results`);
  return response.data;
};

export const getQuizAnswerSheet = async (
  quizId: string,
  passedOnly = true,
): Promise<QuizMasterAnswerSheet> => {
  const response = await api.get<QuizMasterAnswerSheet>(`/quiz/${quizId}/answer-sheet`, {
    params: { passed_only: passedOnly },
  });
  return response.data;
};

export const startQuiz = async (token: string) => {
  const response = await api.post<QuizStartResponse>(
    '/quiz/start',
    null,
    {
      headers: {
        'X-Quiz-Token': token,
      },
    }
  );
  return response.data;
};

export const getQuizMagicLinkContext = async (token: string) => {
  const response = await api.get<QuizMagicLinkContext>('/quiz/magic-link/context', {
    headers: { 'X-Quiz-Token': token },
  });
  return response.data;
};

export const claimQuizMagicLink = async (token: string) => {
  const response = await api.post<{ message: string }>('/quiz/magic-link/claim', null, {
    headers: { 'X-Quiz-Token': token },
  });
  return response.data;
};

export const submitQuiz = async (attemptId: string, answers: Record<string, number>, tabSwitches: number) => {
  const quizToken = sessionStorage.getItem('quiz_token');
  const runtimeQuizToken = sessionStorage.getItem('quiz_access_token');
  const tokenForHeader = quizToken ?? runtimeQuizToken ?? '';
  if (!quizToken) {
    console.warn('Quiz submit without quiz_token in sessionStorage; proceeding with fallback path.');
  }
  // Submit can be slow: scoring + DB write + push notifications.
  // The global api timeout is 30s — that's too tight here. Use 3 minutes.
  // A cancelled request causes Chrome to report "No CORS header" instead of
  // "ERR_ABORTED", which is a well-known Chrome false-positive on aborted XHR.
  const response = await api.post<QuizResult>('/quiz/submit', {
    attempt_id: attemptId,
    answers,
    tab_switches: tabSwitches,
  }, {
    timeout: 180_000,
    headers: {
      'X-Quiz-Token': tokenForHeader,
    },
  });
  return response.data;
};

export const sendQuizLinks = async (candidateIds: string[], quizId: string) => {
  const response = await api.post('/quiz/send-links', { candidate_ids: candidateIds, quiz_id: quizId });
  return response.data;
};


export const evaluateCode = async (attempt_id: string, problem: string, code: string, language: string) => {
  const response = await api.post('/quiz/evaluate-code', { attempt_id, problem, code, language });
  return response.data;
};

export const uploadQuizFromFile = async (
  jobId: string,
  file: File,
  durationMinutes = 30,
): Promise<Quiz> => {
  const form = new FormData();
  form.append('file', file);
  const response = await api.post<Quiz>('/quiz/from-file', form, {
    params: { job_id: jobId, duration_minutes: durationMinutes },
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120_000,
  });
  return response.data;
};
