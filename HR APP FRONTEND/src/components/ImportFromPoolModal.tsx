import React, { useState, useEffect, useMemo } from 'react';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";

import { getPoolMatches, importFromPool } from "@/services/candidates";
import { toast } from "sonner";
import { Layers, Search, CheckSquare, Square, Users, Briefcase, TrendingUp, Filter } from "lucide-react";
import { cn } from "@/lib/utils";

interface PoolCandidate {
  id: string;
  name: string | null;
  email: string | null;
  skills: string[];
  normalized_skills: string[];
  experience_years: number;
  computed_resume_score: number;
  computed_skill_match_pct: number;
  computed_experience_match_pct: number;
  computed_tag: string | null;
}

interface ImportFromPoolModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  jobId: string;
  jobTitle: string;
  jobMustHaveSkills?: string[];
  onImportComplete?: () => void;
}

const TAG_STYLES: Record<string, string> = {
  Strong: 'bg-emerald-100 text-emerald-700 border-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-400',
  Medium: 'bg-amber-100 text-amber-700 border-amber-200 dark:bg-amber-950/40 dark:text-amber-400',
  Reject: 'bg-red-100 text-red-700 border-red-200 dark:bg-red-950/40 dark:text-red-400',
};

const SCORE_COLOR = (score: number) =>
  score >= 70 ? 'text-emerald-600' :
  score >= 45 ? 'text-amber-600' :
  'text-red-500';

const SCORE_BAR_COLOR = (score: number) =>
  score >= 70 ? 'bg-emerald-500' :
  score >= 45 ? 'bg-amber-500' :
  'bg-red-400';

export function ImportFromPoolModal({
  open,
  onOpenChange,
  jobId,
  jobTitle,
  jobMustHaveSkills = [],
  onImportComplete,
}: ImportFromPoolModalProps) {
  const [loading, setLoading] = useState(false);
  const [importing, setImporting] = useState(false);
  const [candidates, setCandidates] = useState<PoolCandidate[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState('');
  const [minScore, setMinScore] = useState(0);

  // Load pool matches when modal opens
  useEffect(() => {
    if (!open) return;
    setLoading(true);
    setSelected(new Set());
    setSearch('');

    getPoolMatches(jobId, 0)
      .then(data => setCandidates(data))
      .catch(() => toast.error('Failed to load pool candidates'))
      .finally(() => setLoading(false));
  }, [open, jobId]);

  // Filtered + searched candidates
  const filtered = useMemo(() => {
    return candidates.filter(c => {
      if (c.computed_resume_score < minScore) return false;
      if (!search.trim()) return true;
      const q = search.toLowerCase();
      return (
        (c.name?.toLowerCase().includes(q) ?? false) ||
        (c.email?.toLowerCase().includes(q) ?? false) ||
        c.skills.some(s => s.toLowerCase().includes(q))
      );
    });
  }, [candidates, minScore, search]);

  const toggleSelect = (id: string) => {
    setSelected(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (selected.size === filtered.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(filtered.map(c => c.id)));
    }
  };

  const handleImport = async () => {
    if (selected.size === 0) return;
    setImporting(true);
    try {
      const res = await importFromPool(jobId, Array.from(selected));
      toast.success(
        `Imported ${res.imported} candidate${res.imported !== 1 ? 's' : ''} into "${jobTitle}"`,
        res.skipped > 0 ? { description: `${res.skipped} already assigned elsewhere were skipped` } : undefined
      );
      onImportComplete?.();
      onOpenChange(false);
    } catch {
      toast.error('Import failed. Please try again.');
    } finally {
      setImporting(false);
    }
  };

  // Stats bar
  const strongCount  = candidates.filter(c => c.computed_tag === 'Strong').length;
  const mediumCount  = candidates.filter(c => c.computed_tag === 'Medium').length;
  const allSelected  = filtered.length > 0 && selected.size === filtered.length;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[720px] max-h-[90vh] flex flex-col p-0 gap-0">

        {/* ── Header ── */}
        <div className="px-6 pt-6 pb-4 border-b bg-card">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-lg">
              <div className="p-1.5 rounded-lg bg-emerald-100 dark:bg-emerald-950/50">
                <Layers className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />
              </div>
              Import from General Pool
            </DialogTitle>
            <DialogDescription className="text-sm mt-1">
              These are unassigned resumes from the pool, scored against{' '}
              <span className="font-semibold text-foreground">"{jobTitle}"</span>.
              Select candidates to assign and score them to this job.
            </DialogDescription>
          </DialogHeader>

          {/* Stats */}
          {!loading && candidates.length > 0 && (
            <div className="flex items-center gap-4 mt-3 text-xs">
              <span className="flex items-center gap-1.5 text-muted-foreground">
                <Users className="h-3.5 w-3.5" />{candidates.length} in pool
              </span>
              <span className="flex items-center gap-1.5 text-emerald-600 font-medium">
                <TrendingUp className="h-3.5 w-3.5" />{strongCount} Strong match
              </span>
              <span className="flex items-center gap-1.5 text-amber-600 font-medium">
                <Briefcase className="h-3.5 w-3.5" />{mediumCount} Medium match
              </span>
            </div>
          )}
        </div>

        {/* ── Filter bar ── */}
        <div className="px-6 py-3 border-b bg-muted/20 flex items-center gap-3 flex-wrap">
          <div className="relative flex-1 min-w-[180px]">
            <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
            <Input
              placeholder="Search by name, email, skill…"
              className="pl-8 h-8 text-sm"
              value={search}
              onChange={e => setSearch(e.target.value)}
            />
          </div>
          <div className="flex items-center gap-2 text-sm text-muted-foreground shrink-0">
            <Filter className="h-3.5 w-3.5" />
            <span>Min match:</span>
            <input
              type="range" min={0} max={80} step={5} value={minScore}
              onChange={e => setMinScore(Number(e.target.value))}
              className="w-20 accent-emerald-600"
            />
            <span className="font-mono w-8 text-foreground font-medium">{minScore}%</span>
          </div>

          {filtered.length > 0 && (
            <button
              onClick={toggleSelectAll}
              className="flex items-center gap-1.5 text-xs font-medium text-primary hover:text-primary/80 transition-colors shrink-0"
            >
              {allSelected
                ? <CheckSquare className="h-3.5 w-3.5" />
                : <Square className="h-3.5 w-3.5" />
              }
              {allSelected ? 'Deselect all' : `Select all (${filtered.length})`}
            </button>
          )}
        </div>

        {/* ── Candidate list ── */}
        <div className="flex-1 overflow-y-auto min-h-0">
          {loading ? (
            <div className="p-6 space-y-3">
              {Array.from({ length: 4 }).map((_, i) => (
                <div key={i} className="flex items-center gap-3 p-3 rounded-xl border">
                  <Skeleton className="h-5 w-5 rounded" />
                  <div className="flex-1 space-y-2">
                    <Skeleton className="h-4 w-40" />
                    <Skeleton className="h-3 w-60" />
                  </div>
                  <Skeleton className="h-6 w-12 rounded-full" />
                  <Skeleton className="h-4 w-16 rounded" />
                </div>
              ))}
            </div>
          ) : filtered.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-48 text-center px-6">
              <Layers className="h-10 w-10 text-muted-foreground/40 mb-3" />
              {candidates.length === 0 ? (
                <>
                  <p className="font-medium">No resumes in the pool</p>
                  <p className="text-sm text-muted-foreground mt-1">
                    Upload resumes via "Bulk Upload → General Pool" first.
                  </p>
                </>
              ) : (
                <>
                  <p className="font-medium">No matches found</p>
                  <p className="text-sm text-muted-foreground mt-1">
                    Try lowering the minimum match score or clearing the search.
                  </p>
                </>
              )}
            </div>
          ) : (
            <div className="p-4 space-y-2">
              {filtered.map(c => {
                const isSelected = selected.has(c.id);


                return (
                  <div
                    key={c.id}
                    onClick={() => toggleSelect(c.id)}
                    className={cn(
                      'flex items-start gap-3 p-3.5 rounded-xl border cursor-pointer transition-all duration-100',
                      isSelected
                        ? 'border-emerald-400 bg-emerald-50/60 dark:bg-emerald-950/20 dark:border-emerald-700 shadow-sm'
                        : 'border-border hover:border-muted-foreground/40 hover:bg-muted/30'
                    )}
                  >
                    {/* Checkbox */}
                    <div className={cn(
                      'mt-0.5 h-4.5 w-4.5 rounded border-2 flex items-center justify-center shrink-0 transition-colors',
                      isSelected
                        ? 'border-emerald-500 bg-emerald-500'
                        : 'border-muted-foreground/40'
                    )}>
                      {isSelected && (
                        <svg className="h-2.5 w-2.5 text-white" viewBox="0 0 10 8" fill="none">
                          <path d="M1 4l3 3 5-6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
                        </svg>
                      )}
                    </div>

                    {/* Candidate info */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-semibold text-sm">{c.name || 'Unknown'}</span>
                        {c.computed_tag && (
                          <span className={cn(
                            'text-xs px-2 py-0.5 rounded-full border font-medium',
                            TAG_STYLES[c.computed_tag] ?? 'bg-secondary text-secondary-foreground'
                          )}>
                            {c.computed_tag}
                          </span>
                        )}
                        <span className="text-xs text-muted-foreground">{c.experience_years} yrs exp</span>
                      </div>

                      <div className="text-xs text-muted-foreground mt-0.5 mb-2">{c.email || '—'}</div>

                      {/* Skill match bar */}
                      <div className="flex items-center gap-2 mb-2">
                        <div className="flex-1 h-1.5 bg-muted rounded-full overflow-hidden">
                          <div
                            className={cn('h-full rounded-full transition-all', SCORE_BAR_COLOR(c.computed_skill_match_pct))}
                            style={{ width: `${c.computed_skill_match_pct}%` }}
                          />
                        </div>
                        <span className={cn('text-[10px] font-mono font-bold w-10 text-right', SCORE_COLOR(c.computed_skill_match_pct))}>
                          {c.computed_skill_match_pct.toFixed(0)}% sk
                        </span>
                      </div>

                      {/* Skills — highlight JD must-haves */}
                      {c.skills.length > 0 && (
                        <div className="flex flex-wrap gap-1">
                          {c.skills.slice(0, 8).map(skill => {
                            const isMatch = jobMustHaveSkills.some(
                              s => skill.toLowerCase().includes(s.toLowerCase()) ||
                                   s.toLowerCase().includes(skill.toLowerCase())
                            );
                            return (
                              <span
                                key={skill}
                                className={cn(
                                  'text-[10px] px-1.5 py-0.5 rounded border',
                                  isMatch
                                    ? 'bg-emerald-100 text-emerald-700 border-emerald-300 font-medium dark:bg-emerald-950/40 dark:text-emerald-400'
                                    : 'bg-muted text-muted-foreground border-transparent'
                                )}
                              >
                                {skill}
                              </span>
                            );
                          })}
                          {c.skills.length > 8 && (
                            <span className="text-[10px] text-muted-foreground px-1">+{c.skills.length - 8} more</span>
                          )}
                        </div>
                      )}
                    </div>

                    {/* Score badge */}
                    <div className="shrink-0 text-right">
                      <div className={cn('text-lg font-bold font-mono', SCORE_COLOR(c.computed_resume_score))}>
                        {c.computed_resume_score.toFixed(0)}%
                      </div>
                      <div className="text-[10px] text-muted-foreground">match</div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* ── Footer ── */}
        <div className="px-6 py-4 border-t bg-card flex items-center justify-between gap-4">
          <div className="text-sm text-muted-foreground">
            {selected.size > 0 ? (
              <span className="text-emerald-700 dark:text-emerald-400 font-medium">
                {selected.size} candidate{selected.size !== 1 ? 's' : ''} selected
              </span>
            ) : (
              <span>Select candidates to import</span>
            )}
          </div>

          <div className="flex gap-2">
            <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button
              disabled={selected.size === 0 || importing}
              onClick={handleImport}
              className="bg-emerald-600 hover:bg-emerald-700 text-white min-w-[120px]"
            >
              {importing
                ? <><div className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent mr-2" />Importing…</>
                : <><Layers className="h-4 w-4 mr-2" />Import {selected.size > 0 ? selected.size : ''}</>
              }
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
