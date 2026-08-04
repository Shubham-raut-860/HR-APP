import React, { useState, useEffect, useRef } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Progress } from "@/components/ui/progress";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  ArrowLeft, MapPin, Briefcase, Clock, Banknote,
  CheckCircle2, AlertCircle, XCircle, Loader2,
  FileText, ChevronDown, Star, Zap, Upload, Plus,
  ShieldAlert, CheckCheck
} from "lucide-react";
import { toast } from "sonner";
import {
  getPublicJob, applyToJob,
  applyWithVaultResume,
  getResumeFitScore, ResumeFitScore,
  StoredResume
} from "@/services/candidatePortal";
import { cn } from "@/lib/utils";
import ResumePickerModal from "@/components/ResumePickerModal";
import { useCandidateApplication } from "@/hooks/useCandidateApplication";
import { CandidateDataProvider, useCandidateData } from "@/context/CandidateDataProvider";

const MAX_RESUME_SIZE_BYTES = 10 * 1024 * 1024;

function CandidateJobDetailContent() {
  const { id }   = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { evaluateResume, getMyApplication, getStepStatus } = useCandidateApplication();
  const { storedResumes, fetchStoredResumes, invalidateResumes } = useCandidateData();

  const [job, setJob]               = useState<any>(null);
  const [loading, setLoading]       = useState(true);
  const [hasApplied, setHasApplied] = useState(false);
  const [myApp, setMyApp]           = useState<any>(null);

  const [resumes, setResumes]           = useState<StoredResume[]>([]);

  const [selected, setSelected]         = useState<string | null>(null);
  const [applying, setApplying]         = useState(false);
  const [dropOpen, setDropOpen]         = useState(false);
  const dropRef = useRef<HTMLDivElement>(null); // BUG FIX: ref for outside-click detection

  const [file, setFile]           = useState<File | null>(null);
  const [evaluating, setEvaluating] = useState(false);
  const [evaluation, setEvaluation] = useState<any>(null);

  const [pickerOpen, setPickerOpen]               = useState(false);
  const [fitScore, setFitScore]                   = useState<ResumeFitScore | null>(null);
  const [fitLoading, setFitLoading]               = useState(false);
  const [showApplyConfirm, setShowApplyConfirm]   = useState(false);
  const evaluationPassThreshold = Number(job?.pass_threshold ?? 60);

  // -- Data loading ----------------------------------------------------------
  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    
    const init = async () => {
      try {
        const [jobData, resultsData] = await Promise.allSettled([
          getPublicJob(id),
          getMyApplication(id),
          fetchStoredResumes(),
        ]);

        if (cancelled) return;

        if (jobData.status === "fulfilled") setJob(jobData.value);
        else { toast.error("Job not found"); navigate("/candidate/jobs"); return; }

        if (resultsData.status === "fulfilled" && resultsData.value) {
          setHasApplied(true); setMyApp(resultsData.value);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);

        }
      }
    };
    init();
    return () => { cancelled = true; };
  }, [id, navigate, getMyApplication, fetchStoredResumes]);

  useEffect(() => {
    setResumes(storedResumes);
    const def = storedResumes.find((r: StoredResume) => r.is_default);
    setSelected(prev => (prev && storedResumes.some(r => r.id === prev)) ? prev : (def?.id ?? storedResumes[0]?.id ?? null));
  }, [storedResumes]);

  // BUG FIX: close dropdown when clicking outside
  useEffect(() => {
    if (!dropOpen) return;
    const handler = (e: MouseEvent) => {
      if (dropRef.current && !dropRef.current.contains(e.target as Node)) {
        setDropOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [dropOpen]);

  // -- Fetch fit score when selected resume changes --------------------------
  useEffect(() => {
    if (!selected || !id || hasApplied) return;
    let cancelled = false;
    const fetchScore = async () => {
      setFitScore(null);
      setFitLoading(true);
      try {
        const score = await getResumeFitScore(id, selected);
        if (!cancelled) setFitScore(score ? { ...score, tag: score.tag?.toLowerCase() } : null);
      } catch {
        if (!cancelled) setFitScore(null);
      } finally {
        if (!cancelled) setFitLoading(false);
      }
    };
    fetchScore();
    return () => { cancelled = true; };
  }, [selected, id, hasApplied]);

  const handleVaultApply = async () => {
    if (!selected || !id) { toast.error("Select a resume first"); return; }
    setApplying(true);
    try {
      await applyWithVaultResume(id, selected);
      setHasApplied(true);
      const app = await getMyApplication(id);
      if (app) setMyApp(app);
      toast.success("Application submitted! --");
    } catch (err: any) {
      if (err.response?.status === 409) {
        setHasApplied(true);
        toast.info("Already applied. Application is under review.");
      } else {
        toast.error(err.response?.data?.detail || "Application failed");
      }
    } finally {
      setApplying(false);
      setShowApplyConfirm(false);
    }
  };

  const handleApplyClick = () => {
    if (!selected) { toast.error("Select a resume first"); return; }
    setShowApplyConfirm(true);
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files?.[0]) return;
    const f = e.target.files[0];
    if (f.size > MAX_RESUME_SIZE_BYTES) {
      toast.error("Resume file must be 10 MB or smaller.");
      e.target.value = "";
      return;
    }
    setFile(f); setEvaluation(null); setEvaluating(true);
    try {
      const data = await evaluateResume(id!, f);
      setEvaluation(data);
    } catch {
      toast.error("Failed to analyse resume. You can still apply.");
    } finally { setEvaluating(false); }
  };

  const handleFileApply = async () => {
    if (!file || !id) { toast.error("Upload a resume first"); return; }
    setApplying(true);
    try {
      await applyToJob(id, file);
      setHasApplied(true);
      const app = await getMyApplication(id);
      if (app) setMyApp(app);
      toast.success("Application submitted!");
    } catch (err: any) {
      if (err.response?.status === 409) { setHasApplied(true); toast.info("Already applied."); }
      else toast.error("Failed to submit application");
    } finally { setApplying(false); }
  };

  const steps = [
    { title: "Application Review", desc: "AI Screening" },
    { title: "Skill Assessment",   desc: "Online Quiz" },
    { title: "Interview",          desc: "With Hiring Manager" },
    { title: "Offer",              desc: "Final Decision" },
  ];

  const selectedResume = resumes.find(r => r.id === selected);
  const hasVault       = resumes.length > 0;
  const formatDate     = (iso: string) => new Date(iso).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
  const selectedResumeSkills = (selectedResume?.normalized_skills || []).map((skill) => skill.toLowerCase().trim());
  const mustHaveSkills = Array.isArray(job?.must_have_skills) ? job.must_have_skills : [];
  const niceToHaveSkills = Array.isArray(job?.good_to_have_skills) ? job.good_to_have_skills : [];
  const hasResumeSkill = (skill: string) => {
    const normalized = skill.toLowerCase().trim();
    return selectedResumeSkills.some((candidateSkill) =>
      candidateSkill === normalized ||
      candidateSkill.includes(normalized) ||
      normalized.includes(candidateSkill)
    );
  };
  const skillMatchGroups = [
    { label: "Must-have skills", skills: mustHaveSkills, required: true },
    { label: "Nice-to-have skills", skills: niceToHaveSkills, required: false },
  ].filter((group) => group.skills.length > 0);
  const skillMatchPanel = skillMatchGroups.length > 0 ? (
    <div className="mt-3 space-y-3 rounded-xl border bg-muted/20 p-3">
      <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Skill match details</p>
      {selectedResumeSkills.length === 0 && (
        <p className="text-xs text-muted-foreground">
          Upload a parsed resume to see exact matched and missing skill tags.
        </p>
      )}
      {skillMatchGroups.map((group) => (
        <div key={group.label} className="space-y-1.5">
          <p className="text-[11px] font-semibold text-muted-foreground">{group.label}</p>
          <div className="flex flex-wrap gap-1.5">
            {group.skills.map((skill: string) => {
              const matched = hasResumeSkill(skill);
              return (
                <span
                  key={`${group.label}-${skill}`}
                  className={cn(
                    "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium",
                    matched
                      ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300"
                      : group.required
                        ? "bg-red-100 text-red-600 dark:bg-red-900/30 dark:text-red-300"
                        : "bg-muted text-muted-foreground",
                  )}
                >
                  {matched ? <CheckCircle2 className="h-3 w-3" /> : <XCircle className="h-3 w-3" />}
                  {skill}
                </span>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  ) : null;

  if (loading || !job) return (
    <div className="space-y-6 w-full">
      <Skeleton className="h-9 w-32" />
      <div className="grid gap-6 md:grid-cols-3">
        <div className="md:col-span-2 space-y-6">
          <div className="space-y-3">
            <Skeleton className="h-10 w-2/3" />
            <Skeleton className="h-5 w-96 max-w-full" />
          </div>
          <Skeleton className="h-64 rounded-3xl" />
          <Skeleton className="h-48 rounded-3xl" />
        </div>
        <div className="space-y-6">
          <Skeleton className="h-72 rounded-3xl" />
          <Skeleton className="h-64 rounded-3xl" />
        </div>
      </div>
    </div>
  );

  return (
    <div className="space-y-6 w-full">
      <Button asChild variant="ghost" className="pl-0">
        <Link to="/candidate/jobs"><ArrowLeft className="mr-2 h-4 w-4" /> Back to Jobs</Link>
      </Button>

      <div className="grid gap-6 md:grid-cols-3">
        {/* -- Left: job info ------------------------------------------------ */}
        <div className="md:col-span-2 space-y-6">
          <div>
            <h1 className="text-3xl font-bold tracking-tight mb-2">{job.title}</h1>
            <div className="flex flex-wrap gap-3 text-sm text-muted-foreground">
              <span className="flex items-center gap-1"><MapPin className="h-4 w-4" />{job.location || "Remote"}</span>
              <span className="flex items-center gap-1"><Briefcase className="h-4 w-4" />{job.employment_type || "Full-time"}</span>
              {job.salary_range && (
                <span className="flex items-center gap-1 font-semibold text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-900/20 px-2 py-0.5 rounded-md border border-emerald-100 dark:border-emerald-800/50">
                  <Banknote className="h-4 w-4" />{job.salary_range}
                </span>
              )}
              <span className="flex items-center gap-1">
                <Clock className="h-4 w-4" />Posted {new Date(job.created_at).toLocaleDateString("en-GB", { day: "2-digit", month: "2-digit", year: "numeric" })}
              </span>
            </div>
          </div>

          <Card>
            <CardHeader><CardTitle>Job Description</CardTitle></CardHeader>
            <CardContent>
              <div className="prose dark:prose-invert max-w-none whitespace-pre-wrap text-sm leading-relaxed">{job.description}</div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>Required Skills</CardTitle></CardHeader>
            <CardContent>
              <h4 className="text-sm font-semibold mb-3 flex items-center gap-2">
                <CheckCircle2 className="h-4 w-4 text-primary" /> Must Have
              </h4>
              <ul className="grid gap-2 sm:grid-cols-2">
                {(job.must_have_skills || []).map((s: string) => (
                  <li key={s} className="flex items-start gap-2 text-sm text-muted-foreground">
                    <span className="mt-1.5 h-1.5 w-1.5 rounded-full bg-primary shrink-0" />{s}
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        </div>

        {/* -- Right: apply card + stepper ------------------------------------ */}
        <div className="space-y-6 md:sticky md:top-24 h-fit">

          <Card>
            <CardHeader>
              <CardTitle>Apply Now</CardTitle>
              {!hasApplied && <CardDescription>Pick a resume from your vault or upload a new one.</CardDescription>}
            </CardHeader>
            <CardContent className="space-y-4">

              {hasApplied ? (
                <div className="bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800 rounded-xl p-4 text-center space-y-3">
                  <CheckCircle2 className="h-8 w-8 text-emerald-600 dark:text-emerald-400 mx-auto" />
                  <p className="font-semibold text-emerald-800 dark:text-emerald-300">Under Review</p>
                  <Button asChild variant="outline" className="w-full rounded-xl">
                    <Link to="/candidate/dashboard">Go to Dashboard</Link>
                  </Button>
                  {myApp?.candidate_id && (
                    <Button asChild variant="ghost" className="w-full rounded-xl">
                      <Link to={`/candidate/feedback/${myApp.candidate_id}`}>View AI Feedback</Link>
                    </Button>
                  )}
                </div>

              ) : hasVault ? (
                <div className="space-y-3">
                  <div className="space-y-1.5">
                    <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Resume</p>

                    {/* BUG FIX: added ref for outside-click detection */}
                    <div className="relative" ref={dropRef}>
                      <Button
                        type="button"
                        variant="ghost"
                        onClick={() => setDropOpen(o => !o)}
                        aria-haspopup="listbox"
                        aria-expanded={dropOpen}
                        aria-label="Select resume from vault"
                        className="w-full h-auto justify-start flex items-center gap-3 p-3 rounded-xl border border-border/60 hover:border-primary/50 bg-muted/20 hover:bg-muted/40 transition-all text-left"
                      >
                        <div className={cn("p-1.5 rounded-lg shrink-0", selectedResume ? "bg-primary/10" : "bg-muted")}>
                          <FileText className={cn("h-4 w-4", selectedResume ? "text-primary" : "text-muted-foreground")} />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-1.5">
                            <span className="text-sm font-medium truncate">{selectedResume?.label ?? "Select a resume"}</span>
                            {selectedResume?.is_default && (
                              <Badge className="text-[9px] px-1.5 py-0 h-4 bg-amber-100 text-amber-700 border-amber-200 dark:bg-amber-900/30 dark:text-amber-400 shrink-0">
                                Default
                              </Badge>
                            )}
                          </div>
                          {selectedResume && (
                            <p className="text-xs text-muted-foreground truncate">{selectedResume.original_filename} - {formatDate(selectedResume.uploaded_at)}</p>
                          )}
                        </div>
                        <ChevronDown className={cn("h-4 w-4 text-muted-foreground shrink-0 transition-transform", dropOpen && "rotate-180")} />
                      </Button>

                      {dropOpen && (
                        <div className="absolute top-full left-0 right-0 mt-1 z-50 bg-popover border border-border/60 rounded-xl shadow-lg overflow-hidden">
                          {resumes.map(r => (
                            <Button
                              type="button"
                              variant="ghost"
                              key={r.id}
                              aria-label={`Select resume ${r.label}`}
                              onClick={() => { setSelected(r.id); setDropOpen(false); }}
                              className={cn(
                                "w-full h-auto justify-start rounded-none flex items-center gap-3 px-3 py-2.5 hover:bg-muted/60 transition-colors text-left",
                                selected === r.id && "bg-primary/5"
                              )}
                            >
                              <div className={cn("h-3.5 w-3.5 rounded-full border-2 shrink-0 flex items-center justify-center",
                                selected === r.id ? "border-primary bg-primary" : "border-muted-foreground/40"
                              )}>
                                {selected === r.id && <div className="h-1 w-1 rounded-full bg-white" />}
                              </div>
                              <FileText className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                              <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-1.5">
                                  <span className="text-sm truncate">{r.label}</span>
                                  {r.is_default && <Star className="h-3 w-3 text-amber-500 fill-amber-500 shrink-0" />}
                                </div>
                                <p className="text-xs text-muted-foreground truncate">{r.original_filename}</p>
                              </div>
                            </Button>
                          ))}
                          <Button
                            type="button"
                            variant="ghost"
                            onClick={() => { setDropOpen(false); setPickerOpen(true); }}
                            className="w-full h-auto justify-start rounded-none flex items-center gap-3 px-3 py-2.5 border-t border-border/40 hover:bg-muted/60 transition-colors text-left text-muted-foreground"
                          >
                            <Plus className="h-3.5 w-3.5 shrink-0" />
                            <span className="text-sm">Upload new resume...</span>
                          </Button>
                        </div>
                      )}
                    </div>
                  </div>

                  {selected && !hasApplied && (
                    <div className="px-1">
                      {fitLoading ? (
                        <div className="flex items-center gap-2 text-xs text-muted-foreground py-1">
                          <Loader2 className="h-3 w-3 animate-spin" />
                          <span>Calculating match score...</span>
                        </div>
                      ) : fitScore ? (
                        <div className="space-y-1.5">
                          <div className="flex items-center justify-between text-xs">
                            <span className="text-muted-foreground font-medium">Resume Match</span>
                            <span className={cn("font-bold",
                              fitScore.tag === "strong" ? "text-emerald-600 dark:text-emerald-400" :
                              fitScore.tag === "medium" ? "text-amber-600 dark:text-amber-400" :
                              "text-red-500"
                            )}>
                              {fitScore.resume_score.toFixed(0)}%
                              {fitScore.tag === "strong" ? " - Strong Match" :
                               fitScore.tag === "medium" ? " - Moderate Match" : " - Low Match"}
                            </span>
                          </div>
                          <div className="h-1.5 rounded-full bg-muted overflow-hidden">
                            <div
                              className={cn("h-full rounded-full transition-all duration-500",
                                fitScore.tag === "strong" ? "bg-emerald-500" :
                                fitScore.tag === "medium" ? "bg-amber-400" : "bg-red-400"
                              )}
                              style={{ width: `${Math.min(100, fitScore.resume_score)}%` }}
                            />
                          </div>
                          {fitScore.tag === "reject" && (
                            <p className="text-[11px] text-amber-600 dark:text-amber-400 flex items-center gap-1">
                              <AlertCircle className="h-3 w-3 shrink-0" />
                              Low match - consider a more tailored resume.
                            </p>
                          )}
                          {skillMatchPanel}
                        </div>
                      ) : skillMatchPanel}
                    </div>
                  )}

                  <Button
                    className={cn("w-full rounded-xl active:scale-[0.98] transition-all",
                      fitScore?.tag === "reject"
                        ? "bg-amber-500 hover:bg-amber-600 text-white"
                        : "bg-primary hover:bg-primary/90"
                    )}
                    disabled={!selected || applying}
                    onClick={handleApplyClick}
                  >
                    {applying
                      ? <><Loader2 className="h-4 w-4 mr-2 animate-spin" />Submitting...</>
                      : fitScore?.tag === "reject"
                        ? <><ShieldAlert className="h-4 w-4 mr-2" />Apply Anyway</>
                        : <><Zap className="h-4 w-4 mr-2 fill-current" />Apply with this Resume</>
                    }
                  </Button>

                  <Button
                    type="button"
                    variant="ghost"
                    onClick={() => setPickerOpen(true)}
                    className="w-full h-auto justify-center p-0 text-xs text-center text-muted-foreground hover:text-primary transition-colors py-1"
                  >
                    Manage resume vault ({resumes.length}/5)
                  </Button>
                </div>

              ) : evaluating ? (
                <div className="py-8 text-center space-y-4 border-2 border-dashed rounded-xl bg-muted/10">
                  <Loader2 className="h-8 w-8 animate-spin text-primary mx-auto" />
                  <p className="text-sm font-medium animate-pulse text-muted-foreground">AI screening your resume...</p>
                </div>

              ) : evaluation ? (
                <div className="space-y-4 border rounded-xl p-4 bg-muted/30">
                  <div className="flex justify-between items-center">
                    <span className="font-semibold text-sm">Match Score</span>
                    <span className={cn("font-bold text-sm", evaluation.match_score >= evaluationPassThreshold ? "text-emerald-500" : "text-amber-500")}>
                      {evaluation.match_score}%
                    </span>
                  </div>
                  <Progress value={evaluation.match_score} className={cn("h-2", evaluation.match_score >= evaluationPassThreshold ? "[&>div]:bg-emerald-500" : "[&>div]:bg-amber-500")} />
                  {evaluation.missing_skills?.length > 0 ? (
                    <div className="p-3 bg-amber-500/10 border border-amber-500/20 rounded-lg">
                      <p className="text-xs font-semibold text-amber-700 dark:text-amber-400 mb-1 flex items-center gap-1">
                        <AlertCircle className="h-3 w-3" /> Missing Skills
                      </p>
                      <p className="text-xs text-muted-foreground">Consider learning: <strong className="text-foreground">{evaluation.missing_skills.join(", ")}</strong></p>
                    </div>
                  ) : (
                    <div className="p-3 bg-emerald-500/10 border border-emerald-500/20 rounded-lg">
                      <p className="text-xs font-semibold text-emerald-700 dark:text-emerald-400 flex items-center gap-1">
                        <CheckCircle2 className="h-3 w-3" /> Great Fit!
                      </p>
                    </div>
                  )}
                  <div className="flex gap-2">
                    <Button variant="outline" className="flex-1 rounded-xl text-xs" onClick={() => { setFile(null); setEvaluation(null); }}>
                      Change
                    </Button>
                    <Button className="flex-1 rounded-xl text-xs" onClick={handleFileApply} disabled={applying}>
                      {applying ? "Submitting..." : "Apply Now"}
                    </Button>
                  </div>
                </div>

              ) : (
                <Button
                  type="button"
                  variant="ghost"
                  aria-label="Upload resume file to evaluate match"
                  className="w-full h-auto border-2 border-dashed rounded-xl p-6 text-center cursor-pointer hover:border-primary/50 hover:bg-primary/5 transition-colors"
                  onClick={() => document.getElementById("resume-upload-detail")?.click()}
                >
                  <Input id="resume-upload-detail" type="file" className="hidden" accept=".pdf,.doc,.docx,.png,.jpg,.jpeg,.webp,.tiff,.tif,.bmp,.gif" onChange={handleFileChange} />
                  <div className="flex flex-col items-center gap-3">
                    <div className="p-2.5 rounded-full bg-primary/10 text-primary"><Upload className="h-5 w-5" /></div>
                    <div className="text-sm">
                      <p className="font-medium">Upload Resume to Check Fit</p>
                      <p className="text-xs text-muted-foreground mt-1">PDF, DOCX, DOC or image - Max 10 MB</p>
                    </div>
                    <p className="text-xs text-muted-foreground">
                      Or{" "}
                      <span
                        role="button"
                        tabIndex={0}
                        className="h-auto p-0 text-primary underline cursor-pointer"
                        onClick={e => { e.stopPropagation(); setPickerOpen(true); }}
                        onKeyDown={e => {
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault();
                            e.stopPropagation();
                            setPickerOpen(true);
                          }
                        }}
                      >
                        save it to your vault
                      </span>
                      {" "}for future applications
                    </p>
                  </div>
                </Button>
              )}
            </CardContent>
          </Card>

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
                      <h4 className={cn("text-sm font-medium", status === "waiting" && "text-muted-foreground")}>{step.title}</h4>
                      <p className="text-xs text-muted-foreground">{step.desc}</p>
                    </div>
                  );
                })}
              </div>
            </CardContent>
          </Card>
        </div>
      </div>

      <Dialog open={showApplyConfirm} onOpenChange={setShowApplyConfirm}>
        <DialogContent className="max-w-sm rounded-2xl">
          <DialogHeader>
            <div className="flex items-center gap-3 mb-1">
              <div className={cn("p-2.5 rounded-xl",
                fitScore?.tag === "reject" ? "bg-amber-100 dark:bg-amber-900/30" :
                fitScore?.tag === "strong" ? "bg-emerald-100 dark:bg-emerald-900/30" :
                "bg-primary/10"
              )}>
                {fitScore?.tag === "reject"
                  ? <ShieldAlert className="h-5 w-5 text-amber-600 dark:text-amber-400" />
                  : fitScore?.tag === "strong"
                    ? <CheckCircle2 className="h-5 w-5 text-emerald-600 dark:text-emerald-400" />
                    : <Zap className="h-5 w-5 text-primary fill-primary/30" />
                }
              </div>
              <DialogTitle className="text-base">
                {fitScore?.tag === "reject" ? "Low Match Score" : "Confirm Application"}
              </DialogTitle>
            </div>
            <DialogDescription className="text-sm leading-relaxed">
              {fitScore ? (
                <>
                  Your resume <span className="font-semibold text-foreground">{selectedResume?.label}</span> scored{" "}
                  <span className={cn("font-bold",
                    fitScore.tag === "strong" ? "text-emerald-500" :
                    fitScore.tag === "medium" ? "text-amber-500" : "text-red-500"
                  )}>{fitScore.resume_score.toFixed(0)}%</span>{" "}
                  for <span className="font-medium text-foreground">{job?.title}</span>.
                  {fitScore.tag === "reject" && " This is below the recommended threshold - you may be less competitive."}
                </>
              ) : (
                <>Apply to <span className="font-medium text-foreground">{job?.title}</span> with <span className="font-medium text-foreground">{selectedResume?.label}</span>?</>
              )}
            </DialogDescription>
          </DialogHeader>

          {fitScore && (
            <div className="space-y-2 my-1 text-xs text-muted-foreground bg-muted/30 rounded-xl p-3 border border-border/40">
              <p className="font-semibold text-foreground text-xs uppercase tracking-wide mb-1.5">Score Breakdown</p>
              {[
                { label: "Skills",     value: fitScore.skill_match_pct },
                { label: "Experience", value: fitScore.experience_match_pct },
                { label: "Projects",   value: fitScore.project_relevance_pct },
                { label: "Education",  value: fitScore.education_match_pct },
              ].map(item => (
                <div key={item.label} className="flex items-center gap-2">
                  <span className="w-20 shrink-0">{item.label}</span>
                  <div className="flex-1 h-1.5 rounded-full bg-muted overflow-hidden">
                    <div
                      className={cn("h-full rounded-full", item.value >= 70 ? "bg-emerald-400" : item.value >= 40 ? "bg-amber-400" : "bg-red-400")}
                      style={{ width: `${item.value}%` }}
                    />
                  </div>
                  <span className="w-8 text-right font-medium">{item.value.toFixed(0)}%</span>
                </div>
              ))}
            </div>
          )}

          {fitScore?.tag === "reject" && (
            <p className="text-xs text-muted-foreground">We suggest uploading a more tailored resume. You can still apply, but consider improving your match first.</p>
          )}

          <div className="flex gap-2 pt-1">
            <Button variant="outline" className="flex-1 rounded-xl" onClick={() => setShowApplyConfirm(false)}>
              Go Back
            </Button>
            <Button
              className={cn("flex-1 rounded-xl", fitScore?.tag === "reject" ? "bg-amber-500 hover:bg-amber-600 text-white" : "")}
              onClick={handleVaultApply}
              disabled={applying}
            >
              {applying
                ? <><Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />Submitting...</>
                : fitScore?.tag === "reject"
                  ? <><CheckCheck className="h-3.5 w-3.5 mr-1.5" />Apply Anyway</>
                  : <><Zap className="h-3.5 w-3.5 mr-1.5 fill-current" />Confirm & Apply</>
              }
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <ResumePickerModal
        open={pickerOpen}
        onClose={() => {
          setPickerOpen(false);
          invalidateResumes().catch(() => {});
        }}
        jobId={id!}
        jobTitle={job.title}
        easyApply={false}
        onSuccess={() => {
          setHasApplied(true);
          getMyApplication(id!).then(app => {
            if (app) setMyApp(app);
          }).catch(() => {});
        }}
      />
    </div>
  );
}

export default function CandidateJobDetail() {
  return (
    <CandidateDataProvider>
      <CandidateJobDetailContent />
    </CandidateDataProvider>
  );
}
