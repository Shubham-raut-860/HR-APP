import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import JobDetails from "@/pages/JobDetails";

const mockGetJob = vi.fn();
const mockGetCandidates = vi.fn();
const mockGetQuizzes = vi.fn();
const mockGetQuestions = vi.fn();
const mockGetSummary = vi.fn();
const mockGetRankings = vi.fn();
const mockGetSkillGap = vi.fn();

vi.mock("@/context/AuthContext", () => ({
  useAuth: () => ({ user: { id: "user-1", role: "hr", full_name: "HR User" } }),
}));

vi.mock("@/services/jobs", () => ({
  getJob: (...args: unknown[]) => mockGetJob(...args),
  updateJob: vi.fn(),
  closeJob: vi.fn(),
}));

vi.mock("@/services/candidates", () => ({
  getCandidates: (...args: unknown[]) => mockGetCandidates(...args),
  uploadBulkResumesAsync: vi.fn(),
  getBulkUploadAsyncStatus: vi.fn(),
  shortlistCandidates: vi.fn(),
  draftCandidateEmail: vi.fn(),
  sendCandidateEmail: vi.fn(),
}));

vi.mock("@/services/quiz", () => ({
  generateQuiz: vi.fn(),
  getQuizzes: (...args: unknown[]) => mockGetQuizzes(...args),
  sendQuizLinks: vi.fn(),
  getQuestions: (...args: unknown[]) => mockGetQuestions(...args),
  uploadQuizFromFile: vi.fn(),
}));

vi.mock("@/services/analytics", () => ({
  getSummary: (...args: unknown[]) => mockGetSummary(...args),
  getRankings: (...args: unknown[]) => mockGetRankings(...args),
  getSkillGap: (...args: unknown[]) => mockGetSkillGap(...args),
  exportExcel: vi.fn(),
  exportPDF: vi.fn(),
}));

vi.mock("@/components/ImportFromPoolModal", () => ({
  ImportFromPoolModal: () => null,
}));

vi.mock("@/components/AnalyticsView", () => ({
  AnalyticsView: () => null,
}));

vi.mock("@/components/ShortlistTable", () => ({
  ShortlistTable: () => null,
}));

vi.mock("@/components/QuizResultModal", () => ({
  QuizResultModal: () => null,
}));

vi.mock("@/components/dev/TokenBudgetWidget", () => ({
  TokenBudgetWidget: () => null,
}));

vi.mock("@/lib/devMonitor", () => ({
  canSeeDevTokenMonitor: () => false,
}));

vi.mock("@/components/job-details/InterviewKitPanel", () => ({
  InterviewKitPanel: () => null,
}));

vi.mock("@/components/job-details/widgets", () => ({
  HireRecBadge: () => null,
  DomainFitPip: () => null,
  scoreColor: () => "",
  scoreBg: () => "",
  CandidateIntelligencePanel: () => null,
  UploadReadyState: () => null,
  StatCard: ({ label, value }: { label: string; value: string | number }) => (
    <div>{`${label}:${String(value)}`}</div>
  ),
  TagBadge: ({ tag }: { tag?: string | null }) => <span>{tag ?? ""}</span>,
}));

const baseJob = {
  id: "job-1",
  title: "Senior React Engineer",
  role: "Frontend Engineer",
  is_active: true,
  employment_type: "Full-time",
  location: "Remote",
  experience_min: 3,
  experience_max: 8,
  created_at: "2026-05-01T00:00:00Z",
  must_have_skills: ["React", "TypeScript"],
  good_to_have_skills: ["Vite"],
  description: "Build and ship frontend apps.",
  resume_weight: 70,
  quiz_weight: 30,
  pass_threshold: 60,
};

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/jobs/job-1"]}>
      <Routes>
        <Route path="/jobs/:id" element={<JobDetails />} />
      </Routes>
    </MemoryRouter>
  );
}

async function activateTab(name: RegExp) {
  const tab = screen.getByRole("tab", { name });
  fireEvent.pointerDown(tab);
  fireEvent.mouseDown(tab);
  fireEvent.click(tab);
  await waitFor(() => {
    expect(screen.getByRole("tab", { name }).getAttribute("aria-selected")).toBe("true");
  });
}

describe("JobDetails quiz and score rendering", () => {
  beforeEach(() => {
    vi.clearAllMocks();

    mockGetJob.mockResolvedValue(baseJob);
    mockGetCandidates.mockResolvedValue([
      { id: "c-1", name: "Alice", email: "alice@example.com", tag: "Strong", quiz_score: 24, created_at: "2026-05-01T01:00:00Z" },
    ]);
    mockGetQuizzes.mockResolvedValue([
      {
        id: "quiz-1",
        title: "Frontend Screening",
        question_count: 4,
        duration_minutes: 15,
        is_active: true,
        created_at: "2026-05-01T02:00:00Z",
      },
    ]);
    mockGetQuestions.mockResolvedValue([
      { id: "q1", difficulty: "easy" },
      { id: "q2", difficulty: "easy" },
      { id: "q3", difficulty: "medium" },
      { id: "q4", difficulty: "hard" },
    ]);
    mockGetSummary.mockResolvedValue({
      total_applicants: 1,
      shortlisted_count: 1,
      shortlisted_pct: 100,
      strong_count: 1,
      medium_count: 0,
      reject_count: 0,
      avg_resume_score: 72.1,
      avg_quiz_score: 66.7,
      avg_quiz_pct: 66.7,
      avg_final_score: 70.2,
      pass_count: 1,
      fail_count: 0,
    });
    mockGetRankings.mockResolvedValue([
      {
        rank: 1,
        candidate_id: "c-1",
        name: "Alice",
        email: "alice@example.com",
        tag: "Strong",
        resume_score: 72.1,
        quiz_score: 24,
        quiz_pct: 66.7,
        final_score: 70.2,
        passed: true,
      },
    ]);
    mockGetSkillGap.mockResolvedValue([]);
  });

  it("computes quiz difficulty pills from question data instead of hardcoded values", async () => {
    renderPage();
    expect(await screen.findByText("Senior React Engineer")).toBeTruthy();

    await activateTab(/Quiz/i);

    await waitFor(() => {
      expect(screen.getByText(/2\s+easy/i)).toBeTruthy();
      expect(screen.getByText(/1\s+medium/i)).toBeTruthy();
      expect(screen.getByText(/1\s+hard/i)).toBeTruthy();
    });

    expect(screen.queryByText(/8\s+Easy/i)).toBeNull();
  });

  it("renders quiz_pct percentages in rankings and does not show hardcoded /36", async () => {
    renderPage();
    expect(await screen.findByText("Senior React Engineer")).toBeTruthy();

    await activateTab(/Analytics/i);
    const rankingButtons = screen.getAllByRole("button", { name: /Rankings/i });
    fireEvent.click(rankingButtons[rankingButtons.length - 1]);

    await waitFor(() => {
      expect(screen.getByText("66.7%")).toBeTruthy();
    });
    expect(screen.queryByText(/\/36/)).toBeNull();
  });
});
