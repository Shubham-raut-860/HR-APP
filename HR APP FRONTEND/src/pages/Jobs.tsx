import { useState, useEffect, useCallback, useMemo } from 'react';
import { useAuth } from '@/context/AuthContext';
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, EmptyStateButton } from "@/components/ui/empty-state";
import { InfoHint } from "@/components/ui/info-hint";

import { Plus, Search, MapPin, Briefcase, Clock, Sparkles, Trash2, Upload, FileUp, CheckCircle2, Loader2, X, AlertCircle, Files, IndianRupee, Users, ChevronRight, ChevronDown } from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';
import { getJobs, createJob, generateJob, deleteJob, bulkCreateJobsFromDocuments } from '@/services/jobs';
import { getCandidates } from '@/services/candidates';
import { toast } from "sonner";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,

} from "@/components/ui/dialog";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { BulkUploadModal } from "@/components/BulkUploadModal";
import { Slider } from "@/components/ui/slider";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";

export default function Jobs() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [jobs, setJobs] = useState<any[]>([]);
  const [candidates, setCandidates] = useState<any[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isFromDocOpen, setIsFromDocOpen] = useState(false);
  const [fromDocFiles, setFromDocFiles] = useState<File[]>([]);
  const [fromDocLoading, setFromDocLoading] = useState(false);
  const [fromDocDragging, setFromDocDragging] = useState(false);
  const [fromDocResults, setFromDocResults] = useState<{
    success: any[]; failed: any[]; done: boolean;
  } | null>(null);
  
  // New Local State for the Dual Slider [Min, Max]
  const [salaryRange, setSalaryRange] = useState([8, 18]);
  const [salaryBracket, setSalaryBracket] = useState('competitive');

  const [newJob, setNewJob] = useState({
    title: "",
    role: "",
    location: "Remote",
    description: "",
    experience_min: 0,
    experience_max: 5,
    must_have_skills: "",
    good_to_have_skills: ""
  });

  useEffect(() => {
    const controller = new AbortController();
    fetchData(controller.signal);
    return () => controller.abort();
  }, []);

  const fetchData = async (signal?: AbortSignal) => {
    try {
      const [jobsData, candidatesData] = await Promise.all([
        getJobs(true, signal),
        getCandidates(undefined, undefined, signal)
      ]);
      setJobs(jobsData);
      setCandidates(candidatesData);
    } catch (error: any) {
      if (error.name !== "AbortError" && error.code !== "ERR_CANCELED") {
        toast.error("Failed to fetch data");
      }
    } finally {
      setLoading(false);
    }
  };

  const parseSkillList = (raw: string): string[] => {
    const seen = new Set<string>();
    return raw
      .split(',')
      .map((s: string) => s.trim())
      .filter(Boolean)
      .filter((s: string) => {
        const key = s.toLowerCase();
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      });
  };

  const hasMeaningfulDescription = (value: string): boolean => {
    const compact = (value || "").replace(/[^a-zA-Z0-9]+/g, "");
    return compact.length >= 20;
  };

  const jobQuality = useMemo(() => {
    const title = (newJob.title || "").trim();
    const role = (newJob.role || newJob.title || "").trim();
    const mustHave = parseSkillList(newJob.must_have_skills);
    const goodToHave = parseSkillList(newJob.good_to_have_skills);
    const checks = [
      { key: "title", label: "Clear job title", pass: title.length >= 2 && /[a-zA-Z]/.test(title) },
      { key: "role", label: "Role label", pass: role.length >= 2 && /[a-zA-Z]/.test(role) },
      { key: "experience", label: "Experience range", pass: Number(newJob.experience_min) <= Number(newJob.experience_max) },
      { key: "skills", label: "At least 2 skills", pass: mustHave.length + goodToHave.length >= 2 },
      { key: "description", label: "Meaningful description", pass: hasMeaningfulDescription(newJob.description) },
    ];
    const passed = checks.filter((c) => c.pass).length;
    const score = Math.round((passed / checks.length) * 100);
    return {
      checks,
      score,
      ready: passed >= 4,
      mustHaveCount: mustHave.length,
      goodToHaveCount: goodToHave.length,
    };
  }, [newJob]);

  const handleCreateJob = async () => {
    try {
      // Company info lives in user.preferences (kept in sync by AuthContext after
      // every refreshUser() call from Settings). Reading localStorage here was a
      // secondary cache that caused stale data in fresh tabs — removed.
      const prefs = (user as any)?.preferences || {};
      const companyName    = (prefs.companyName    as string) || "";
      const companyBio     = (prefs.companyBio     as string) || "";
      const companyWebsite = (prefs.companyWebsite as string) || "";

      // Removed strict profile setup check to prevent blocking dev testing.
      // The `company` field will fall back to "Your Company" below.

      const mustHave = parseSkillList(newJob.must_have_skills);
      const goodToHave = parseSkillList(newJob.good_to_have_skills);
      const title = (newJob.title || "").trim();
      const role = (newJob.role || newJob.title || "").trim();
      const hasAlphaTitle = /[a-zA-Z]/.test(title);
      const hasAlphaRole = /[a-zA-Z]/.test(role);
      if (title.length < 2 || !hasAlphaTitle) {
        toast.error("Enter a valid job title (not just numbers/symbols).");
        return;
      }
      if (role.length < 2 || !hasAlphaRole) {
        toast.error("Enter a valid role (not just numbers/symbols).");
        return;
      }
      if (Number(newJob.experience_min) > Number(newJob.experience_max)) {
        toast.error("Minimum experience cannot be greater than maximum experience.");
        return;
      }
      if (mustHave.length === 0 && goodToHave.length === 0 && !hasMeaningfulDescription(newJob.description)) {
        toast.error("Add at least one required/preferred skill or a meaningful job description.");
        return;
      }

      const jobData = {
        ...newJob,
        title,
        role,
        company: companyName || "Your Company",
        company_bio: companyBio,
        company_blog: companyWebsite,
        // Formats the array back into the expected string for the database!
        salary_range: salaryBracket === 'custom'
          ? `₹${salaryRange[0]} LPA – ₹${salaryRange[1]} LPA`
          : salaryBracket === 'competitive'
            ? 'Competitive'
            : salaryBracket === 'not_disclosed'
              ? 'Not disclosed'
              : salaryBracket,
        must_have_skills: mustHave,
        good_to_have_skills: goodToHave,
        experience_min: Number(newJob.experience_min),
        experience_max: Number(newJob.experience_max)
      };

      await createJob(jobData);
      toast.success("Job created successfully");
      setIsCreateOpen(false);
      fetchData();
      resetForm();
    } catch (error: any) {
      const message = error?.response?.data?.detail || error?.message || "Failed to create job";
      toast.error(message);
    }
  };

  const handleGenerateJob = async () => {
    if (!newJob.title) {
      toast.error("Please enter a job title/role first");
      return;
    }

    setIsGenerating(true);
    toast.info("Generating job description with AI...");

    const localFallback = {
      role: newJob.title,
      description: `We are hiring a ${newJob.title} with ${Number(newJob.experience_min)}-${Number(newJob.experience_max)} years of experience in ${newJob.location || "Remote"}. Responsibilities include designing and delivering reliable features, collaborating with cross-functional teams, writing maintainable code, and improving system quality, performance, and observability.`,
      must_have_skills: [] as string[],
      good_to_have_skills: [] as string[],
    };

    const applyGeneratedState = (generated: any) => {
      const generatedDescription = (generated?.description || "").trim();
      const generatedMustHave = Array.isArray(generated?.must_have_skills) ? generated.must_have_skills : [];
      const generatedGoodToHave = Array.isArray(generated?.good_to_have_skills) ? generated.good_to_have_skills : [];
      const hasContent =
        !!generatedDescription || generatedMustHave.length > 0 || generatedGoodToHave.length > 0;

      const finalPayload = hasContent ? generated : localFallback;
      const finalDescription = (finalPayload?.description || "").trim();
      const finalMustHave = Array.isArray(finalPayload?.must_have_skills) ? finalPayload.must_have_skills : [];
      const finalGoodToHave = Array.isArray(finalPayload?.good_to_have_skills) ? finalPayload.good_to_have_skills : [];

      setNewJob(prev => ({
        ...prev,
        description: finalDescription,
        must_have_skills: finalMustHave.join(', ') || "",
        good_to_have_skills: finalGoodToHave.join(', ') || "",
        role: finalPayload?.role || prev.title
      }));

      return hasContent;
    };

    try {
      const generated = await generateJob({
        role: newJob.title,
        location: newJob.location,
        experience_min: Number(newJob.experience_min),
        experience_max: Number(newJob.experience_max)
      });
      const usedAi = applyGeneratedState(generated);
      if (usedAi) {
        toast.success("Job description generated!");
      } else {
        toast.warning("AI returned empty output. Added a fallback JD template.");
      }
    } catch (error: any) {
      const message =
        error?.response?.data?.detail ||
        error?.message ||
        "Failed to generate job description";
      applyGeneratedState(localFallback);
      toast.warning(`AI unavailable: ${message}. Added a fallback JD template.`);
    } finally {
      setIsGenerating(false);
    }
  };

  const handleDeleteJob = async (id: string) => {
    try {
      await deleteJob(id);
      toast.success("Job deleted successfully");
      fetchData();
    } catch (error) {
      toast.error("Failed to delete job");
    }
  };

  const addFromDocFiles = useCallback((incoming: FileList | File[]) => {
    const allowed = new Set(['.pdf', '.docx', '.doc', '.txt', '.png', '.jpg', '.jpeg', '.webp', '.tiff', '.tif', '.bmp', '.gif']);
    const maxBytes = 5 * 1024 * 1024;
    const filteredByType = Array.from(incoming).filter(f => {
      const ext = '.' + f.name.split('.').pop()!.toLowerCase();
      return allowed.has(ext);
    });
    if (filteredByType.length < incoming.length) {
      toast.warning('Some files were skipped — only PDF, DOCX, DOC, TXT, and image files are supported');
    }
    const valid = filteredByType.filter(f => f.size <= maxBytes);
    if (valid.length < filteredByType.length) {
      toast.warning('Some files were skipped — JD file size limit is 5 MB per file');
    }
    setFromDocFiles(prev => {
      const names = new Set(prev.map(f => f.name));
      const deduped = valid.filter(f => !names.has(f.name));
      const next = [...prev, ...deduped];
      if (next.length > 20) {
        toast.warning('Max 20 files — only the first 20 will be uploaded');
        return next.slice(0, 20);
      }
      return next;
    });
  }, []);

  const handleFromDocument = async () => {
    if (!fromDocFiles.length) return;
    setFromDocLoading(true);
    setFromDocResults(null);
    toast.info(`Processing ${fromDocFiles.length} document${fromDocFiles.length > 1 ? 's' : ''}…`);
    try {
      const result = await bulkCreateJobsFromDocuments(fromDocFiles);
      setFromDocResults({ ...result, done: true });
      if (result.success_count > 0) {
        toast.success(`Created ${result.success_count} job${result.success_count > 1 ? 's' : ''} successfully`);
        fetchData();
      }
      if (result.failed_count > 0) {
        toast.error(`${result.failed_count} file${result.failed_count > 1 ? 's' : ''} failed`);
      }
    } catch {
      toast.error('Failed to process documents. Please try again.');
    } finally {
      setFromDocLoading(false);
    }
  };

  const closeFromDocModal = () => {
    if (fromDocLoading) return;
    setIsFromDocOpen(false);
    setFromDocFiles([]);
    setFromDocResults(null);
  };

  const resetForm = () => {
    setNewJob({
      title: "",
      role: "",
      location: "Remote",
      description: "",
      experience_min: 0,
      experience_max: 5,
      must_have_skills: "",
      good_to_have_skills: ""
    });
    setSalaryRange([8, 18]);
    setSalaryBracket('competitive');
  };

  const filteredJobs = jobs.filter((job: any) => 
    job.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
    (job.role && job.role.toLowerCase().includes(searchQuery.toLowerCase()))
  );

  const getCandidateCount = (jobId: string) => {
    return candidates.filter((c: any) => c.job_id === jobId).length;
  };

  const getCandidateTags = (jobId: string) => {
    const jc = candidates.filter((c: any) => c.job_id === jobId);
    const normalize = (tag: string | null | undefined) => (tag || "").trim().toLowerCase();
    const strong = jc.filter((c: any) => normalize(c.tag) === 'strong').length;
    const medium = jc.filter((c: any) => normalize(c.tag) === 'medium').length;
    const reject = jc.filter((c: any) => normalize(c.tag) === 'reject').length;
    return { strong, medium, reject, total: jc.length };
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-3xl font-bold tracking-tight">Jobs</h2>
          <p className="text-muted-foreground">Manage your job postings and applications.</p>
        </div>
      <div className="flex gap-2">
          {/* Single "+ New" dropdown — replaces three separate creation buttons */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button className="rounded-xl gap-1" aria-label="Open new job actions">
                <Plus className="h-4 w-4" /> New <ChevronDown className="h-3.5 w-3.5 opacity-70" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
              <DropdownMenuItem onSelect={() => setIsCreateOpen(true)}>
                <Plus className="mr-2 h-4 w-4" /> Create job manually
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => setIsFromDocOpen(true)}>
                <FileUp className="mr-2 h-4 w-4" /> Job from document
                <span className="ml-auto text-[10px] text-muted-foreground">DOC/IMG</span>
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <BulkUploadModal
                jobs={jobs}
                onUploadComplete={fetchData}
                trigger={
                  <DropdownMenuItem onSelect={(e) => e.preventDefault()}>
                    <Upload className="mr-2 h-4 w-4" /> Bulk upload resumes
                    <span className="ml-auto text-[10px] text-muted-foreground">500+</span>
                  </DropdownMenuItem>
                }
              />
            </DropdownMenuContent>
          </DropdownMenu>

          {/* From Document modal — triggered from dropdown above */}
          <Dialog open={isFromDocOpen} onOpenChange={(o) => { if (!o) closeFromDocModal(); else setIsFromDocOpen(true); }}>
            <DialogContent className="sm:max-w-[520px] rounded-3xl">
              <DialogHeader>
                <DialogTitle className="flex items-center gap-2 text-lg">
                  <span className="inline-flex items-center justify-center w-8 h-8 rounded-xl bg-muted">
                    <Files className="h-4 w-4" />
                  </span>
                  Create Jobs from Documents
                </DialogTitle>
                <DialogDescription>
                  Upload one or more JD files — one job is created per file automatically.
                  Supports PDF, DOCX, DOC, TXT, and image files (max 20 files, 5 MB each).
                </DialogDescription>
              </DialogHeader>

              <div className="py-3 space-y-4">
                {/* Drop zone */}
                {!fromDocResults?.done && (
                  <div
                    role="button"
                    tabIndex={0}
                    aria-label="Choose job description document files"
                    className={`relative border-2 border-dashed rounded-2xl p-6 text-center transition-all cursor-pointer select-none ${
                      fromDocDragging
                        ? "border-primary bg-primary/5 scale-[1.01]"
                        : fromDocFiles.length
                          ? "border-emerald-400 bg-emerald-50/50 dark:bg-emerald-950/20"
                          : "border-muted-foreground/25 hover:border-primary/50 hover:bg-muted/30"
                    }`}
                    onDragOver={(e) => { e.preventDefault(); setFromDocDragging(true); }}
                    onDragLeave={() => setFromDocDragging(false)}
                    onDrop={(e) => {
                      e.preventDefault();
                      setFromDocDragging(false);
                      if (e.dataTransfer.files?.length) addFromDocFiles(e.dataTransfer.files);
                    }}
                    onClick={() => document.getElementById('jd-doc-input')?.click()}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        document.getElementById('jd-doc-input')?.click();
                      }
                    }}
                  >
                    <input
                      id="jd-doc-input"
                      type="file"
                      multiple
                      className="hidden"
                      aria-label="Job description document files"
                      accept=".pdf,.docx,.doc,.txt,.png,.jpg,.jpeg,.webp,.tiff,.tif,.bmp,.gif"
                      onChange={(e) => { if (e.target.files?.length) addFromDocFiles(e.target.files); e.target.value = ''; }}
                    />
                    {fromDocFiles.length ? (
                      <div className="flex flex-col items-center gap-1">
                        <Files className="h-8 w-8 text-emerald-500 mb-1" />
                        <p className="font-semibold text-sm">{fromDocFiles.length} file{fromDocFiles.length > 1 ? 's' : ''} selected</p>
                        <p className="text-xs text-muted-foreground">Click to add more or drop additional files</p>
                      </div>
                    ) : (
                      <div className="flex flex-col items-center gap-2">
                        <div className="w-12 h-12 rounded-2xl bg-muted flex items-center justify-center mx-auto">
                          <FileUp className="h-6 w-6 text-muted-foreground" />
                        </div>
                        <p className="font-medium text-sm">Drop files here or click to browse</p>
                        <p className="text-xs text-muted-foreground">PDF, DOCX, DOC, TXT or image · Max 20 files · 5 MB each</p>
                      </div>
                    )}
                  </div>
                )}

                {/* File list */}
                {fromDocFiles.length > 0 && !fromDocResults?.done && (
                  <div className="space-y-1.5 max-h-48 overflow-y-auto">
                    {fromDocFiles.map((f, i) => (
                      <div key={i} className="flex items-center gap-2 px-3 py-2 rounded-xl bg-muted/30 text-sm">
                        {fromDocLoading
                          ? <Loader2 className="h-4 w-4 text-primary shrink-0 animate-spin" />
                          : <CheckCircle2 className="h-4 w-4 text-emerald-500 shrink-0" />
                        }
                        <span className="flex-1 truncate text-foreground">{f.name}</span>
                        <span className="text-xs text-muted-foreground shrink-0">{(f.size / 1024).toFixed(0)} KB</span>
                        {!fromDocLoading && (
                          <button
                            type="button"
                            aria-label={`Remove ${f.name}`}
                            onClick={(e) => { e.stopPropagation(); setFromDocFiles(prev => prev.filter((_, j) => j !== i)); }}
                            className="text-muted-foreground hover:text-destructive transition-colors"
                          >
                            <X className="h-3.5 w-3.5" />
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                )}

                {/* Results */}
                {fromDocResults?.done && (
                  <div className="space-y-2">
                    {fromDocResults.success.length > 0 && (
                      <div className="space-y-1">
                        <p className="text-xs font-semibold text-emerald-600 uppercase tracking-wide">
                          Created ({fromDocResults.success.length})
                        </p>
                        <div className="max-h-40 overflow-y-auto space-y-1">
                          {fromDocResults.success.map((r: any, i: number) => (
                            <div key={i} className="flex items-center gap-2 px-3 py-2 rounded-xl bg-emerald-50/60 dark:bg-emerald-950/20 text-sm">
                              <CheckCircle2 className="h-4 w-4 text-emerald-500 shrink-0" />
                              <div className="flex-1 min-w-0">
                                <p className="font-medium truncate">{r.title}</p>
                                <p className="text-xs text-muted-foreground truncate">{r.filename}</p>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                    {fromDocResults.failed.length > 0 && (
                      <div className="space-y-1">
                        <p className="text-xs font-semibold text-destructive uppercase tracking-wide">
                          Failed ({fromDocResults.failed.length})
                        </p>
                        <div className="max-h-32 overflow-y-auto space-y-1">
                          {fromDocResults.failed.map((r: any, i: number) => (
                            <div key={i} className="flex items-start gap-2 px-3 py-2 rounded-xl bg-destructive/5 text-sm">
                              <AlertCircle className="h-4 w-4 text-destructive shrink-0 mt-0.5" />
                              <div className="flex-1 min-w-0">
                                <p className="font-medium truncate">{r.filename}</p>
                                <p className="text-xs text-muted-foreground">{r.error}</p>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>

              <DialogFooter className="gap-2">
                <Button variant="ghost" className="rounded-full" onClick={closeFromDocModal} disabled={fromDocLoading}>
                  {fromDocResults?.done ? 'Close' : 'Cancel'}
                </Button>
                {!fromDocResults?.done && (
                  <Button
                    className="rounded-full px-6"
                    disabled={!fromDocFiles.length || fromDocLoading}
                    onClick={handleFromDocument}
                  >
                    {fromDocLoading ? (
                      <><Loader2 className="mr-2 h-4 w-4 animate-spin" /> Creating {fromDocFiles.length} Job{fromDocFiles.length > 1 ? 's' : ''}…</>
                    ) : (
                      <><Sparkles className="mr-2 h-4 w-4" /> Create {fromDocFiles.length || ''} Job{fromDocFiles.length !== 1 ? 's' : ''}</>
                    )}
                  </Button>
                )}
                {fromDocResults?.done && fromDocResults.failed.length > 0 && (
                  <Button className="rounded-full px-6" onClick={() => {
                    setFromDocResults(null);
                    setFromDocFiles([]);
                  }}>
                    Retry Failed
                  </Button>
                )}
              </DialogFooter>
            </DialogContent>
          </Dialog>

          <Dialog open={isCreateOpen} onOpenChange={(open) => { setIsCreateOpen(open); if (!open) resetForm(); }}>
            <DialogContent className="sm:max-w-[650px] max-h-[90vh] flex flex-col p-0 gap-0 rounded-2xl overflow-hidden">
              {/* Fixed header */}
              <DialogHeader className="px-6 pt-6 pb-4 border-b shrink-0">
                <DialogTitle>Create Job Posting</DialogTitle>
                <DialogDescription>
                  Add a new job opening. Use AI to generate the description.
                </DialogDescription>
              </DialogHeader>

              {/* Scrollable body - custom thin scrollbar */}
              <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5 scrollbar-thin">
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-1.5">
                    <Label htmlFor="job-title" className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Job Title / Role</Label>
                    <Input id="job-title" value={newJob.title} onChange={(e) => setNewJob({...newJob, title: e.target.value})} placeholder="e.g. Senior React Developer" className="h-9 rounded-xl bg-muted/20" />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="job-location" className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Location</Label>
                    <Input id="job-location" value={newJob.location} onChange={(e) => setNewJob({...newJob, location: e.target.value})} className="h-9 rounded-xl bg-muted/20" />
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-1.5">
                    <Label htmlFor="job-exp-min" className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Min Experience (Years)</Label>
                    <Input id="job-exp-min" type="number" value={newJob.experience_min} onChange={(e) => setNewJob({...newJob, experience_min: Number(e.target.value)})} className="h-9 rounded-xl bg-muted/20" />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="job-exp-max" className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Max Experience (Years)</Label>
                    <Input id="job-exp-max" type="number" value={newJob.experience_max} onChange={(e) => setNewJob({...newJob, experience_max: Number(e.target.value)})} className="h-9 rounded-xl bg-muted/20" />
                  </div>
                </div>

                {/* Salary / Compensation */}
                <div className="space-y-2.5">
                  <Label id="job-compensation-label" className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Compensation</Label>
                  <Select value={salaryBracket} onValueChange={setSalaryBracket}>
                    <SelectTrigger className="h-9 rounded-xl bg-muted/20" aria-labelledby="job-compensation-label">
                      <SelectValue placeholder="Select compensation…" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="competitive">Competitive (industry standard)</SelectItem>
                      <SelectItem value="not_disclosed">Not disclosed</SelectItem>
                      <SelectItem value="0-3 LPA">₹0 – 3 LPA  (Entry level)</SelectItem>
                      <SelectItem value="3-6 LPA">₹3 – 6 LPA  (Junior)</SelectItem>
                      <SelectItem value="6-10 LPA">₹6 – 10 LPA  (Mid level)</SelectItem>
                      <SelectItem value="10-15 LPA">₹10 – 15 LPA  (Senior)</SelectItem>
                      <SelectItem value="15-25 LPA">₹15 – 25 LPA  (Lead)</SelectItem>
                      <SelectItem value="25-40 LPA">₹25 – 40 LPA  (Principal / Staff)</SelectItem>
                      <SelectItem value="40+ LPA">₹40+ LPA  (Director / VP)</SelectItem>
                      <SelectItem value="custom">Custom range…</SelectItem>
                    </SelectContent>
                  </Select>
                  {salaryBracket === 'custom' && (
                    <div className="space-y-2 bg-muted/20 px-4 pt-3 pb-4 rounded-xl border border-border/50">
                      <div className="flex justify-between items-center">
                        <span className="text-xs text-muted-foreground">Custom range</span>
                        <span className="text-sm font-bold">₹{salaryRange[0]} – ₹{salaryRange[1]} LPA</span>
                      </div>
                      <Slider value={salaryRange} onValueChange={setSalaryRange} max={60} min={1} step={1} className="py-1" aria-label="Custom compensation range" />
                    </div>
                  )}
                </div>

                {/* Must-Have Skills */}
                <div className="space-y-1.5">
                  <div className="flex items-center gap-2">
                    <div className="h-2 w-2 rounded-full bg-red-500 shrink-0" />
                    <Label htmlFor="job-must-skills" className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Must-Have Skills</Label>
                    <span className="text-xs text-muted-foreground ml-auto">comma separated</span>
                  </div>
                  <Textarea
                    id="job-must-skills"
                    value={newJob.must_have_skills}
                    onChange={(e) => setNewJob({...newJob, must_have_skills: e.target.value})}
                    placeholder="React, TypeScript, Node.js, PostgreSQL"
                    className="min-h-[64px] resize-none rounded-xl bg-muted/20 text-sm leading-relaxed"
                  />
                  {newJob.must_have_skills.trim() && (
                    <div className="flex flex-wrap gap-1.5 pt-0.5">
                      {newJob.must_have_skills.split(',').map(s => s.trim()).filter(Boolean).map((s, i) => (
                        <span key={i} className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-red-50 text-red-700 border border-red-200 dark:bg-red-950/30 dark:text-red-300 dark:border-red-800">
                          <span className="h-1.5 w-1.5 rounded-full bg-red-500 shrink-0" />{s}
                        </span>
                      ))}
                    </div>
                  )}
                </div>

                {/* Good-to-Have Skills */}
                <div className="space-y-1.5">
                  <div className="flex items-center gap-2">
                    <div className="h-2 w-2 rounded-full bg-blue-500 shrink-0" />
                    <Label htmlFor="job-good-skills" className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Good-to-Have Skills</Label>
                    <span className="text-xs text-muted-foreground ml-auto">comma separated</span>
                  </div>
                  <Textarea
                    id="job-good-skills"
                    value={newJob.good_to_have_skills}
                    onChange={(e) => setNewJob({...newJob, good_to_have_skills: e.target.value})}
                    placeholder="AWS, Docker, GraphQL, Redis"
                    className="min-h-[52px] resize-none rounded-xl bg-muted/20 text-sm leading-relaxed"
                  />
                  {newJob.good_to_have_skills.trim() && (
                    <div className="flex flex-wrap gap-1.5 pt-0.5">
                      {newJob.good_to_have_skills.split(',').map(s => s.trim()).filter(Boolean).map((s, i) => (
                        <span key={i} className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-blue-50 text-blue-700 border border-blue-200 dark:bg-blue-950/30 dark:text-blue-300 dark:border-blue-800">
                          <span className="h-1.5 w-1.5 rounded-full bg-blue-400 shrink-0" />{s}
                        </span>
                      ))}
                    </div>
                  )}
                </div>

                {/* Description */}
                <div className="space-y-1.5">
                  <div className="flex justify-between items-center">
                    <Label htmlFor="job-description" className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Description</Label>
                    <Button type="button" variant="ghost" size="sm" aria-label="Generate job description with AI" onClick={handleGenerateJob} disabled={isGenerating || !newJob.title} className="h-7 text-xs rounded-full bg-primary/5 hover:bg-primary/10 text-primary">
                      <Sparkles className="mr-1.5 h-3 w-3" />
                      {isGenerating ? "Generating..." : "Generate with AI"}
                    </Button>
                  </div>
                  <Textarea id="job-description" value={newJob.description} onChange={(e) => setNewJob({...newJob, description: e.target.value})} className="min-h-[150px] rounded-xl bg-muted/20 resize-none text-sm leading-relaxed" placeholder="Job description..." />
                </div>

                <div className="rounded-xl border bg-muted/20 p-3 space-y-2">
                  <div className="flex items-center justify-between">
                    <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Quality Guard</p>
                    <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${jobQuality.score >= 80 ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700'}`}>
                      {jobQuality.score}%
                    </span>
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
                    {jobQuality.checks.map((check) => (
                      <div key={check.key} className="text-xs flex items-center gap-1.5">
                        <span className={`h-1.5 w-1.5 rounded-full ${check.pass ? 'bg-emerald-500' : 'bg-amber-500'}`} />
                        <span className={check.pass ? "text-foreground" : "text-muted-foreground"}>{check.label}</span>
                      </div>
                    ))}
                  </div>
                  {!jobQuality.ready && (
                    <p className="text-[11px] text-muted-foreground">
                      Add a stronger description or more skills before publishing this job.
                    </p>
                  )}
                </div>
              </div>

              {/* Fixed footer */}
              <div className="px-6 py-4 border-t bg-muted/30 shrink-0 flex justify-end gap-2">
                <Button type="button" variant="ghost" onClick={() => setIsCreateOpen(false)} className="rounded-full">Cancel</Button>
                <Button type="button" onClick={handleCreateJob} disabled={!jobQuality.ready} className="rounded-full px-6">Create Job</Button>
              </div>
            </DialogContent>
          </Dialog>
        </div>
      </div>

      <div className="flex items-center space-x-2">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input type="search" aria-label="Search jobs" placeholder="Search jobs..." className="pl-9 rounded-full bg-muted/20" value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} />
        </div>
      </div>

      {loading ? (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, idx) => (
            <Card key={`job-skeleton-${idx}`} className="rounded-2xl">
              <CardHeader className="space-y-2">
                <Skeleton className="h-5 w-2/3" />
                <Skeleton className="h-4 w-1/3" />
              </CardHeader>
              <CardContent className="space-y-3">
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-5/6" />
                <Skeleton className="h-12 w-full rounded-xl" />
              </CardContent>
              <CardFooter>
                <Skeleton className="h-9 w-28 rounded-full" />
              </CardFooter>
            </Card>
          ))}
        </div>
      ) : filteredJobs.length === 0 ? (
        <EmptyState
          icon={Briefcase}
          title={searchQuery ? "No matching jobs" : "No jobs found"}
          description={searchQuery ? "Try a different title, role, or keyword." : "Create a role manually or import a JD document to start your hiring pipeline."}
          action={<EmptyStateButton onClick={() => setIsCreateOpen(true)}>Create Job</EmptyStateButton>}
          className="py-20"
        />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {filteredJobs.map((job: any) => {
            const tags = getCandidateTags(job.id);
            const strongPct = tags.total > 0 ? Math.round(tags.strong / tags.total * 100) : 0;
            const mediumPct = tags.total > 0 ? Math.round(tags.medium / tags.total * 100) : 0;
            const rejectPct = tags.total > 0 ? Math.round(tags.reject / tags.total * 100) : 0;
            const mustSkills: string[] = (job.must_have_skills || []).slice(0, 4);
            const extraSkills = (job.must_have_skills || []).length - mustSkills.length;
            return (
            <Card key={job.id} className={`flex flex-col hover:shadow-md transition-all group rounded-2xl border-l-[3px] overflow-hidden ${job.is_active ? 'border-l-emerald-500' : 'border-l-muted-foreground/20'}`}>
              <CardHeader className="pb-2 pt-4 px-4">
                <div className="flex items-start justify-between gap-2">
                  <div className="flex-1 min-w-0">
                    <CardTitle className="text-base font-semibold leading-snug group-hover:text-primary transition-colors cursor-pointer line-clamp-2" onClick={() => navigate(`/jobs/${job.id}`)}>
                      {job.title}
                    </CardTitle>
                    {job.role && job.role !== job.title && (
                      <p className="text-xs text-muted-foreground mt-0.5 truncate">{job.role}</p>
                    )}
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${job.is_active ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400' : 'bg-muted text-muted-foreground'}`}>
                      {job.is_active ? "Active" : "Closed"}
                    </span>
                    <AlertDialog>
                      <AlertDialogTrigger asChild>
                        <Button variant="ghost" size="icon" className="h-7 w-7 opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive hover:bg-destructive/10 rounded-full transition-all">
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </AlertDialogTrigger>
                      <AlertDialogContent className="rounded-2xl">
                        <AlertDialogHeader>
                          <AlertDialogTitle>Delete this job?</AlertDialogTitle>
                          <AlertDialogDescription>
                            This permanently deletes <strong>{job.title}</strong> and all associated candidate data. This cannot be undone.
                          </AlertDialogDescription>
                        </AlertDialogHeader>
                        <AlertDialogFooter>
                          <AlertDialogCancel className="rounded-full">Cancel</AlertDialogCancel>
                          <AlertDialogAction onClick={() => handleDeleteJob(job.id)} className="bg-destructive text-destructive-foreground hover:bg-destructive/90 rounded-full">
                            Delete
                          </AlertDialogAction>
                        </AlertDialogFooter>
                      </AlertDialogContent>
                    </AlertDialog>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="flex-1 pb-3 px-4 space-y-3">
                {/* Meta chips */}
                <div className="flex flex-wrap gap-1.5">
                  <span className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-md bg-muted text-muted-foreground">
                    <MapPin className="h-3 w-3" />{job.location || 'Remote'}
                  </span>
                  <span className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-md bg-muted text-muted-foreground">
                    <Briefcase className="h-3 w-3" />{job.experience_min}–{job.experience_max} yrs
                  </span>
                  {job.employment_type && (
                    <span className="inline-flex items-center text-[11px] px-2 py-0.5 rounded-md bg-muted text-muted-foreground">
                      {job.employment_type}
                    </span>
                  )}
                  {job.salary_range && (
                    <span className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-md bg-primary/8 text-primary font-medium border border-primary/15">
                      <IndianRupee className="h-3 w-3" />{job.salary_range}
                    </span>
                  )}
                </div>
                {/* Skills preview */}
                {mustSkills.length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {mustSkills.map((skill: string, i: number) => (
                      <span key={i} className="inline-flex items-center text-[10px] px-1.5 py-0.5 rounded bg-muted/80 text-muted-foreground font-medium border border-border/40">
                        {skill}
                      </span>
                    ))}
                    {extraSkills > 0 && (
                      <span className="inline-flex items-center text-[10px] px-1.5 py-0.5 rounded bg-muted/50 text-muted-foreground">
                        +{extraSkills} more
                      </span>
                    )}
                  </div>
                )}
                {/* Posted date */}
                <p className="text-[11px] text-muted-foreground flex items-center gap-1">
                  <Clock className="h-3 w-3" />
                  Posted {new Date(job.created_at).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })}
                </p>
              </CardContent>
              <CardFooter className="border-t border-border/40 pt-3 pb-3 px-4 bg-muted/20 rounded-b-2xl">
                <div className="flex w-full flex-col gap-2">
                  {tags.total > 0 && (
                    <div className="space-y-1">
                      <div className="flex h-1.5 rounded-full overflow-hidden bg-muted gap-px">
                        {strongPct > 0 && <div className="bg-emerald-500 transition-all" style={{ width: `${strongPct}%` }} />}
                        {mediumPct > 0 && <div className="bg-amber-400 transition-all" style={{ width: `${mediumPct}%` }} />}
                        {rejectPct > 0 && <div className="bg-red-400 transition-all" style={{ width: `${rejectPct}%` }} />}
                      </div>
                      <div className="flex items-center gap-3 text-[10px]">
                        {tags.strong > 0 && <span className="text-emerald-700 dark:text-emerald-400 font-medium">{tags.strong} Strong</span>}
                        {tags.medium > 0 && <span className="text-amber-700 dark:text-amber-400 font-medium">{tags.medium} Medium</span>}
                        {tags.reject > 0 && <span className="text-muted-foreground">{tags.reject} Reject</span>}
                        {tags.total > 0 && tags.strong === 0 && tags.medium === 0 && tags.reject === 0 && (
                          <span className="text-muted-foreground">{tags.total} untagged</span>
                        )}
                      </div>
                    </div>
                  )}
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-1.5">
                      <Users className="h-3.5 w-3.5 text-muted-foreground" />
                      <span className="text-sm font-semibold">{getCandidateCount(job.id)}</span>
                      <span className="text-xs text-muted-foreground">candidates</span>
                      <InfoHint
                        label={`Pipeline stats for ${job.title}`}
                        description="Candidate quality tags are normalized from live application data for this job."
                        side="left"
                      />
                    </div>
                    <Button size="sm" className="rounded-full gap-1 h-7 text-xs px-3" asChild>
                      <Link to={`/jobs/${job.id}`}>Open <ChevronRight className="h-3 w-3" /></Link>
                    </Button>
                  </div>
                </div>
              </CardFooter>
            </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
