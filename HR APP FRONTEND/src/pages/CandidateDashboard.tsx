import { useState, useEffect, useMemo } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";
import { Progress } from "@/components/ui/progress";
import { Link } from "react-router-dom";
import {
  Briefcase, CheckCircle2, Clock, XCircle, BrainCircuit,
  LineChart, FileText, Star, Plus, ArrowRight, Zap, ShieldCheck, Target, UserRoundCheck
} from "lucide-react";
import { getKycChecklist, getMyPendingQuiz, StoredResume, CandidateKycChecklist } from "@/services/candidatePortal";
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

function normalizeTag(tag: string | null | undefined): string {
  return (tag ?? "").toLowerCase().trim();
}

function candidateTagLabel(tag: string | null | undefined): string {
  const normalized = normalizeTag(tag);
  if (normalized === "strong") return "Shortlisted";
  if (normalized === "medium") return "Under consideration";
  if (normalized === "reject") return "Not shortlisted";
  return "Under review";
}

function CandidateDashboardContent() {
  const { user } = useAuth();
  const [pendingQuiz, setPendingQuiz]   = useState<any>(null);
  const [loadingQuiz, setLoadingQuiz]   = useState(true);
  const [kycChecklist, setKycChecklist] = useState<CandidateKycChecklist | null>(null);
  const { myResults, storedResumes, publicJobs, loading, fetchMyResults, fetchStoredResumes, fetchPublicJobs } = useCandidateData();

  useEffect(() => {
    const controller = new AbortController();
    const load = async () => {
      try {
        const [, quiz] = await Promise.all([
          Promise.all([
            fetchMyResults(),
            fetchStoredResumes(),
            fetchPublicJobs(),
            getKycChecklist().then(setKycChecklist).catch(() => setKycChecklist(null)),
          ]),
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
  }, [fetchMyResults, fetchStoredResumes, fetchPublicJobs]);

  const applications = myResults;
  const resumes: StoredResume[] = storedResumes;
  const pageLoading = loadingQuiz || loading.myResults || loading.storedResumes;

  const firstName  = user?.full_name?.split(" ")[0] ?? "there";
  const defaultRes = resumes.find(r => r.is_default);
  const vaultCount = resumes.length;
  const resumeSkills = useMemo(
    () => (defaultRes?.normalized_skills || resumes[0]?.normalized_skills || []).map((skill) => skill.toLowerCase().trim()),
    [defaultRes, resumes],
  );

  const stats = {
    applied:     applications.length,
    // BUG-F2 FIX: lowercase comparison - "Strong"/"Medium" -> "strong"/"medium"
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

  const profileItems = [
    { label: "Account created", done: Boolean(user?.email), href: "/candidate/settings", icon: UserRoundCheck },
    { label: "Resume uploaded", done: vaultCount > 0, href: "/candidate/settings?tab=vault", icon: FileText },
    { label: "Default resume set", done: Boolean(defaultRes), href: "/candidate/settings?tab=vault", icon: Star },
    { label: "KYC checklist ready", done: Boolean(kycChecklist?.all_mandatory_uploaded), href: "/candidate/settings?tab=kyc", icon: ShieldCheck },
    { label: "First application sent", done: applications.length > 0, href: "/candidate/jobs", icon: Briefcase },
  ];
  const completionPct = Math.round((profileItems.filter((item) => item.done).length / profileItems.length) * 100);

  const recommendedJobs = useMemo(() => {
    const appliedIds = new Set(applications.map((app) => app.job_id).filter(Boolean));
    const hasResumeSkills = resumeSkills.length > 0;
    return (publicJobs || [])
      .filter((job) => !appliedIds.has(job.id) && job.is_active !== false)
      .map((job) => {
        const requiredSkills = Array.isArray(job.must_have_skills) ? job.must_have_skills : [];
        const matched = requiredSkills.filter((skill: string) => {
          const normalized = skill.toLowerCase().trim();
          return resumeSkills.some((candidateSkill) =>
            candidateSkill === normalized ||
            candidateSkill.includes(normalized) ||
            normalized.includes(candidateSkill)
          );
        });
        const score = hasResumeSkills && requiredSkills.length > 0
          ? matched.length / requiredSkills.length
          : (job.created_at ? Math.max(0, 1 - ((Date.now() - new Date(job.created_at).getTime()) / (30 * 86_400_000))) : 0);
        return { ...job, matchedSkills: matched, requiredSkills, recommendationScore: score };
      })
      .sort((a, b) => b.recommendationScore - a.recommendationScore)
      .slice(0, 3);
  }, [applications, publicJobs, resumeSkills]);

  const latestApplication = [...applications].sort(
    (a, b) => new Date(b.created_at || 0).getTime() - new Date(a.created_at || 0).getTime(),
  )[0];
  const latestTag = normalizeTag(latestApplication?.tag);
  const hasDecision = Boolean(latestApplication && (latestTag || latestApplication.passed != null));
  const quizTouched = Boolean(
    latestApplication?.quiz_status ||
    latestApplication?.quiz_score != null ||
    latestApplication?.quiz_max_score != null,
  );
  const timelineSteps = [
    {
      label: "Applied",
      detail: latestApplication
        ? new Date(latestApplication.created_at || Date.now()).toLocaleDateString("en-GB", { day: "2-digit", month: "short" })
        : "Not started",
      active: Boolean(latestApplication),
      icon: Briefcase,
    },
    {
      label: "Screening",
      detail: latestApplication?.resume_score != null ? `${Math.round(latestApplication.resume_score)}% resume match` : "Awaiting resume score",
      active: latestApplication?.resume_score != null,
      icon: FileText,
    },
    {
      label: "Assessment",
      detail: quizTouched
        ? latestApplication?.quiz_score != null && latestApplication?.quiz_max_score
          ? `${Math.round((latestApplication.quiz_score / latestApplication.quiz_max_score) * 100)}% quiz`
          : latestApplication?.quiz_status?.replace("_", " ") || "Assigned"
        : "Not assigned yet",
      active: quizTouched,
      icon: BrainCircuit,
    },
    {
      label: "Decision",
      detail: hasDecision ? candidateTagLabel(latestApplication?.tag) : "Pending recruiter review",
      active: hasDecision,
      icon: CheckCircle2,
    },
  ];

  if (pageLoading) return (
    <div className="space-y-8 max-w-7xl mx-auto">
      <div className="flex flex-col sm:flex-row justify-between gap-4">
        <div className="space-y-2">
          <Skeleton className="h-9 w-48" />
          <Skeleton className="h-4 w-80 max-w-full" />
        </div>
        <Skeleton className="h-10 w-32 rounded-xl" />
      </div>
      <div className="grid gap-4 grid-cols-2 md:grid-cols-4">
        {Array.from({ length: 4 }).map((_, idx) => (
          <Card key={`candidate-stat-${idx}`}>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2 pt-4 px-5">
              <Skeleton className="h-4 w-24" />
              <Skeleton className="h-8 w-8 rounded-lg" />
            </CardHeader>
            <CardContent className="px-5 pb-4">
              <Skeleton className="h-9 w-14" />
            </CardContent>
          </Card>
        ))}
      </div>
      <Card>
        <CardContent className="p-5 space-y-4">
          <Skeleton className="h-5 w-44" />
          <div className="grid gap-3 md:grid-cols-4">
            {Array.from({ length: 4 }).map((_, idx) => (
              <Skeleton key={`timeline-skeleton-${idx}`} className="h-20 rounded-2xl" />
            ))}
          </div>
        </CardContent>
      </Card>
      <Skeleton className="h-28 rounded-3xl" />
      <div className="grid gap-5 grid-cols-1 lg:grid-cols-2 xl:grid-cols-3">
        {Array.from({ length: 3 }).map((_, idx) => (
          <Skeleton key={`application-skeleton-${idx}`} className="h-64 rounded-3xl" />
        ))}
      </div>
    </div>
  );

  return (
    <div className="space-y-8 max-w-7xl mx-auto">

      {/* ------ Header ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">My Dashboard</h1>
          <p className="text-muted-foreground mt-1">Hi {firstName}, here is your hiring pipeline at a glance.</p>
        </div>
        <Button asChild className="shrink-0 rounded-xl">
          <Link to="/candidate/jobs"><Zap className="h-4 w-4 mr-1.5 fill-current" /> Browse Jobs</Link>
        </Button>
      </div>

      {/* ------ Stats --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- */}
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

      <Card className="overflow-hidden">
        <CardContent className="p-5">
          <div className="grid gap-5 lg:grid-cols-[280px_1fr] lg:items-center">
            <div>
              <div className="flex items-center gap-2">
                <Target className="h-5 w-5 text-primary" />
                <h2 className="text-lg font-semibold tracking-tight">Profile strength</h2>
              </div>
              <p className="mt-1 text-sm text-muted-foreground">
                Complete the basics once to make every application stronger.
              </p>
              <div className="mt-4 space-y-2">
                <div className="flex items-center justify-between text-sm">
                  <span className="font-medium">{completionPct}% complete</span>
                  <span className="text-xs text-muted-foreground">{profileItems.filter((item) => item.done).length}/{profileItems.length} done</span>
                </div>
                <Progress value={completionPct} className="h-2" />
              </div>
            </div>
            <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
              {profileItems.map((item) => {
                const Icon = item.icon;
                return (
                  <Link
                    key={item.label}
                    to={item.href}
                    className={cn(
                      "rounded-2xl border p-3 transition-colors hover:border-primary/40 hover:bg-primary/5",
                      item.done ? "bg-emerald-50/60 border-emerald-200 dark:bg-emerald-900/10 dark:border-emerald-800/60" : "bg-muted/20",
                    )}
                  >
                    <div className="flex items-center gap-2">
                      <span className={cn("flex h-8 w-8 items-center justify-center rounded-xl", item.done ? "bg-emerald-500 text-white" : "bg-background text-muted-foreground")}>
                        {item.done ? <CheckCircle2 className="h-4 w-4" /> : <Icon className="h-4 w-4" />}
                      </span>
                      <span className="text-sm font-medium leading-snug">{item.label}</span>
                    </div>
                  </Link>
                );
              })}
            </div>
          </div>
        </CardContent>
      </Card>

      {/* ------ Resume Vault card --------------------------------------------------------------------------------------------------------------------------------------------- */}
      <Card className="overflow-hidden">
        <CardHeader className="pb-3">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <CardTitle className="text-base">Latest Application Timeline</CardTitle>
              <p className="text-sm text-muted-foreground">A quick view of where your most recent application stands.</p>
            </div>
            {latestApplication?.job_id && (
              <Button asChild variant="outline" size="sm" className="rounded-xl">
                <Link to={`/candidate/jobs/${latestApplication.job_id}`}>Open job</Link>
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent>
          {!latestApplication ? (
            <EmptyState
              icon={Briefcase}
              title="No active application timeline yet"
              description="Apply to a role and your screening, quiz, and recruiter decision checkpoints will appear here."
              action={<Button asChild className="rounded-xl"><Link to="/candidate/jobs">Browse Jobs</Link></Button>}
              className="py-8"
            />
          ) : (
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              {timelineSteps.map((step, idx) => {
                const Icon = step.icon;
                return (
                  <div
                    key={step.label}
                    className={cn(
                      "relative rounded-2xl border p-4 transition-colors",
                      step.active ? "border-primary/25 bg-primary/5" : "bg-muted/20 text-muted-foreground",
                    )}
                  >
                    <div className="flex items-center gap-3">
                      <div className={cn("flex h-9 w-9 items-center justify-center rounded-xl", step.active ? "bg-primary text-primary-foreground" : "bg-background")}>
                        <Icon className="h-4 w-4" />
                      </div>
                      <div className="min-w-0">
                        <p className="text-sm font-semibold text-foreground">{step.label}</p>
                        <p className="truncate text-xs text-muted-foreground">{step.detail}</p>
                      </div>
                    </div>
                    {idx < timelineSteps.length - 1 && (
                      <div className="absolute -right-2 top-1/2 hidden h-px w-4 bg-border xl:block" />
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>

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
                  Save a resume to use <strong className="text-foreground">Easy Apply</strong> on any job - no re-uploading.
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

      <Card className="overflow-hidden">
        <CardHeader className="pb-3">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <CardTitle className="text-base">Recommended for You</CardTitle>
              <p className="text-sm text-muted-foreground">
                Matches are estimated from your resume skills and currently open roles.
              </p>
            </div>
            <Button asChild variant="outline" size="sm" className="rounded-xl">
              <Link to="/candidate/jobs">View all jobs</Link>
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {loading.publicJobs ? (
            <div className="grid gap-3 md:grid-cols-3">
              {Array.from({ length: 3 }).map((_, idx) => <Skeleton key={`rec-${idx}`} className="h-32 rounded-2xl" />)}
            </div>
          ) : recommendedJobs.length === 0 ? (
            <EmptyState
              icon={Briefcase}
              title="No recommendations yet"
              description="Upload a resume or check back when more open roles are published."
              action={<Button asChild className="rounded-xl"><Link to="/candidate/jobs">Browse Jobs</Link></Button>}
              className="py-8"
            />
          ) : (
            <div className="grid gap-3 md:grid-cols-3">
              {recommendedJobs.map((job) => {
                const requiredCount = job.requiredSkills.length;
                const matchedCount = job.matchedSkills.length;
                const matchPct = requiredCount > 0 ? Math.round((matchedCount / requiredCount) * 100) : 0;
                return (
                  <Link
                    key={job.id}
                    to={`/candidate/jobs/${job.id}`}
                    className="group rounded-2xl border bg-muted/15 p-4 transition-all hover:border-primary/40 hover:bg-primary/5"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="line-clamp-1 font-semibold group-hover:text-primary">{job.title}</p>
                        <p className="mt-1 line-clamp-1 text-xs text-muted-foreground">{job.company || job.location || "Open role"}</p>
                      </div>
                      <Badge variant={matchPct >= 70 ? "default" : "secondary"} className="shrink-0">
                        {requiredCount > 0 ? `${matchPct}%` : "New"}
                      </Badge>
                    </div>
                    <p className="mt-3 text-xs text-muted-foreground">
                      {requiredCount > 0
                        ? `${matchedCount} of ${requiredCount} required skills match`
                        : "New role available for review"}
                    </p>
                    <div className="mt-3 flex flex-wrap gap-1.5">
                      {job.matchedSkills.slice(0, 3).map((skill: string) => (
                        <span key={skill} className="rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-medium text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300">
                          {skill}
                        </span>
                      ))}
                      {job.matchedSkills.length === 0 && requiredCount > 0 && (
                        <span className="text-[11px] text-muted-foreground">Open to explore</span>
                      )}
                    </div>
                  </Link>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>

      {/* ------ Pending quiz alerts --------------------------------------------------------------------------------------------------------------------------------------- */}
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

      {/* ------ Applications grid ------------------------------------------------------------------------------------------------------------------------------------------ */}
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
          <EmptyState
            icon={Briefcase}
            title="No applications yet"
            description="Browse open positions and start applying. Your progress, scores, and feedback will show up here."
            action={<Button asChild className="rounded-xl"><Link to="/candidate/jobs">Browse Open Jobs</Link></Button>}
          />
        ) : (
          <div className="grid gap-5 grid-cols-1 lg:grid-cols-2 xl:grid-cols-3">
            {applications.map((app, idx) => {
              const normalizedTag = normalizeTag(app.tag);
              const hrActed = normalizedTag.length > 0;
              // BUG-F2 FIX: case-insensitive tag check
              const isApproved = hrActed && (matchesTag(app.tag, "strong", "medium") || app.passed === true);
              const isRejected = hrActed && matchesTag(app.tag, "reject");
              const companyName = ((app as any).company || "").trim() || "Unknown Company";

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
                        <Briefcase className="h-3 w-3" /> {companyName}
                      </p>
                    </div>
                    <Badge
                      variant={matchesTag(app.tag, "reject") ? "destructive" : matchesTag(app.tag, "strong") ? "default" : "secondary"}
                      className="shrink-0 capitalize"
                    >
                      {candidateTagLabel(app.tag)}
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
                        ? <><CheckCircle2 className="h-4 w-4 shrink-0" /> Shortlisted - HR will be in touch soon.</>
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
                        {app.resume_score != null ? `${app.resume_score.toFixed(0)}%` : " - "}
                      </p>
                    </div>
                    <div className="bg-muted/40 rounded-xl p-3 border group-hover:bg-primary/5 transition-colors">
                      <p className="text-[10px] uppercase tracking-wider font-semibold text-muted-foreground mb-1">Quiz</p>
                      <p className="font-bold text-lg">
                        {/* BUG-F1 FIX: quiz_max_score is now nullable - guard against null before dividing */}
                        {app.quiz_score != null && app.quiz_max_score != null && app.quiz_max_score > 0
                          ? `${((app.quiz_score / app.quiz_max_score) * 100).toFixed(0)}%`
                          : " - "}
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
