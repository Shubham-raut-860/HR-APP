import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Link } from "react-router-dom";
import {
  Briefcase, CheckCircle2, Clock, XCircle, BrainCircuit,
  LineChart, FileText, Star, Plus, ArrowRight, Zap
} from "lucide-react";
import { getMyPendingQuiz, StoredResume } from "@/services/candidatePortal";
import { useAuth } from "@/context/AuthContext";
import { cn } from "@/lib/utils";
import { CandidateDataProvider, useCandidateData } from "@/context/CandidateDataProvider";

// BUG-F2 FIX: Python CandidateTag enum serializes as lowercase ("strong", "medium",
// "reject") via Pydantic. The previous comparisons used Title Case strings which
// never matched, making shortlisted/rejected stats always show 0. Normalise to
// lowercase before any comparison throughout the file.
function matchesTag(tag: string | null | undefined, ...values: string[]): boolean {
  return values.includes((tag ?? "").toLowerCase());
}

function CandidateDashboardContent() {
  const { user } = useAuth();
  const [pendingQuiz, setPendingQuiz]   = useState<any>(null);
  const [loadingQuiz, setLoadingQuiz]   = useState(true);
  const { myResults, storedResumes, loading, fetchMyResults, fetchStoredResumes } = useCandidateData();

  useEffect(() => {
    const controller = new AbortController();
    const load = async () => {
      try {
        const [, quiz] = await Promise.all([
          Promise.all([fetchMyResults(), fetchStoredResumes()]),
          getMyPendingQuiz(controller.signal).catch(() => null),
        ]);
        setPendingQuiz(quiz);
      } catch (e: any) { 
        if (e.name !== "AbortError" && e.code !== "ERR_CANCELED") {
          console.error("Dashboard fetch error:", e);
        }
      }
      finally { setLoadingQuiz(false); }
    };
    load();
    return () => controller.abort();
  }, [fetchMyResults, fetchStoredResumes]);

  const applications = myResults;
  const resumes: StoredResume[] = storedResumes;
  const pageLoading = loadingQuiz || loading.myResults || loading.storedResumes;

  if (pageLoading) return (
    <div className="p-8 flex items-center justify-center gap-2 text-muted-foreground">
      <div className="h-5 w-5 rounded-full border-2 border-primary border-t-transparent animate-spin" />
      Loading…
    </div>
  );

  const firstName  = user?.full_name?.split(" ")[0] ?? "there";
  const defaultRes = resumes.find(r => r.is_default);
  const vaultCount = resumes.length;

  const stats = {
    applied:     applications.length,
    // BUG-F2 FIX: lowercase comparison — "Strong"/"Medium" → "strong"/"medium"
    shortlisted: applications.filter(a => matchesTag(a.tag, "strong", "medium")).length,
    quizzes:     applications.filter(a =>
      a.quiz_status === "pending" || a.quiz_status === "in_progress"
    ).length,
    rejected: applications.filter(a => matchesTag(a.tag, "reject")).length,
  };

  const statCards = [
    { label: "Applied",         value: stats.applied,     icon: Briefcase,    color: "text-blue-500",   bg: "bg-blue-50 dark:bg-blue-900/20" },
    { label: "Shortlisted",     value: stats.shortlisted, icon: CheckCircle2, color: "text-emerald-500", bg: "bg-emerald-50 dark:bg-emerald-900/20" },
    { label: "Pending Quizzes", value: stats.quizzes,     icon: BrainCircuit, color: "text-amber-500",   bg: "bg-amber-50 dark:bg-amber-900/20" },
    { label: "Rejected",        value: stats.rejected,    icon: XCircle,      color: "text-red-500",     bg: "bg-red-50 dark:bg-red-900/20" },
  ];

  return (
    <div className="space-y-8 max-w-7xl mx-auto">

      {/* ── Header ────────────────────────────────────────────────────────── */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Welcome back, {firstName}!</h1>
          <p className="text-muted-foreground mt-1">Here's your hiring pipeline at a glance.</p>
        </div>
        <Button asChild className="shrink-0 rounded-xl">
          <Link to="/candidate/jobs"><Zap className="h-4 w-4 mr-1.5 fill-current" /> Browse Jobs</Link>
        </Button>
      </div>

      {/* ── Stats ─────────────────────────────────────────────────────────── */}
      <div className="grid gap-4 grid-cols-2 md:grid-cols-4">
        {statCards.map(({ label, value, icon: Icon, color, bg }) => (
          <Card key={label} className="overflow-hidden">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2 pt-4 px-5">
              <CardTitle className="text-sm font-medium text-muted-foreground">{label}</CardTitle>
              <div className={cn("h-8 w-8 rounded-lg flex items-center justify-center shrink-0", bg)}>
                <Icon className={cn("h-4 w-4", color)} />
              </div>
            </CardHeader>
            <CardContent className="px-5 pb-4">
              <div className="text-3xl font-bold tracking-tight">{value}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* ── Resume Vault card ─────────────────────────────────────────────── */}
      <Card className={cn(
        "overflow-hidden transition-all",
        vaultCount === 0
          ? "border-dashed border-2 border-primary/30 bg-primary/5"
          : "border-border/60"
      )}>
        <CardContent className="p-5 flex flex-col sm:flex-row items-start sm:items-center gap-5">

          <div className="flex items-center gap-4 flex-1 min-w-0">
            <div className={cn(
              "shrink-0 h-12 w-12 rounded-xl flex items-center justify-center",
              vaultCount === 0 ? "bg-primary/10" : "bg-muted"
            )}>
              <FileText className={cn("h-6 w-6", vaultCount === 0 ? "text-primary" : "text-muted-foreground")} />
            </div>

            <div className="min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <p className="font-semibold">Resume Vault</p>
                <Badge variant="outline" className="text-[10px] font-normal px-1.5">
                  {vaultCount}/5 saved
                </Badge>
              </div>

              {vaultCount === 0 ? (
                <p className="text-sm text-muted-foreground mt-0.5">
                  Save a resume to use <strong className="text-foreground">Easy Apply</strong> on any job — no re-uploading.
                </p>
              ) : (
                <div className="mt-1.5 space-y-1.5">
                  <div className="flex gap-1">
                    {Array.from({ length: 5 }).map((_, i) => (
                      <div key={i} className={cn(
                        "h-1 w-6 rounded-full",
                        i < vaultCount
                          ? resumes[i]?.is_default ? "bg-amber-400" : "bg-primary"
                          : "bg-muted"
                      )} />
                    ))}
                  </div>
                  {defaultRes && (
                    <p className="text-xs text-muted-foreground flex items-center gap-1">
                      <Star className="h-3 w-3 text-amber-500 fill-amber-500" />
                      Default: <span className="font-medium text-foreground truncate">{defaultRes.label}</span>
                    </p>
                  )}
                </div>
              )}
            </div>
          </div>

          <div className="flex gap-2 shrink-0 w-full sm:w-auto">
            {vaultCount === 0 ? (
              <Button asChild className="flex-1 sm:flex-none rounded-xl">
                <Link to="/candidate/settings?tab=vault">
                  <Plus className="h-4 w-4 mr-1.5" /> Upload Resume
                </Link>
              </Button>
            ) : (
              <>
                <Button asChild variant="outline" size="sm" className="flex-1 sm:flex-none rounded-xl">
                  <Link to="/candidate/settings?tab=vault">Manage Vault</Link>
                </Button>
                <Button asChild size="sm" className="flex-1 sm:flex-none rounded-xl">
                  <Link to="/candidate/jobs">
                    <Zap className="h-3.5 w-3.5 mr-1.5 fill-current" /> Easy Apply
                  </Link>
                </Button>
              </>
            )}
          </div>
        </CardContent>
      </Card>

      {/* ── Pending quiz alerts ───────────────────────────────────────────── */}
      {pendingQuiz?.pending && pendingQuiz.attempts?.map((quiz: any) => (
        <Card key={quiz.token} className="border-amber-200 bg-amber-50 dark:bg-amber-900/10 dark:border-amber-900 shadow-sm">
          <CardContent className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 p-5">
            <div className="space-y-0.5">
              <h3 className="font-semibold text-amber-900 dark:text-amber-100 flex items-center gap-2">
                <BrainCircuit className="h-5 w-5 animate-pulse" /> Action Required: Skill Assessment
              </h3>
              <p className="text-sm text-amber-800 dark:text-amber-200">
                You've been shortlisted for <strong>{quiz.quiz_title || "a position"}</strong>. Complete the quiz to proceed.
              </p>
            </div>
            <Button asChild className="bg-amber-600 hover:bg-amber-700 text-white shrink-0 rounded-xl">
              <Link to="/take-quiz" state={{ quizToken: quiz.token }}>Start Assessment</Link>
            </Button>
          </CardContent>
        </Card>
      ))}

      {/* ── Applications grid ────────────────────────────────────────────── */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-semibold tracking-tight">Your Applications</h2>
          {applications.length > 0 && (
            <Button asChild variant="ghost" size="sm" className="text-muted-foreground hover:text-foreground">
              <Link to="/candidate/jobs">Browse more <ArrowRight className="h-4 w-4 ml-1.5" /></Link>
            </Button>
          )}
        </div>

        {applications.length === 0 ? (
          <Card className="p-12 text-center bg-muted/20 border-dashed">
            <div className="flex flex-col items-center gap-3">
              <div className="h-12 w-12 rounded-full bg-primary/10 flex items-center justify-center">
                <Briefcase className="h-6 w-6 text-primary" />
              </div>
              <h3 className="font-semibold text-lg">No applications yet</h3>
              <p className="text-muted-foreground text-sm max-w-sm">Browse open positions and start applying — your progress will show up here.</p>
              <Button asChild className="rounded-xl mt-2"><Link to="/candidate/jobs">Browse Open Jobs</Link></Button>
            </div>
          </Card>
        ) : (
          <div className="grid gap-5 grid-cols-1 lg:grid-cols-2 xl:grid-cols-3">
            {applications.map((app, idx) => {
              const hrActed = app.tag != null;
              // BUG-F2 FIX: case-insensitive tag check
              const isApproved = hrActed && (matchesTag(app.tag, "strong", "medium") || app.passed === true);
              const isRejected = hrActed && matchesTag(app.tag, "reject");

              return (
              <Card key={app.candidate_id ?? `${app.job_id}-${idx}`} className={cn(
                "flex flex-col overflow-hidden transition-all hover:shadow-md group",
                isApproved  ? "border-emerald-400/60 hover:border-emerald-500/70"
                : isRejected ? "border-red-300/60 hover:border-red-400/70"
                : "hover:border-primary/30"
              )}>
                {hrActed && (
                  <div className={cn("h-1.5 w-full", isApproved ? "bg-emerald-500" : "bg-red-400")} />
                )}

                <div className="p-5 flex-1 space-y-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <h3 className="font-semibold text-base leading-tight line-clamp-2">{app.job_title || "Application"}</h3>
                      <p className="text-xs text-muted-foreground mt-1 flex items-center gap-1">
                        <Briefcase className="h-3 w-3" /> HireAI Hub
                      </p>
                    </div>
                    <Badge
                      variant={matchesTag(app.tag, "reject") ? "destructive" : matchesTag(app.tag, "strong") ? "default" : "secondary"}
                      className="shrink-0 capitalize"
                    >
                      {app.tag ?? "Under Review"}
                    </Badge>
                  </div>

                  {hrActed && (
                    <div className={cn(
                      "flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold",
                      isApproved
                        ? "bg-emerald-50 text-emerald-800 border border-emerald-200 dark:bg-emerald-900/20 dark:text-emerald-300 dark:border-emerald-800"
                        : "bg-red-50 text-red-800 border border-red-200 dark:bg-red-900/20 dark:text-red-300 dark:border-red-800"
                    )}>
                      {isApproved
                        ? <><CheckCircle2 className="h-4 w-4 shrink-0" /> Shortlisted — HR will be in touch soon.</>
                        : <><XCircle className="h-4 w-4 shrink-0" /> Not shortlisted for this role.</>}
                    </div>
                  )}

                  <div className="space-y-1.5">
                    <div className="flex justify-between text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                      <span className={app.resume_score != null ? "text-primary" : ""}>Screening</span>
                      <span className={app.quiz_score != null ? "text-primary" : ""}>Assessment</span>
                      <span className={hrActed ? (isApproved ? "text-emerald-600 dark:text-emerald-400" : "text-destructive") : ""}>
                        Decision
                      </span>
                    </div>
                    <div className="h-1.5 bg-secondary rounded-full overflow-hidden flex">
                      <div className={cn("h-full w-1/3 border-r border-background transition-colors duration-500", app.resume_score != null ? "bg-primary" : "")} />
                      <div className={cn("h-full w-1/3 border-r border-background transition-colors duration-500", app.quiz_score != null ? "bg-primary" : "")} />
                      <div className={cn(
                        "h-full w-1/3 transition-colors duration-500",
                        hrActed ? (isApproved ? "bg-emerald-500" : "bg-destructive") : ""
                      )} />
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-2.5">
                    <div className="bg-muted/40 rounded-xl p-3 border group-hover:bg-primary/5 transition-colors">
                      <p className="text-[10px] uppercase tracking-wider font-semibold text-muted-foreground mb-1">Resume</p>
                      <p className="font-bold text-lg">
                        {app.resume_score != null ? `${app.resume_score.toFixed(0)}%` : "—"}
                      </p>
                    </div>
                    <div className="bg-muted/40 rounded-xl p-3 border group-hover:bg-primary/5 transition-colors">
                      <p className="text-[10px] uppercase tracking-wider font-semibold text-muted-foreground mb-1">Quiz</p>
                      <p className="font-bold text-lg">
                        {/* BUG-F1 FIX: quiz_max_score is now nullable — guard against null before dividing */}
                        {app.quiz_score != null && app.quiz_max_score != null && app.quiz_max_score > 0
                          ? `${((app.quiz_score / app.quiz_max_score) * 100).toFixed(0)}%`
                          : "—"}
                      </p>
                    </div>
                  </div>
                </div>

                <div className="bg-muted/20 px-5 py-3 border-t flex items-center justify-between gap-2">
                  <span className="text-xs text-muted-foreground flex items-center gap-1.5">
                    <Clock className="h-3 w-3" />
                    {new Date(app.created_at || Date.now()).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}
                  </span>
                  <div className="flex gap-1.5">
                    <Button variant="ghost" size="sm" asChild className="h-7 text-xs rounded-lg">
                      <Link to={"/candidate/jobs/" + app.job_id}>View Job</Link>
                    </Button>
                    {app.candidate_id && (
                      <Button variant="outline" size="sm" asChild className="h-7 text-xs rounded-lg bg-background shadow-sm">
                        <Link to={"/candidate/feedback/" + app.candidate_id}>
                          <LineChart className="h-3 w-3 mr-1" /> Insights
                        </Link>
                      </Button>
                    )}
                  </div>
                </div>
              </Card>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

export default function CandidateDashboard() {
  return (
    <CandidateDataProvider>
      <CandidateDashboardContent />
    </CandidateDataProvider>
  );
}
