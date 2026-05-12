import React from "react";
import { Button } from "@/components/ui/button";
import { Briefcase, Calendar, CalendarOff, MessageSquarePlus } from "lucide-react";

export function scoreColor(pct: number) {
  if (pct >= 75) return "hsl(142 71% 45%)";
  if (pct >= 50) return "hsl(38 92% 50%)";
  return "hsl(0 72% 51%)";
}

export function scoreBg(pct: number) {
  if (pct >= 75) return "bg-emerald-50 dark:bg-emerald-950/30";
  if (pct >= 50) return "bg-amber-50 dark:bg-amber-950/30";
  return "bg-red-50 dark:bg-red-950/30";
}

export function scoreText(pct: number) {
  if (pct >= 75) return "text-emerald-700 dark:text-emerald-400";
  if (pct >= 50) return "text-amber-700 dark:text-amber-400";
  return "text-red-600 dark:text-red-400";
}

export function ScoreArc({ value, size = 120 }: { value: number; size?: number }) {
  const strokeW = size < 80 ? 5 : 7;
  const r = (size - strokeW * 2) / 2;
  const circ = 2 * Math.PI * r;
  const filled = (value / 100) * circ;
  const color = scoreColor(value);
  return (
    <svg width={size} height={size}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none"
        stroke="currentColor" strokeWidth={strokeW} className="text-muted/30" />
      <circle cx={size / 2} cy={size / 2} r={r} fill="none"
        stroke={color} strokeWidth={strokeW}
        strokeDasharray={`${filled} ${circ - filled}`}
        strokeDashoffset={circ / 4} strokeLinecap="round"
        style={{ transition: "stroke-dasharray 0.9s cubic-bezier(.4,0,.2,1)" }} />
      <text x={size / 2} y={size / 2 + (size < 80 ? 4 : 6)}
        textAnchor="middle" fontSize={size < 80 ? 13 : 20}
        fontWeight="700" fill={color}>{Math.round(value)}%</text>
    </svg>
  );
}

export function ScoreBar({ label, value }: { label: string; value: number }) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-sm">
        <span className="text-muted-foreground">{label}</span>
        <span className={`font-semibold tabular-nums ${scoreText(value)}`}>{Math.round(value)}%</span>
      </div>
      <div className="h-1.5 rounded-full bg-muted overflow-hidden">
        <div className="h-full rounded-full transition-[width] duration-700 ease-out"
          style={{ width: `${value}%`, background: scoreColor(value) }} />
      </div>
    </div>
  );
}

export const TAG_STYLES: Record<string, { badge: string; text: string }> = {
  Strong: { badge: "bg-emerald-100 text-emerald-800 border border-emerald-200 dark:bg-emerald-900/30 dark:text-emerald-300 dark:border-emerald-800", text: "text-emerald-700 dark:text-emerald-400" },
  Medium: { badge: "bg-amber-100 text-amber-800 border border-amber-200 dark:bg-amber-900/30 dark:text-amber-300 dark:border-amber-800", text: "text-amber-700 dark:text-amber-400" },
  Reject: { badge: "bg-red-100 text-red-800 border border-red-200 dark:bg-red-900/30 dark:text-red-300 dark:border-red-800", text: "text-red-700 dark:text-red-400" },
};

export function SectionHeader({ icon: Icon, title, right }: {
  icon: React.ElementType; title: string; right?: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between mb-4">
      <div className="flex items-center gap-2">
        <div className="p-1.5 rounded-md bg-primary/10">
          <Icon className="h-3.5 w-3.5 text-primary" />
        </div>
        <h2 className="font-semibold text-sm tracking-wide uppercase text-muted-foreground">{title}</h2>
      </div>
      {right}
    </div>
  );
}

const BREAK_REASON_LABELS: Record<string, string> = {
  upskilling:  "Upskilling / Education",
  caregiving:  "Caregiving / Family",
  medical:     "Medical / Health",
  relocation:  "Relocation",
  personal:    "Personal / Sabbatical",
  job_search:  "Job Search",
  layoff:      "Layoff / Company closure",
  other:       "Other",
};

interface TimelineEntry {
  type: "role" | "gap";
  label: string;
  sublabel?: string;
  dateRange?: string;
  sortTs?: number;
  durationYears?: number;
  durationMonths?: number;
  skills?: string[];
  reason?: string | null;
  notes?: string | null;
}

const NARRATIVE_ROLE_RE =
  /^(developed|designed|implemented|built|responsible|worked|ensured|ensuring|contributed|maintained|optimized)\b/i;

function isNoisyRoleLabel(value: string): boolean {
  const text = (value || "").trim();
  if (!text) return true;
  const words = text.split(/\s+/).filter(Boolean).length;
  if (NARRATIVE_ROLE_RE.test(text)) return true;
  if (words > 10) return true;
  if (/[.!?]$/.test(text) && words >= 6) return true;
  return false;
}

function _parseTimelineDate(value: string | null | undefined): number {
  if (!value) return 0;
  const clean = String(value).trim();
  if (!clean) return 0;
  const parsed = Date.parse(clean);
  if (!Number.isNaN(parsed)) return parsed;
  const yearOnly = clean.match(/\b(19|20)\d{2}\b/);
  if (yearOnly) return Date.parse(`${yearOnly[0]}-01-01`) || 0;
  return 0;
}

function _formatDateRange(start: string | null | undefined, end: string | null | undefined): string | undefined {
  const s = String(start || "").trim();
  const e = String(end || "").trim();
  if (s && e) return `${s} - ${e}`;
  if (s) return s;
  if (e) return e;
  return undefined;
}

function buildTimeline(workExp: any[], careerBreaks: any[]): TimelineEntry[] {
  const items: TimelineEntry[] = [];
  const sorted = [...(workExp || [])].sort((a, b) => {
    const da = _parseTimelineDate(a?.start_date) || _parseTimelineDate(a?.end_date);
    const db = _parseTimelineDate(b?.start_date) || _parseTimelineDate(b?.end_date);
    return db - da;
  });

  sorted.forEach(role => {
    const roleLabel = String(role.role || "").trim();
    const companyLabel = String(role.company || "").trim();
    if (!roleLabel) return;
    if (isNoisyRoleLabel(roleLabel) && !companyLabel) return;

    const durationRaw = Number(role.duration_years);
    const durationYears = Number.isFinite(durationRaw) && durationRaw > 0 ? durationRaw : undefined;
    const sortTs = _parseTimelineDate(role.start_date) || _parseTimelineDate(role.end_date);
    items.push({
      type: "role",
      label: roleLabel,
      sublabel: companyLabel,
      dateRange: _formatDateRange(role.start_date, role.end_date),
      sortTs,
      durationYears,
      skills: role.skills || [],
    });
  });

  (careerBreaks || []).forEach(gap => {
    const monthsRaw = gap.duration_months ?? gap.durationMonths;
    const months = Number(monthsRaw ?? 0);
    if (Number.isFinite(months) && months >= 6) {
      const sortTs = _parseTimelineDate(gap.end) || _parseTimelineDate(gap.start);
      const entry: TimelineEntry = {
        type: "gap",
        label: "Career Break",
        dateRange: _formatDateRange(gap.start, gap.end),
        sortTs,
        durationMonths: months,
        reason: gap.reason,
        notes: gap.notes,
      };
      items.push(entry);
    }
  });

  items.sort((a, b) => (b.sortTs || 0) - (a.sortTs || 0));
  return items;
}

export function CareerTimeline({
  workExp, careerBreaks, onAskAboutGap,
}: {
  workExp: any[];
  careerBreaks: any[];
  onAskAboutGap?: (entry: any) => void;
}) {
  const timeline = buildTimeline(workExp, careerBreaks);
  if (timeline.length === 0) return null;

  return (
    <div className="rounded-2xl border bg-card p-5">
      <SectionHeader icon={Calendar} title="Career Timeline" />
      <div className="relative space-y-0">
        <div className="absolute left-[11px] top-2 bottom-2 w-0.5 bg-border" />

        {timeline.map((entry, i) => (
          <div key={i} className="relative pl-8 pb-5 last:pb-0">
            <div className={`absolute left-0 top-1 w-6 h-6 rounded-full border-2 flex items-center justify-center z-10 bg-background ${
              entry.type === "gap"
                ? "border-amber-400 dark:border-amber-600"
                : "border-primary"
            }`}>
              {entry.type === "gap"
                ? <CalendarOff className="h-3 w-3 text-amber-500" />
                : <Briefcase className="h-3 w-3 text-primary" />}
            </div>

            {entry.type === "role" ? (
              <div className="rounded-xl border bg-muted/20 p-3 space-y-2">
                <div className="flex items-start justify-between gap-2 flex-wrap">
                  <div>
                    <p className="font-semibold text-sm leading-snug">{entry.label}</p>
                    {entry.sublabel && (
                      <p className="text-xs text-muted-foreground mt-0.5">{entry.sublabel}</p>
                    )}
                  </div>
                  <div className="text-right shrink-0">
                    {entry.dateRange && (
                      <p className="text-xs text-muted-foreground">{entry.dateRange}</p>
                    )}
                    {entry.durationYears != null && (
                      <p className="text-xs font-medium text-primary">
                        {entry.durationYears.toFixed(1)} yr{entry.durationYears !== 1 ? "s" : ""}
                      </p>
                    )}
                  </div>
                </div>
                {entry.skills && entry.skills.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {entry.skills.slice(0, 6).map((s, si) => (
                      <span key={si} className="text-[10px] px-2 py-0.5 rounded-full bg-primary/8 text-primary font-medium border border-primary/15">
                        {s}
                      </span>
                    ))}
                    {entry.skills.length > 6 && (
                      <span className="text-[10px] px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                        +{entry.skills.length - 6}
                      </span>
                    )}
                  </div>
                )}
              </div>
            ) : (
              <div className="rounded-xl border border-amber-200 dark:border-amber-800 bg-amber-50/40 dark:bg-amber-950/20 p-3 space-y-2">
                <div className="flex items-start justify-between gap-2 flex-wrap">
                  <div className="flex items-center gap-2">
                    <p className="font-semibold text-sm text-amber-800 dark:text-amber-300">
                      {entry.reason
                        ? (BREAK_REASON_LABELS[entry.reason] ?? entry.reason)
                        : "Career Break"}
                    </p>
                    {!entry.reason && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-amber-100 text-amber-600 dark:bg-amber-900/30 dark:text-amber-400 border border-amber-200 dark:border-amber-700">
                        No context
                      </span>
                    )}
                  </div>
                  <div className="text-right shrink-0">
                    {entry.dateRange && (
                      <p className="text-xs text-muted-foreground">{entry.dateRange}</p>
                    )}
                    {entry.durationMonths != null && (
                      <p className="text-xs font-medium text-amber-600 dark:text-amber-400">
                        {entry.durationMonths} months
                      </p>
                    )}
                  </div>
                </div>

                {entry.notes && (
                  <p className="text-xs text-muted-foreground italic">"{entry.notes}"</p>
                )}

                {!entry.reason && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-7 text-[11px] gap-1.5 border-amber-300 text-amber-700 hover:bg-amber-100 dark:border-amber-700 dark:text-amber-400 dark:hover:bg-amber-950/40"
                    onClick={() => onAskAboutGap?.(entry)}
                  >
                    <MessageSquarePlus className="h-3 w-3" />
                    Ask about this gap
                  </Button>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
