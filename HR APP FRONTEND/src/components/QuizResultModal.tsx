import * as React from 'react';
import { useState } from 'react';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { toast } from 'sonner';
import {
  CheckCircle2, XCircle, AlertTriangle, BookOpen,
  BarChart3, Brain, Loader2, Eye, Shield,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import {
  getCandidateQuizResult,
  type CandidateQuizResult,
  type QuizSkillBreakdown,
} from '@/services/candidates';

// ── Helpers ───────────────────────────────────────────────────────────────────

function pctColor(pct: number) {
  if (pct >= 75) return 'text-emerald-600 dark:text-emerald-400';
  if (pct >= 50) return 'text-amber-600 dark:text-amber-400';
  return 'text-red-500 dark:text-red-400';
}

function pctBg(pct: number) {
  if (pct >= 75) return 'bg-emerald-500';
  if (pct >= 50) return 'bg-amber-400';
  return 'bg-red-400';
}

function ScoreBar({ label, score, max, pct }: { label: string; score: number; max: number; pct: number }) {
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-sm">
        <span className="font-medium capitalize">{label}</span>
        <span className={cn('text-xs font-bold tabular-nums', pctColor(pct))}>
          {score}/{max} &nbsp;·&nbsp; {pct.toFixed(0)}%
        </span>
      </div>
      <div className="h-2 w-full rounded-full bg-muted overflow-hidden">
        <div
          className={cn('h-full rounded-full transition-all duration-500', pctBg(pct))}
          style={{ width: `${Math.min(100, pct)}%` }}
        />
      </div>
    </div>
  );
}

// ── Main Modal ────────────────────────────────────────────────────────────────

interface QuizResultModalProps {
  candidateId: string;
  candidateName?: string | null;
  quizScore?: number | null;   // raw score stored on Candidate row — used to show button conditionally
}

export function QuizResultModal({ candidateId, candidateName, quizScore }: QuizResultModalProps) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<CandidateQuizResult | null>(null);

  const handleOpen = async () => {
    setOpen(true);
    if (result) return; // already loaded
    setLoading(true);
    try {
      const data = await getCandidateQuizResult(candidateId);
      setResult(data);
    } catch (err: any) {
      const detail = err?.response?.data?.detail ?? 'No quiz results found for this candidate.';
      toast.error(detail);
      setOpen(false);
    } finally {
      setLoading(false);
    }
  };

  // If candidate hasn't taken a quiz, show nothing
  if (quizScore === null || quizScore === undefined) return null;

  const skillEntries: Array<[string, QuizSkillBreakdown]> = result
    ? Object.entries(result.skill_breakdown) as Array<[string, QuizSkillBreakdown]>
    : [];
  const difficultyOrder = ['easy', 'medium', 'hard'];
  const diffEntries: Array<[string, QuizSkillBreakdown]> = result
    ? difficultyOrder
        .map(d => [d, result.difficulty_breakdown[d]] as const)
        .filter((entry): entry is readonly [string, QuizSkillBreakdown] => Boolean(entry[1] && entry[1].max > 0))
        .map(([d, v]) => [d, v])
    : [];

  const timeTaken =
    result?.started_at && result?.submitted_at
      ? Math.round(
          (new Date(result.submitted_at).getTime() - new Date(result.started_at).getTime()) / 60000,
        )
      : null;

  return (
    <>
      <Button
        size="sm"
        variant="outline"
        className="h-7 px-2 text-xs gap-1 border-violet-400/60 text-violet-600 dark:text-violet-400 hover:bg-violet-50 dark:hover:bg-violet-950/20"
        onClick={handleOpen}
      >
        <Eye className="h-3.5 w-3.5" />
        Results
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-base">
              <Brain className="h-4 w-4 text-violet-500" />
              Assessment Results
              {result && (
                <span className="text-muted-foreground font-normal text-sm ml-1">
                  — {result.candidate_name ?? candidateName ?? 'Candidate'}
                </span>
              )}
            </DialogTitle>
          </DialogHeader>

          {loading && (
            <div className="py-12 flex flex-col items-center justify-center gap-3 text-muted-foreground">
              <Loader2 className="h-7 w-7 animate-spin" />
              <span className="text-sm">Loading results…</span>
            </div>
          )}

          {!loading && result && (
            <div className="space-y-5 pt-1">

              {/* ── Header summary ── */}
              <div className="rounded-xl border bg-muted/20 p-4 flex items-center justify-between gap-4">
                <div>
                  <p className="text-xs text-muted-foreground mb-0.5">{result.quiz_title}</p>
                  <div className={cn('text-4xl font-black tabular-nums', pctColor(result.percentage))}>
                    {result.percentage.toFixed(0)}%
                  </div>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    {result.raw_score} / {result.max_score} pts
                  </p>
                </div>
                <div className="space-y-2 text-right">
                  {result.passed === true && (
                    <Badge className="bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300 border-emerald-300/50 gap-1">
                      <CheckCircle2 className="h-3 w-3" /> Passed
                    </Badge>
                  )}
                  {result.passed === false && (
                    <Badge className="bg-red-100 text-red-600 dark:bg-red-900/30 dark:text-red-400 border-red-300/50 gap-1">
                      <XCircle className="h-3 w-3" /> Failed
                    </Badge>
                  )}
                  {result.passed === null && (
                    <Badge variant="secondary" className="gap-1">
                      <AlertTriangle className="h-3 w-3" /> Pending
                    </Badge>
                  )}
                  {timeTaken !== null && (
                    <p className="text-xs text-muted-foreground">
                      Completed in <span className="font-semibold">{timeTaken} min</span>
                    </p>
                  )}
                  {result.tab_switches > 0 && (
                    <p className="text-xs text-amber-600 dark:text-amber-400 flex items-center justify-end gap-1">
                      <Shield className="h-3 w-3" />
                      {result.tab_switches} tab switch{result.tab_switches !== 1 ? 'es' : ''} detected
                    </p>
                  )}
                </div>
              </div>

              {/* ── By Topic ── */}
              {skillEntries.length > 0 && (
                <div>
                  <div className="flex items-center gap-1.5 mb-3">
                    <BookOpen className="h-3.5 w-3.5 text-primary" />
                    <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      Performance by Topic
                    </span>
                  </div>
                  <div className="space-y-3">
                    {skillEntries.map(([skill, val]) => (
                      <React.Fragment key={skill}>
                        <ScoreBar
                          label={skill}
                          score={val.score}
                          max={val.max}
                          pct={val.pct ?? (val.max > 0 ? Math.round((val.score / val.max) * 100) : 0)}
                        />
                      </React.Fragment>
                    ))}
                  </div>
                </div>
              )}

              {/* ── By Difficulty ── */}
              {diffEntries.length > 0 && (
                <div>
                  <div className="flex items-center gap-1.5 mb-3">
                    <BarChart3 className="h-3.5 w-3.5 text-primary" />
                    <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      Performance by Difficulty
                    </span>
                  </div>
                  <div className="grid grid-cols-3 gap-2">
                    {diffEntries.map(([diff, val]) => (
                      <div
                        key={diff}
                        className="rounded-lg border bg-muted/20 p-2.5 text-center space-y-1"
                      >
                        <p className="text-[10px] font-semibold uppercase text-muted-foreground capitalize">{diff}</p>
                        <p className={cn('text-lg font-black', pctColor(val.pct ?? 0))}>
                          {(val.pct ?? (val.max > 0 ? Math.round((val.score / val.max) * 100) : 0)).toFixed(0)}%
                        </p>
                        <p className="text-[10px] text-muted-foreground">{val.score}/{val.max} pts</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* ── Submitted at ── */}
              {result.submitted_at && (
                <p className="text-xs text-muted-foreground text-center border-t pt-3">
                  Submitted {new Date(result.submitted_at).toLocaleString('en-GB', {
                    day: '2-digit', month: 'short', year: 'numeric',
                    hour: '2-digit', minute: '2-digit',
                  })}
                </p>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
