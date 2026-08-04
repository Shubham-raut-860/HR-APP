import { useEffect, useState } from "react";
import { AlertTriangle, Bot, Briefcase, Loader2, RefreshCw, Send, Sparkles, Target, Users } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { askRecruiterCopilot, type RecruiterCopilotResponse } from "@/services/recruiterCopilot";

const DEFAULT_QUESTION = "Summarize my hiring pipeline and recommend the next actions.";

function metricValue(result: RecruiterCopilotResponse | null, key: string): number {
  const value = result?.metrics?.[key];
  return typeof value === "number" ? value : Number(value || 0);
}

function scoreText(value: unknown): string {
  const num = Number(value || 0);
  return Number.isFinite(num) ? `${num.toFixed(1)}%` : "n/a";
}

export default function RecruiterCopilot() {
  const [question, setQuestion] = useState(DEFAULT_QUESTION);
  const [result, setResult] = useState<RecruiterCopilotResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const runCopilot = async (nextQuestion = question) => {
    setLoading(true);
    setError(null);
    try {
      const data = await askRecruiterCopilot({ question: nextQuestion || DEFAULT_QUESTION });
      setResult(data);
    } catch (err: any) {
      setError(err?.response?.data?.detail || err?.message || "Recruiter copilot failed");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    runCopilot(DEFAULT_QUESTION);
  }, []);

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
        <div>
          <h2 className="flex items-center gap-2 text-3xl font-bold tracking-tight">
            <Bot className="h-7 w-7 text-primary" />
            Recruiter Copilot
          </h2>
          <p className="text-sm text-muted-foreground">
            Pipeline guidance from recruiter-owned jobs, candidates, and assessments.
          </p>
        </div>
        <Badge variant="outline" className="w-fit">
          {result?.data_scope || "recruiter_owned"}
        </Badge>
      </div>

      {error && (
        <Card className="border-destructive/40">
          <CardContent className="flex items-start gap-2 pt-6 text-destructive">
            <AlertTriangle className="mt-0.5 h-4 w-4" />
            <span>{error}</span>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Card>
          <CardHeader className="pb-3">
            <CardDescription>Active jobs</CardDescription>
            <CardTitle className="flex items-center gap-2 text-lg">
              <Briefcase className="h-5 w-5 text-primary" />
              Jobs
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">{metricValue(result, "active_jobs")}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-3">
            <CardDescription>Pipeline</CardDescription>
            <CardTitle className="flex items-center gap-2 text-lg">
              <Users className="h-5 w-5 text-primary" />
              Candidates
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">{metricValue(result, "total_candidates")}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-3">
            <CardDescription>Strong matches</CardDescription>
            <CardTitle className="flex items-center gap-2 text-lg">
              <Target className="h-5 w-5 text-primary" />
              Ready
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">{metricValue(result, "strong_candidates")}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-3">
            <CardDescription>Completed</CardDescription>
            <CardTitle className="flex items-center gap-2 text-lg">
              <Sparkles className="h-5 w-5 text-primary" />
              Assessments
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">{metricValue(result, "completed_assessments")}</div>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(320px,440px)_1fr]">
        <Card>
          <CardHeader>
            <CardTitle className="text-xl">Ask Copilot</CardTitle>
            <CardDescription>Questions are answered from your visible recruiter pipeline.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <Textarea
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              className="min-h-[160px]"
              aria-label="Recruiter copilot question"
            />
            <div className="flex flex-col gap-2 sm:flex-row">
              <Button onClick={() => runCopilot()} disabled={loading || !question.trim()} className="flex-1">
                {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Send className="mr-2 h-4 w-4" />}
                Ask
              </Button>
              <Button variant="outline" onClick={() => runCopilot(DEFAULT_QUESTION)} disabled={loading}>
                <RefreshCw className="mr-2 h-4 w-4" />
                Refresh
              </Button>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-xl">Answer</CardTitle>
            <CardDescription>{result?.headline || "Loading pipeline summary"}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            <p className="text-sm leading-6 text-foreground">
              {loading && !result ? "Analyzing recruiter pipeline..." : result?.answer || "No answer yet."}
            </p>
            <div className="space-y-2">
              <div className="text-sm font-medium">Next Actions</div>
              <div className="grid gap-2">
                {(result?.recommendations || []).map((item, index) => (
                  <div key={`${item}-${index}`} className="rounded-md border px-3 py-2 text-sm">
                    {item}
                  </div>
                ))}
                {result && result.recommendations.length === 0 && (
                  <div className="rounded-md border border-dashed px-3 py-6 text-center text-sm text-muted-foreground">
                    No recommendations right now
                  </div>
                )}
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-xl">Focus Jobs</CardTitle>
            <CardDescription>Jobs with the strongest current action signal.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {(result?.focus_jobs || []).map((job) => (
              <div key={String(job.id)} className="rounded-md border px-3 py-3">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="font-medium">{String(job.title || "Untitled job")}</div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      {Number(job.candidate_count || 0)} candidates - {Number(job.completed_assessments || 0)} completed assessments
                    </div>
                  </div>
                  <Badge variant={Number(job.strong_candidates || 0) > 0 ? "success" : "outline"}>
                    {Number(job.strong_candidates || 0)} strong
                  </Badge>
                </div>
              </div>
            ))}
            {result && result.focus_jobs.length === 0 && (
              <div className="rounded-md border border-dashed px-3 py-8 text-center text-sm text-muted-foreground">
                No recruiter-owned jobs yet
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-xl">Top Candidates</CardTitle>
            <CardDescription>Sorted by existing final, resume, or quiz score.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {(result?.top_candidates || []).map((candidate) => (
              <div key={String(candidate.id)} className="rounded-md border px-3 py-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate font-medium">{String(candidate.name || "Candidate")}</div>
                    <div className="mt-1 truncate text-xs text-muted-foreground">{String(candidate.job_title || "No job title")}</div>
                  </div>
                  <div className="text-right">
                    <div className="text-sm font-semibold">{scoreText(candidate.final_score)}</div>
                    <div className="text-xs text-muted-foreground">{String(candidate.tag || "Untagged")}</div>
                  </div>
                </div>
              </div>
            ))}
            {result && result.top_candidates.length === 0 && (
              <div className="rounded-md border border-dashed px-3 py-8 text-center text-sm text-muted-foreground">
                No candidates to rank yet
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {result?.risks?.length ? (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-xl">
              <AlertTriangle className="h-5 w-5 text-amber-500" />
              Watch Items
            </CardTitle>
          </CardHeader>
          <CardContent className="grid gap-2 md:grid-cols-2">
            {result.risks.map((risk, index) => (
              <div key={`${risk}-${index}`} className="rounded-md border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-sm">
                {risk}
              </div>
            ))}
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
