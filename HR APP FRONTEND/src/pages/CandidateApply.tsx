import React, { useState, useEffect } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  ArrowLeft, MapPin, Briefcase, Clock, Upload, CheckCircle2,
  AlertCircle, XCircle, Loader2, CalendarOff, ChevronDown, ChevronUp,
} from "lucide-react";
import { toast } from "sonner";
import { getPublicJob, applyToJob } from "@/services/candidatePortal";
import { cn } from "@/lib/utils";
import { useCandidateApplication } from "@/hooks/useCandidateApplication";

// ─── Career break reason options (aligned with PDF recommendation) ────────────
const BREAK_REASONS = [
  { value: "upskilling",    label: "Upskilling / Education" },
  { value: "caregiving",    label: "Caregiving / Family" },
  { value: "medical",       label: "Medical / Health" },
  { value: "relocation",    label: "Relocation" },
  { value: "personal",      label: "Personal / Sabbatical" },
  { value: "job_search",    label: "Job Search" },
  { value: "layoff",        label: "Layoff / Company closure" },
  { value: "other",         label: "Other" },
];
// Must stay in sync with MAX_FILE_SIZE_BYTES in app/config.py
const MAX_RESUME_SIZE_BYTES = 20 * 1024 * 1024;

interface CareerBreak {
  start: string;
  end: string;
  duration_months: number;
  reason: string | null;
  notes: string | null;
}

// ─── CareerBreakCard ──────────────────────────────────────────────────────────
function CareerBreakCard({
  gap, index, onChange,
}: {
  key?: React.Key;
  gap: CareerBreak;
  index: number;
  onChange: (i: number, updated: Partial<CareerBreak>) => void;
}) {
  const [expanded, setExpanded] = useState(true);

  return (
    <div className="rounded-lg border border-amber-200 dark:border-amber-800 bg-amber-50/60 dark:bg-amber-950/20 p-3 space-y-2">
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="w-full h-auto flex items-center justify-between gap-2 text-left"
        aria-expanded={expanded}
        aria-label={`Toggle career break details for gap ${gap.start} to ${gap.end}`}
        onClick={() => setExpanded(p => !p)}
      >
        <div className="flex items-center gap-2">
          <CalendarOff className="h-4 w-4 text-amber-600 shrink-0" />
          <span className="text-sm font-medium text-amber-800 dark:text-amber-300">
            Career break · {gap.start} → {gap.end}
          </span>
          <span className="text-xs text-amber-600 dark:text-amber-400">
            ({gap.duration_months} months)
          </span>
        </div>
        {expanded
          ? <ChevronUp className="h-3.5 w-3.5 text-amber-500 shrink-0" />
          : <ChevronDown className="h-3.5 w-3.5 text-amber-500 shrink-0" />}
      </Button>

      {expanded && (
        <div className="space-y-2 pt-1">
          <p className="text-xs text-muted-foreground">
            Optionally tell the recruiter what you were doing during this period.
            This context can only help — gaps are never penalised by our system.
          </p>

          {/* Reason dropdown */}
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">Reason (optional)</label>
            <select
              value={gap.reason ?? ""}
              onChange={e => onChange(index, { reason: e.target.value || null })}
              className="w-full rounded-md border border-input bg-background px-3 py-1.5 text-sm
                         focus:outline-none focus:ring-2 focus:ring-ring"
            >
              <option value="">Prefer not to say</option>
              {BREAK_REASONS.map(r => (
                <option key={r.value} value={r.value}>{r.label}</option>
              ))}
            </select>
          </div>

          {/* Notes */}
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">Additional context (optional)</label>
            <Textarea
              placeholder="e.g. Completed AWS certification, cared for a family member, freelanced..."
              value={gap.notes ?? ""}
              onChange={e => onChange(index, { notes: e.target.value || null })}
              className="min-h-[60px] resize-none text-xs"
            />
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Main Component ───────────────────────────────────────────────────────────
export default function CandidateApply() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { evaluateResume, getMyApplication, getStepStatus } = useCandidateApplication();
  const [job, setJob] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [applying, setApplying] = useState(false);
  const [evaluating, setEvaluating] = useState(false);
  const [evaluation, setEvaluation] = useState<any>(null);
  const [file, setFile] = useState<File | null>(null);
  const [hasApplied, setHasApplied] = useState(false);
  const [myApp, setMyApp] = useState<any>(null);

  // Career break context — populated from parsed resume, enriched by candidate
  const [careerBreaks, setCareerBreaks] = useState<CareerBreak[]>([]);

  useEffect(() => {
    if (!id) return;
    const fetchJob = async () => {
      try {
        const data = await getPublicJob(id);
        setJob(data);
        try {
          const app = await getMyApplication(id);
          if (app) { setHasApplied(true); setMyApp(app); }
        } catch (e) {}
      } catch (error) {
        toast.error("Job not found");
        navigate("/candidate/jobs");
      } finally {
        setLoading(false);
      }
    };
    fetchJob();
  }, [id, navigate, getMyApplication]);

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const selectedFile = e.target.files[0];
      if (selectedFile.size > MAX_RESUME_SIZE_BYTES) {
        toast.error("Resume file must be 20 MB or smaller.");
        e.target.value = "";
        return;
      }
      setFile(selectedFile);
      setEvaluation(null);
      setCareerBreaks([]);
      setEvaluating(true);
      try {
        const data = await evaluateResume(id!, selectedFile);
        setEvaluation(data);
        const careerBreaksData = data?.career_breaks ?? [];
        // Populate gap context cards from detected career breaks
        if (Array.isArray(careerBreaksData) && careerBreaksData.length > 0) {
          setCareerBreaks(careerBreaksData.map((b: any) => ({
            start:           b.start ?? "",
            end:             b.end ?? "",
            duration_months: b.duration_months ?? 0,
            reason:          null,
            notes:           null,
          })));
        }
      } catch (error) {
        toast.error("Failed to analyze resume. You can still apply directly.");
      } finally {
        setEvaluating(false);
      }
    }
  };

  const handleBreakChange = (i: number, updated: Partial<CareerBreak>) => {
    setCareerBreaks(prev => prev.map((b, idx) => idx === i ? { ...b, ...updated } : b));
  };

  const handleApply = async () => {
    if (applying) return;
    if (!file || !id) { toast.error("Please upload your resume first"); return; }
    setApplying(true);
    try {
      // Pass enriched career_breaks context with the application
      const formData = new FormData();
      formData.append("file", file);
      if (careerBreaks.length > 0) {
        formData.append("career_breaks", JSON.stringify(careerBreaks));
      }
      await applyToJob(id, file, careerBreaks.length > 0 ? careerBreaks : undefined);
      setHasApplied(true);
      toast.success("Application submitted successfully!");
      const app = await getMyApplication(id);
      if (app) setMyApp(app);
    } catch (error: any) {
      if (error.response?.status === 409) {
        setHasApplied(true);
        toast.info("Already applied. Application is under review.");
      } else {
        toast.error("Failed to submit application");
      }
    } finally {
      setApplying(false);
    }
  };

  const steps = [
    { title: "Application Review", desc: "AI Screening" },
    { title: "Skill Assessment",   desc: "Online Quiz" },
    { title: "Interview",          desc: "With Hiring Manager" },
    { title: "Offer",              desc: "Final Decision" },
  ];

  if (loading || !job) return <div className="p-8 text-center">Loading...</div>;

  return (
    <div className="space-y-6 w-full">
      <Button asChild variant="ghost" className="pl-0">
        <Link to="/candidate/jobs"><ArrowLeft className="mr-2 h-4 w-4" /> Back to Jobs</Link>
      </Button>

      <div className="grid gap-6 md:grid-cols-3">
        {/* ── Left: Job info ─────────────────────────────────────────── */}
        <div className="md:col-span-2 space-y-6">
          <div>
            <h1 className="text-3xl font-bold tracking-tight mb-2">{job.title}</h1>
            <div className="flex flex-wrap gap-3 text-sm text-muted-foreground">
              <span className="flex items-center gap-1"><MapPin className="h-4 w-4" /> {job.location || "Remote"}</span>
              <span className="flex items-center gap-1"><Briefcase className="h-4 w-4" /> {job.employment_type || "Full-time"}</span>
              <span className="flex items-center gap-1">
                <Clock className="h-4 w-4" />
                Posted {new Date(job.created_at).toLocaleDateString("en-GB", { day: "2-digit", month: "2-digit", year: "numeric" })}
              </span>
            </div>
          </div>

          <Card>
            <CardHeader><CardTitle>Job Description</CardTitle></CardHeader>
            <CardContent>
              <div className="prose dark:prose-invert max-w-none whitespace-pre-wrap text-sm leading-relaxed">
                {job.description}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>Required Skills</CardTitle></CardHeader>
            <CardContent>
              <div className="space-y-6">
                <div>
                  <h4 className="text-sm font-semibold mb-3 flex items-center gap-2">
                    <CheckCircle2 className="h-4 w-4 text-primary" /> Must Have
                  </h4>
                  <ul className="grid gap-2 sm:grid-cols-2">
                    {(job.must_have_skills || []).map((s: string) => (
                      <li key={s} className="flex items-start gap-2 text-sm text-muted-foreground">
                        <span className="mt-1.5 h-1.5 w-1.5 rounded-full bg-primary shrink-0" />
                        <span>{s}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* ── Gap policy notice ─────────────────────────────────── */}
          <div className="rounded-xl border border-blue-200 dark:border-blue-800 bg-blue-50/60 dark:bg-blue-950/20 px-4 py-3 flex items-start gap-3">
            <CalendarOff className="h-4 w-4 text-blue-500 shrink-0 mt-0.5" />
            <div className="text-xs text-blue-700 dark:text-blue-300 leading-relaxed">
              <span className="font-semibold">Career gaps are never penalised.</span>{" "}
              Our AI scores strictly on your skills and experience. If we detect a gap in your
              timeline, you'll get the option to add context — this can only work in your favour.
            </div>
          </div>
        </div>

        {/* ── Right: Apply card ──────────────────────────────────────── */}
        <div className="space-y-6 md:sticky md:top-24 h-fit">
          <Card>
            <CardHeader>
              <CardTitle>Apply Now</CardTitle>
              {!hasApplied && <CardDescription>Upload your resume to check your fit.</CardDescription>}
            </CardHeader>
            <CardContent className="space-y-4">
              {hasApplied ? (
                <div className="bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800 rounded-lg p-4 text-center space-y-2">
                  <CheckCircle2 className="h-8 w-8 text-emerald-600 mx-auto" />
                  <h3 className="font-semibold text-emerald-800 dark:text-emerald-300">Under Review</h3>
                  <Button asChild variant="outline" className="w-full mt-2">
                    <Link to="/candidate/dashboard">Go to Dashboard</Link>
                  </Button>
                  <Button asChild variant="ghost" className="w-full mt-1">
                    <Link to={`/candidate/feedback/${myApp?.candidate_id}`}>View Feedback →</Link>
                  </Button>
                </div>
              ) : evaluating ? (
                <div className="py-8 text-center space-y-4 border-2 border-dashed rounded-lg bg-muted/10">
                  <Loader2 className="h-8 w-8 animate-spin text-primary mx-auto" />
                  <p className="text-sm font-medium animate-pulse text-muted-foreground">
                    AI Screening your resume...
                  </p>
                </div>
              ) : evaluation ? (
                <div className="space-y-4">
                  {/* Match score */}
                  <div className="text-left border rounded-lg p-4 bg-muted/30 space-y-3">
                    <div className="flex justify-between items-center">
                      <span className="font-semibold text-sm">Match Score</span>
                      <span className={cn("font-bold", evaluation.match_score >= 60 ? "text-emerald-500" : "text-amber-500")}>
                        {evaluation.match_score}%
                      </span>
                    </div>
                    <Progress
                      value={evaluation.match_score}
                      className={cn("h-2", evaluation.match_score >= 60
                        ? "[&>div]:bg-emerald-500" : "[&>div]:bg-amber-500")}
                    />
                    {evaluation.missing_skills?.length > 0 ? (
                      <div className="p-3 bg-amber-500/10 border border-amber-500/20 rounded-md">
                        <p className="text-xs font-semibold text-amber-700 dark:text-amber-400 mb-1 flex items-center gap-1">
                          <AlertCircle className="h-3 w-3" /> Missing Skills Detected
                        </p>
                        <p className="text-xs text-muted-foreground mb-2">
                          Consider learning: <strong className="text-foreground">{evaluation.missing_skills.join(", ")}</strong>
                        </p>
                      </div>
                    ) : (
                      <div className="p-3 bg-emerald-500/10 border border-emerald-500/20 rounded-md">
                        <p className="text-xs font-semibold text-emerald-700 dark:text-emerald-400 mb-1 flex items-center gap-1">
                          <CheckCircle2 className="h-3 w-3" /> Great Fit!
                        </p>
                        <p className="text-xs text-muted-foreground">You have the core skills required.</p>
                      </div>
                    )}
                  </div>

                  {/* ── Career break context cards ─────────────────── */}
                  {careerBreaks.length > 0 && (
                    <div className="space-y-2">
                      <p className="text-xs font-semibold text-muted-foreground flex items-center gap-1.5">
                        <CalendarOff className="h-3.5 w-3.5 text-amber-500" />
                        Career break{careerBreaks.length > 1 ? "s" : ""} detected — add context (optional)
                      </p>
                      {careerBreaks.map((gap, i) => (
                        <CareerBreakCard key={i} gap={gap} index={i} onChange={handleBreakChange} />
                      ))}
                    </div>
                  )}

                  {/* Action buttons */}
                  <div className="flex gap-2">
                    <Button
                      variant="outline" className="flex-1 text-xs"
                      onClick={() => { setFile(null); setEvaluation(null); setCareerBreaks([]); }}
                    >
                      Change
                    </Button>
                    <Button className="flex-1 text-xs" onClick={handleApply} disabled={applying}>
                      {applying ? "Submitting..." : "Apply Now"}
                    </Button>
                  </div>
                </div>
              ) : (
                <Button
                  type="button"
                  variant="ghost"
                  aria-label="Upload resume file to evaluate match"
                  className="w-full h-auto border-2 border-dashed rounded-lg p-6 text-center cursor-pointer hover:border-primary/50 transition-colors"
                  onClick={() => document.getElementById("resume-upload")?.click()}
                >
                  <Input
                    id="resume-upload" type="file" className="hidden"
                    accept=".pdf,.doc,.docx,.png,.jpg,.jpeg,.webp,.tiff,.tif,.bmp,.gif" onChange={handleFileChange}
                  />
                  <div className="flex flex-col items-center gap-2">
                    <div className="p-2 rounded-full bg-primary/10 text-primary">
                      <Upload className="h-6 w-6" />
                    </div>
                    <div className="text-sm">
                      <p className="font-medium">Upload Resume to Check Fit</p>
                      <p className="text-xs text-muted-foreground">PDF, DOCX, DOC or image (Max 20MB)</p>
                    </div>
                  </div>
                </Button>
              )}
            </CardContent>
          </Card>

          {/* Hiring process stepper */}
          <Card>
            <CardHeader className="pb-3"><CardTitle className="text-sm">Hiring Process</CardTitle></CardHeader>
            <CardContent>
              <div className="space-y-6 relative">
                <div className="absolute left-[11px] top-3 bottom-3 w-0.5 bg-muted" />
                {steps.map((step, i) => {
                  const status = getStepStatus(myApp, i);
                  return (
                    <div key={i} className="relative pl-8">
                      <div className={cn(
                        "absolute left-0 top-1 h-6 w-6 rounded-full border-2 flex items-center justify-center z-10 bg-background transition-colors",
                        status === "passed"  ? "border-emerald-500 text-emerald-500" :
                        status === "failed"  ? "border-red-500 text-red-500" :
                        status === "current" ? "border-primary text-primary" :
                                               "border-muted text-muted-foreground"
                      )}>
                        {status === "passed"  ? <CheckCircle2 className="h-4 w-4" /> :
                         status === "failed"  ? <XCircle className="h-4 w-4" /> :
                         status === "current" ? <div className="h-2 w-2 bg-primary rounded-full animate-pulse" /> :
                                               <div className="h-2 w-2 bg-muted rounded-full" />}
                      </div>
                      {status === "passed" && i < steps.length - 1 && (
                        <div className="absolute left-[11px] top-7 w-0.5 h-10 bg-emerald-500 z-0" />
                      )}
                      <h4 className={cn("text-sm font-medium", status === "waiting" && "text-muted-foreground")}>
                        {step.title}
                      </h4>
                      <p className="text-xs text-muted-foreground">{step.desc}</p>
                    </div>
                  );
                })}
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
