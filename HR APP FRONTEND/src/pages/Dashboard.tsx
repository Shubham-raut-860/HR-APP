import { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, Cell, LabelList } from 'recharts';
import { Briefcase, Users, FileText, BrainCircuit, AlertCircle } from 'lucide-react';
import { getJobs } from '@/services/jobs';
import { getCandidates, getPipelineStats } from '@/services/candidates';
import { useAuth } from '@/context/AuthContext';
import { DropdownMenu, DropdownMenuContent, DropdownMenuCheckboxItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";
import { SlidersHorizontal } from 'lucide-react';

type ActivityType = 'job' | 'candidate';

export default function Dashboard() {
  const { user } = useAuth();
  const [stats, setStats] = useState({
    totalJobs: 0,
    shortlisted: 0,
    hired: 0,
    resumesParsed: 0,
    avgQuizScore: 0
  });
  const [allActivities, setAllActivities] = useState<any[]>([]);
  const [activityFilter, setActivityFilter] = useState<Set<ActivityType>>(new Set(['job', 'candidate']));
  const [funnelData, setFunnelData] = useState<any[]>([]);
  const [statsDegraded, setStatsDegraded] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;

    const fetchData = async () => {
      if (!user) return;
      try {
        const [jobs, recentCandidates] = await Promise.all([
          getJobs(false, controller.signal),
          getCandidates(undefined, 20, controller.signal),
        ]);

        if (cancelled) return;

        const totalJobs = jobs.filter((j: any) => j.is_active).length;

        // Stats endpoint requires the is_archived column (migrate_all.py).
        // If it hasn't been run yet the endpoint 500s — catch that independently
        // so the rest of the dashboard still renders. Once migrate_all.py is run
        // and the backend is restarted this will start working automatically.
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
          if (!cancelled) setStatsDegraded(false);
        } catch {
          if (!cancelled) setStatsDegraded(true);
        }

        if (cancelled) return;

        if (pipelineStats) {
          setStats({
            totalJobs,
            shortlisted:   pipelineStats.shortlisted,
            hired:         pipelineStats.hired,
            resumesParsed: pipelineStats.total_candidates,
            avgQuizScore:  Math.round(pipelineStats.avg_quiz_score ?? 0),
          });

          setFunnelData([
            { name: 'Parsed',      value: pipelineStats.total_candidates, fill: '#8884d8' },
            { name: 'Shortlisted', value: pipelineStats.shortlisted,      fill: '#82ca9d' },
            { name: 'Tested',      value: pipelineStats.tested,           fill: '#ffc658' },
            { name: 'Final Rank',  value: pipelineStats.final_ranked,     fill: '#ff8042' },
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

        // Build a job_id → title lookup for the activity feed so candidate
        // entries show the actual job title instead of the fallback "a job".
        const jobTitleMap = new Map<string, string>(
          jobs.map((j: any) => [j.id, j.title])
        );

        // Activity feed — jobs + most-recent candidates (capped)
        const jobActivities = jobs
          .sort((a: any, b: any) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
          .map((j: any) => ({
            type: 'job' as ActivityType,
            user: "System",
            action: "posted",
            target: j.title,
            time: new Date(j.created_at).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }),
            rawTime: new Date(j.created_at).getTime(),
            avatar: "SJ",
            key: `job-${j.id}`,
          }));

        const candidateActivities = recentCandidates
          .sort((a: any, b: any) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
          .map((c: any) => ({
            type: 'candidate' as ActivityType,
            user: c.name || 'Unknown',
            action: "applied for",
            target: (c.job_id && jobTitleMap.get(c.job_id)) || "a job",
            time: new Date(c.created_at).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }),
            rawTime: new Date(c.created_at).getTime(),
            avatar: (c.name || "??").substring(0, 2).toUpperCase(),
            key: `cand-${c.id}`,
          }));

        if (cancelled) return;

        setAllActivities(
          [...jobActivities, ...candidateActivities].sort((a, b) => b.rawTime - a.rawTime)
        );
      } catch (error: any) {
        if (error.name !== "AbortError" && error.code !== "ERR_CANCELED") {
          console.error("Dashboard fetch error", error);
        }
      }
    };

    fetchData();

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [user]);

  const visibleActivities = allActivities.filter(a => activityFilter.has(a.type));

  const toggleFilter = (type: ActivityType) => {
    setActivityFilter(prev => {
      const next = new Set(prev);
      if (next.has(type)) {
        if (next.size > 1) next.delete(type); // keep at least one
      } else {
        next.add(type);
      }
      return next;
    });
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-3xl font-bold tracking-tight">Dashboard</h2>
        <p className="text-muted-foreground">Welcome back, {user?.full_name || 'User'}. Here's what's happening today.</p>
      </div>

      {statsDegraded && (
        <Card className="border-amber-300 bg-amber-50/70 dark:border-amber-800 dark:bg-amber-900/20">
          <CardContent className="py-3">
            <div className="flex items-start gap-2 text-amber-900 dark:text-amber-300">
              <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
              <p className="text-sm">
                Pipeline stats unavailable — data could not be loaded. Displaying may be incomplete.
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Stats Cards */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card className={statsDegraded ? "opacity-60 pointer-events-none" : ""}>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Active Jobs</CardTitle>
            <div className="h-8 w-8 rounded-lg bg-blue-50 dark:bg-blue-900/20 flex items-center justify-center">
              <Briefcase className="h-4 w-4 text-blue-500" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{statsDegraded ? "—" : stats.totalJobs}</div>
            <p className="text-xs text-muted-foreground">{statsDegraded ? "N/A" : "Open job postings"}</p>
          </CardContent>
        </Card>
        <Card className={statsDegraded ? "opacity-60 pointer-events-none" : ""}>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Total Applicants</CardTitle>
            <div className="h-8 w-8 rounded-lg bg-indigo-50 dark:bg-indigo-900/20 flex items-center justify-center">
              <Users className="h-4 w-4 text-indigo-500" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{statsDegraded ? "—" : stats.resumesParsed}</div>
            <p className="text-xs text-muted-foreground">{statsDegraded ? "N/A" : "Resumes parsed"}</p>
          </CardContent>
        </Card>
        <Card className={statsDegraded ? "opacity-60 pointer-events-none" : ""}>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Shortlisted</CardTitle>
            <div className="h-8 w-8 rounded-lg bg-emerald-50 dark:bg-emerald-900/20 flex items-center justify-center">
              <FileText className="h-4 w-4 text-emerald-500" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{statsDegraded ? "—" : stats.shortlisted}</div>
            <p className="text-xs text-muted-foreground">{statsDegraded ? "N/A" : "Strong &amp; Medium candidates"}</p>
          </CardContent>
        </Card>
        <Card className={statsDegraded ? "opacity-60 pointer-events-none" : ""}>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Avg. Quiz Score</CardTitle>
            <div className="h-8 w-8 rounded-lg bg-violet-50 dark:bg-violet-900/20 flex items-center justify-center">
              <BrainCircuit className="h-4 w-4 text-violet-500" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{statsDegraded ? "—" : stats.avgQuizScore}</div>
            <p className="text-xs text-muted-foreground">{statsDegraded ? "N/A" : "Across all candidates"}</p>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-7">
        {/* Hiring Funnel Chart */}
        <Card className="col-span-4">
          <CardHeader>
            <CardTitle>Hiring Funnel</CardTitle>
          </CardHeader>
          <CardContent className="pl-2">
            {funnelData.every(d => d.value === 0) ? (
              <div className="flex flex-col items-center justify-center h-[350px] text-center text-muted-foreground">
                <Briefcase className="h-10 w-10 mb-3 opacity-20" />
                <p className="font-medium">No pipeline data yet</p>
                <p className="text-sm">Upload resumes and run the quiz to populate this funnel.</p>
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={350} minWidth={0}>
                <BarChart data={funnelData} layout="vertical" margin={{ top: 5, right: 60, left: 40, bottom: 5 }}>
                  <XAxis type="number" hide />
                  <YAxis dataKey="name" type="category" width={100} tick={{ fontSize: 13, fontWeight: 500 }} />
                  <Tooltip
                    contentStyle={{ background: 'hsl(var(--card))', border: '1px solid hsl(var(--border))', borderRadius: 'var(--radius)' }}
                    cursor={{ fill: 'hsl(var(--muted))' }}
                    formatter={(value: number) => [value, 'Candidates']}
                  />
                  <Bar dataKey="value" radius={[0, 6, 6, 0]} barSize={32}>
                    <LabelList dataKey="value" position="right" style={{ fill: 'hsl(var(--foreground))', fontSize: 13, fontWeight: 600 }} />
                    {funnelData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={entry.fill} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>

        {/* Recent Activity — scrollable, full history, filterable */}
        <Card className="col-span-3 flex flex-col" style={{ maxHeight: '460px' }}>
          <CardHeader className="pb-3 shrink-0">
            <div className="flex items-center justify-between">
              <div>
                <CardTitle>Recent Activity</CardTitle>
                <p className="text-sm text-muted-foreground mt-0.5">
                  {visibleActivities.length} event{visibleActivities.length !== 1 ? 's' : ''}
                </p>
              </div>
              {/* Activity type filter */}
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
                  <DropdownMenuCheckboxItem
                    checked={activityFilter.has('job')}
                    onCheckedChange={() => toggleFilter('job')}
                  >
                    <Briefcase className="mr-2 h-3.5 w-3.5 text-muted-foreground" />
                    Job postings
                  </DropdownMenuCheckboxItem>
                  <DropdownMenuCheckboxItem
                    checked={activityFilter.has('candidate')}
                    onCheckedChange={() => toggleFilter('candidate')}
                  >
                    <Users className="mr-2 h-3.5 w-3.5 text-muted-foreground" />
                    Applications
                  </DropdownMenuCheckboxItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </CardHeader>
          <CardContent className="flex-1 overflow-y-auto min-h-0 pr-2">
            {visibleActivities.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-8 text-center text-muted-foreground h-full">
                <p className="text-sm">No activity to show</p>
                <p className="text-xs mt-1">Create a job or add candidates to see activity here.</p>
              </div>
            ) : (
              <div className="space-y-4">
                {visibleActivities.map((item: any) => (
                  <div key={item.key} className="flex items-start gap-3">
                    <div className={`h-8 w-8 rounded-full flex items-center justify-center text-xs font-medium shrink-0 ${
                      item.type === 'job'
                        ? 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300'
                        : 'bg-primary/10 text-primary'
                    }`}>
                      {item.avatar}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm leading-snug">
                        <span className="font-medium">{item.user}</span>{' '}
                        <span className="text-muted-foreground">{item.action}</span>{' '}
                        <span className="font-medium truncate">{item.target}</span>
                      </p>
                      <p className="text-xs text-muted-foreground mt-0.5">{item.time}</p>
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
