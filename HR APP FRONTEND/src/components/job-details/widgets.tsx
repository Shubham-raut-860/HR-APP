import * as React from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import {
  ThumbsUp, CheckCircle2, Minus, XCircle, ThumbsDown, CircleDot, Flame,
  ShieldAlert, ChevronDown, Eye, Award, Target, ChevronRight, Sparkles,
  BrainCircuit, TrendingUp, Loader2,
} from "lucide-react";
import { QuizResultModal } from "@/components/QuizResultModal";
import { getCandidate } from "@/services/candidates";

export interface ScoreBreakdown {
  ai_score_used?: boolean;
  hire_recommendation?: string;
  reasoning?: string;
  standout_factors?: string[];
  red_flags?: string[];
  candidate_tier?: string;
  matched_must_have?: string[];
  missing_must_have?: string[];
  [key: string]: any;
}

export function HireRecBadge({ rec }: { rec: string }) {
  const map: Record<string, { label: string; cls: string; icon: React.ElementType }> = {
    strong_hire: { label: "Strong Hire", cls: "bg-emerald-100 text-emerald-800 border-emerald-300 dark:bg-emerald-900/40 dark:text-emerald-300", icon: ThumbsUp },
    hire: { label: "Hire", cls: "bg-blue-100 text-blue-800 border-blue-300 dark:bg-blue-900/40 dark:text-blue-300", icon: CheckCircle2 },
    maybe: { label: "Maybe", cls: "bg-amber-100 text-amber-700 border-amber-300 dark:bg-amber-900/40 dark:text-amber-300", icon: Minus },
    no_hire: { label: "No Hire", cls: "bg-red-100 text-red-700 border-red-300 dark:bg-red-900/40 dark:text-red-300", icon: XCircle },
    strong_no_hire: { label: "Strong No Hire", cls: "bg-red-200 text-red-900 border-red-400 dark:bg-red-900/60 dark:text-red-200", icon: ThumbsDown },
  };
  const cfg = map[rec] || map.maybe;
  const Icon = cfg.icon;
  return (
    <span className={cn("inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-full border", cfg.cls)}>
      <Icon className="h-2.5 w-2.5" />{cfg.label}
    </span>
  );
}

export function DomainFitPip({ fit }: { fit: string }) {
  if (fit === "exact") return <span title="Exact domain match" className="inline-flex items-center gap-1 text-[10px] text-emerald-600 font-medium"><CircleDot className="h-3 w-3" />Exact domain</span>;
  if (fit === "adjacent") return <span title="Adjacent domain" className="inline-flex items-center gap-1 text-[10px] text-amber-600 font-medium"><CircleDot className="h-3 w-3" />Adjacent domain</span>;
  return <span title="Different domain" className="inline-flex items-center gap-1 text-[10px] text-red-500 font-medium"><CircleDot className="h-3 w-3" />Wrong domain</span>;
}

export function scoreColor(pct: number) {
  if (pct >= 75) return "text-emerald-600 dark:text-emerald-400";
  if (pct >= 50) return "text-amber-600 dark:text-amber-400";
  return "text-red-500 dark:text-red-400";
}

export function scoreBg(pct: number) {
  if (pct >= 75) return "hsl(142 71% 45%)";
  if (pct >= 50) return "hsl(38 92% 50%)";
  return "hsl(0 72% 51%)";
}

export function CandidateIntelligencePanel({
  candidates, navigate, onViewAllShortlist
}: {
  candidates: any[];
  navigate: (path: string) => void;
  onViewAllShortlist?: () => void;
}) {
  const [expanded, setExpanded] = React.useState<string | null>(null);
  const [detailsById, setDetailsById] = React.useState<Record<string, any>>({});
  const [loadingDetailsById, setLoadingDetailsById] = React.useState<Record<string, boolean>>({});
  const [detailErrorsById, setDetailErrorsById] = React.useState<Record<string, string>>({});
  const sorted = [...candidates].sort((a: any, b: any) => b.resume_score - a.resume_score);
  const top = sorted.slice(0, 6);

  const strong = candidates.filter((c: any) => c.tag === "Strong").length;
  const medium = candidates.filter((c: any) => c.tag === "Medium").length;
  const reject = candidates.filter((c: any) => c.tag === "Reject").length;
  const total = candidates.length;
  const avgScore = total > 0 ? candidates.reduce((s: number, c: any) => s + (c.resume_score || 0), 0) / total : 0;

  const strongPct = total > 0 ? Math.round(strong / total * 100) : 0;
  const mediumPct = total > 0 ? Math.round(medium / total * 100) : 0;
  const rejectPct = 100 - strongPct - mediumPct;

  const strongHireCount = candidates.filter((c: any) => c.score_breakdown?.hire_recommendation === "strong_hire").length;
  const noHireCount = candidates.filter((c: any) => ["no_hire", "strong_no_hire"].includes(c.score_breakdown?.hire_recommendation)).length;
  const flaggedCount = candidates.filter((c: any) => (c.score_breakdown?.red_flags?.length || 0) > 0).length;

  const loadCandidateDetails = React.useCallback(async (candidateId: string) => {
    if (!candidateId || detailsById[candidateId] || loadingDetailsById[candidateId]) return;
    setLoadingDetailsById(prev => ({ ...prev, [candidateId]: true }));
    setDetailErrorsById(prev => {
      const next = { ...prev };
      delete next[candidateId];
      return next;
    });
    try {
      const detail = await getCandidate(candidateId);
      setDetailsById(prev => ({ ...prev, [candidateId]: detail }));
    } catch {
      setDetailErrorsById(prev => ({ ...prev, [candidateId]: "Failed to load parsed resume details." }));
    } finally {
      setLoadingDetailsById(prev => ({ ...prev, [candidateId]: false }));
    }
  }, [detailsById, loadingDetailsById]);

  return (
    <div className="rounded-xl border overflow-hidden bg-card mt-1">
      <div className="flex items-center justify-between px-4 py-2.5 bg-muted/40 border-b">
        <div className="flex items-center gap-2">
          <div className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
          <span className="text-xs font-semibold text-foreground">Candidate Intelligence</span>
          <span className="text-xs text-muted-foreground">— {total} parsed</span>
        </div>
        <div className="flex items-center gap-3 text-[11px] font-medium">
          <span className="text-emerald-600 dark:text-emerald-400">{strong} Strong</span>
          <span className="text-amber-600 dark:text-amber-400">{medium} Medium</span>
          <span className="text-red-500 dark:text-red-400">{reject} Reject</span>
          <span className="text-muted-foreground ml-1">Avg <span className={cn("font-bold", scoreColor(avgScore))}>{avgScore.toFixed(0)}%</span></span>
        </div>
      </div>

      <div className="px-4 pt-3 pb-2 border-b">
        <div className="flex gap-0.5 h-2.5 rounded-full overflow-hidden w-full bg-muted">
          {strongPct > 0 && <div className="bg-emerald-500 h-full transition-all" style={{ width: `${strongPct}%` }} />}
          {mediumPct > 0 && <div className="bg-amber-400 h-full transition-all" style={{ width: `${mediumPct}%` }} />}
          {rejectPct > 0 && <div className="bg-red-400 h-full transition-all" style={{ width: `${rejectPct}%` }} />}
        </div>
        <div className="flex justify-between text-[10px] text-muted-foreground mt-1.5">
          <span>{strongPct}% shortlist-ready</span>
          <div className="flex gap-3">
            {strongHireCount > 0 && (
              <span className="flex items-center gap-1 text-emerald-600 font-medium">
                <Flame className="h-3 w-3" />{strongHireCount} hot {strongHireCount === 1 ? "pick" : "picks"}
              </span>
            )}
            {flaggedCount > 0 && (
              <span className="flex items-center gap-1 text-amber-600 font-medium">
                <ShieldAlert className="h-3 w-3" />{flaggedCount} flagged
              </span>
            )}
            {noHireCount > 0 && (
              <span className="flex items-center gap-1 text-red-500 font-medium">
                <XCircle className="h-3 w-3" />{noHireCount} no-hire
              </span>
            )}
          </div>
        </div>
      </div>

      <div className="divide-y max-h-72 overflow-y-auto">
        {top.map((c: any, i: number) => {
          const bd: ScoreBreakdown = c.score_breakdown || {};
          const isExpanded = expanded === c.id;
          const detail = detailsById[c.id] || c;
          const parsedSkills: string[] = Array.isArray(detail?.skills) ? detail.skills : [];
          const parsedWorkExp: any[] = Array.isArray(detail?.work_experience) ? detail.work_experience : [];
          const parsedEducation: any[] = Array.isArray(detail?.education) ? detail.education : [];
          const parsedProjects: any[] = Array.isArray(detail?.projects) ? detail.projects : [];
          const parsedCareerBreaks: any[] = Array.isArray(detail?.career_breaks) ? detail.career_breaks : [];
          const hasParsedDetails =
            parsedSkills.length > 0 ||
            parsedWorkExp.length > 0 ||
            parsedEducation.length > 0 ||
            parsedProjects.length > 0 ||
            parsedCareerBreaks.length > 0;
          const hasFlags = (bd.red_flags?.length || 0) > 0;
          const hasStandout = (bd.standout_factors?.length || 0) > 0;
          return (
            <div key={c.id} className={cn(
              "transition-colors",
              i === 0 && "bg-emerald-50/40 dark:bg-emerald-950/10",
              hasFlags && "border-l-2 border-l-amber-400",
              bd.hire_recommendation === "strong_hire" && "border-l-2 border-l-emerald-500",
              ["no_hire", "strong_no_hire"].includes(bd.hire_recommendation) && "border-l-2 border-l-red-400"
            )}>
              <div className="flex items-center gap-2.5 px-3 py-2.5">
                <span className={cn(
                  "text-xs font-bold w-5 text-center shrink-0",
                  i === 0 ? "text-amber-500" : i === 1 ? "text-slate-400" : i === 2 ? "text-amber-700/70" : "text-muted-foreground"
                )}>
                  {i < 3 ? ["🥇", "🥈", "🥉"][i] : `#${i + 1}`}
                </span>

                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5 flex-wrap">
                    <span className="font-medium text-sm truncate max-w-[140px]">{c.name || "Unknown"}</span>
                    {bd.hire_recommendation && <HireRecBadge rec={bd.hire_recommendation} />}
                    {bd.domain_fit && bd.domain_fit !== "exact" && <DomainFitPip fit={bd.domain_fit} />}
                    {hasFlags && (
                      <span className="inline-flex items-center gap-0.5 text-[10px] text-amber-600 font-medium">
                        <ShieldAlert className="h-2.5 w-2.5" />{bd.red_flags.length} flag{bd.red_flags.length > 1 ? "s" : ""}
                      </span>
                    )}
                  </div>
                  <div className="text-[11px] text-muted-foreground mt-0.5">
                    {c.experience_years}yr exp
                    {bd.confidence && <span className={cn("ml-1.5", bd.confidence === "low" ? "text-amber-500" : "")}>
                      | {bd.confidence} confidence
                    </span>}
                  </div>
                </div>

                <div className="text-right shrink-0">
                  <div className={cn("text-sm font-bold tabular-nums", scoreColor(c.resume_score))}>
                    {(c.resume_score || 0).toFixed(0)}%
                  </div>
                  <div className="w-12 h-1 rounded-full bg-muted overflow-hidden mt-1">
                    <div className="h-full rounded-full" style={{ width: `${c.resume_score || 0}%`, background: scoreBg(c.resume_score || 0) }} />
                  </div>
                </div>

                <div className="flex items-center gap-1 shrink-0">
                  <Button size="sm" variant="ghost" className="h-7 px-2 text-xs"
                    onClick={() => {
                      if (isExpanded) {
                        setExpanded(null);
                        return;
                      }
                      setExpanded(c.id);
                      void loadCandidateDetails(c.id);
                    }}>
                    <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", isExpanded && "rotate-180")} />
                  </Button>
                  <Button size="sm" variant="ghost" className="h-7 px-2 text-xs"
                    onClick={() => navigate(`/candidates/${c.id}`)}>
                    <Eye className="h-3.5 w-3.5" />
                  </Button>
                  {c.quiz_score !== null && c.quiz_score !== undefined && (
                    <QuizResultModal candidateId={c.id} candidateName={c.name} quizScore={c.quiz_score} />
                  )}
                </div>
              </div>

              {isExpanded && (
                <div className="px-4 pb-3 pt-0 space-y-2 bg-muted/20 text-xs border-t">
                  {bd.reasoning && (
                    <p className="text-muted-foreground leading-relaxed italic">"{bd.reasoning}"</p>
                  )}
                  <div className="flex flex-wrap gap-3">
                    {hasStandout && (
                      <div>
                        <span className="font-semibold text-emerald-700 dark:text-emerald-400 flex items-center gap-1 mb-1">
                          <Award className="h-3 w-3" />Standouts
                        </span>
                        <ul className="space-y-0.5">
                          {(bd.standout_factors || []).map((f: string, fi: number) => (
                            <li key={fi} className="flex items-start gap-1 text-foreground">
                              <span className="text-emerald-500 mt-0.5">✦</span>{f}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                    {hasFlags && (
                      <div>
                        <span className="font-semibold text-amber-600 flex items-center gap-1 mb-1">
                          <ShieldAlert className="h-3 w-3" />Red flags
                        </span>
                        <ul className="space-y-0.5">
                          {(bd.red_flags || []).map((f: string, fi: number) => (
                            <li key={fi} className="flex items-start gap-1 text-foreground">
                              <span className="text-amber-500 mt-0.5">⚠</span>{f}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                    {(bd.matched_must_have?.length > 0 || bd.missing_must_have?.length > 0) && (
                      <div>
                        <span className="font-semibold text-foreground flex items-center gap-1 mb-1">
                          <Target className="h-3 w-3" />Required skills
                        </span>
                        <div className="flex flex-wrap gap-1">
                          {(bd.matched_must_have || []).map((s: string, si: number) => (
                            <span key={si} className="px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300 text-[10px]">✓ {s}</span>
                          ))}
                          {(bd.missing_must_have || []).map((s: string, si: number) => (
                            <span key={si} className="px-1.5 py-0.5 rounded bg-red-100 text-red-600 dark:bg-red-900/30 dark:text-red-400 text-[10px]">✗ {s}</span>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>

                  <div className="pt-2 border-t space-y-2">
                    {loadingDetailsById[c.id] && (
                      <div className="flex items-center gap-1.5 text-muted-foreground">
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        Loading parsed resume profile...
                      </div>
                    )}

                    {!loadingDetailsById[c.id] && detailErrorsById[c.id] && (
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-amber-600">{detailErrorsById[c.id]}</span>
                        <Button
                          size="sm"
                          variant="outline"
                          className="h-6 px-2 text-[11px]"
                          onClick={() => void loadCandidateDetails(c.id)}
                        >
                          Retry
                        </Button>
                      </div>
                    )}

                    {!loadingDetailsById[c.id] && !detailErrorsById[c.id] && hasParsedDetails && (
                      <div className="space-y-2">
                        {parsedSkills.length > 0 && (
                          <div>
                            <span className="font-semibold text-foreground mb-1 inline-block">Skills</span>
                            <div className="flex flex-wrap gap-1">
                              {parsedSkills.slice(0, 12).map((skill: string, si: number) => (
                                <span key={si} className="px-1.5 py-0.5 rounded bg-secondary text-secondary-foreground text-[10px]">
                                  {skill}
                                </span>
                              ))}
                              {parsedSkills.length > 12 && (
                                <span className="px-1.5 py-0.5 rounded bg-muted text-muted-foreground text-[10px]">
                                  +{parsedSkills.length - 12} more
                                </span>
                              )}
                            </div>
                          </div>
                        )}

                        {parsedWorkExp.length > 0 && (
                          <div>
                            <span className="font-semibold text-foreground mb-1 inline-block">Work Experience</span>
                            <ul className="space-y-1">
                              {parsedWorkExp.slice(0, 4).map((exp: any, ei: number) => (
                                <li key={ei} className="text-foreground">
                                  {(exp?.role || exp?.title || "Role")} at {(exp?.company || exp?.organization || "Company")}
                                  {(exp?.duration || exp?.start_date || exp?.end_date) && (
                                    <span className="text-muted-foreground"> | {exp?.duration || `${exp?.start_date || "N/A"} to ${exp?.end_date || "Present"}`}</span>
                                  )}
                                </li>
                              ))}
                              {parsedWorkExp.length > 4 && (
                                <li className="text-muted-foreground">+{parsedWorkExp.length - 4} more roles</li>
                              )}
                            </ul>
                          </div>
                        )}

                        {parsedEducation.length > 0 && (
                          <div>
                            <span className="font-semibold text-foreground mb-1 inline-block">Education</span>
                            <ul className="space-y-1">
                              {parsedEducation.slice(0, 3).map((edu: any, ei: number) => (
                                <li key={ei} className="text-foreground">
                                  {edu?.degree || "Degree"}{edu?.institute || edu?.institution ? `, ${edu?.institute || edu?.institution}` : ""}
                                  {edu?.year ? <span className="text-muted-foreground"> | {edu.year}</span> : null}
                                </li>
                              ))}
                            </ul>
                          </div>
                        )}

                        {parsedProjects.length > 0 && (
                          <div>
                            <span className="font-semibold text-foreground mb-1 inline-block">Projects</span>
                            <ul className="space-y-1">
                              {parsedProjects.slice(0, 3).map((proj: any, pi: number) => (
                                <li key={pi} className="text-foreground">
                                  {proj?.title || `Project ${pi + 1}`}
                                  {proj?.description ? <span className="text-muted-foreground"> | {proj.description}</span> : null}
                                </li>
                              ))}
                            </ul>
                          </div>
                        )}

                        {parsedCareerBreaks.length > 0 && (
                          <div>
                            <span className="font-semibold text-foreground mb-1 inline-block">Career Breaks</span>
                            <ul className="space-y-1">
                              {parsedCareerBreaks.slice(0, 3).map((gap: any, gi: number) => (
                                <li key={gi} className="text-foreground">
                                  {(gap?.start || "Unknown start")} to {(gap?.end || "Unknown end")}
                                  {gap?.duration_months ? <span className="text-muted-foreground"> | {gap.duration_months} months</span> : null}
                                </li>
                              ))}
                            </ul>
                          </div>
                        )}
                      </div>
                    )}

                    {!loadingDetailsById[c.id] && !detailErrorsById[c.id] && !hasParsedDetails && (
                      <p className="text-muted-foreground">
                        No parsed profile fields are available for this candidate yet.
                      </p>
                    )}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {candidates.length > 6 && (
        <div className="px-4 py-2 border-t bg-muted/20 flex items-center justify-between">
          <span className="text-[11px] text-muted-foreground">Showing top 6 of {candidates.length}</span>
          <button
            className="text-[11px] text-primary hover:underline flex items-center gap-1"
            onClick={() => {
              if (onViewAllShortlist) {
                onViewAllShortlist();
                return;
              }
              navigate('#shortlist');
            }}
          >
            View all in Shortlist tab <ChevronRight className="h-3 w-3" />
          </button>
        </div>
      )}
    </div>
  );
}

export function UploadReadyState() {
  const checks = [
    { icon: Sparkles, label: "Skill depth", desc: "Checks years of usage, not just presence" },
    { icon: BrainCircuit, label: "Domain fit", desc: "Flags wrong-domain candidates immediately" },
    { icon: ShieldAlert, label: "Red flags", desc: "Job-hopping, gaps, domain mismatch" },
    { icon: Award, label: "Standout factors", desc: "Identifies what makes each candidate unique" },
    { icon: Target, label: "Seniority match", desc: "Detects over/under-qualified candidates" },
    { icon: TrendingUp, label: "Hire signal", desc: "Strong hire → maybe → no-hire verdict" },
  ];
  return (
    <div className="mt-3 rounded-xl border border-dashed bg-muted/20 p-5">
      <div className="flex items-center gap-2 mb-3">
        <Sparkles className="h-4 w-4 text-primary" />
        <p className="text-sm font-semibold">What the AI checks on every resume</p>
      </div>
      <div className="grid grid-cols-2 gap-2">
        {checks.map(({ icon: Icon, label, desc }) => (
          <div key={label} className="flex items-start gap-2.5 p-2.5 rounded-lg bg-background border">
            <div className="p-1.5 rounded-md bg-primary/10 shrink-0 mt-0.5">
              <Icon className="h-3 w-3 text-primary" />
            </div>
            <div>
              <p className="text-xs font-semibold leading-tight">{label}</p>
              <p className="text-[11px] text-muted-foreground leading-tight mt-0.5">{desc}</p>
            </div>
          </div>
        ))}
      </div>
      <p className="text-[11px] text-muted-foreground mt-3 text-center">
        Drop up to 50 resumes at once | Results appear instantly as files are processed
      </p>
    </div>
  );
}

export function StatCard({ icon: Icon, label, value, sub, color = "text-primary" }: {
  icon: any; label: string; value: string | number; sub?: string; color?: string;
}) {
  return (
    <Card>
      <CardContent className="p-5">
        <div className="flex items-center justify-between mb-3">
          <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">{label}</span>
          <Icon className={cn("h-4 w-4", color)} />
        </div>
        <div className={cn("text-2xl font-bold", color)}>{value}</div>
        {sub && <p className="text-xs text-muted-foreground mt-1">{sub}</p>}
      </CardContent>
    </Card>
  );
}

export function TagBadge({ tag }: { tag: string | null }) {
  if (!tag) return <Badge variant="outline">-</Badge>;
  const map: Record<string, string> = {
    Strong: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400",
    Medium: "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400",
    Reject: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
  };
  return (
    <span className={cn("inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium", map[tag] || "bg-secondary text-secondary-foreground")}>
      {tag}
    </span>
  );
}

