import { useEffect, useState } from "react";
import { AlertTriangle, Bot, Briefcase, FileText, Loader2, RefreshCw, Send, Target } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { askCandidateCoach, type CandidateCoachResponse } from "@/services/candidatePortal";

const DEFAULT_QUESTION = "Summarize my applications and recommend the next steps.";

function metricValue(result: CandidateCoachResponse | null, key: string): number {
  const value = result?.metrics?.[key];
  return typeof value === "number" ? value : Number(value || 0);
}

function scoreText(value: unknown): string {
  if (value === null || value === undefined || value === "") return "n/a";
  const num = Number(value);
  return Number.isFinite(num) ? `${num.toFixed(1)}%` : "n/a";
}

export default function CandidateCoach() {
  const [question, setQuestion] = useState(DEFAULT_QUESTION);
  const [result, setResult] = useState<CandidateCoachResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const runCoach = async (nextQuestion = question) => {
    setLoading(true);
    setError(null);
    try {
      const data = await askCandidateCoach({ question: nextQuestion || DEFAULT_QUESTION });
      setResult(data);
    } catch (err: any) {
      setError(err?.response?.data?.detail || err?.message || "Candidate coach failed");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    runCoach(DEFAULT_QUESTION);
  }, []);

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
        <div>
          <h2 className="flex items-center gap-2 text-3xl font-bold tracking-tight">
            <Bot className="h-7 w-7 text-primary" />
            Candidate Coach
          </h2>
          <p className="text-sm text-muted-foreground">
            Read-only guidance from your applications, resumes, and assessment status.
          </p>
        </div>
        <Badge variant="outline" className="w-fit">
          {result?.data_scope || "candidate_owned"}
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
            <CardDescription>Applications</CardDescription>
            <CardTitle className="flex items-center gap-2 text-lg">
              <Briefcase className="h-5 w-5 text-primary" />
              Active
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">{metricValue(result, "active_applications")}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-3">
            <CardDescription>Assessments</CardDescription>
            <CardTitle className="flex items-center gap-2 text-lg">
              <Target className="h-5 w-5 text-primary" />
              Pending
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">{metricValue(result, "pending_assessments")}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-3">
            <CardDescription>Assessments</CardDescription>
            <CardTitle className="flex items-center gap-2 text-lg">
              <Target className="h-5 w-5 text-primary" />
              Completed
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">{metricValue(result, "completed_assessments")}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-3">
            <CardDescription>Resume vault</CardDescription>
            <CardTitle className="flex items-center gap-2 text-lg">
              <FileText className="h-5 w-5 text-primary" />
              Resumes
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">{metricValue(result, "vault_resumes")}</div>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(320px,440px)_1fr]">
        <Card>
          <CardHeader>
            <CardTitle className="text-xl">Ask Coach</CardTitle>
            <CardDescription>Answers use only your candidate-owned data.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <Textarea
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              className="min-h-[160px]"
              aria-label="Candidate coach question"
            />
            <div className="flex flex-col gap-2 sm:flex-row">
              <Button onClick={() => runCoach()} disabled={loading || !question.trim()} className="flex-1">
                {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Send className="mr-2 h-4 w-4" />}
                Ask
              </Button>
              <Button variant="outline" onClick={() => runCoach(DEFAULT_QUESTION)} disabled={loading}>
                <RefreshCw className="mr-2 h-4 w-4" />
                Refresh
              </Button>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-xl">Answer</CardTitle>
            <CardDescription>{result?.headline || "Loading candidate summary"}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            <p className="text-sm leading-6 text-foreground">
              {loading && !result ? "Reviewing your candidate workspace..." : result?.answer || "No answer yet."}
            </p>
            <div className="space-y-2">
              <div className="text-sm font-medium">Next Steps</div>
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
            <CardTitle className="text-xl">Applications</CardTitle>
            <CardDescription>Your latest applications and assessment state.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {(result?.applications || []).map((application) => (
              <div key={String(application.candidate_id)} className="rounded-md border px-3 py-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate font-medium">{String(application.job_title || "Untitled job")}</div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      {String(application.application_status || "active")} - {String(application.quiz_status || "no assessment")}
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-sm font-semibold">{scoreText(application.final_score)}</div>
                    <div className="text-xs text-muted-foreground">{String(application.tag || "Pending")}</div>
                  </div>
                </div>
              </div>
            ))}
            {result && result.applications.length === 0 && (
              <div className="rounded-md border border-dashed px-3 py-8 text-center text-sm text-muted-foreground">
                No applications yet
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-xl">Resume Readiness</CardTitle>
            <CardDescription>Vault resumes available for future applications.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {(result?.resumes || []).map((resume) => (
              <div key={String(resume.id)} className="rounded-md border px-3 py-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate font-medium">{String(resume.label || resume.original_filename || "Resume")}</div>
                    <div className="mt-1 truncate text-xs text-muted-foreground">
                      {(resume.skills || []).slice(0, 4).join(", ") || "No parsed skills yet"}
                    </div>
                  </div>
                  <Badge variant={resume.is_default ? "default" : "outline"}>
                    {resume.is_default ? "Default" : "Saved"}
                  </Badge>
                </div>
              </div>
            ))}
            {result && result.resumes.length === 0 && (
              <div className="rounded-md border border-dashed px-3 py-8 text-center text-sm text-muted-foreground">
                No saved resumes yet
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
