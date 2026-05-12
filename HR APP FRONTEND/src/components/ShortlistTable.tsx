import { useState, useMemo, useEffect, memo } from 'react';
import { useNavigate } from 'react-router-dom';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

import { Skeleton } from "@/components/ui/skeleton";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { ArrowUpDown, ArrowUp, ArrowDown, Calendar, CheckCircle2, X, XCircle, ChevronRight, ChevronLeft, ChevronsLeft, ChevronsRight, User, SlidersHorizontal } from 'lucide-react';
import { DropdownMenu, DropdownMenuContent, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { toast } from "sonner";
import { draftCandidateEmail, sendCandidateEmail } from "@/services/candidates";
import { ShortlistCandidateSheet } from "@/components/shortlist/ShortlistCandidateSheet";
import { ShortlistEmailDialog } from "@/components/shortlist/ShortlistEmailDialog";

interface Candidate {
  id: string;
  name: string;
  email: string;
  resume_score: number;
  tag: 'Strong' | 'Medium' | 'Reject';
  job_id: string;
  experience_years?: number;
  skills?: string[];
  normalized_skills?: string[];
  created_at?: string;
}

interface Job {
  id: string;
  title: string;
  role?: string;
}

interface ShortlistTableProps {
  candidates: Candidate[];
  jobs?: Job[];
  isLoading?: boolean;
  onRefresh?: () => void;
}

type SortField = 'resume_score' | 'tag' | 'name' | 'created_at';
type SortDirection = 'asc' | 'desc';

// ─── Experience bucket definition ─────────────────────────────────────────────
interface ExpBucket { label: string; min: number; max: number; }

// ─── Date range filter options ────────────────────────────────────────────────
type DateRange = 'all' | 'today' | '7d' | '30d' | '90d';
const DATE_RANGE_OPTIONS: { value: DateRange; label: string }[] = [
  { value: 'all',  label: 'All time'    },
  { value: 'today',label: 'Today'       },
  { value: '7d',   label: 'Last 7 days' },
  { value: '30d',  label: 'Last 30 days'},
  { value: '90d',  label: 'Last 3 months'},
];

function buildExpBuckets(candidates: Candidate[]): ExpBucket[] {
  // Derive buckets dynamically from the actual experience spread in the data.
  // We define fixed breakpoints but only include a bucket if at least one
  // candidate falls inside it — so the filter panel only shows what's relevant.
  const breakpoints: ExpBucket[] = [
    { label: '0 – 1 yr',   min: 0,   max: 1   },
    { label: '1 – 3 yrs',  min: 1,   max: 3   },
    { label: '3 – 5 yrs',  min: 3,   max: 5   },
    { label: '5 – 8 yrs',  min: 5,   max: 8   },
    { label: '8 – 12 yrs', min: 8,   max: 12  },
    { label: '12+ yrs',    min: 12,  max: Infinity },
  ];

  return breakpoints.filter(bucket =>
    candidates.some(c => {
      const yrs = c.experience_years ?? 0;
      return yrs >= bucket.min && yrs < bucket.max;
    })
  );
}

// ─── Derive unique job roles from uploaded candidates ─────────────────────────
function buildRoleOptions(candidates: Candidate[], jobs: Job[]): { id: string; label: string }[] {
  const jobMap = new Map(jobs.map(j => [j.id, j.title || j.role || 'Unknown Role']));
  const seen = new Set<string>();
  const result: { id: string; label: string }[] = [];

  for (const c of candidates) {
    if (!seen.has(c.job_id)) {
      seen.add(c.job_id);
      result.push({ id: c.job_id, label: jobMap.get(c.job_id) ?? 'Unknown Role' });
    }
  }

  return result.sort((a, b) => a.label.localeCompare(b.label));
}

export const ShortlistTable = memo(function ShortlistTable({ candidates, jobs = [], isLoading }: ShortlistTableProps) {
  const navigate = useNavigate();
  const [cutoff, setCutoff] = useState(50);
  const [cutoffTemp, setCutoffTemp] = useState(50);

  useEffect(() => {
    const t = setTimeout(() => setCutoff(cutoffTemp), 200);
    return () => clearTimeout(t);
  }, [cutoffTemp]);

  const [selectedRoles, setSelectedRoles] = useState<Set<string>>(new Set());
  const [selectedExpBuckets, setSelectedExpBuckets] = useState<Set<string>>(new Set());
  const [selectedStatuses, setSelectedStatuses] = useState<Set<string>>(new Set());
  const [dateRange, setDateRange] = useState<DateRange>('all');
  const [sortField, setSortField] = useState<SortField>('resume_score');
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc');
  const [selectedCandidate, setSelectedCandidate] = useState<Candidate | null>(null);
  const [filterOpen, setFilterOpen] = useState(false);

  // ── Pagination state ─────────────────────────────────────────────────────
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);

  // Email modal state
  const [emailModalOpen, setEmailModalOpen] = useState(false);
  const [emailDraft, setEmailDraft] = useState({ subject: '', body: '', candidateId: '', candidateName: '', toEmail: '' });
  const [draftingEmail, setDraftingEmail] = useState(false);
  const [sendingEmail, setSendingEmail] = useState(false);

  // ── Derived filter options (dynamic from uploaded data) ──────────────────
  const roleOptions = useMemo(() => buildRoleOptions(candidates, jobs), [candidates, jobs]);
  const expBuckets  = useMemo(() => buildExpBuckets(candidates), [candidates]);

  // Count candidates per role for the badge next to each option
  const roleCount = useMemo(() => {
    const map = new Map<string, number>();
    candidates.forEach(c => map.set(c.job_id, (map.get(c.job_id) ?? 0) + 1));
    return map;
  }, [candidates]);

  // Count candidates per experience bucket
  const expCount = useMemo(() => {
    const map = new Map<string, number>();
    expBuckets.forEach(b => {
      const count = candidates.filter(c => {
        const yrs = c.experience_years ?? 0;
        return yrs >= b.min && yrs < b.max;
      }).length;
      map.set(b.label, count);
    });
    return map;
  }, [candidates, expBuckets]);

  const statusCount = useMemo(() => {
    const map = new Map<string, number>([
      ['Strong', 0],
      ['Medium', 0],
      ['Reject', 0],
    ]);
    for (const c of candidates) {
      map.set(c.tag, (map.get(c.tag) ?? 0) + 1);
    }
    return map;
  }, [candidates]);

  // ── Toggle helpers ───────────────────────────────────────────────────────
  const toggleRole = (id: string) =>
    setSelectedRoles(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  const toggleExpBucket = (label: string) =>
    setSelectedExpBuckets(prev => {
      const next = new Set(prev);
      next.has(label) ? next.delete(label) : next.add(label);
      return next;
    });

  const toggleStatus = (status: string) =>
    setSelectedStatuses(prev => {
      const next = new Set(prev);
      next.has(status) ? next.delete(status) : next.add(status);
      return next;
    });

  const activeFilterCount =
    (selectedRoles.size > 0 ? 1 : 0) +
    (selectedExpBuckets.size > 0 ? 1 : 0) +
    (selectedStatuses.size > 0 ? 1 : 0) +
    (dateRange !== 'all' ? 1 : 0);

  const clearAllFilters = () => {
    setSelectedRoles(new Set());
    setSelectedExpBuckets(new Set());
    setSelectedStatuses(new Set());
    setDateRange('all');
    setCutoffTemp(50);
    setCutoff(50);
  };

  // ── Sorting + filtering ──────────────────────────────────────────────────
  const handleSort = (field: SortField) => {
    if (sortField === field) setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc');
    else { setSortField(field); setSortDirection('desc'); }
  };

  const filteredAndSorted = useMemo(() => {
    // Pre-compute cutoff date once
    const now = new Date();
    const cutoffDate = (() => {
      if (dateRange === 'today') { const d = new Date(now); d.setHours(0,0,0,0); return d; }
      if (dateRange === '7d')   return new Date(now.getTime() - 7  * 86400000);
      if (dateRange === '30d')  return new Date(now.getTime() - 30 * 86400000);
      if (dateRange === '90d')  return new Date(now.getTime() - 90 * 86400000);
      return null;
    })();

    return [...candidates]
      .filter(c => {
        // Cutoff score
        if (c.resume_score < cutoff) return false;

        // Role filter
        if (selectedRoles.size > 0 && !selectedRoles.has(c.job_id)) return false;

        // Experience bucket filter
        if (selectedExpBuckets.size > 0) {
          const yrs = c.experience_years ?? 0;
          const inAny = expBuckets.some(b =>
            selectedExpBuckets.has(b.label) && yrs >= b.min && yrs < b.max
          );
          if (!inAny) return false;
        }

        // Status filter
        if (selectedStatuses.size > 0 && !selectedStatuses.has(c.tag)) return false;

        // Date range filter
        if (cutoffDate && c.created_at) {
          const applied = new Date(c.created_at);
          if (applied < cutoffDate) return false;
        }

        return true;
      })
      .sort((a, b) => {
        const mod = sortDirection === 'asc' ? 1 : -1;
        if (sortField === 'resume_score') {
          const diff = a.resume_score - b.resume_score;
          if (diff !== 0) return diff * mod;
          return (a.id || '').localeCompare(b.id || '') * mod;
        }
        if (sortField === 'tag')          return (a.tag || '').localeCompare(b.tag || '') * mod;
        if (sortField === 'name')         return (a.name || '').localeCompare(b.name || '') * mod;
        if (sortField === 'created_at') {
          const da = a.created_at ? new Date(a.created_at).getTime() : 0;
          const db = b.created_at ? new Date(b.created_at).getTime() : 0;
          return (da - db) * mod;
        }
        return 0;
      });
  }, [candidates, cutoff, selectedRoles, selectedExpBuckets, expBuckets, selectedStatuses, dateRange, sortField, sortDirection]);

  // ── Reset to page 1 whenever filter/sort/data changes ───────────────────
  useEffect(() => { setCurrentPage(1); },
    [cutoff, selectedRoles, selectedExpBuckets, selectedStatuses, dateRange, sortField, sortDirection, candidates.length]);

  // ── Pagination derived values ────────────────────────────────────────────
  const totalPages   = Math.max(1, Math.ceil(filteredAndSorted.length / pageSize));
  const clampedPage  = Math.min(currentPage, totalPages);
  const pageStart    = (clampedPage - 1) * pageSize;                          // 0-based index
  const pageEnd      = Math.min(pageStart + pageSize, filteredAndSorted.length);
  const paginated    = filteredAndSorted.slice(pageStart, pageEnd);

  /** Build the page-number array shown in the nav bar, with ellipsis gaps. */
  function buildPageNumbers(total: number, current: number): (number | '…')[] {
    if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);
    const pages: (number | '…')[] = [1];
    if (current > 3)          pages.push('…');
    for (let p = Math.max(2, current - 1); p <= Math.min(total - 1, current + 1); p++) pages.push(p);
    if (current < total - 2)  pages.push('…');
    pages.push(total);
    return pages;
  }
  const pageNumbers = buildPageNumbers(totalPages, clampedPage);

  // ── Email helpers ────────────────────────────────────────────────────────
  const handleDraftEmail = async (c: Candidate, type: 'invite' | 'reject' | 'offer') => {
    setDraftingEmail(true);
    toast.info(`AI is drafting ${type} email...`);
    try {
      const data = await draftCandidateEmail(c.id, type);
      setEmailDraft({ subject: data.subject || '', body: data.body || '', candidateId: c.id, candidateName: c.name, toEmail: c.email || 'No email' });
      setEmailModalOpen(true);
    } catch {
      toast.error('Failed to draft email. Check backend connection.');
    } finally {
      setDraftingEmail(false);
    }
  };

  const handleSendDraftedEmail = async () => {
    setSendingEmail(true);
    try {
      await sendCandidateEmail(emailDraft.candidateId, emailDraft.subject, emailDraft.body);
      toast.success('Email successfully dispatched!');
      setEmailModalOpen(false);
    } catch {
      toast.error('Failed to send email');
    } finally {
      setSendingEmail(false);
    }
  };

  const SortIcon = ({ field }: { field: SortField }) => {
    if (sortField !== field) return <ArrowUpDown className="ml-2 h-3 w-3 text-muted-foreground/50" />;
    return sortDirection === 'asc' ? <ArrowUp className="ml-2 h-3 w-3" /> : <ArrowDown className="ml-2 h-3 w-3" />;
  };

  // SortIcon helper
  return (
    <div className="flex flex-col h-full min-h-0">

      {/* ── Candidate table (full width) ── */}
      <div className="flex-1 flex flex-col min-h-0 border bg-card rounded-3xl overflow-hidden shadow-sm">

        {/* Inline filter toolbar */}
        <div className="flex items-center gap-2 px-4 py-2.5 border-b bg-muted/10 shrink-0 flex-wrap">

          {/* Filter button — uses DropdownMenu so it renders in a portal and is never clipped by overflow:hidden */}
          <DropdownMenu open={filterOpen} onOpenChange={setFilterOpen}>
            <DropdownMenuTrigger asChild>
              <button
                className={`flex items-center gap-1.5 h-8 px-3 rounded-lg border text-xs font-medium transition-colors ${
                  filterOpen
                    ? 'border-primary bg-primary/5 text-primary'
                    : activeFilterCount > 0
                      ? 'border-primary/40 bg-primary/5 text-primary'
                      : 'border-border/60 text-muted-foreground hover:text-foreground hover:bg-muted'
                }`}
              >
                <SlidersHorizontal className="h-3.5 w-3.5" />
                Filters
                {activeFilterCount > 0 && (
                  <span className="h-4 min-w-[16px] px-1 rounded-full bg-primary text-primary-foreground text-[10px] font-bold flex items-center justify-center">
                    {activeFilterCount}
                  </span>
                )}
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              align="start"
              sideOffset={6}
              className="w-72 p-0 overflow-hidden"
              onCloseAutoFocus={e => e.preventDefault()}
            >
              <div className="flex items-center justify-between px-4 py-3 border-b bg-muted/20">
                <span className="text-sm font-semibold">Filters</span>
                {activeFilterCount > 0 && (
                  <button onClick={clearAllFilters} className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1">
                    <X className="h-3 w-3" /> Clear all
                  </button>
                )}
              </div>
              <div className="px-4 py-3 space-y-4 max-h-[420px] overflow-y-auto">
                <div className="space-y-2">
                  <div className="flex justify-between items-center">
                    <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Cutoff Score</span>
                    <span className="text-xs font-bold text-primary bg-primary/10 px-2 py-0.5 rounded-full">{cutoffTemp}%</span>
                  </div>
                  <input type="range" min="0" max="100" value={cutoffTemp} onChange={e => setCutoffTemp(Number(e.target.value))} className="w-full h-1.5 bg-muted rounded-lg appearance-none cursor-pointer accent-primary" />
                  <div className="flex justify-between text-[10px] text-muted-foreground"><span>0%</span><span>100%</span></div>
                </div>
                <div className="h-px bg-border" />
                <div className="space-y-1.5">
                  <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Status</span>
                  {(['Strong', 'Medium', 'Reject'] as const).map(status => {
                    const active = selectedStatuses.has(status);
                    const count = statusCount.get(status) ?? 0;
                    const cls: Record<string, string> = {
                      Strong: active ? 'bg-emerald-600 text-white border-emerald-600' : 'bg-background border-border/60 text-foreground hover:bg-muted',
                      Medium: active ? 'bg-amber-500 text-white border-amber-500' : 'bg-background border-border/60 text-foreground hover:bg-muted',
                      Reject: active ? 'bg-red-500 text-white border-red-500' : 'bg-background border-border/60 text-foreground hover:bg-muted',
                    };
                    return <button key={status} onClick={() => toggleStatus(status)} className={`w-full flex items-center justify-between px-3 py-2 rounded-lg text-xs font-medium border transition-all ${cls[status]}`}><span>{status}</span><span className={`px-1.5 py-0.5 rounded-full text-[10px] font-bold ${active ? 'bg-white/25' : 'bg-muted text-muted-foreground'}`}>{count}</span></button>;
                  })}
                </div>
                {roleOptions.length > 0 && <><div className="h-px bg-border" /><div className="space-y-1.5"><span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Job Role</span>{roleOptions.map(role => { const active = selectedRoles.has(role.id); return <button key={role.id} onClick={() => toggleRole(role.id)} className={`w-full flex items-center justify-between px-3 py-2 rounded-lg text-xs font-medium border transition-all ${active ? 'bg-primary text-primary-foreground border-primary' : 'bg-background border-border/60 text-foreground hover:bg-muted'}`}><span className="truncate">{role.label}</span><span className={`ml-2 px-1.5 py-0.5 rounded-full text-[10px] font-bold shrink-0 ${active ? 'bg-white/25' : 'bg-muted text-muted-foreground'}`}>{roleCount.get(role.id) ?? 0}</span></button>; })}</div></>}
                {expBuckets.length > 0 && <><div className="h-px bg-border" /><div className="space-y-1.5"><span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Experience</span>{expBuckets.map(bucket => { const active = selectedExpBuckets.has(bucket.label); const count = expCount.get(bucket.label) ?? 0; return <button key={bucket.label} onClick={() => toggleExpBucket(bucket.label)} className={`w-full flex items-center justify-between px-3 py-2 rounded-lg text-xs font-medium border transition-all ${active ? 'bg-primary text-primary-foreground border-primary' : 'bg-background border-border/60 text-foreground hover:bg-muted'}`}><span>{bucket.label}</span><span className={`px-1.5 py-0.5 rounded-full text-[10px] font-bold ${active ? 'bg-white/25' : 'bg-muted text-muted-foreground'}`}>{count}</span></button>; })}</div></>}
                <div className="h-px bg-border" />
                <div className="space-y-1.5">
                  <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Applied date</span>
                  <div className="grid grid-cols-2 gap-1.5">
                    {DATE_RANGE_OPTIONS.map(opt => { const active = dateRange === opt.value; return <button key={opt.value} onClick={() => setDateRange(opt.value)} className={`flex items-center justify-center px-2 py-1.5 rounded-lg text-[11px] font-medium border transition-all ${active ? 'bg-primary text-primary-foreground border-primary' : 'bg-background border-border/60 text-muted-foreground hover:text-foreground hover:bg-muted'}`}>{active && <CheckCircle2 className="h-3 w-3 mr-1 shrink-0" />}{opt.label}</button>; })}
                  </div>
                </div>
              </div>
              <div className="px-4 pb-3 pt-2 border-t bg-muted/10">
                <Button className="w-full h-8 text-sm" onClick={() => setFilterOpen(false)}>
                  Show {filteredAndSorted.length} result{filteredAndSorted.length !== 1 ? 's' : ''}
                </Button>
              </div>
            </DropdownMenuContent>
          </DropdownMenu>

          {/* Active filter chips */}
          {cutoff !== 50 && <span className="h-7 px-2 rounded-md bg-primary/10 text-primary text-[11px] font-medium flex items-center gap-1">Score ≥{cutoff}%<button onClick={() => { setCutoffTemp(50); setCutoff(50); }} className="ml-0.5"><X className="h-3 w-3" /></button></span>}
          {selectedStatuses.size > 0 && <span className="h-7 px-2 rounded-md bg-primary/10 text-primary text-[11px] font-medium flex items-center gap-1">Status: {[...selectedStatuses].join(', ')}<button onClick={() => setSelectedStatuses(new Set())} className="ml-0.5"><X className="h-3 w-3" /></button></span>}
          {activeFilterCount > 0 && <button onClick={clearAllFilters} className="text-[11px] text-muted-foreground hover:text-foreground underline underline-offset-2">Clear all</button>}

          <span className="ml-auto text-xs text-muted-foreground shrink-0">
            {activeFilterCount > 0
              ? <><span className="font-semibold text-foreground">{filteredAndSorted.length}</span>{' of '}<span className="font-semibold text-foreground">{candidates.length}</span>{' match'}</>
              : <><span className="font-semibold text-foreground">{candidates.length}</span>{' candidates'}</>
            }
          </span>
        </div>

        <div className="flex-1 overflow-y-auto">
        <Table>
          <TableHeader className="bg-muted/30 hover:bg-muted/30 sticky top-0 z-10">
            <TableRow className="border-b-black/[0.04]">
              <TableHead className="cursor-pointer py-4 w-[35%]" onClick={() => handleSort('name')}>
                <div className="flex items-center text-xs font-semibold uppercase tracking-wider">Candidate <SortIcon field="name" /></div>
              </TableHead>
              <TableHead className="cursor-pointer py-4 w-[12%]" onClick={() => handleSort('resume_score')}>
                <div className="flex items-center text-xs font-semibold uppercase tracking-wider">Match <SortIcon field="resume_score" /></div>
              </TableHead>
              <TableHead className="cursor-pointer py-4 w-[12%]" onClick={() => handleSort('tag')}>
                <div className="flex items-center text-xs font-semibold uppercase tracking-wider">Status <SortIcon field="tag" /></div>
              </TableHead>
              <TableHead className="cursor-pointer py-4 w-[16%]" onClick={() => handleSort('created_at')}>
                <div className="flex items-center text-xs font-semibold uppercase tracking-wider">Applied <SortIcon field="created_at" /></div>
              </TableHead>
              <TableHead className="py-4 w-[25%] text-xs font-semibold uppercase tracking-wider">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              Array.from({ length: 5 }).map((_, i) => (
                <TableRow key={i} className="border-b-black/[0.04]">
                  <TableCell><div className="flex items-center gap-3"><Skeleton className="h-10 w-10 rounded-full shrink-0" /><div className="space-y-2 min-w-0"><Skeleton className="h-4 w-32" /><Skeleton className="h-3 w-24" /></div></div></TableCell>
                  <TableCell><Skeleton className="h-6 w-16 rounded-full" /></TableCell>
                  <TableCell><Skeleton className="h-6 w-20 rounded-full" /></TableCell>
                  <TableCell><Skeleton className="h-4 w-20" /></TableCell>
                  <TableCell className="text-right"><Skeleton className="h-8 w-24 ml-auto rounded-full" /></TableCell>
                </TableRow>
              ))
            ) : filteredAndSorted.length === 0 ? (
              <TableRow>
                <TableCell colSpan={5} className="h-32 text-center text-muted-foreground">
                  No candidates meet the current filter criteria.
                </TableCell>
              </TableRow>
            ) : (
              paginated.map(c => (
                <TableRow
                  key={c.id}
                  className="group cursor-pointer hover:bg-muted/30 transition-all border-b-black/[0.04]"
                  onClick={() => setSelectedCandidate(c)}
                >
                  <TableCell className="max-w-0">
                    <div className="flex items-center gap-3 min-w-0">
                      <Avatar className="h-10 w-10 border shadow-sm shrink-0">
                        <AvatarFallback className="bg-background text-foreground font-medium">
                          {(c.name || '??').substring(0, 2).toUpperCase()}
                        </AvatarFallback>
                      </Avatar>
                      <div className="min-w-0">
                        <div className="font-semibold truncate">{c.name || 'Unknown'}</div>
                        <div className="text-xs text-muted-foreground truncate">{c.email}</div>
                      </div>
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="font-bold text-sm bg-primary/5 text-primary w-fit px-2.5 py-1 rounded-md">
                      {c.resume_score}%
                    </div>
                  </TableCell>
                  <TableCell>
                    <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-semibold ${
                      c.tag === 'Strong'
                        ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400'
                        : c.tag === 'Medium'
                        ? 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400'
                        : 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400'
                    }`}>
                      {c.tag}
                    </span>
                  </TableCell>
                  <TableCell>
                    <div className="text-xs text-muted-foreground">
                      {c.created_at
                        ? new Date(c.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
                        : <span className="italic opacity-50">—</span>
                      }
                    </div>
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex items-center justify-end gap-1">
                      <Button
                        size="icon"
                        variant="outline"
                        className="h-8 w-8 rounded-full border-border/60 bg-background shadow-sm hover:bg-accent hover:border-border"
                        disabled={draftingEmail}
                        onClick={e => { e.stopPropagation(); handleDraftEmail(c, 'invite'); }}
                        title="Schedule Interview"
                      >
                        <Calendar className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        size="icon"
                        variant="outline"
                        className="h-8 w-8 rounded-full border-red-200 bg-background text-red-500 shadow-sm hover:bg-red-50 hover:border-red-300 dark:border-red-900 dark:hover:bg-red-950/30"
                        disabled={draftingEmail}
                        onClick={e => { e.stopPropagation(); handleDraftEmail(c, 'reject'); }}
                        title="Reject Candidate"
                      >
                        <XCircle className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        size="icon"
                        variant="outline"
                        className="h-8 w-8 rounded-full border-border/60 bg-background shadow-sm hover:bg-accent hover:border-border"
                        onClick={e => { e.stopPropagation(); navigate(`/candidates/${c.id}`); }}
                        title="View Full Profile"
                      >
                        <User className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
        </div>{/* end overflow-y-auto scroll wrapper */}

        {/* ── Pagination bar ─────────────────────────────────────────────── */}
        {!isLoading && filteredAndSorted.length > 0 && (
          <div className="flex items-center justify-between gap-4 px-4 py-3 border-t bg-muted/20 shrink-0">
            {/* Left: result range info */}
            <p className="text-xs text-muted-foreground whitespace-nowrap shrink-0">
              Showing{' '}
              <span className="font-semibold text-foreground">{pageStart + 1}–{pageEnd}</span>
              {' '}of{' '}
              <span className="font-semibold text-foreground">{filteredAndSorted.length}</span>
              {filteredAndSorted.length !== candidates.length && (
                <span className="text-muted-foreground"> (filtered from {candidates.length})</span>
              )}
            </p>

            {/* Centre: page nav */}
            <div className="flex items-center gap-1">
              <Button
                variant="ghost" size="icon"
                className="h-7 w-7 rounded-lg"
                disabled={clampedPage === 1}
                onClick={() => setCurrentPage(1)}
                title="First page"
              >
                <ChevronsLeft className="h-3.5 w-3.5" />
              </Button>
              <Button
                variant="ghost" size="icon"
                className="h-7 w-7 rounded-lg"
                disabled={clampedPage === 1}
                onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                title="Previous page"
              >
                <ChevronLeft className="h-3.5 w-3.5" />
              </Button>

              {pageNumbers.map((p, i) =>
                p === '…' ? (
                  <span key={`ellipsis-${i}`} className="px-1 text-xs text-muted-foreground select-none">…</span>
                ) : (
                  <Button
                    key={p}
                    variant={p === clampedPage ? 'default' : 'ghost'}
                    size="icon"
                    className={`h-7 w-7 rounded-lg text-xs font-medium ${p === clampedPage ? 'shadow-sm' : ''}`}
                    onClick={() => setCurrentPage(p as number)}
                  >
                    {p}
                  </Button>
                )
              )}

              <Button
                variant="ghost" size="icon"
                className="h-7 w-7 rounded-lg"
                disabled={clampedPage === totalPages}
                onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
                title="Next page"
              >
                <ChevronRight className="h-3.5 w-3.5" />
              </Button>
              <Button
                variant="ghost" size="icon"
                className="h-7 w-7 rounded-lg"
                disabled={clampedPage === totalPages}
                onClick={() => setCurrentPage(totalPages)}
                title="Last page"
              >
                <ChevronsRight className="h-3.5 w-3.5" />
              </Button>
            </div>

            {/* Right: page size selector — native button group avoids Radix portal clipping */}
            <div className="flex items-center gap-2 shrink-0">
              <span className="text-xs text-muted-foreground">Rows</span>
              <div className="flex items-center border border-border/60 rounded-lg overflow-hidden">
                {[25, 50, 100, 200].map(n => (
                  <button
                    key={n}
                    onClick={() => { setPageSize(n); setCurrentPage(1); }}
                    className={`px-2.5 py-1 text-xs font-medium transition-colors border-r border-border/40 last:border-r-0 ${
                      pageSize === n
                        ? 'bg-primary text-primary-foreground'
                        : 'bg-background text-muted-foreground hover:bg-muted hover:text-foreground'
                    }`}
                  >
                    {n}
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>

      <ShortlistCandidateSheet
        selectedCandidate={selectedCandidate}
        onClose={() => setSelectedCandidate(null)}
        onViewProfile={(candidateId) => {
          setSelectedCandidate(null);
          navigate(`/candidates/${candidateId}`);
        }}
        onDraftEmail={handleDraftEmail}
        draftingEmail={draftingEmail}
      />

      <ShortlistEmailDialog
        open={emailModalOpen}
        onOpenChange={setEmailModalOpen}
        emailDraft={emailDraft}
        setEmailDraft={setEmailDraft}
        sendingEmail={sendingEmail}
        onSend={handleSendDraftedEmail}
      />
    </div>
  );
});
