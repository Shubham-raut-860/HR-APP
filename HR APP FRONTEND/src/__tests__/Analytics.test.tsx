import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import Analytics from "@/pages/Analytics";
import Dashboard from "@/pages/Dashboard";

const mockGetJobs = vi.fn();
const mockGetSummary = vi.fn();
const mockGetRankings = vi.fn();
const mockGetSkillGap = vi.fn();
const mockGetCandidates = vi.fn();
const mockGetPipelineStats = vi.fn();

vi.mock("@/context/AuthContext", () => ({
  useAuth: () => ({
    user: { id: "user-1", role: "hr", full_name: "HR User" },
  }),
}));

vi.mock("@/services/jobs", () => ({
  getJobs: (...args: unknown[]) => mockGetJobs(...args),
}));

vi.mock("@/services/analytics", () => ({
  getSummary: (...args: unknown[]) => mockGetSummary(...args),
  getRankings: (...args: unknown[]) => mockGetRankings(...args),
  getSkillGap: (...args: unknown[]) => mockGetSkillGap(...args),
  exportExcel: vi.fn(),
  exportPDF: vi.fn(),
}));

vi.mock("@/services/candidates", () => ({
  getCandidates: (...args: unknown[]) => mockGetCandidates(...args),
  getPipelineStats: (...args: unknown[]) => mockGetPipelineStats(...args),
}));

vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  BarChart: ({ data = [] }: { data?: Array<{ name: string; value: number }> }) => (
    <div data-testid="bar-chart">
      {data.map((d) => (
        <div key={d.name}>{`${d.name}:${d.value}`}</div>
      ))}
    </div>
  ),
  Bar: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
  XAxis: () => null,
  YAxis: () => null,
  Tooltip: () => null,
  Cell: () => null,
  LabelList: () => null,
  CartesianGrid: () => null,
}));

describe("Analytics and Dashboard contracts", () => {
  beforeEach(() => {
    vi.clearAllMocks();

    if (!("ResizeObserver" in globalThis)) {
      class ResizeObserver {
        observe() {}
        unobserve() {}
        disconnect() {}
      }
      (globalThis as typeof globalThis & { ResizeObserver: typeof ResizeObserver }).ResizeObserver = ResizeObserver;
    }
  });

  it("renders quiz_taken_count and ranked_count from analytics API response", async () => {
    mockGetJobs.mockResolvedValue([{ id: "job-1", title: "Backend Engineer", is_active: true }]);
    mockGetSummary.mockResolvedValue({
      total_applicants: 20,
      shortlisted_count: 10,
      shortlisted_pct: 50,
      quiz_taken_count: 7,
      ranked_count: 5,
      strong_count: 4,
      medium_count: 6,
      reject_count: 10,
      avg_resume_score: 61.2,
      avg_quiz_score: 68.5,
      avg_final_score: 63.9,
      pass_count: 3,
      fail_count: 2,
    });
    mockGetRankings.mockResolvedValue([]);
    mockGetSkillGap.mockResolvedValue([]);

    render(
      <MemoryRouter>
        <Analytics />
      </MemoryRouter>
    );

    await waitFor(() => expect(mockGetSummary).toHaveBeenCalled());
    expect(screen.getByText("Quiz Taken:7")).toBeTruthy();
    expect(screen.getByText("Final Ranked:5")).toBeTruthy();
  });

  it("renders explicit degraded state when pipeline stats API fails", async () => {
    mockGetJobs.mockResolvedValue([{ id: "job-1", title: "Platform Engineer", is_active: true }]);
    mockGetCandidates.mockResolvedValue([]);
    mockGetPipelineStats.mockRejectedValue(new Error("stats endpoint down"));

    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>
    );

    expect(await screen.findByText(/Pipeline stats unavailable/i)).toBeTruthy();
    expect(screen.getAllByText("N/A").length).toBeGreaterThan(0);
  });
});
