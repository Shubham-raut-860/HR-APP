import { beforeEach, describe, expect, it, vi } from "vitest";

const mockPost = vi.fn();

vi.mock("@/services/api", () => ({
  default: {
    post: (...args: unknown[]) => mockPost(...args),
  },
}));

import { shortlistCandidates } from "@/services/candidates";

describe("shortlist threshold contract", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("sends medium threshold = 55 by default", async () => {
    mockPost.mockResolvedValue({ data: { shortlisted_ids: [] } });
    await shortlistCandidates("job-1");

    expect(mockPost).toHaveBeenCalledTimes(1);
    const [, , config] = mockPost.mock.calls[0];
    expect(config.params.medium_threshold).toBe(55);
  });

  it("includes score=55 and excludes score=54 at threshold boundary with mocked API response", async () => {
    const sample = [
      { candidate_id: "c-55", final_score: 55 },
      { candidate_id: "c-54", final_score: 54 },
    ];

    mockPost.mockImplementation((_url: string, _body: unknown, config: { params: { medium_threshold: number } }) => {
      const cutoff = config.params.medium_threshold;
      const shortlisted = sample.filter((c) => c.final_score >= cutoff);
      return Promise.resolve({ data: { shortlisted } });
    });

    const result = await shortlistCandidates("job-1");
    const ids = (result.shortlisted as Array<{ candidate_id: string }>).map((c) => c.candidate_id);

    expect(ids).toContain("c-55");
    expect(ids).not.toContain("c-54");
  });
});
