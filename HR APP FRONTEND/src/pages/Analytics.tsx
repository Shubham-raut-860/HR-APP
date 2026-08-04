import React, { useState, useEffect, useMemo } from "react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select, SelectContent, SelectItem,
  SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis,
  Tooltip, LabelList, Cell, CartesianGrid,
} from "recharts";
import {
  Users, TrendingUp, CheckCircle2, BarChart2,
  Trophy, Search, ChevronLeft, ChevronRight,
  RefreshCw, TrendingDown, AlertCircle,
  Layers, Target, Award, ArrowUpDown, ArrowUp, ArrowDown,
  FileSpreadsheet, FileText,
} from "lucide-react";

import { getJobs } from "@/services/jobs";
import { getSkillGap, getRankings, getSummary, exportExcel, exportPDF } from "@/services/analytics";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import type { AnalyticsSummary } from "@/types";
import { SegmentedTabs } from "@/components/ui/segmented-tabs";

const FUNNEL_COLORS = ["#8b5cf6", "#6366f1", "#3b82f6", "#0ea5e9", "#10b981"];
const PAGE_SIZE = 50;

function normalizeTag(tag: string | null | undefined): string {
  return (tag ?? "").toLowerCase().trim();
}

function formatTagLabel(tag: string | null | undefined): string {
  const normalized = normalizeTag(tag);
  if (normalized === "strong") return "Strong";
  if (normalized === "medium") return "Medium";
  if (normalized === "reject") return "Reject";
  return "Untagged";
}

function scoreColor(v: number) {
  if (v >= 75) return "text-emerald-600 dark:text-emerald-400";
  if (v >= 50) return "text-amber-600 dark:text-amber-400";
  return "text-red-500 dark:text-red-400";
}
function scoreBg(v: number) {
  if (v >= 75) return "bg-emerald-500";
  if (v >= 50) return "bg-amber-500";
  return "bg-red-500";
}

function MiniBar({ value }: { value: number }) {
  return (
    <div className="flex items-center gap-2 w-full">
      <div className="flex-1 h-1.5 rounded-full bg-muted overflow-hidden">
        <div className={cn("h-full rounded-full transition-all duration-500", scoreBg(value))} style={{ width: `${Math.min(100, value)}%` }} />
      </div>
      <span className={cn("text-xs tabular-nums font-semibold w-10 text-right", scoreColor(value))}>{value.toFixed(1)}%</span>
    </div>
  );
}

const TAG_BADGE: Record<string, string> = {
  strong: "bg-emerald-100 text-emerald-700 border-emerald-200 dark:bg-emerald-900/30 dark:text-emerald-300",
  medium: "bg-amber-100 text-amber-700 border-amber-200 dark:bg-amber-900/30 dark:text-amber-300",
  reject: "bg-red-100 text-red-600 border-red-200 dark:bg-red-900/30 dark:text-red-400",
};

function cleanSkillLabel(skill: string, maxLen = 22): string {
  const t = skill.trim();
  if (t.length <= maxLen) return t;
  const s = t.split(/[,(]/)[0].trim();
  return s.length > 0 && s.length <= maxLen ? s : t.slice(0, maxLen - 1) + "…";
}

function StatCard({ icon: Icon, label, value, sub, color = "primary" }: {
  icon: React.ElementType; label: string; value: string | number; sub?: string; color?: string;
}) {
  const colorMap: Record<string, string> = {
    primary: "bg-primary/10 text-primary",
    emerald: "bg-emerald-100 text-emerald-600 dark:bg-emerald-900/30 dark:text-emerald-400",
    amber:   "bg-amber-100 text-amber-600 dark:bg-amber-900/30 dark:text-amber-400",
    blue:    "bg-blue-100 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400",
    violet:  "bg-violet-100 text-violet-600 dark:bg-violet-900/30 dark:text-violet-400",
  };
  return (
    <div className="rounded-2xl border bg-card p-4 flex items-center gap-4">
      <div className={cn("p-2.5 rounded-xl flex-shrink-0", colorMap[color] || colorMap.primary)}>
        <Icon className="h-5 w-5" />
      </div>
      <div className="min-w-0">
        <p className="text-xs text-muted-foreground font-medium">{label}</p>
        <p className="text-2xl font-bold tabular-nums leading-tight">{value}</p>
        {sub && <p className="text-xs text-muted-foreground mt-0.5">{sub}</p>}
      </div>
    </div>
  );
}

const FunnelTooltip = ({ active, payload, funnelData }: any) => {
  if (!active || !payload?.length) return null;
  const top = funnelData[0]?.value || 1;
  const val = payload[0]?.value ?? 0;
  return (
    <div className="rounded-xl border bg-card shadow-lg p-3 text-sm">
      <p className="font-semibold mb-1">{payload[0]?.payload?.name}</p>
      <p className="text-muted-foreground">{val} candidates</p>
      <p className="font-medium text-primary">{Math.round((val / top) * 100)}% of total</p>
    </div>
  );
};

const GapTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null;
  const match = payload.find((p: any) => p.dataKey === "Match")?.value ?? 0;
  const gap = payload.find((p: any) => p.dataKey === "Gap")?.value ?? 0;
  return (
    <div className="rounded-xl border bg-card shadow-lg p-3 text-sm min-w-[160px]">
      <p className="font-semibold mb-2 border-b pb-1.5">{label}</p>
      <div className="space-y-1">
        <p className="flex items-center justify-between gap-4">
          <span className="flex items-center gap-1.5 text-emerald-600"><span className="w-2 h-2 rounded-full bg-emerald-500 inline-block"/>Match</span>
          <span className="font-bold tabular-nums">{match}%</span>
        </p>
        <p className="flex items-center justify-between gap-4">
          <span className="flex items-center gap-1.5 text-red-500"><span className="w-2 h-2 rounded-full bg-red-500 inline-block"/>Gap</span>
          <span className="font-bold tabular-nums">{gap}%</span>
        </p>
      </div>
    </div>
  );
};

type Tab = "overview" | "rankings" | "skillgap";
type SortKey = "rank" | "name" | "resume_score" | "quiz_pct" | "final_score";
type SortDir = "asc" | "desc";

export default function Analytics() {
  const [tab, setTab] = useState<Tab>("overview");
  const [jobs, setJobs] = useState<any[]>([]);
  const [selectedJobId, setSelectedJobId] = useState("");
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);
  const [funnelData, setFunnelData] = useState<any[]>([]);
  const [rankings, setRankings] = useState<any[]>([]);
  const [skillGaps, setSkillGaps] = useState<any[]>([]);
  const [loadingOverview, setLoadingOverview] = useState(false);
  const [loadingRankings, setLoadingRankings] = useState(false);
  const [loadingSkillGap, setLoadingSkillGap] = useState(false);
  const [exporting, setExporting] = useState<"excel" | "pdf" | null>(null);
  const [search, setSearch] = useState("");
  const [tagFilter, setTagFilter] = useState<"all" | "strong" | "medium" | "reject">("all");
  const [sortKey, setSortKey] = useState<SortKey>("rank");
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  const [page, setPage] = useState(0);
  const [gapFilter, setGapFilter] = useState<"all" | "required" | "nice">("all");

  useEffect(() => {
    (async () => {
      try {
        const allJobs = await getJobs();
        setJobs(allJobs);
        if (allJobs.length > 0) setSelectedJobId(allJobs[0].id);
      } catch { toast.error("Failed to load analytics"); }
    })();
  }, []);

  useEffect(() => {
    if (!selectedJobId) return;
    fetchJobData(selectedJobId);
  }, [selectedJobId]);

  const fetchJobData = async (jobId: string) => {
    setLoadingOverview(true); setLoadingRankings(true); setLoadingSkillGap(true); setPage(0);
    try {
      const [sum, rank, gap] = await Promise.all([getSummary(jobId), getRankings(jobId), getSkillGap(jobId)]);
      setSummary(sum);
      setRankings(Array.isArray(rank) ? rank : []);
      setSkillGaps(Array.isArray(gap) ? gap : []);
    } catch { toast.error("Failed to load job analytics"); }
    finally { setLoadingOverview(false); setLoadingRankings(false); setLoadingSkillGap(false); }
  };

  useEffect(() => {
    if (summary) {
      setFunnelData([
        { name: "Applied", value: summary.total_applicants },
        { name: "Shortlisted", value: summary.shortlisted_count },
        { name: "Quiz Taken", value: summary.quiz_taken_count },
        { name: "Final Ranked", value: summary.ranked_count },
        { name: "Hired", value: summary.pass_count },
      ]);
    } else {
      setFunnelData([]);
    }
  }, [summary]);

  const handleExport = async (type: "excel" | "pdf") => {
    if (!selectedJobId) return;
    setExporting(type);
    try {
      if (type === "excel") await exportExcel(selectedJobId);
      else await exportPDF(selectedJobId);
      toast.success(`${type.toUpperCase()} exported`);
    } catch { toast.error("Export failed"); }
    finally { setExporting(null); }
  };

  const filteredRankings = useMemo(() => {
    let r = [...rankings];
    if (search.trim()) { const q = search.toLowerCase(); r = r.filter(c => c.name?.toLowerCase().includes(q) || c.email?.toLowerCase().includes(q)); }
    if (tagFilter !== "all") r = r.filter(c => normalizeTag(c.tag) === tagFilter);
    r.sort((a, b) => {
      const av = a[sortKey] ?? 0; const bv = b[sortKey] ?? 0;
      if (typeof av === "string") return sortDir === "asc" ? av.localeCompare(bv) : bv.localeCompare(av);
      return sortDir === "asc" ? av - bv : bv - av;
    });
    return r;
  }, [rankings, search, tagFilter, sortKey, sortDir]);

  const totalPages = Math.ceil(filteredRankings.length / PAGE_SIZE);
  const pageData = filteredRankings.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setSortDir(d => d === "asc" ? "desc" : "asc");
    else { setSortKey(key); setSortDir("asc"); }
  };

  const SortIcon = ({ k }: { k: SortKey }) =>
    sortKey !== k ? <ArrowUpDown className="h-3.5 w-3.5 text-muted-foreground/40" /> :
    sortDir === "asc" ? <ArrowUp className="h-3.5 w-3.5 text-primary" /> : <ArrowDown className="h-3.5 w-3.5 text-primary" />;

  const processedGaps = useMemo(() => {
    const seen = new Set<string>();
    return skillGaps
      .filter(item => { const k = cleanSkillLabel(item.skill).toLowerCase(); if (seen.has(k)) return false; seen.add(k); return true; })
      .filter(item => gapFilter === "all" || (gapFilter === "required" ? item.required : !item.required))
      .sort((a, b) => b.gap_pct - a.gap_pct);
  }, [skillGaps, gapFilter]);

  const chartGaps = processedGaps.slice(0, 12).map(item => ({
    name: cleanSkillLabel(item.skill),
    Match: Math.round(item.candidate_match_pct),
    Gap: Math.round(item.gap_pct),
    required: item.required,
  }));

  const selectedJob = jobs.find(j => j.id === selectedJobId);
  const tabOptions = useMemo(
    () => ([
      { value: "overview" as const, label: "Overview", icon: BarChart2 },
      { value: "rankings" as const, label: "Final Rankings", icon: Trophy, badge: rankings.length > 0 ? rankings.length : undefined },
      { value: "skillgap" as const, label: "Skill Gap", icon: Target },
    ]),
    [rankings.length]
  );

  return (
    <div className="space-y-0 pb-8 max-w-7xl mx-auto">

      {/* Header */}
      <div className="flex items-start justify-between gap-4 mb-6">
        <div>
          <h2 className="text-3xl font-bold tracking-tight">Analytics</h2>
          <p className="text-muted-foreground mt-1">Hiring intelligence across your pipeline.</p>
        </div>
        <div className="flex items-center gap-2 flex-wrap flex-shrink-0">
          {jobs.length > 0 && (
            <Select value={selectedJobId} onValueChange={v => { setSelectedJobId(v); setPage(0); }}>
              <SelectTrigger className="w-[220px]"><SelectValue placeholder="Select a job…" /></SelectTrigger>
              <SelectContent>{jobs.map(j => <SelectItem key={j.id} value={j.id}>{j.title}</SelectItem>)}</SelectContent>
            </Select>
          )}
          <Button variant="outline" size="sm" onClick={() => fetchJobData(selectedJobId)} disabled={!selectedJobId}>
            <RefreshCw className="h-3.5 w-3.5" />
          </Button>
          <Button variant="outline" size="sm" onClick={() => handleExport("excel")} disabled={!selectedJobId || exporting === "excel"}>
            <FileSpreadsheet className="h-3.5 w-3.5 mr-1.5" />{exporting === "excel" ? "…" : "Excel"}
          </Button>
          <Button variant="outline" size="sm" onClick={() => handleExport("pdf")} disabled={!selectedJobId || exporting === "pdf"}>
            <FileText className="h-3.5 w-3.5 mr-1.5" />{exporting === "pdf" ? "…" : "PDF"}
          </Button>
        </div>
      </div>

      <div className="mb-6">
        <SegmentedTabs value={tab} onChange={setTab} options={tabOptions} />
      </div>

      {/* ── OVERVIEW ── */}
      {tab === "overview" && (
        <div className="space-y-6">
          {summary && (
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
              <StatCard icon={Users}        label="Total Applicants" value={summary.total_applicants} color="blue" />
              <StatCard icon={TrendingUp}   label="Shortlisted"      value={summary.shortlisted_count} sub={`${summary.shortlisted_pct}% rate`} color="emerald" />
              <StatCard icon={Award}        label="Strong Fit"        value={summary.strong_count} color="violet" />
              <StatCard icon={CheckCircle2} label="Passed Quiz"      value={summary.pass_count} sub={`${summary.fail_count} failed`} color="amber" />
              <StatCard icon={Target}       label="Avg Resume Score" value={`${(summary.avg_resume_score ?? 0).toFixed(1)}%`} color="primary" />
            </div>
          )}

          <div className="grid lg:grid-cols-2 gap-5">
            {/* Funnel */}
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base flex items-center gap-2"><Layers className="h-4 w-4 text-primary" />Hiring Funnel</CardTitle>
                <CardDescription>Conversion across all pipeline stages</CardDescription>
              </CardHeader>
              <CardContent>
                {!funnelData.some(d => d.value > 0) ? (
                  <div className="flex flex-col items-center justify-center h-[260px] text-muted-foreground">
                    <Users className="h-9 w-9 mb-3 opacity-20" /><p className="text-sm font-medium">No pipeline data yet</p>
                  </div>
                ) : (
                  <ResponsiveContainer width="100%" height={260}>
                    <BarChart data={funnelData} layout="vertical" margin={{ top: 4, right: 60, left: 10, bottom: 4 }}>
                      <XAxis type="number" hide />
                      <YAxis dataKey="name" type="category" width={90} tick={{ fontSize: 12, fontWeight: 500 }} />
                      <Tooltip content={<FunnelTooltip funnelData={funnelData} />} cursor={{ fill: "hsl(var(--muted))" }} />
                      <Bar dataKey="value" radius={[0, 6, 6, 0]} barSize={28}>
                        <LabelList dataKey="value" position="right" style={{ fill: "hsl(var(--foreground))", fontSize: 12, fontWeight: 600 }} />
                        {funnelData.map((_, i) => <Cell key={i} fill={FUNNEL_COLORS[i % FUNNEL_COLORS.length]} />)}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                )}
              </CardContent>
            </Card>

            {/* Distribution */}
            {summary ? (
              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-base flex items-center gap-2"><Users className="h-4 w-4 text-primary" />Candidate Distribution</CardTitle>
                  <CardDescription>Tag breakdown for {selectedJob?.title || "selected job"}</CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  {summary.total_applicants > 0 ? (
                    <>
                      <div className="flex h-5 rounded-full overflow-hidden gap-0.5">
                        {[
                          { label: "Strong",   val: summary.strong_count, color: "bg-emerald-500" },
                          { label: "Medium",   val: summary.medium_count, color: "bg-amber-500" },
                          { label: "Reject",   val: summary.reject_count, color: "bg-red-400" },
                          { label: "Untagged", val: summary.total_applicants - summary.strong_count - summary.medium_count - summary.reject_count, color: "bg-muted" },
                        ].filter(s => s.val > 0).map((s, i) => (
                          <div key={i} title={`${s.label}: ${s.val}`}
                            className={cn("h-full transition-all first:rounded-l-full last:rounded-r-full", s.color)}
                            style={{ width: `${(s.val / summary.total_applicants) * 100}%` }} />
                        ))}
                      </div>
                      <div className="grid grid-cols-2 gap-2">
                        {[
                          { label: "Strong",   val: summary.strong_count,      color: "bg-emerald-500" },
                          { label: "Medium",   val: summary.medium_count,      color: "bg-amber-500" },
                          { label: "Rejected", val: summary.reject_count,      color: "bg-red-400" },
                          { label: "Total",    val: summary.total_applicants,  color: "bg-primary" },
                        ].map(s => (
                          <div key={s.label} className="flex items-center gap-2 p-2 rounded-lg bg-muted/40">
                            <span className={cn("w-2.5 h-2.5 rounded-full flex-shrink-0", s.color)} />
                            <span className="text-xs text-muted-foreground">{s.label}</span>
                            <span className="ml-auto font-bold text-sm tabular-nums">{s.val}</span>
                          </div>
                        ))}
                      </div>
                      {(() => {
                        const quizMetric = summary.avg_quiz_pct ?? summary.avg_quiz_score;
                        const finalMetric = summary.avg_final_score;
                        return (quizMetric != null || finalMetric != null) ? (
                          <div className="border-t pt-3 grid grid-cols-2 gap-3">
                            {quizMetric != null && (
                              <div className="text-center p-3 rounded-xl bg-muted/30">
                                <p className="text-xs text-muted-foreground mb-1">Avg Quiz Score</p>
                                <p className={cn("text-xl font-bold tabular-nums", scoreColor(quizMetric))}>{quizMetric.toFixed(1)}%</p>
                              </div>
                            )}
                            {finalMetric != null && (
                              <div className="text-center p-3 rounded-xl bg-muted/30">
                                <p className="text-xs text-muted-foreground mb-1">Avg Final Score</p>
                                <p className={cn("text-xl font-bold tabular-nums", scoreColor(finalMetric))}>{finalMetric.toFixed(1)}%</p>
                              </div>
                            )}
                          </div>
                        ) : null;
                      })()}
                    </>
                  ) : (
                    <div className="flex flex-col items-center justify-center h-[220px] text-muted-foreground">
                      <Users className="h-9 w-9 mb-3 opacity-20" /><p className="text-sm font-medium">No candidates for this job yet</p>
                    </div>
                  )}
                </CardContent>
              </Card>
            ) : (
              <Card>
                <CardContent className="flex items-center justify-center h-[300px] text-muted-foreground">
                  {loadingOverview
                    ? <div className="animate-spin rounded-full h-7 w-7 border-b-2 border-primary" />
                    : <p className="text-sm">Select a job to see distribution</p>}
                </CardContent>
              </Card>
            )}
          </div>
        </div>
      )}

      {/* ── RANKINGS ── */}
      {tab === "rankings" && (
        <div className="space-y-4">
          <div className="flex items-center gap-3 flex-wrap">
            <div className="relative flex-1 min-w-[200px] max-w-sm">
              <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input placeholder="Search by name or email…" className="pl-8" value={search}
                onChange={e => { setSearch(e.target.value); setPage(0); }} />
            </div>
            <Select value={tagFilter} onValueChange={v => { setTagFilter(v); setPage(0); }}>
              <SelectTrigger className="w-[130px]"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Tags</SelectItem>
                <SelectItem value="strong">Strong</SelectItem>
                <SelectItem value="medium">Medium</SelectItem>
                <SelectItem value="reject">Reject</SelectItem>
              </SelectContent>
            </Select>
            <span className="text-sm text-muted-foreground ml-auto">
              {filteredRankings.length} candidate{filteredRankings.length !== 1 ? "s" : ""}
              {filteredRankings.length !== rankings.length && ` of ${rankings.length}`}
            </span>
          </div>

          {loadingRankings ? (
            <div className="flex items-center justify-center h-48"><div className="animate-spin rounded-full h-7 w-7 border-b-2 border-primary" /></div>
          ) : rankings.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-48 text-muted-foreground border rounded-2xl">
              <Trophy className="h-10 w-10 mb-3 opacity-20" />
              <p className="font-medium text-sm">No rankings yet</p>
              <p className="text-xs mt-1">Process resumes for this job to generate rankings.</p>
            </div>
          ) : (
            <>
              <div className="rounded-2xl border overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-muted/50 border-b">
                    <tr>
                      {[
                        { k: "rank" as SortKey,         label: "Rank",         w: "w-14" },
                        { k: "name" as SortKey,         label: "Candidate",    w: "" },
                        { k: null,                      label: "Tag",          w: "w-24" },
                        { k: "resume_score" as SortKey, label: "Resume Score", w: "w-44" },
                        { k: "quiz_pct" as SortKey,     label: "Quiz Score",   w: "w-44" },
                        { k: "final_score" as SortKey,  label: "Final Score",  w: "w-44" },
                        { k: null,                      label: "Status",       w: "w-24" },
                      ].map((col, i) => (
                        <th key={i} className={cn("text-left px-4 py-3 font-medium text-muted-foreground text-xs", col.w)}>
                          {col.k ? (
                            <button className="flex items-center gap-1 hover:text-foreground transition-colors" onClick={() => toggleSort(col.k as SortKey)}>
                              {col.label} <SortIcon k={col.k as SortKey} />
                            </button>
                          ) : col.label}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {pageData.map((c: any, idx: number) => {
                      const rankNum = c.rank || (page * PAGE_SIZE + idx + 1);
                      return (
                        <tr key={c.candidate_id} className={cn("hover:bg-muted/30 transition-colors", rankNum <= 3 && "bg-primary/[0.02]")}>
                          <td className="px-4 py-3">
                            {rankNum <= 3 ? (
                              <span className="text-xl leading-none">
                                {rankNum === 1 ? '🥇' : rankNum === 2 ? '🥈' : '🥉'}
                              </span>
                            ) : <span className="text-muted-foreground tabular-nums text-xs pl-2">{rankNum}</span>}
                          </td>
                          <td className="px-4 py-3">
                            <div className="flex items-center gap-2.5">
                              <div className="w-7 h-7 rounded-full bg-primary/10 flex items-center justify-center text-xs font-semibold text-primary flex-shrink-0">
                                {(c.name || "?")[0].toUpperCase()}
                              </div>
                              <div className="min-w-0">
                                <p className="font-medium truncate max-w-[160px]">{c.name || "—"}</p>
                                <p className="text-xs text-muted-foreground truncate max-w-[160px]">{c.email || "—"}</p>
                              </div>
                            </div>
                          </td>
                          <td className="px-4 py-3">
                            {c.tag ? (
                              <span className={cn("text-xs px-2 py-0.5 rounded-full font-medium border", TAG_BADGE[normalizeTag(c.tag)] || "bg-muted text-muted-foreground border-border")}>
                                {formatTagLabel(c.tag)}
                              </span>
                            ) : <span className="text-muted-foreground text-xs">—</span>}
                          </td>
                          <td className="px-4 py-3">{c.resume_score != null ? <MiniBar value={c.resume_score} /> : <span className="text-muted-foreground text-xs">—</span>}</td>
                          <td className="px-4 py-3">{c.quiz_pct != null ? <MiniBar value={c.quiz_pct} /> : <span className="text-muted-foreground text-xs">—</span>}</td>
                          <td className="px-4 py-3">{c.final_score != null ? <MiniBar value={c.final_score} /> : <span className="text-muted-foreground text-xs">—</span>}</td>
                          <td className="px-4 py-3">
                            {c.passed === true ? <span className="flex items-center gap-1 text-xs text-emerald-600 font-medium"><CheckCircle2 className="h-3.5 w-3.5"/>Passed</span>
                            : c.passed === false ? <span className="flex items-center gap-1 text-xs text-red-500 font-medium"><AlertCircle className="h-3.5 w-3.5"/>Failed</span>
                            : <span className="text-xs text-muted-foreground">—</span>}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              {totalPages > 1 && (
                <div className="flex items-center justify-between pt-1">
                  <span className="text-sm text-muted-foreground">
                    Page {page + 1} of {totalPages} · {pageData.length} of {filteredRankings.length} shown
                  </span>
                  <div className="flex items-center gap-1">
                    <Button variant="outline" size="sm" onClick={() => setPage(0)} disabled={page === 0}>«</Button>
                    <Button variant="outline" size="sm" onClick={() => setPage(p => Math.max(0, p - 1))} disabled={page === 0}><ChevronLeft className="h-4 w-4" /></Button>
                    {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                      const p = Math.min(Math.max(page - 2, 0) + i, totalPages - 1);
                      return (
                        <Button key={p} variant={p === page ? "default" : "outline"} size="sm" className="w-8 h-8 p-0" onClick={() => setPage(p)}>{p + 1}</Button>
                      );
                    })}
                    <Button variant="outline" size="sm" onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))} disabled={page === totalPages - 1}><ChevronRight className="h-4 w-4" /></Button>
                    <Button variant="outline" size="sm" onClick={() => setPage(totalPages - 1)} disabled={page === totalPages - 1}>»</Button>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* ── SKILL GAP ── */}
      {tab === "skillgap" && (
        <div className="space-y-4">
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1 p-1 rounded-lg border bg-muted/30">
              {(["all", "required", "nice"] as const).map(f => (
                <button key={f} onClick={() => setGapFilter(f)}
                  className={cn("px-3 py-1.5 rounded-md text-xs font-medium transition-colors",
                    gapFilter === f ? "bg-background shadow-sm text-foreground" : "text-muted-foreground hover:text-foreground"
                  )}>
                  {f === "all" ? "All Skills" : f === "required" ? "Must-Have" : "Nice-to-Have"}
                </button>
              ))}
            </div>
            <span className="text-sm text-muted-foreground ml-auto">{processedGaps.length} skill{processedGaps.length !== 1 ? "s" : ""} analysed</span>
          </div>

          {loadingSkillGap ? (
            <div className="flex items-center justify-center h-48"><div className="animate-spin rounded-full h-7 w-7 border-b-2 border-primary" /></div>
          ) : processedGaps.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-48 text-muted-foreground border rounded-2xl">
              <TrendingDown className="h-10 w-10 mb-3 opacity-20" />
              <p className="font-medium text-sm">No skill gap data</p>
              <p className="text-xs mt-1">Upload and process resumes for this job first.</p>
            </div>
          ) : (
            <div className="grid lg:grid-cols-2 gap-5">
              {/* Chart */}
              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-base flex items-center gap-2"><Target className="h-4 w-4 text-primary" />Top Gaps</CardTitle>
                  <CardDescription>Skills with the highest coverage gap (top 12)</CardDescription>
                </CardHeader>
                <CardContent>
                  {chartGaps.every(c => c.Gap === 100) ? (
                    <div className="flex flex-col items-center justify-center py-8 text-amber-500 text-center">
                      <AlertCircle className="h-8 w-8 mb-2" />
                      <p className="font-semibold text-sm">100% gap across all skills</p>
                      <p className="text-xs text-muted-foreground mt-1">No uploaded resumes match this JD yet.</p>
                    </div>
                  ) : (
                    <div style={{ minHeight: Math.max(240, chartGaps.length * 38) }}>
                      <ResponsiveContainer width="100%" height={Math.max(240, chartGaps.length * 38)}>
                        <BarChart data={chartGaps} layout="vertical" margin={{ top: 4, right: 8, left: 8, bottom: 4 }}>
                          <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="hsl(var(--border))" opacity={0.4} />
                          <XAxis type="number" domain={[0, 100]} tickFormatter={v => `${v}%`} tick={{ fontSize: 10 }} />
                          <YAxis dataKey="name" type="category" width={120}
                            tick={({ x, y, payload }) => {
                              const item = chartGaps.find(d => d.name === payload.value);
                              return (
                                <g transform={`translate(${x},${y})`}>
                                  <text x={-4} y={0} dy={4} textAnchor="end" fontSize={11} fill="currentColor">{payload.value}</text>
                                  {item?.required && <circle cx={-124} cy={0} r={3} fill="#f43f5e" />}
                                </g>
                              );
                            }} />
                          <Tooltip content={<GapTooltip />} cursor={{ fill: "hsl(var(--muted))", opacity: 0.4 }} />
                          <Bar dataKey="Match" stackId="a" fill="#10b981" />
                          <Bar dataKey="Gap" stackId="a" fill="#f43f5e" radius={[0, 4, 4, 0]} />
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                  )}
                  <div className="flex items-center gap-4 mt-3 pt-3 border-t text-xs text-muted-foreground">
                    <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-emerald-500 inline-block"/>Match</span>
                    <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-red-500 inline-block"/>Gap</span>
                    <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-red-400 inline-block"/>● = Required</span>
                  </div>
                </CardContent>
              </Card>

              {/* Full skills table */}
              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-base flex items-center gap-2"><BarChart2 className="h-4 w-4 text-primary" />All Skills</CardTitle>
                  <CardDescription>Complete coverage for {selectedJob?.title}</CardDescription>
                </CardHeader>
                <CardContent className="p-0">
                  <div className="max-h-[420px] overflow-y-auto">
                    <table className="w-full text-sm">
                      <thead className="sticky top-0 bg-muted/60 backdrop-blur border-b z-10">
                        <tr>
                          <th className="text-left px-4 py-2.5 font-medium text-muted-foreground text-xs">Skill</th>
                          <th className="text-left px-4 py-2.5 font-medium text-muted-foreground text-xs w-16">Type</th>
                          <th className="text-left px-4 py-2.5 font-medium text-muted-foreground text-xs w-36">Coverage</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y">
                        {processedGaps.map((item, i) => (
                          <tr key={i} className="hover:bg-muted/30 transition-colors">
                            <td className="px-4 py-2.5 font-medium">{item.skill}</td>
                            <td className="px-4 py-2.5">
                              {item.required
                                ? <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full bg-red-100 text-red-600 dark:bg-red-900/30 dark:text-red-400">Must</span>
                                : <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full bg-blue-100 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400">Nice</span>}
                            </td>
                            <td className="px-4 py-2.5"><MiniBar value={item.candidate_match_pct} /></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </CardContent>
              </Card>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
