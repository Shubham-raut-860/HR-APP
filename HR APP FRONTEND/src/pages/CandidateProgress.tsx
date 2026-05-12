import * as React from "react";
import { Link } from "react-router-dom";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
} from "recharts";
import { motion } from "framer-motion";
import {
  ArrowRight,
  BarChart3,
  Briefcase,
  CheckCircle2,
  Clock3,
  Filter,
  Trophy,
  XCircle,
} from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { CandidateResultOut } from "@/services/candidatePortal";
import { CandidateDataProvider, useCandidateData } from "@/context/CandidateDataProvider";

type StageFilter = "all" | "active" | "shortlisted" | "rejected" | "passed";

function normalizeTag(tag: string | null | undefined): string {
  return (tag || "").trim().toLowerCase();
}

function getStageLabel(result: CandidateResultOut): "passed" | "rejected" | "shortlisted" | "active" {
  const tag = normalizeTag(result.tag);
  if (result.passed === true) return "passed";
  if (tag === "reject") return "rejected";
  if (tag === "strong" || tag === "medium") return "shortlisted";
  return "active";
}

function stageClasses(stage: ReturnType<typeof getStageLabel>): string {
  switch (stage) {
    case "passed":
      return "bg-emerald-100 text-emerald-700 border-emerald-300 dark:bg-emerald-900/30 dark:text-emerald-300 dark:border-emerald-700";
    case "rejected":
      return "bg-red-100 text-red-700 border-red-300 dark:bg-red-900/30 dark:text-red-300 dark:border-red-700";
    case "shortlisted":
      return "bg-blue-100 text-blue-700 border-blue-300 dark:bg-blue-900/30 dark:text-blue-300 dark:border-blue-700";
    default:
      return "bg-amber-100 text-amber-700 border-amber-300 dark:bg-amber-900/30 dark:text-amber-300 dark:border-amber-700";
  }
}

function CandidateProgressContent() {
  const { myResults, loading, fetchMyResults } = useCandidateData();
  const [stageFilter, setStageFilter] = React.useState<StageFilter>("all");

  React.useEffect(() => {
    fetchMyResults().catch(() => undefined);
  }, [fetchMyResults]);

  const sortedResults = React.useMemo(() => {
    return [...myResults].sort(
      (a: CandidateResultOut, b: CandidateResultOut) =>
        new Date(b.created_at || 0).getTime() - new Date(a.created_at || 0).getTime(),
    );
  }, [myResults]);

  const filteredResults = React.useMemo(() => {
    if (stageFilter === "all") return sortedResults;
    return sortedResults.filter((r: CandidateResultOut) => {
      const stage = getStageLabel(r);
      return stageFilter === stage;
    });
  }, [sortedResults, stageFilter]);

  const stats = React.useMemo(() => {
    const total = sortedResults.length;
    const shortlist = sortedResults.filter((r: CandidateResultOut) => {
      const tag = normalizeTag(r.tag);
      return tag === "strong" || tag === "medium";
    }).length;
    const passed = sortedResults.filter((r: CandidateResultOut) => r.passed === true).length;
    const avgResume = total
      ? sortedResults.reduce((acc: number, r: CandidateResultOut) => acc + (r.resume_score || 0), 0) / total
      : 0;
    const avgFinalRows = sortedResults.filter((r: CandidateResultOut) => typeof r.final_score === "number");
    const avgFinal = avgFinalRows.length
      ? avgFinalRows.reduce((acc: number, r: CandidateResultOut) => acc + (r.final_score || 0), 0) / avgFinalRows.length
      : 0;
    return {
      total,
      shortlist,
      passed,
      avgResume: Math.round(avgResume),
      avgFinal: Math.round(avgFinal),
    };
  }, [sortedResults]);

  const trendData = React.useMemo(() => {
    return [...sortedResults]
      .reverse()
      .map((r: CandidateResultOut, idx: number) => ({
        index: idx + 1,
        role: r.job_title || `Application ${idx + 1}`,
        resume: Math.round(r.resume_score || 0),
        final: r.final_score != null ? Math.round(r.final_score) : null,
      }));
  }, [sortedResults]);

  const outcomeData = React.useMemo(() => {
    const counts = {
      passed: 0,
      shortlisted: 0,
      active: 0,
      rejected: 0,
    };
    for (const r of sortedResults) {
      counts[getStageLabel(r)] += 1;
    }
    return [
      { name: "Passed", value: counts.passed, fill: "#16a34a" },
      { name: "Shortlisted", value: counts.shortlisted, fill: "#2563eb" },
      { name: "In Progress", value: counts.active, fill: "#f59e0b" },
      { name: "Rejected", value: counts.rejected, fill: "#ef4444" },
    ].filter((d) => d.value > 0);
  }, [sortedResults]);

  if (loading.myResults) {
    return (
      <div className="p-8 text-center text-muted-foreground">
        <div className="h-6 w-6 rounded-full border-2 border-primary border-t-transparent animate-spin mx-auto mb-3" />
        Loading progress timeline...
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-3">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">My Progress</h1>
          <p className="text-muted-foreground mt-1">Track your hiring pipeline with score trends and status checkpoints.</p>
        </div>
        <Button asChild variant="outline" className="rounded-xl">
          <Link to="/candidate/jobs">
            Browse More Jobs <ArrowRight className="h-4 w-4 ml-1.5" />
          </Link>
        </Button>
      </div>

      <div className="grid gap-4 grid-cols-2 lg:grid-cols-5">
        <Card><CardContent className="pt-5"><p className="text-xs text-muted-foreground">Applications</p><p className="text-2xl font-semibold">{stats.total}</p></CardContent></Card>
        <Card><CardContent className="pt-5"><p className="text-xs text-muted-foreground">Shortlisted</p><p className="text-2xl font-semibold text-blue-600">{stats.shortlist}</p></CardContent></Card>
        <Card><CardContent className="pt-5"><p className="text-xs text-muted-foreground">Passed</p><p className="text-2xl font-semibold text-emerald-600">{stats.passed}</p></CardContent></Card>
        <Card><CardContent className="pt-5"><p className="text-xs text-muted-foreground">Avg Resume</p><p className="text-2xl font-semibold">{stats.avgResume}%</p></CardContent></Card>
        <Card><CardContent className="pt-5"><p className="text-xs text-muted-foreground">Avg Final</p><p className="text-2xl font-semibold">{stats.avgFinal || 0}%</p></CardContent></Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2 min-h-[340px]">
          <CardHeader className="pb-0">
            <CardTitle className="text-base flex items-center gap-2"><BarChart3 className="h-4 w-4 text-primary" />Score Evolution</CardTitle>
            <CardDescription>How your resume and final outcomes progressed across applications.</CardDescription>
          </CardHeader>
          <CardContent className="h-[280px]">
            {trendData.length === 0 ? (
              <div className="h-full flex items-center justify-center text-muted-foreground">No applications yet.</div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={trendData} margin={{ left: 5, right: 20, top: 20, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <Tooltip />
                  <Legend />
                  <Line type="monotone" dataKey="resume" name="Resume Score" stroke="#2563eb" strokeWidth={2.5} dot={{ r: 3 }} />
                  <Line type="monotone" dataKey="final" name="Final Score" stroke="#16a34a" strokeWidth={2.5} dot={{ r: 3 }} connectNulls />
                </LineChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>

        <Card className="min-h-[340px]">
          <CardHeader className="pb-0">
            <CardTitle className="text-base flex items-center gap-2"><Trophy className="h-4 w-4 text-primary" />Outcome Split</CardTitle>
            <CardDescription>Distribution of your application outcomes.</CardDescription>
          </CardHeader>
          <CardContent className="h-[280px]">
            {outcomeData.length === 0 ? (
              <div className="h-full flex items-center justify-center text-muted-foreground">No outcome data yet.</div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={outcomeData}
                    dataKey="value"
                    nameKey="name"
                    innerRadius={55}
                    outerRadius={95}
                    paddingAngle={2}
                  />
                  <Tooltip />
                  <Legend />
                </PieChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div>
              <CardTitle className="text-base">Application Timeline</CardTitle>
              <CardDescription>Clickable status history for each role.</CardDescription>
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <Filter className="h-4 w-4 text-muted-foreground" />
              {(["all", "active", "shortlisted", "passed", "rejected"] as StageFilter[]).map((stage) => (
                <Button
                  key={stage}
                  size="sm"
                  variant={stageFilter === stage ? "default" : "outline"}
                  className="capitalize"
                  onClick={() => setStageFilter(stage)}
                >
                  {stage}
                </Button>
              ))}
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          {filteredResults.length === 0 ? (
            <div className="rounded-lg border border-dashed p-8 text-center text-muted-foreground">
              No applications match this filter.
            </div>
          ) : (
            filteredResults.map((r: CandidateResultOut, idx: number) => {
              const stage = getStageLabel(r);
              const score = Math.round(r.final_score ?? r.resume_score ?? 0);
              const quizPct = r.quiz_score != null && r.quiz_max_score && r.quiz_max_score > 0
                ? Math.round((r.quiz_score / r.quiz_max_score) * 100)
                : null;
              return (
                <motion.div
                  key={r.candidate_id || `${r.job_id}-${idx}`}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.2, delay: idx * 0.03 }}
                  className="rounded-xl border border-border/60 p-4 hover:bg-muted/20 transition-colors"
                >
                  <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3">
                    <div className="min-w-0">
                      <p className="font-semibold truncate">{r.job_title || "Job Application"}</p>
                      <p className="text-xs text-muted-foreground flex items-center gap-1 mt-0.5">
                        <Briefcase className="h-3 w-3" />
                        {r.job_title || "Role not specified"} · {new Date(r.created_at).toLocaleDateString("en-GB")}
                      </p>
                    </div>
                    <div className="flex items-center gap-2 flex-wrap">
                      <Badge className={cn("border", stageClasses(stage))}>{stage}</Badge>
                      <Badge variant="outline">Overall {score}%</Badge>
                      {quizPct != null && <Badge variant="outline">Quiz {quizPct}%</Badge>}
                    </div>
                  </div>

                  <div className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
                    <span className={cn("inline-flex items-center gap-1", r.resume_score != null ? "text-primary" : "")}>
                      <Clock3 className="h-3 w-3" /> Resume
                    </span>
                    <div className="h-1.5 w-7 rounded-full bg-muted" />
                    <span className={cn("inline-flex items-center gap-1", quizPct != null ? "text-primary" : "")}>
                      <CheckCircle2 className="h-3 w-3" /> Quiz
                    </span>
                    <div className="h-1.5 w-7 rounded-full bg-muted" />
                    <span className={cn("inline-flex items-center gap-1", stage === "rejected" ? "text-red-600" : stage === "passed" ? "text-emerald-600" : "text-muted-foreground")}>
                      {stage === "rejected" ? <XCircle className="h-3 w-3" /> : <CheckCircle2 className="h-3 w-3" />}
                      Decision
                    </span>
                  </div>

                  <div className="mt-3 h-1.5 rounded-full bg-muted overflow-hidden">
                    <div
                      className={cn(
                        "h-full rounded-full transition-all",
                        stage === "passed" ? "bg-emerald-500" : stage === "rejected" ? "bg-red-500" : "bg-blue-500",
                      )}
                      style={{ width: `${Math.max(8, Math.min(100, score))}%` }}
                    />
                  </div>

                  <div className="mt-3 flex justify-end">
                    <Button asChild variant="ghost" size="sm">
                      <Link to={`/candidate/jobs/${r.job_id}`}>Open job details <ArrowRight className="h-3.5 w-3.5 ml-1" /></Link>
                    </Button>
                  </div>
                </motion.div>
              );
            })
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export default function CandidateProgress() {
  return (
    <CandidateDataProvider>
      <CandidateProgressContent />
    </CandidateDataProvider>
  );
}
