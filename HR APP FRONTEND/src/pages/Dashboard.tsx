import { useState, useEffect, useMemo } from "react";
import { Link } from "react-router-dom";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Briefcase, Users, FileText, BrainCircuit, AlertCircle, UserCheck, Rocket, Settings, UploadCloud, CalendarDays } from "lucide-react";
import { getJobs } from "@/services/jobs";
import { getCandidates, getPipelineStats } from "@/services/candidates";
import { useAuth } from "@/context/AuthContext";
import { DropdownMenu, DropdownMenuContent, DropdownMenuCheckboxItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";
import { SlidersHorizontal } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";
import { InfoHint } from "@/components/ui/info-hint";

type ActivityType = "job" | "candidate";
type DateRange = "7d" | "month" | "90d" | "all";

const DATE_RANGE_OPTIONS: Array<{ value: DateRange; label: string }> = [
  { value: "7d", label: "Last 7 days" },
  { value: "month", label: "This month" },
  { value: "90d", label: "Last 3 months" },
  { value: "all", label: "All time" },
];

const isWithinDateRange = (timestamp: number, range: DateRange) => {
  if (!timestamp || range === "all") return true;
  const date = new Date(timestamp);
  const now = new Date();
  if (range === "7d") return now.getTime() - timestamp <= 7 * 86_400_000;
  if (range === "90d") return now.getTime() - timestamp <= 90 * 86_400_000;
  return date.getFullYear() === now.getFullYear() && date.getMonth() === now.getMonth();
};

const getActivityBucket = (timestamp: number) => {
  const date = new Date(timestamp);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const activityDay = new Date(date);
  activityDay.setHours(0, 0, 0, 0);
  const diffDays = Math.round((today.getTime() - activityDay.getTime()) / 86_400_000);
  if (diffDays === 0) return "Today";
  if (diffDays === 1) return "Yesterday";
  if (diffDays <= 7) return "Last 7 days";
  return date.toLocaleDateString("en-GB", { month: "short", year: "numeric" });
};

export default function Dashboard() {
  const { user } = useAuth();
  const userId = user?.id ?? "";
  const userFullName = user?.full_name ?? "";
  const userEmail = user?.email ?? "";
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState({
    totalJobs: 0,
    shortlisted: 0,
    hired: 0,
    resumesParsed: 0,
    avgQuizScore: 0,
  });
  const [allActivities, setAllActivities] = useState<any[]>([]);
  const [activityFilter, setActivityFilter] = useState<Set<ActivityType>>(new Set(["job", "candidate"]));
  const [funnelData, setFunnelData] = useState<any[]>([]);
  const [statsDegraded, setStatsDegraded] = useState(false);
  const [dateRange, setDateRange] = useState<DateRange>("all");
  const [jobsSnapshot, setJobsSnapshot] = useState<any[]>([]);
  const [candidateSnapshot, setCandidateSnapshot] = useState<any[]>([]);
  const [pipelineStatsSnapshot, setPipelineStatsSnapshot] = useState<{
    total_candidates: number;
    shortlisted: number;
    hired: number;
    tested: number;
    final_ranked: number;
    avg_quiz_score: number | null;
  } | null>(null);
  const [onboardingDismissed, setOnboardingDismissed] = useState(() =>
    typeof window !== "undefined" &&
    typeof window.localStorage?.getItem === "function" &&
    window.localStorage.getItem("recruiter_onboarding_dismissed") === "1"
  );

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;

    const fetchData = async () => {
      if (!userId) {
        setLoading(false);
        return;
      }
      setLoading(true);
      try {
        const [jobs, recentCandidates] = await Promise.all([
          getJobs(false, controller.signal),
          getCandidates(undefined, 250, controller.signal),
        ]);

        if (cancelled) return;
        setJobsSnapshot(jobs);
        setCandidateSnapshot(recentCandidates);

        const totalJobs = jobs.filter((j: any) => j.is_active).length;

        let pipelineStats: {
          total_candidates: number;
          shortlisted: number;
          hired: number;
          tested: number;
          final_ranked: number;
          avg_quiz_score: number | null;
        } | null = null;

        try {
          pipelineStats = await getPipelineStats(controller.signal);
          if (!cancelled) {
            setStatsDegraded(false);
            setPipelineStatsSnapshot(pipelineStats);
          }
        } catch {
          if (!cancelled) {
            setStatsDegraded(true);
            setPipelineStatsSnapshot(null);
          }
        }

        if (cancelled) return;

        if (pipelineStats) {
          setStats({
            totalJobs,
            shortlisted: pipelineStats.shortlisted,
            hired: pipelineStats.hired,
            resumesParsed: pipelineStats.total_candidates,
            avgQuizScore: Math.round(pipelineStats.avg_quiz_score ?? 0),
          });

          setFunnelData([
            { name: "Parsed", value: pipelineStats.total_candidates, fill: "#8884d8" },
            { name: "Shortlisted", value: pipelineStats.shortlisted, fill: "#82ca9d" },
            { name: "Tested", value: pipelineStats.tested, fill: "#ffc658" },
            { name: "Final Rank", value: pipelineStats.final_ranked, fill: "#ff8042" },
          ]);
        } else {
          setStats({
            totalJobs,
            shortlisted: 0,
            hired: 0,
            resumesParsed: 0,
            avgQuizScore: 0,
          });
          setFunnelData([]);
        }

        const jobTitleMap = new Map<string, string>(jobs.map((j: any) => [j.id, j.title]));

        const jobActivities = jobs
          .sort((a: any, b: any) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
          .map((j: any) => ({
            type: "job" as ActivityType,
            user: userFullName || "Recruiter",
            action: "posted",
            target: j.title,
            time: new Date(j.created_at).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" }),
            rawTime: new Date(j.created_at).getTime(),
            avatar: (userFullName || userEmail || "R").substring(0, 2).toUpperCase(),
            key: `job-${j.id}`,
          }));

        const candidateActivities = recentCandidates
          .sort((a: any, b: any) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
          .map((c: any) => ({
            type: "candidate" as ActivityType,
            user: c.name || "Unknown",
            action: "applied for",
            target: (c.job_id && jobTitleMap.get(c.job_id)) || "a job",
            time: new Date(c.created_at).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" }),
            rawTime: new Date(c.created_at).getTime(),
            avatar: (c.name || "??").substring(0, 2).toUpperCase(),
            key: `cand-${c.id}`,
          }));

        if (cancelled) return;

        setAllActivities([...jobActivities, ...candidateActivities].sort((a, b) => b.rawTime - a.rawTime));
      } catch (error: any) {
        if (error.name !== "AbortError" && error.code !== "ERR_CANCELED") {
          console.error("Dashboard fetch error", error);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    fetchData();

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [userEmail, userFullName, userId]);

  const dateFilteredActivities = useMemo(
    () => allActivities.filter((a) => isWithinDateRange(a.rawTime, dateRange)),
    [allActivities, dateRange]
  );
  const visibleActivities = useMemo(
    () => dateFilteredActivities.filter((a) => activityFilter.has(a.type)),
    [activityFilter, dateFilteredActivities]
  );
  const groupedActivities = useMemo(() => {
    const groups: Array<{ label: string; items: any[] }> = [];
    visibleActivities.forEach((activity) => {
      const label = getActivityBucket(activity.rawTime);
      const group = groups.find((item) => item.label === label);
      if (group) group.items.push(activity);
      else groups.push({ label, items: [activity] });
    });
    return groups;
  }, [visibleActivities]);

  const displayStats = useMemo(() => {
    if (dateRange === "all" || statsDegraded) return stats;
    const filteredJobs = jobsSnapshot.filter((job) => isWithinDateRange(new Date(job.created_at || 0).getTime(), dateRange));
    const filteredCandidates = candidateSnapshot.filter((candidate) =>
      isWithinDateRange(new Date(candidate.created_at || 0).getTime(), dateRange)
    );
    const quizScores = filteredCandidates
      .map((candidate) => Number(candidate.quiz_score))
      .filter((score) => Number.isFinite(score));
    return {
      totalJobs: filteredJobs.filter((job) => job.is_active).length,
      shortlisted: filteredCandidates.filter((candidate) => ["strong", "medium"].includes((candidate.tag || "").toLowerCase())).length,
      hired: filteredCandidates.filter((candidate) =>
        Boolean(candidate.hired) || String(candidate.status || candidate.hire_status || "").toLowerCase() === "hired"
      ).length,
      resumesParsed: filteredCandidates.length,
      avgQuizScore: quizScores.length ? Math.round(quizScores.reduce((sum, score) => sum + score, 0) / quizScores.length) : 0,
    };
  }, [candidateSnapshot, dateRange, jobsSnapshot, stats, statsDegraded]);

  const displayFunnelData = useMemo(() => {
    if (dateRange === "all") return funnelData;
    const filteredCandidates = candidateSnapshot.filter((candidate) =>
      isWithinDateRange(new Date(candidate.created_at || 0).getTime(), dateRange)
    );
    return [
      { name: "Parsed", value: filteredCandidates.length, fill: "#8884d8" },
      { name: "Shortlisted", value: filteredCandidates.filter((candidate) => ["strong", "medium"].includes((candidate.tag || "").toLowerCase())).length, fill: "#82ca9d" },
      { name: "Tested", value: filteredCandidates.filter((candidate) => candidate.quiz_score != null).length, fill: "#ffc658" },
      { name: "Final Rank", value: filteredCandidates.filter((candidate) => candidate.final_score != null || candidate.rank != null).length, fill: "#ff8042" },
    ];
  }, [candidateSnapshot, dateRange, funnelData]);
  const maxFunnelValue = useMemo(
    () => Math.max(1, ...displayFunnelData.map((item) => Number(item.value) || 0)),
    [displayFunnelData]
  );

  const showOnboarding =
    !onboardingDismissed &&
    !statsDegraded &&
    stats.totalJobs === 0 &&
    (pipelineStatsSnapshot?.total_candidates ?? candidateSnapshot.length) === 0;

  const dismissOnboarding = () => {
    localStorage.setItem("recruiter_onboarding_dismissed", "1");
    setOnboardingDismissed(true);
  };

  const toggleFilter = (type: ActivityType) => {
    setActivityFilter((prev) => {
      const next = new Set(prev);
      if (next.has(type)) {
        if (next.size > 1) next.delete(type);
      } else {
        next.add(type);
      }
      return next;
    });
  };

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <h2 className="text-3xl font-bold tracking-tight">Dashboard</h2>
            <p className="text-muted-foreground">Hiring overview and pipeline status for your active roles.</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button asChild className="rounded-xl">
              <Link to="/jobs"><Briefcase className="mr-2 h-4 w-4" /> Create job</Link>
            </Button>
            <Button asChild variant="outline" className="rounded-xl">
              <Link to="/candidates"><UploadCloud className="mr-2 h-4 w-4" /> Add candidates</Link>
            </Button>
          </div>
        </div>
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-5">
          {Array.from({ length: 5 }).map((_, idx) => (
            <Card key={`dashboard-stat-${idx}`}>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <Skeleton className="h-4 w-24" />
                <Skeleton className="h-8 w-8 rounded-lg" />
              </CardHeader>
              <CardContent className="space-y-2">
                <Skeleton className="h-8 w-16" />
                <Skeleton className="h-3 w-28" />
              </CardContent>
            </Card>
          ))}
        </div>
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-7">
          <Card className="col-span-4">
            <CardHeader>
              <Skeleton className="h-5 w-36" />
            </CardHeader>
            <CardContent>
              <Skeleton className="h-[320px] w-full rounded-2xl" />
            </CardContent>
          </Card>
          <Card className="col-span-3">
            <CardHeader>
              <Skeleton className="h-5 w-36" />
              <Skeleton className="h-4 w-24" />
            </CardHeader>
            <CardContent className="space-y-3">
              {Array.from({ length: 5 }).map((_, idx) => (
                <div key={`activity-skeleton-${idx}`} className="flex items-center gap-3">
                  <Skeleton className="h-8 w-8 rounded-full" />
                  <div className="flex-1 space-y-2">
                    <Skeleton className="h-4 w-3/4" />
                    <Skeleton className="h-3 w-24" />
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h2 className="text-3xl font-bold tracking-tight">Dashboard</h2>
          <p className="text-muted-foreground">Hiring overview and pipeline status for your active roles.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            <CalendarDays className="h-3.5 w-3.5" /> Range
          </span>
          <div className="flex flex-wrap gap-1 rounded-2xl border bg-background p-1">
            {DATE_RANGE_OPTIONS.map((option) => (
              <Button
                key={option.value}
                type="button"
                variant={dateRange === option.value ? "default" : "ghost"}
                size="sm"
                className="h-8 rounded-xl px-3 text-xs"
                onClick={() => setDateRange(option.value)}
              >
                {option.label}
              </Button>
            ))}
          </div>
        </div>
      </div>

      {statsDegraded && (
        <Card className="border-amber-300 bg-amber-50/70 dark:border-amber-800 dark:bg-amber-900/20">
          <CardContent className="py-3">
            <div className="flex items-start gap-2 text-amber-900 dark:text-amber-300">
              <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
              <p className="text-sm">Pipeline stats unavailable - data could not be loaded. Displaying may be incomplete.</p>
            </div>
          </CardContent>
        </Card>
      )}

      {showOnboarding && (
        <Card className="overflow-hidden border-primary/20 bg-gradient-to-br from-primary/8 via-background to-background">
          <CardContent className="p-5">
            <div className="flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
              <div className="flex gap-4">
                <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-primary text-primary-foreground shadow-sm">
                  <Rocket className="h-5 w-5" />
                </div>
                <div>
                  <p className="text-sm font-semibold uppercase tracking-wider text-primary">First hire setup</p>
                  <h3 className="text-xl font-bold tracking-tight">Post your first role in a guided flow</h3>
                  <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
                    Start with company details, create a job, then upload resumes or share the role with candidates.
                  </p>
                </div>
              </div>
              <div className="grid gap-2 sm:grid-cols-3 lg:min-w-[520px]">
                <Button asChild variant="outline" className="justify-start rounded-xl">
                  <Link to="/settings"><Settings className="mr-2 h-4 w-4" /> Company profile</Link>
                </Button>
                <Button asChild className="justify-start rounded-xl">
                  <Link to="/jobs"><Briefcase className="mr-2 h-4 w-4" /> Create job</Link>
                </Button>
                <Button asChild variant="outline" className="justify-start rounded-xl">
                  <Link to="/candidates"><UploadCloud className="mr-2 h-4 w-4" /> Add candidates</Link>
                </Button>
              </div>
            </div>
            <div className="mt-4 flex justify-end">
              <Button type="button" variant="ghost" size="sm" className="rounded-xl text-muted-foreground" onClick={dismissOnboarding}>
                Hide this guide
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-5">
        <Card className={statsDegraded ? "opacity-60 pointer-events-none" : ""}>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="flex items-center gap-1.5 text-sm font-medium">
              Active Jobs
              <InfoHint label="Active jobs help" description="Jobs currently open to candidates and counted in the live hiring pipeline." />
            </CardTitle>
            <div className="h-8 w-8 rounded-lg bg-blue-50 dark:bg-blue-900/20 flex items-center justify-center">
              <Briefcase className="h-4 w-4 text-blue-500" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{statsDegraded ? "-" : displayStats.totalJobs}</div>
            <p className="text-xs text-muted-foreground">{statsDegraded ? "N/A" : "Open job postings"}</p>
          </CardContent>
        </Card>
        <Card className={statsDegraded ? "opacity-60 pointer-events-none" : ""}>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="flex items-center gap-1.5 text-sm font-medium">
              Total Applicants
              <InfoHint label="Total applicants help" description="Total candidate applications currently visible across your recruiter workspace." />
            </CardTitle>
            <div className="h-8 w-8 rounded-lg bg-indigo-50 dark:bg-indigo-900/20 flex items-center justify-center">
              <Users className="h-4 w-4 text-indigo-500" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{statsDegraded ? "-" : displayStats.resumesParsed}</div>
            <p className="text-xs text-muted-foreground">{statsDegraded ? "N/A" : "Resumes parsed"}</p>
          </CardContent>
        </Card>
        <Card className={statsDegraded ? "opacity-60 pointer-events-none" : ""}>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="flex items-center gap-1.5 text-sm font-medium">
              Shortlisted
              <InfoHint label="Shortlisted help" description="Candidates marked as strong or medium fit after resume screening and review." />
            </CardTitle>
            <div className="h-8 w-8 rounded-lg bg-emerald-50 dark:bg-emerald-900/20 flex items-center justify-center">
              <FileText className="h-4 w-4 text-emerald-500" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{statsDegraded ? "-" : displayStats.shortlisted}</div>
            <p className="text-xs text-muted-foreground">{statsDegraded ? "N/A" : "Strong and medium candidates"}</p>
          </CardContent>
        </Card>
        <Card className={statsDegraded ? "opacity-60 pointer-events-none" : ""}>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="flex items-center gap-1.5 text-sm font-medium">
              Avg. Quiz Score
              <InfoHint label="Average quiz score help" description="Average assessment score for candidates who have completed assigned quizzes." side="left" />
            </CardTitle>
            <div className="h-8 w-8 rounded-lg bg-violet-50 dark:bg-violet-900/20 flex items-center justify-center">
              <BrainCircuit className="h-4 w-4 text-violet-500" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{statsDegraded ? "-" : displayStats.avgQuizScore}</div>
            <p className="text-xs text-muted-foreground">{statsDegraded ? "N/A" : "Across all candidates"}</p>
          </CardContent>
        </Card>
        <Card className={statsDegraded ? "opacity-60 pointer-events-none" : ""}>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="flex items-center gap-1.5 text-sm font-medium">
              Hired
              <InfoHint label="Hired help" description="Candidates marked as hired in your pipeline." side="left" />
            </CardTitle>
            <div className="h-8 w-8 rounded-lg bg-amber-50 dark:bg-amber-900/20 flex items-center justify-center">
              <UserCheck className="h-4 w-4 text-amber-500" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{statsDegraded ? "-" : displayStats.hired}</div>
            <p className="text-xs text-muted-foreground">{statsDegraded ? "N/A" : "Marked as hired"}</p>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-7">
        <Card className="col-span-4">
          <CardHeader>
            <CardTitle>Hiring Funnel</CardTitle>
          </CardHeader>
          <CardContent className="pl-2">
            {displayFunnelData.every((d) => d.value === 0) ? (
              <EmptyState
                icon={Briefcase}
                title="No pipeline data yet"
                description="Upload resumes, shortlist candidates, and send quizzes to populate this funnel."
                className="h-[350px] border-0 bg-transparent"
              />
            ) : (
              <div className="space-y-5 px-3 py-4 min-h-[350px] flex flex-col justify-center">
                {displayFunnelData.map((stage) => {
                  const value = Number(stage.value) || 0;
                  const width = value > 0 ? Math.max(12, Math.round((value / maxFunnelValue) * 100)) : 0;
                  return (
                    <div key={stage.name} className="space-y-2">
                      <div className="flex items-center justify-between gap-3">
                        <span className="text-sm font-medium text-foreground">{stage.name}</span>
                        <span className="text-sm font-semibold tabular-nums">{value}</span>
                      </div>
                      <div className="h-3 rounded-full bg-muted overflow-hidden" aria-label={`${stage.name}: ${value} candidates`}>
                        <div
                          className="h-full rounded-full transition-all duration-500"
                          style={{ width: `${width}%`, backgroundColor: stage.fill }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </CardContent>
        </Card>

        <Card className="col-span-3 flex flex-col max-h-[460px]">
          <CardHeader className="pb-3 shrink-0">
            <div className="flex items-center justify-between">
              <div>
                <CardTitle>Recent Activity</CardTitle>
                <p className="text-sm text-muted-foreground mt-0.5">
                  {visibleActivities.length} event{visibleActivities.length !== 1 ? "s" : ""}
                </p>
              </div>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline" size="sm" className="h-7 px-2 text-xs gap-1.5 rounded-lg">
                    <SlidersHorizontal className="h-3 w-3" />
                    Filter
                    {activityFilter.size < 2 && (
                      <span className="h-4 min-w-[16px] px-1 rounded-full bg-primary text-primary-foreground text-[10px] font-bold flex items-center justify-center">
                        {activityFilter.size}
                      </span>
                    )}
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-44">
                  <DropdownMenuCheckboxItem checked={activityFilter.has("job")} onCheckedChange={() => toggleFilter("job")}>
                    <Briefcase className="mr-2 h-3.5 w-3.5 text-muted-foreground" />
                    Job postings
                  </DropdownMenuCheckboxItem>
                  <DropdownMenuCheckboxItem checked={activityFilter.has("candidate")} onCheckedChange={() => toggleFilter("candidate")}>
                    <Users className="mr-2 h-3.5 w-3.5 text-muted-foreground" />
                    Applications
                  </DropdownMenuCheckboxItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </CardHeader>
          <CardContent className="flex-1 overflow-y-auto min-h-0 pr-2">
            {visibleActivities.length === 0 ? (
              <EmptyState
                icon={Users}
                title="No activity to show"
                description="Create a job or add candidates to see a live hiring feed here."
                className="h-full border-0 bg-transparent py-8"
              />
            ) : (
              <div className="space-y-4">
                {groupedActivities.map((group) => (
                  <div key={group.label} className="space-y-3">
                    <p className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground">{group.label}</p>
                    <div className="space-y-4">
                      {group.items.map((item: any) => (
                        <div key={item.key} className="flex items-start gap-3">
                          <div
                            className={`h-8 w-8 rounded-full flex items-center justify-center text-xs font-medium shrink-0 ${
                              item.type === "job"
                                ? "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300"
                                : "bg-primary/10 text-primary"
                            }`}
                          >
                            {item.avatar}
                          </div>
                          <div className="flex-1 min-w-0">
                            <p className="text-sm leading-snug">
                              <span className="font-medium">{item.user}</span>{" "}
                              <span className="text-muted-foreground">{item.action}</span>{" "}
                              <span className="font-medium truncate">{item.target}</span>
                            </p>
                            <p className="text-xs text-muted-foreground mt-0.5">{item.time}</p>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
