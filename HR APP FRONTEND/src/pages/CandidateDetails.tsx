import React, { useState, useEffect } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import {
  Dialog, DialogContent, DialogHeader,
  DialogTitle, DialogDescription, DialogFooter,
} from "@/components/ui/dialog";
import {
  ArrowLeft, Mail, Phone, FileText, Download,
  GraduationCap, Briefcase, Code2, BarChart3,
  Calendar, Star, CheckCircle2, XCircle, AlertCircle,
  MapPin, Clock, ChevronDown, ChevronUp, Send, Sparkles,
  CalendarOff, MessageSquarePlus, RefreshCw,
} from "lucide-react";
import { toast } from "sonner";
import {
  getCandidate,
  downloadResume,
  draftCandidateEmail,
  sendCandidateEmail,
  refreshJobJDSimilarity,
} from "@/services/candidates";
import { getJob } from "@/services/jobs";
import { QuizResultModal } from "@/components/QuizResultModal";
import {
  scoreColor,
  scoreBg,
  scoreText,
  ScoreArc,
  ScoreBar,
  TAG_STYLES,
  SectionHeader,
  CareerTimeline,
} from "@/components/candidate-details/sections";
import {
  RadarChart, Radar, PolarGrid, PolarAngleAxis,
  ResponsiveContainer,
} from "recharts";

export interface ScoreBreakdown {
  ai_score_used?: boolean;
  hire_recommendation?: string;
  reasoning?: string;
  standout_factors?: string[];
  red_flags?: string[];
  candidate_tier?: string;
  [key: string]: any;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

// Candidate detail section components were extracted to /components/candidate-details/sections.tsx

export default function CandidateDetails() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [candidate, setCandidate] = useState<any>(null);
  const [job, setJob] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [downloading, setDownloading] = useState(false);
  const [showAllSkills, setShowAllSkills] = useState(false);
  const [refreshingSimilarity, setRefreshingSimilarity] = useState(false);

  // Contact email modal
  const [contactOpen, setContactOpen] = useState(false);
  const [emailSubject, setEmailSubject] = useState("");
  const [emailBody, setEmailBody] = useState("");
  const [generatingAI, setGeneratingAI] = useState(false);
  const [sendingEmail, setSendingEmail] = useState(false);

  useEffect(() => {
    if (!id) return;
    (async () => {
      try {
        const data = await getCandidate(id);
        setCandidate(data);
        if (data.job_id) {
          try { setJob(await getJob(data.job_id)); } catch { /* optional */ }
        }
      } catch {
        toast.error("Candidate not found");
        navigate("/candidates");
      } finally {
        setLoading(false);
      }
    })();
  }, [id, navigate]);

  const handleOpenContact = () => { setEmailSubject(""); setEmailBody(""); setContactOpen(true); };

  // Pre-fill the contact email to ask about a specific gap
  const handleAskAboutGap = (gap: any) => {
    const dateRange = gap.dateRange ?? `${gap.start ?? ""} → ${gap.end ?? ""}`;
    setEmailSubject(`Quick question about your career timeline — ${dateRange}`);
    setEmailBody(
      `Hi ${candidate?.name?.split(" ")[0] ?? "there"},\n\n` +
      `Thank you for applying for the ${job?.title ?? "role"} position.\n\n` +
      `We noticed a career break in your timeline around ${dateRange} (approx. ${gap.durationMonths ?? gap.duration_months ?? "?"} months). ` +
      `We'd love to hear about what you were doing during that period — any personal projects, ` +
      `learning, or other activities are absolutely welcome.\n\n` +
      `Please feel free to reply to this email with any context you'd like to share.\n\n` +
      `Best regards,\n${job?.title ? `The ${job.title} Hiring Team` : "The Hiring Team"}`
    );
    setContactOpen(true);
  };

  const handleGenerateAI = async () => {
    if (!candidate?.id) return;
    setGeneratingAI(true);
    toast.info("AI is drafting your email…");
    try {
      const data = await draftCandidateEmail(candidate.id, "invite");
      setEmailSubject(data.subject || "");
      setEmailBody(data.body || "");
      toast.success("AI draft ready — feel free to edit it");
    } catch {
      toast.error("Failed to generate AI draft");
    } finally {
      setGeneratingAI(false);
    }
  };

  const handleSendEmail = async () => {
    if (!candidate?.id || !emailSubject.trim() || !emailBody.trim()) {
      toast.error("Subject and body are required");
      return;
    }
    setSendingEmail(true);
    try {
      await sendCandidateEmail(candidate.id, emailSubject, emailBody);
      toast.success("Email sent successfully!");
      setContactOpen(false);
    } catch {
      toast.error("Failed to send email");
    } finally {
      setSendingEmail(false);
    }
  };

  const handleDownload = async () => {
    if (!candidate?.id) return;
    setDownloading(true);
    try {
      const blob = await downloadResume(candidate.id);
      const url = window.URL.createObjectURL(new Blob([blob]));
      const a = document.createElement("a");
      a.href = url;
      a.download = `${(candidate.name || "Candidate").replace(/\s+/g, "_")}_Resume.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
      toast.success("Resume downloaded");
    } catch (err: any) {
      toast.error(err?.response?.status === 404 ? "File not found on server." : "Download failed.");
    } finally {
      setDownloading(false);
    }
  };

  const handleRefreshSimilarity = async () => {
    const jobId = candidate?.job_id;
    if (!jobId || !id) return;

    setRefreshingSimilarity(true);
    try {
      const result = await refreshJobJDSimilarity(jobId, {
        limit: 500,
        includeArchived: false,
      });
      const updatedCount = Number(result?.updated ?? 0);
      toast.success(
        `JD similarity refresh done. Updated ${updatedCount} candidate${updatedCount === 1 ? "" : "s"}.`
      );

      const updatedCandidate = await getCandidate(id);
      setCandidate(updatedCandidate);
    } catch (err: any) {
      const detail =
        err?.response?.data?.detail ||
        err?.message ||
        "Failed to refresh JD similarity.";
      toast.error(String(detail));
    } finally {
      setRefreshingSimilarity(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="flex flex-col items-center gap-3">
          <div className="animate-spin rounded-full h-8 w-8 border-2 border-primary border-t-transparent" />
          <span className="text-sm text-muted-foreground">Loading profile…</span>
        </div>
      </div>
    );
  }
  if (!candidate) return null;

  // ── Normalise ─────────────────────────────────────────────────────────────
  const skills: string[] = Array.isArray(candidate.skills)
    ? candidate.skills
    : typeof candidate.skills === "string"
      ? (() => { try { return JSON.parse(candidate.skills); } catch { return []; } })()
      : [];
  const scoreBreakdown: ScoreBreakdown = (candidate.score_breakdown || {}) as ScoreBreakdown;
  const matchedMustFromBackend: string[] = Array.isArray(scoreBreakdown.matched_must_have)
    ? scoreBreakdown.matched_must_have
    : [];
  const missingMustFromBackend: string[] = Array.isArray(scoreBreakdown.missing_must_have)
    ? scoreBreakdown.missing_must_have
    : [];
  const matchedNiceFromBackend: string[] = Array.isArray(scoreBreakdown.matched_good_to_have)
    ? scoreBreakdown.matched_good_to_have
    : [];
  const hasBackendSkillBreakdown =
    matchedMustFromBackend.length > 0 ||
    missingMustFromBackend.length > 0 ||
    matchedNiceFromBackend.length > 0;
  const matchedMustSet = new Set(matchedMustFromBackend.map((s: string) => s.toLowerCase().trim()));
  const matchedNiceSet = new Set(matchedNiceFromBackend.map((s: string) => s.toLowerCase().trim()));
  const education: any[] = Array.isArray(candidate.education) ? candidate.education : [];
  const projects: any[] = Array.isArray(candidate.projects) ? candidate.projects : [];
  const workExperience: any[] = Array.isArray(candidate.work_experience) ? candidate.work_experience : [];
  const careerBreaks: any[] = Array.isArray(candidate.career_breaks) ? candidate.career_breaks : [];

  const mustHave: string[] = job?.must_have_skills || [];
  const niceToHave: string[] = job?.good_to_have_skills || [];

  const expOk = job
    ? candidate.experience_years >= (job.experience_min ?? 0) &&
      (job.experience_max == null || candidate.experience_years <= job.experience_max)
    : null;

  const tag = candidate.tag as string;
  const tagStyle = TAG_STYLES[tag];
  const resumeScore = Math.round(candidate.resume_score ?? 0);

  const radarData = [
    { subject: "Skills",     value: Math.round(candidate.skill_match_pct ?? 0) },
    { subject: "Experience", value: Math.round(candidate.experience_match_pct ?? 0) },
    { subject: "Projects",   value: Math.round(candidate.project_relevance_pct ?? 0) },
    { subject: "Education",  value: Math.round(candidate.education_match_pct ?? 0) },
    ...(candidate.location_match_pct != null
      ? [{ subject: "Location", value: Math.round(candidate.location_match_pct) }]
      : []),
  ];

  const classifySkill = (skill: string) => {
    const key = (skill || "").toLowerCase().trim();
    if (matchedMustSet.has(key)) return "required";
    if (matchedNiceSet.has(key)) return "nice";
    return "neutral";
  };

  const SKILLS_VISIBLE = 20;
  const visibleSkills = showAllSkills ? skills : skills.slice(0, SKILLS_VISIBLE);

  // Count unaddressed gaps for badge
  const unaddressedGaps = careerBreaks.filter((b) => {
    const months = Number(b?.duration_months ?? b?.durationMonths ?? 0);
    return !b?.reason && Number.isFinite(months) && months >= 6;
  });
  const hasLegacyMissingSimilarity =
    !scoreBreakdown.ai_score_used &&
    (candidate.vector_similarity == null || Number(candidate.vector_similarity) === 0) &&
    !Object.prototype.hasOwnProperty.call(scoreBreakdown, "jd_hash");

  const jdSimilarityUnavailable = Boolean(
    !scoreBreakdown.ai_score_used &&
    (scoreBreakdown.fast_mode === true || scoreBreakdown.degraded_mode === true || hasLegacyMissingSimilarity)
  );

  return (
    <div className="max-w-6xl mx-auto space-y-0 pb-16">

      {/* ── Top nav ───────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between gap-4 mb-6 pt-1">
        <Button asChild variant="ghost" size="sm" className="gap-1.5 text-muted-foreground hover:text-foreground">
          <Link to="/candidates">
            <ArrowLeft className="h-4 w-4" />
            All Candidates
          </Link>
        </Button>
        <div className="flex items-center gap-2">
          {candidate.email && (
            <Button variant="outline" size="sm" className="gap-1.5" onClick={handleOpenContact}>
              <Mail className="h-3.5 w-3.5" />
              Contact
            </Button>
          )}
          <Button size="sm" variant="outline" onClick={handleDownload} disabled={downloading} className="gap-1.5">
            <Download className="h-3.5 w-3.5" />
            {downloading ? "Downloading…" : "Download Resume"}
          </Button>
          {candidate.quiz_score !== null && candidate.quiz_score !== undefined && (
            <QuizResultModal candidateId={candidate.id} candidateName={candidate.name} quizScore={candidate.quiz_score} />
          )}
        </div>
      </div>

      {/* ── Hero ──────────────────────────────────────────────────────────── */}
      <div className="rounded-2xl border bg-card p-6 mb-6">
        <div className="flex items-start gap-6 flex-wrap">
          <div className="shrink-0">
            <div className={`w-16 h-16 rounded-2xl flex items-center justify-center text-2xl font-bold ${scoreBg(resumeScore)} ${scoreText(resumeScore)}`}>
              {(candidate.name || "?")[0].toUpperCase()}
            </div>
          </div>
          <div className="flex-1 min-w-0 space-y-3">
            <div>
              <div className="flex items-center gap-3 flex-wrap">
                <h1 className="text-2xl font-bold tracking-tight">{candidate.name || "Unknown Candidate"}</h1>
                {tag && tagStyle && (
                  <span className={`text-xs font-semibold px-2.5 py-1 rounded-full ${tagStyle.badge}`}>{tag}</span>
                )}
                {candidate.rank && (
                  <span className="text-xs text-muted-foreground border px-2.5 py-1 rounded-full">Rank #{candidate.rank}</span>
                )}
                {/* Gap badge — draws recruiter attention */}
                {unaddressedGaps.length > 0 && (
                  <span className="text-xs font-semibold px-2.5 py-1 rounded-full bg-amber-100 text-amber-700 border border-amber-200 dark:bg-amber-900/30 dark:text-amber-300 dark:border-amber-800 flex items-center gap-1">
                    <CalendarOff className="h-3 w-3" />
                    {unaddressedGaps.length} gap{unaddressedGaps.length > 1 ? "s" : ""} in timeline
                  </span>
                )}
              </div>
              {job && (
                <p className="text-sm text-muted-foreground mt-1 flex items-center gap-1.5">
                  <Briefcase className="h-3.5 w-3.5 shrink-0" />
                  Applied for <span className="font-medium text-foreground">{job.title}</span>
                  {job.location && (<><span className="text-muted-foreground/40">·</span><MapPin className="h-3 w-3 shrink-0" />{job.location}</>)}
                </p>
              )}
            </div>
            <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm text-muted-foreground">
              {candidate.email && (
                <a href={`mailto:${candidate.email}`} className="flex items-center gap-1.5 hover:text-foreground transition-colors">
                  <Mail className="h-3.5 w-3.5 shrink-0" />{candidate.email}
                </a>
              )}
              {candidate.phone && (
                <span className="flex items-center gap-1.5"><Phone className="h-3.5 w-3.5 shrink-0" />{candidate.phone}</span>
              )}
              {candidate.experience_years != null && (
                <span className="flex items-center gap-1.5">
                  <Clock className="h-3.5 w-3.5 shrink-0" />
                  {candidate.experience_years} yr{candidate.experience_years !== 1 ? "s" : ""} experience
                </span>
              )}
              <span className="flex items-center gap-1.5">
                <Calendar className="h-3.5 w-3.5 shrink-0" />
                Added {new Date(candidate.created_at).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" })}
              </span>
            </div>
          </div>
          <div className="shrink-0 flex flex-col items-center gap-1 text-center">
            <ScoreArc value={resumeScore} size={100} />
            <span className="text-xs text-muted-foreground font-medium">Resume Match</span>
          </div>
        </div>
      </div>

      {/* ── Two-column grid ────────────────────────────────────────────────── */}
      <div className="grid gap-6 lg:grid-cols-3">

        {/* ══ LEFT SIDEBAR ════════════════════════════════════════════════ */}
        <div className="space-y-5">

          {/* Score breakdown */}
          <div className="rounded-2xl border bg-card p-5">
            <SectionHeader
              icon={BarChart3}
              title="Score Breakdown"
              right={
                candidate.score_breakdown?.ai_score_used ? (
                  <span className="inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-300 border border-violet-200 dark:border-violet-800">
                    <Sparkles className="h-2.5 w-2.5" />AI Scored
                  </span>
                ) : (
                  <span className="text-[10px] text-muted-foreground">Rule-based</span>
                )
              }
            />
            <div className="space-y-3.5">
              <ScoreBar label="Skill Match"  value={candidate.skill_match_pct ?? 0} />
              <ScoreBar label="Experience"   value={candidate.experience_match_pct ?? 0} />
              <ScoreBar label="Projects"     value={candidate.project_relevance_pct ?? 0} />
              <ScoreBar label="Education"    value={candidate.education_match_pct ?? 0} />
              {candidate.location_match_pct != null && (
                <ScoreBar label="Location"   value={candidate.location_match_pct} />
              )}
              {!(candidate.score_breakdown?.ai_score_used) && (
                jdSimilarityUnavailable ? (
                  <div className="space-y-1.5">
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-muted-foreground">JD Similarity</span>
                      <span className="font-semibold tabular-nums text-amber-600 dark:text-amber-400">
                        N/A
                      </span>
                    </div>
                    <p className="text-xs text-muted-foreground">
                      AI was in degraded mode during upload. Run JD similarity refresh to compute this value.
                    </p>
                    {candidate?.job_id && (
                      <div className="pt-1">
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          onClick={handleRefreshSimilarity}
                          disabled={refreshingSimilarity}
                          className="h-7 text-xs"
                        >
                          <RefreshCw className={`mr-1.5 h-3.5 w-3.5 ${refreshingSimilarity ? "animate-spin" : ""}`} />
                          {refreshingSimilarity ? "Refreshing..." : "Refresh JD Similarity"}
                        </Button>
                      </div>
                    )}
                  </div>
                ) : (
                  <ScoreBar label="JD Similarity" value={(candidate.vector_similarity ?? 0) * 100} />
                )
              )}
              {candidate.score_breakdown?.candidate_tier && (
                <div className="flex items-center justify-between text-xs pt-1 border-t mt-1">
                  <span className="text-muted-foreground">Scoring Tier</span>
                  <span className={`font-semibold capitalize px-2 py-0.5 rounded-full text-[11px] ${
                    candidate.score_breakdown.candidate_tier === "fresher"
                      ? "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300"
                      : candidate.score_breakdown.candidate_tier === "mid"
                      ? "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300"
                      : "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300"
                  }`}>
                    {candidate.score_breakdown.candidate_tier}
                  </span>
                </div>
              )}
            </div>

            {/* AI panel */}
            {candidate.score_breakdown?.ai_score_used && (
              <div className="mt-4 pt-4 border-t space-y-3">
                {candidate.score_breakdown?.hire_recommendation && (
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Verdict</span>
                    <span className={`text-[11px] font-semibold px-2.5 py-0.5 rounded-full capitalize ${
                      candidate.score_breakdown.hire_recommendation === "strong_hire"
                        ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300"
                        : candidate.score_breakdown.hire_recommendation === "hire"
                        ? "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300"
                        : candidate.score_breakdown.hire_recommendation === "no_hire"
                        ? "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300"
                        : candidate.score_breakdown.hire_recommendation === "strong_no_hire"
                        ? "bg-red-200 text-red-900 dark:bg-red-900/50 dark:text-red-200"
                        : "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300"
                    }`}>
                      {candidate.score_breakdown.hire_recommendation.replace(/_/g, " ")}
                    </span>
                  </div>
                )}
                {candidate.score_breakdown?.reasoning && (
                  <div>
                    <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-1.5 flex items-center gap-1">
                      <Sparkles className="h-2.5 w-2.5" />AI Assessment
                    </p>
                    <p className="text-xs text-muted-foreground leading-relaxed">{candidate.score_breakdown.reasoning}</p>
                  </div>
                )}
                {(candidate.score_breakdown?.standout_factors ?? []).length > 0 && (
                  <div>
                    <p className="text-[10px] font-semibold uppercase tracking-wider text-emerald-600 dark:text-emerald-400 mb-1.5 flex items-center gap-1">
                      <CheckCircle2 className="h-2.5 w-2.5" />Standout Factors
                    </p>
                    <ul className="space-y-1">
                      {(candidate.score_breakdown?.standout_factors || []).map((f: string, i: number) => (
                        <li key={i} className="text-xs text-muted-foreground flex items-start gap-1.5">
                          <span className="text-emerald-500 mt-0.5 shrink-0">✓</span>{f}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {(candidate.score_breakdown?.red_flags ?? []).length > 0 && (
                  <div>
                    <p className="text-[10px] font-semibold uppercase tracking-wider text-red-600 dark:text-red-400 mb-1.5 flex items-center gap-1">
                      <AlertCircle className="h-2.5 w-2.5" />Red Flags
                    </p>
                    <ul className="space-y-1">
                      {(candidate.score_breakdown?.red_flags || []).map((f: string, i: number) => (
                        <li key={i} className="text-xs text-muted-foreground flex items-start gap-1.5">
                          <span className="text-red-500 mt-0.5 shrink-0">!</span>{f}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}

            {(candidate.quiz_score != null || candidate.final_score != null) && (
              <div className="mt-4 pt-4 border-t space-y-2.5">
                {candidate.quiz_score != null && (
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-muted-foreground">Quiz Score</span>
                    <span className="font-semibold">{candidate.quiz_score}</span>
                  </div>
                )}
                {candidate.final_score != null && (
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-muted-foreground">Final Score</span>
                    <span className={`font-bold text-base ${scoreText(candidate.final_score)}`}>{candidate.final_score}%</span>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Radar */}
          <div className="rounded-2xl border bg-card p-5">
            <SectionHeader icon={Star} title="Radar" right={
              job && <span className="text-xs text-muted-foreground">vs {job.title}</span>
            } />
            <ResponsiveContainer width="100%" height={200}>
              <RadarChart data={radarData} margin={{ top: 5, right: 15, bottom: 5, left: 15 }}>
                <PolarGrid stroke="hsl(var(--border))" />
                <PolarAngleAxis dataKey="subject" tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }} />
                <Radar dataKey="value" stroke="hsl(var(--primary))" fill="hsl(var(--primary))" fillOpacity={0.15} strokeWidth={2} />
              </RadarChart>
            </ResponsiveContainer>
          </div>

          {/* Education */}
          {education.length > 0 && (
            <div className="rounded-2xl border bg-card p-5">
              <SectionHeader icon={GraduationCap} title="Education" />
              <div className="space-y-4">
                {education.map((edu: any, i: number) => (
                  <div key={i} className="pl-4 border-l-2 border-border relative">
                    <div className="absolute -left-[5px] top-1.5 w-2.5 h-2.5 rounded-full bg-primary ring-2 ring-background" />
                    <p className="font-semibold text-sm leading-snug">{edu.degree || "Degree"}</p>
                    <p className="text-sm text-muted-foreground mt-0.5">{edu.institute || edu.institution || "Institution not specified"}</p>
                    <div className="flex items-center gap-2 mt-1.5 flex-wrap">
                      {edu.year && <span className="text-xs text-muted-foreground">{edu.year}</span>}
                      {edu.gpa && <span className="text-xs bg-muted px-2 py-0.5 rounded-full font-medium">GPA {edu.gpa}</span>}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Resume file */}
          <div className="rounded-2xl border bg-card p-5">
            <SectionHeader icon={FileText} title="Resume File" />
            <button onClick={handleDownload}
              className="w-full flex items-center gap-3 p-3 rounded-xl border bg-muted/30 hover:bg-muted/60 transition-colors group text-left">
              <div className="p-2 rounded-lg bg-background border shrink-0">
                <FileText className="h-5 w-5 text-primary" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium truncate">
                  {(candidate.name || "Candidate").replace(/\s+/g, "_")}_Resume.pdf
                </p>
                <p className="text-xs text-muted-foreground mt-0.5">Click to download</p>
              </div>
              <Download className="h-4 w-4 text-muted-foreground group-hover:text-foreground transition-colors shrink-0" />
            </button>
          </div>
        </div>

        {/* ══ MAIN CONTENT ════════════════════════════════════════════════ */}
        <div className="lg:col-span-2 space-y-5">

          {/* Job fit verdict */}
          {job && (() => {
            const breakdown = candidate.score_breakdown;
            const useBackendSkills =
              Array.isArray(breakdown?.matched_must_have) &&
              Array.isArray(breakdown?.missing_must_have);
            const aiMatchedMust: string[] = useBackendSkills ? breakdown.matched_must_have : [];
            const aiMissingMust: string[] = useBackendSkills ? breakdown.missing_must_have : [];
            const aiMatchedNice: string[] = useBackendSkills && Array.isArray(breakdown?.matched_good_to_have)
              ? breakdown.matched_good_to_have : [];

            const metCount  = aiMatchedMust.length;
            const totalMust = mustHave.length;
            const isStrong  = tag === "Strong";
            const isMedium  = tag === "Medium";
            const color     = isStrong ? "emerald" : isMedium ? "amber" : "red";
            const FitIcon   = isStrong ? CheckCircle2 : isMedium ? AlertCircle : XCircle;
            const fitLabel  = isStrong ? "Strong Fit" : isMedium ? "Partial Fit" : "Not a Fit";

            return (
              <div className={`rounded-2xl border p-5 bg-${color}-50/50 dark:bg-${color}-950/20 border-${color}-200 dark:border-${color}-800`}>
                <div className={`flex items-center gap-2 mb-4 text-${color}-700 dark:text-${color}-400`}>
                  <FitIcon className="h-5 w-5 shrink-0" />
                  <span className="font-semibold">{fitLabel}</span>
                  {useBackendSkills && (
                    <span className="inline-flex items-center gap-0.5 text-[10px] font-semibold px-1.5 py-0.5 rounded-full bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-300">
                      <Sparkles className="h-2.5 w-2.5" />AI
                    </span>
                  )}
                  {totalMust > 0 && (
                    <span className="ml-auto text-xs font-normal text-muted-foreground">
                      {metCount}/{totalMust} required skills matched
                    </span>
                  )}
                </div>

                <div className="flex items-center justify-between py-2.5 border-b text-sm">
                  <span className="text-muted-foreground">Experience required</span>
                  <span className={`font-medium flex items-center gap-1.5 ${expOk ? "text-emerald-600 dark:text-emerald-400" : "text-red-500"}`}>
                    {expOk ? <CheckCircle2 className="h-3.5 w-3.5" /> : <XCircle className="h-3.5 w-3.5" />}
                    {job.experience_min}–{job.experience_max ?? "∞"} yrs
                    {!expOk && ` (has ${candidate.experience_years})`}
                  </span>
                </div>

                {useBackendSkills && mustHave.length > 0 && (
                  <div className="pt-3 space-y-2">
                    <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Required Skills</p>
                    <div className="flex flex-wrap gap-1.5">
                      {aiMatchedMust.map((skill: string, i: number) => (
                        <span key={`m-${i}`} className="inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-full font-medium bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300">
                          <CheckCircle2 className="h-3 w-3 shrink-0" />{skill}
                        </span>
                      ))}
                      {aiMissingMust.map((skill: string, i: number) => (
                        <span key={`x-${i}`} className="inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-full font-medium bg-red-100 text-red-600 dark:bg-red-900/30 dark:text-red-400">
                          <XCircle className="h-3 w-3 shrink-0" />{skill}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {!useBackendSkills && mustHave.length > 0 && (
                  <div className="pt-3 space-y-2">
                    <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Required Skills</p>
                    <p className="text-xs text-muted-foreground">Backend skill breakdown unavailable for this candidate.</p>
                  </div>
                )}

                {useBackendSkills && niceToHave.length > 0 && aiMatchedNice.length > 0 && (
                  <div className="pt-3 space-y-2">
                    <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                      Nice-to-have <span className="font-normal normal-case">({aiMatchedNice.length}/{niceToHave.length} matched)</span>
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                      {niceToHave.map((skill: string, i: number) => {
                        const matched = aiMatchedNice.some((s: string) =>
                          s.toLowerCase().includes(skill.toLowerCase()) || skill.toLowerCase().includes(s.toLowerCase()));
                        return (
                          <span key={i} className={`text-xs px-2.5 py-1 rounded-full ${
                            matched ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300"
                                    : "bg-muted text-muted-foreground"
                          }`}>{skill}</span>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
            );
          })()}

          {/* ── Career Timeline ── NEW ──────────────────────────────────── */}
          {(workExperience.length > 0 || careerBreaks.length > 0) && (
            <CareerTimeline
              workExp={workExperience}
              careerBreaks={careerBreaks}

              onAskAboutGap={handleAskAboutGap}
            />
          )}

          {/* Skills */}
          {skills.length > 0 && (
            <div className="rounded-2xl border bg-card p-5">
              <SectionHeader icon={Code2} title="Skills"
                right={<Badge variant="secondary" className="font-normal text-xs">{skills.length} found</Badge>} />
              <div className="flex flex-wrap gap-2">
                {visibleSkills.map((skill: string, i: number) => {
                  const cls = classifySkill(skill);
                  return (
                    <span key={i} className={`inline-flex items-center px-3 py-1.5 rounded-full text-xs font-medium border transition-colors ${
                      cls === "required"
                        ? "bg-emerald-100 text-emerald-700 border-emerald-200 dark:bg-emerald-900/30 dark:text-emerald-300 dark:border-emerald-800"
                        : cls === "nice"
                          ? "bg-blue-100 text-blue-700 border-blue-200 dark:bg-blue-900/30 dark:text-blue-300 dark:border-blue-800"
                          : "bg-secondary/60 text-secondary-foreground border-border/40 hover:bg-secondary"
                    }`}>{skill}</span>
                  );
                })}
              </div>
              {skills.length > SKILLS_VISIBLE && (
                <button onClick={() => setShowAllSkills(p => !p)}
                  className="mt-3 flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors">
                  {showAllSkills
                    ? <><ChevronUp className="h-3.5 w-3.5" /> Show less</>
                    : <><ChevronDown className="h-3.5 w-3.5" /> Show {skills.length - SKILLS_VISIBLE} more skills</>}
                </button>
              )}
              {job && hasBackendSkillBreakdown && (mustHave.length > 0 || niceToHave.length > 0) && (
                <div className="flex flex-wrap gap-4 mt-3 pt-3 border-t text-xs text-muted-foreground">
                  <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-emerald-400 inline-block" />Required match</span>
                  <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-blue-400 inline-block" />Nice-to-have</span>
                </div>
              )}
            </div>
          )}

          {/* Projects */}
          {projects.length > 0 && (
            <div className="rounded-2xl border bg-card p-5">
              <SectionHeader icon={Briefcase} title="Projects"
                right={<Badge variant="secondary" className="font-normal text-xs">{projects.length} listed</Badge>} />
              <div className="space-y-4">
                {projects.map((project: any, i: number) => (
                  <div key={i} className="p-4 rounded-xl border bg-muted/20 space-y-3">
                    <div className="flex items-start gap-3">
                      <div className="w-7 h-7 rounded-lg bg-primary/10 flex items-center justify-center shrink-0 mt-0.5">
                        <span className="text-xs font-bold text-primary">{i + 1}</span>
                      </div>
                      <div className="flex-1 min-w-0">
                        <h4 className="font-semibold text-sm leading-snug">{project.title || `Project ${i + 1}`}</h4>
                        {project.description && (
                          <p className="text-sm text-muted-foreground mt-1.5 leading-relaxed">{project.description}</p>
                        )}
                      </div>
                    </div>
                    {project.skills && project.skills.length > 0 && (
                      <div className="flex flex-wrap gap-1.5 pl-10">
                        {project.skills.slice(0, 6).map((s: string, si: number) => (
                          <span key={si} className="text-[11px] px-2 py-0.5 rounded-full bg-primary/8 text-primary font-medium border border-primary/15">{s}</span>
                        ))}
                        {project.skills.length > 6 && (
                          <span className="text-[11px] px-2 py-0.5 rounded-full bg-muted text-muted-foreground">+{project.skills.length - 6} more</span>
                        )}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Empty state */}
          {skills.length === 0 && projects.length === 0 && education.length === 0 && workExperience.length === 0 && (
            <div className="rounded-2xl border border-dashed p-12 text-center bg-card">
              <FileText className="h-10 w-10 mx-auto text-muted-foreground/30 mb-3" />
              <p className="text-sm text-muted-foreground">Limited structured data extracted from this resume.</p>
              <p className="text-xs text-muted-foreground mt-1">Download the original file to view the full document.</p>
              <Button variant="outline" className="mt-5" onClick={handleDownload}>
                <Download className="mr-2 h-4 w-4" />Download Resume
              </Button>
            </div>
          )}
        </div>
      </div>

      {/* ── Contact Email Modal ────────────────────────────────────────────── */}
      <Dialog open={contactOpen} onOpenChange={setContactOpen}>
        <DialogContent className="sm:max-w-[580px] p-0 gap-0 overflow-hidden">
          <DialogHeader className="px-6 pt-6 pb-4 border-b">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-lg bg-primary/10 flex-shrink-0">
                <Mail className="h-5 w-5 text-primary" />
              </div>
              <div>
                <DialogTitle className="text-base">Contact Candidate</DialogTitle>
                <DialogDescription className="text-xs mt-0.5">
                  To: <span className="font-medium text-foreground">{candidate?.name}</span>
                  {" · "}<span className="text-muted-foreground">{candidate?.email}</span>
                </DialogDescription>
              </div>
            </div>
          </DialogHeader>

          <div className="px-6 py-5 space-y-4">
            <div className="flex items-center justify-between rounded-xl border border-dashed bg-muted/30 px-4 py-3">
              <div className="flex items-center gap-2.5">
                <Sparkles className="h-4 w-4 text-primary flex-shrink-0" />
                <div>
                  <p className="text-sm font-medium">Generate with AI</p>
                  <p className="text-xs text-muted-foreground">Auto-draft a personalised invite email</p>
                </div>
              </div>
              <Button size="sm" variant="secondary" onClick={handleGenerateAI} disabled={generatingAI} className="flex-shrink-0">
                {generatingAI
                  ? <span className="flex items-center gap-1.5"><span className="animate-spin rounded-full h-3 w-3 border-b-2 border-current" />Generating…</span>
                  : <span className="flex items-center gap-1.5"><Sparkles className="h-3.5 w-3.5" />Generate Draft</span>}
              </Button>
            </div>

            <div className="space-y-1.5">
              <Label className="text-sm">Subject</Label>
              <Input placeholder="e.g. Interview Invitation — Net Core Developer"
                value={emailSubject} onChange={e => setEmailSubject(e.target.value)} />
            </div>

            <div className="space-y-1.5">
              <Label className="text-sm">Message</Label>
              <Textarea
                placeholder="Write your message here, or click 'Generate Draft' to let AI write it for you…"
                value={emailBody} onChange={e => setEmailBody(e.target.value)}
                className="min-h-[200px] resize-none text-sm" />
            </div>
          </div>

          <DialogFooter className="px-6 py-4 border-t bg-muted/20 flex items-center justify-between gap-3">
            <span className="text-xs text-muted-foreground">
              {emailBody.length > 0 ? `${emailBody.length} characters` : "No message yet"}
            </span>
            <div className="flex items-center gap-2">
              <Button variant="outline" size="sm" onClick={() => setContactOpen(false)}>Cancel</Button>
              <Button size="sm" onClick={handleSendEmail}
                disabled={sendingEmail || !emailSubject.trim() || !emailBody.trim()}>
                {sendingEmail
                  ? <span className="flex items-center gap-1.5"><span className="animate-spin rounded-full h-3 w-3 border-b-2 border-current" />Sending…</span>
                  : <span className="flex items-center gap-1.5"><Send className="h-3.5 w-3.5" />Send Email</span>}
              </Button>
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}


