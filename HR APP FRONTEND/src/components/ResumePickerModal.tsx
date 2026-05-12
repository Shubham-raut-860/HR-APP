import { useState, useEffect, useRef } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import {
  FileText, Star, Upload, Trash2, CheckCircle2,
  Loader2, Zap, AlertCircle, Plus, Pencil, X,
  TrendingUp, TrendingDown, Minus, ShieldAlert, CheckCheck
} from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import {
  uploadStoredResume, updateStoredResume,
  deleteStoredResume, applyWithVaultResume,
  getResumeFitScore, ResumeFitScore,
  StoredResume
} from "@/services/candidatePortal";
import { useCandidateData } from "@/context/CandidateDataProvider";

interface ResumePickerModalProps {
  open: boolean;
  onClose: () => void;
  jobId: string;
  jobTitle: string;
  onSuccess: (candidateId: string) => void;
  easyApply: boolean;
}

type FitScoreMap = Record<string, ResumeFitScore | null>;

function ScoreBadge({ score, tag }: { score: number; tag: string }) {
  const color =
    tag === "strong" ? "bg-emerald-500" :
  tag === "medium" ? "bg-amber-400" : "bg-red-400";
  const label =
    tag === "strong" ? "Strong Match" :
  tag === "medium" ? "Moderate Match" : "Low Match";
  return (
    // w-full + min-w-0 ensure the flex container is bounded by its parent
    // and the progress bar (flex-1) genuinely absorbs remaining space instead
    // of the badge span overflowing the card edge.
    <div className="flex items-center gap-2 w-full min-w-0">
      <div className="flex-1 min-w-0 h-1.5 rounded-full bg-muted overflow-hidden">
        <div className={cn("h-full rounded-full transition-all duration-500", color)} style={{ width: `${Math.min(100, score)}%` }} />
      </div>
      <span className={cn(
        "text-[10px] font-bold shrink-0 whitespace-nowrap px-1.5 py-0.5 rounded-full",
        tag === "strong" ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-400" :
        tag === "medium" ? "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-400" :
        "bg-red-100 text-red-600 dark:bg-red-900/40 dark:text-red-400"
      )}>
        {score.toFixed(0)}% - {label}
      </span>
    </div>
  );
}

export default function ResumePickerModal({
  open, onClose, jobId, jobTitle, onSuccess, easyApply = false
}: ResumePickerModalProps) {
  const { storedResumes, fetchStoredResumes, invalidateResumes } = useCandidateData();
  const [resumes, setResumes] = useState<StoredResume[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);
  const [uploadingNew, setUploadingNew] = useState(false);
  const [showUploadArea, setShowUploadArea] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [newLabel, setNewLabel] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editLabel, setEditLabel] = useState("");
  const [uploadProgress, setUploadProgress] = useState(0);
  const fileRef = useRef<HTMLInputElement>(null);
  const [fitScores, setFitScores] = useState<FitScoreMap>({});
  const [fetchingScores, setFetchingScores] = useState<Set<string>>(new Set());
  const [showConfirm, setShowConfirm] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setFitScores({});
    setFetchingScores(new Set());
    loadResumes();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    setResumes(storedResumes);
    const def = storedResumes.find(r => r.is_default);
    const initialSelected = def?.id ?? (storedResumes.length > 0 ? storedResumes[0].id : null);
    setSelected(prev => (prev && storedResumes.some(r => r.id === prev)) ? prev : initialSelected);
    if (easyApply && def) {
      setLoading(false);
      setTimeout(() => handleApply(def.id), 50);
      return;
    }
    storedResumes.forEach(r => fetchFitScore(r.id));
  }, [open, storedResumes, easyApply]);

  const loadResumes = async () => {
    setLoading(true);
    try {
      await fetchStoredResumes();
    } catch {
      toast.error("Failed to load your resumes");
    } finally {
      setLoading(false);
    }
  };

  const fetchFitScore = async (resumeId: string) => {
    setFetchingScores(prev => new Set(prev).add(resumeId));
    try {
      const score = await getResumeFitScore(jobId, resumeId);
      setFitScores(prev => ({ ...prev, [resumeId]: score ? { ...score, tag: score.tag.toLowerCase() } : null }));
    } catch {
      setFitScores(prev => ({ ...prev, [resumeId]: null }));
    } finally {
      setFetchingScores(prev => { const next = new Set(prev); next.delete(resumeId); return next; });
    }
  };

  const handleFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    const file = files[0];
    if (file.size > 10 * 1024 * 1024) { toast.error("File must be under 10MB"); return; }
    const label = newLabel.trim() || file.name.replace(/\.[^.]+$/, "");
    setUploadingNew(true); setUploadProgress(0);
    const prog = setInterval(() => setUploadProgress(p => Math.min(p + 12, 88)), 200);
    try {
      const isFirst = resumes.length === 0;
      const uploaded = await uploadStoredResume(file, label, isFirst);
      clearInterval(prog); setUploadProgress(100);
      await new Promise(r => setTimeout(r, 300));
      setResumes(prev => [uploaded, ...prev.map(r => isFirst ? { ...r, is_default: false } : r)]);
      setSelected(uploaded.id); setShowUploadArea(false); setNewLabel("");
      toast.success(`"${label}" added to your resume vault `);
      fetchFitScore(uploaded.id);
      invalidateResumes().catch(() => {});
    } catch (err: any) {
      clearInterval(prog);
      toast.error(err.response.data.detail || "Upload failed");
    } finally { setUploadingNew(false); setUploadProgress(0); }
  };

  const handleSetDefault = async (id: string) => {
    try {
      await updateStoredResume(id, { is_default: true });
      setResumes(prev => prev.map(r => ({ ...r, is_default: r.id === id })));
      toast.success("Default resume updated");
      invalidateResumes().catch(() => {});
    } catch { toast.error("Failed to update default"); }
  };

  const [deleteConfirm, setDeleteConfirm] = useState<{ id: string; label: string } | null>(null);

  const handleDelete = async (id: string) => {
    try {
      await deleteStoredResume(id);
      setResumes(prev => { 
        const rem = prev.filter(r => r.id !== id); 
        if (rem.length > 0 && prev.find(r => r.id === id).is_default) {
          rem[0].is_default = true;
        }
        return rem; 
      });
      setFitScores(prev => { const n = { ...prev }; delete n[id]; return n; });
      if (selected === id) setSelected(resumes.find(r => r.id !== id).id || null);
      toast.success("Resume removed");
      invalidateResumes().catch(() => {});
    } catch { toast.error("Failed to delete resume"); }
    setDeleteConfirm(null);
  };

  const handleRename = async (id: string) => {
    if (!editLabel.trim()) return;
    try {
      const updated = await updateStoredResume(id, { label: editLabel.trim() });
      setResumes(prev => prev.map(r => r.id === id ? { ...r, label: updated.label } : r));
      setEditingId(null); toast.success("Renamed");
      invalidateResumes().catch(() => {});
    } catch { toast.error("Rename failed"); }
  };

  const handleApplyClick = () => {
    if (!selected) { toast.error("Select a resume first"); return; }
    const score = fitScores[selected];
    if (score && score.tag === "reject") { setShowConfirm(true); return; }
    handleApply();
  };

  const handleApply = async (overrideId: string) => {
    const resumeId = overrideId || selected;
    if (!resumeId) { toast.error("Select a resume first"); return; }
    setShowConfirm(false); setApplying(true); setServerError(null);
    try {
      const result = await applyWithVaultResume(jobId, resumeId);
      toast.success(`Application submitted for ${jobTitle}!`);
      onSuccess(result.id); onClose();
    } catch (err: any) {
      if (err.response.status === 409) {
        toast.info("You've already applied to this job");
        onSuccess(); onClose();
        return;
      }

      const status: number | undefined = err.response.status;
      const detail: string = String(err.response.data.detail ?? "");
      const detailLower = detail.toLowerCase();

      if (detailLower.includes("poppler") || detailLower.includes("ocr") || detailLower.includes("page count")) {
        const msg = "The server cannot process PDFs right now (poppler is not installed). Try uploading a .docx file instead, or contact support.";
        setServerError(msg);
        toast.error("PDF processing unavailable", {
          description: msg,
          duration: 8000,
        });
        return;
      }

      if (
        status === 503 ||
        status === 504 ||
        detailLower.includes("ai service temporarily unavailable") ||
        detailLower.includes("circuit open") ||
        detailLower.includes("deploymentnotfound") ||
        detailLower.includes("timed out")
      ) {
        const msg = "Scoring service is temporarily unavailable. Your application was not submitted. Please retry in a minute.";
        setServerError(msg);
        toast.error("Service temporarily unavailable", {
          description: msg,
          duration: 8000,
        });
        return;
      }

      if (status && status >= 500) {
        const msg = "We hit a temporary server issue while submitting your application. Please try again.";
        setServerError(msg);
        toast.error("Application failed", {
          description: msg,
          duration: 8000,
        });
        return;
      }

      toast.error("Application failed. Please verify your resume selection and try again.");
    } finally {
      setApplying(false);
    }
  };

  const formatSize = (kb: number) => kb < 1024 ? `${kb} KB` : `${(kb / 1024).toFixed(1)} MB`;
  const formatDate = (iso: string) => new Date(iso).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });

  const selectedResume = resumes.find(r => r.id === selected);
  const selectedScore = selected ? fitScores[selected] : null;
  const isSelectedScoreLow = selectedScore.tag === "reject";

  return (
    <>
      <Dialog open={open} onOpenChange={v => { if (!v) onClose(); }}>
        <DialogContent className="max-w-lg w-full p-0 gap-0 overflow-hidden rounded-2xl border border-border/60 shadow-2xl">
          <DialogHeader className="px-6 pt-6 pb-4 border-b border-border/40 bg-muted/20">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-xl bg-primary/10"><Zap className="h-5 w-5 text-primary fill-primary/30" /></div>
              <div>
                <DialogTitle className="text-base font-semibold leading-tight">Apply to {jobTitle}</DialogTitle>
                <DialogDescription className="text-xs mt-0.5">
  {resumes.length > 0 ? "Choose a resume - AI match score shown for each" : "Upload a resume to apply"}
                </DialogDescription>
              </div>
            </div>
          </DialogHeader>

          <div className="px-6 py-5 space-y-4 max-h-[70vh] overflow-y-auto">

            {/* Server-side error banner */}
            {serverError && (
              <div className="flex items-start gap-3 p-3.5 rounded-xl border border-red-200 bg-red-50 dark:bg-red-950/30 dark:border-red-800">
                <AlertCircle className="h-4 w-4 text-red-500 shrink-0 mt-0.5" />
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-red-700 dark:text-red-400">Server Error</p>
                  <p className="text-xs text-red-600 dark:text-red-300 mt-0.5 leading-relaxed">{serverError}</p>
                </div>
                <Button type="button" variant="ghost" size="icon" onClick={() => setServerError(null)} className="shrink-0 ml-auto h-6 w-6 hover:opacity-70 transition-opacity">
                  <X className="h-3.5 w-3.5 text-red-400" />
                </Button>
              </div>
            )}

            {loading ? (
              <div className="py-10 flex flex-col items-center gap-3 text-muted-foreground">
                <Loader2 className="h-6 w-6 animate-spin" />
                <span className="text-sm">Loading your resume vault</span>
              </div>
            ) : (
              <>
                {resumes.length > 0 && (
                  <div className="space-y-2">
                    <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground px-0.5">Your Resumes ({resumes.length}/5)</p>
                    {resumes.map(r => {
                      const fit = fitScores[r.id];
                      const isFetching = fetchingScores.has(r.id);
                      return (
                        <Card
                          key={r.id}
                          role="button"
                          tabIndex={0}
                          aria-label={`Select resume ${r.label}`}
                          aria-pressed={selected === r.id}
                          onClick={() => setSelected(r.id)}
                          onKeyDown={e => {
                            if (e.key === "Enter" || e.key === " ") {
                              e.preventDefault();
                              setSelected(r.id);
                            }
                          }}
                          className={cn(
                          "group relative flex flex-col gap-2.5 p-3.5 rounded-xl border cursor-pointer transition-all duration-200",
  selected === r.id ? "border-primary/60 bg-primary/5 shadow-sm shadow-primary/10" : "border-border/50 hover:border-border hover:bg-muted/30"
                        )}
                        >
                          <div className="relative z-10 flex items-center gap-3 min-w-0">
  <div className={cn("shrink-0 h-4 w-4 rounded-full border-2 flex items-center justify-center transition-all", selected === r.id ? "border-primary bg-primary" : "border-muted-foreground/40")}>
                              {selected === r.id && <div className="h-1.5 w-1.5 rounded-full bg-white" />}
                            </div>
  <div className={cn("shrink-0 p-2 rounded-lg transition-colors", selected === r.id ? "bg-primary/15" : "bg-muted/50 group-hover:bg-muted")}>
  <FileText className={cn("h-4 w-4", selected === r.id ? "text-primary" : "text-muted-foreground")} />
                            </div>
                            <div className="flex-1 min-w-0 pr-20">
                              {editingId === r.id ? (
                                <div className="flex items-center gap-2" onClick={e => e.stopPropagation()}>
                                  <Input value={editLabel} onChange={e => setEditLabel(e.target.value)} onKeyDown={e => { if (e.key === "Enter") handleRename(r.id); if (e.key === "Escape") setEditingId(null); }} className="h-7 text-sm px-2 py-0" autoFocus />
                                  <Button size="icon" variant="ghost" className="h-6 w-6 shrink-0" onClick={() => handleRename(r.id)}><CheckCircle2 className="h-3.5 w-3.5 text-primary" /></Button>
                                  <Button size="icon" variant="ghost" className="h-6 w-6 shrink-0" onClick={() => setEditingId(null)}><X className="h-3.5 w-3.5" /></Button>
                                </div>
                              ) : (
                                <>
                                  <div className="flex items-center gap-1.5 min-w-0">
                                    <span className="block min-w-0 flex-1 text-sm font-medium truncate" title={r.label}>{r.label}</span>
                                    {r.is_default && <Badge className="text-[9px] px-1.5 py-0 h-4 bg-amber-100 text-amber-700 border-amber-200 dark:bg-amber-900/30 dark:text-amber-400 shrink-0">Default</Badge>}
                                  </div>
                                  <p className="text-xs text-muted-foreground truncate mt-0.5" title={r.original_filename}>{r.original_filename}</p>
                                  <p className="text-[11px] text-muted-foreground mt-0.5">{formatSize(r.file_size_kb)} | {formatDate(r.uploaded_at)}</p>
                                </>
                              )}
                            </div>
                          </div>
                          {/* Action buttons: absolutely positioned so they never consume flex space in the row */}
                          {editingId !== r.id && (
                            <div className="absolute top-2.5 right-2.5 z-20 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity" onClick={e => e.stopPropagation()}>
                              {!r.is_default && <Button size="icon" variant="ghost" className="h-7 w-7 hover:text-amber-500 rounded-lg bg-background/80 backdrop-blur-sm" title="Set as default" onClick={() => handleSetDefault(r.id)}><Star className="h-3.5 w-3.5" /></Button>}
                              <Button size="icon" variant="ghost" className="h-7 w-7 hover:text-blue-500 rounded-lg bg-background/80 backdrop-blur-sm" title="Rename" onClick={() => { setEditingId(r.id); setEditLabel(r.label); }}><Pencil className="h-3.5 w-3.5" /></Button>
                              <Button size="icon" variant="ghost" className="h-7 w-7 hover:text-destructive rounded-lg bg-background/80 backdrop-blur-sm" title="Delete" onClick={() => setDeleteConfirm({ id: r.id, label: r.label })}><Trash2 className="h-3.5 w-3.5" /></Button>
                            </div>
                          )}
                          {/* Fit Score Bar */}
                          {editingId !== r.id && (
                            <div className="relative z-10 pl-10 overflow-hidden">
                              {isFetching ? (
                                <div className="flex items-center gap-2 text-[10px] text-muted-foreground"><Loader2 className="h-3 w-3 animate-spin" />Calculating match</div>
                              ) : fit ? (
                                <ScoreBadge score={fit.resume_score} tag={fit.tag} />
                              ) : fit === null ? (
                                <span className="text-[10px] text-muted-foreground">Score unavailable</span>
                              ) : null}
                            </div>
                          )}
                        </Card>
                      );
                    })}
                  </div>
                )}

                {resumes.length < 5 && (
                  <div>
                    {!showUploadArea ? (
                      <Button type="button" variant="ghost" onClick={() => setShowUploadArea(true)} className="w-full h-auto flex items-center justify-center gap-2 py-3 rounded-xl border-2 border-dashed border-border/50 text-sm text-muted-foreground hover:border-primary/40 hover:text-primary hover:bg-primary/5 transition-all duration-200">
                        <Plus className="h-4 w-4" /> Add another resume
                      </Button>
                    ) : (
                      <div className="space-y-3 rounded-xl border border-border/50 p-4 bg-muted/20">
                        <div className="flex items-center justify-between">
                          <p className="text-sm font-medium">Upload new resume</p>
                          <Button size="icon" variant="ghost" className="h-6 w-6" onClick={() => setShowUploadArea(false)}><X className="h-3.5 w-3.5" /></Button>
                        </div>
                        <Input placeholder="Label (e.g. Senior Backend Dev)" value={newLabel} onChange={e => setNewLabel(e.target.value)} className="text-sm h-9" />
  <Button type="button" variant="ghost" aria-label="Upload resume file" onDragOver={e => { e.preventDefault(); setDragOver(true); }} onDragLeave={() => setDragOver(false)} onDrop={e => { e.preventDefault(); setDragOver(false); handleFiles(e.dataTransfer.files); }} onClick={() => fileRef.current.click()} className={cn("w-full h-auto border-2 border-dashed rounded-xl p-6 text-center cursor-pointer transition-all", dragOver ? "border-primary bg-primary/10" : "border-border/50 hover:border-primary/50 hover:bg-muted/30")}>
                          <Input ref={fileRef} type="file" className="hidden" accept=".pdf,.doc,.docx,.png,.jpg,.jpeg,.webp,.tiff,.tif,.bmp,.gif" onChange={e => handleFiles(e.target.files)} />
                          {uploadingNew ? (
                            <div className="space-y-3"><Loader2 className="h-6 w-6 animate-spin text-primary mx-auto" /><p className="text-xs text-muted-foreground">Uploading & encrypting</p><Progress value={uploadProgress} className="h-1.5" /></div>
                          ) : (
                            <><Upload className="h-6 w-6 text-muted-foreground mx-auto mb-2" /><p className="text-sm font-medium">Drop file here or click to browse</p><p className="text-xs text-muted-foreground mt-1">PDF, DOC, DOCX or image | Max 10 MB</p></>
                          )}
                        </Button>
                      </div>
                    )}
                  </div>
                )}

                {resumes.length >= 5 && (
                  <div className="flex items-center gap-2 p-3 rounded-xl bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 text-sm text-amber-700 dark:text-amber-400">
                    <AlertCircle className="h-4 w-4 shrink-0" /> Vault full (5/5). Delete an old resume to add a new one.
                  </div>
                )}

                {resumes.length === 0 && !showUploadArea && (
                  <Button type="button" variant="ghost" onClick={() => setShowUploadArea(true)} className="w-full h-auto py-12 rounded-xl border-2 border-dashed border-border/50 flex flex-col items-center gap-3 hover:border-primary/50 hover:bg-primary/5 transition-all duration-200 group">
                    <div className="p-3 rounded-full bg-muted/50 group-hover:bg-primary/10 transition-colors"><Upload className="h-6 w-6 text-muted-foreground group-hover:text-primary transition-colors" /></div>
                    <div className="text-center"><p className="text-sm font-medium">No resumes saved yet</p><p className="text-xs text-muted-foreground mt-0.5">Click to upload your first resume</p></div>
                  </Button>
                )}
              </>
            )}
          </div>

          {/* Footer */}
          <div className="px-6 py-4 border-t border-border/40 bg-muted/10 flex items-center justify-between gap-3">
            <div className="text-xs text-muted-foreground min-w-0 flex-1">
              {selectedResume ? (
                selectedScore ? (
                  <span className={cn("flex items-center gap-1 font-medium min-w-0", isSelectedScoreLow ? "text-red-500" : selectedScore.tag === "medium" ? "text-amber-600 dark:text-amber-400" : "text-emerald-600 dark:text-emerald-400")}>
                    {isSelectedScoreLow ? <TrendingDown className="h-3 w-3" /> : selectedScore.tag === "medium" ? <Minus className="h-3 w-3" /> : <TrendingUp className="h-3 w-3" />}
                    <span className="truncate" title={selectedResume.label}>
                      {selectedScore.resume_score.toFixed(0)}% match - {selectedResume.label}
                    </span>
                  </span>
                ) : (
                  <span className="block truncate" title={selectedResume.label}>Using: <span className="font-medium text-foreground">{selectedResume.label}</span></span>
                )
              ) : (
                <span className="text-amber-600 dark:text-amber-400 flex items-center gap-1"><AlertCircle className="h-3 w-3" /> Select a resume</span>
              )}
            </div>
            <div className="flex gap-2 shrink-0">
              <Button variant="outline" size="sm" onClick={onClose} className="rounded-xl">Cancel</Button>
              <Button size="sm" disabled={!selected || applying || loading} onClick={handleApplyClick} className={cn("rounded-xl min-w-[110px]", isSelectedScoreLow ? "bg-amber-500 hover:bg-amber-600 text-white" : "bg-primary hover:bg-primary/90")}>
                {applying ? <><Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" /> Submitting</> : isSelectedScoreLow ? <><ShieldAlert className="h-3.5 w-3.5 mr-1.5" /> Apply Anyway</> : <><Zap className="h-3.5 w-3.5 mr-1.5 fill-current" /> Apply Now</>}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* Low Score Warning Dialog */}
      <Dialog open={showConfirm} onOpenChange={setShowConfirm}>
        <DialogContent className="max-w-sm rounded-2xl">
          <DialogHeader>
            <div className="flex items-center gap-3 mb-1">
              <div className="p-2.5 rounded-xl bg-amber-100 dark:bg-amber-900/30"><ShieldAlert className="h-5 w-5 text-amber-600 dark:text-amber-400" /></div>
              <DialogTitle className="text-base">Low Match Score</DialogTitle>
            </div>
            <DialogDescription className="text-sm leading-relaxed">
              Your resume scored <span className="font-bold text-red-500">{selectedScore.resume_score.toFixed(0)}%</span> for <span className="font-medium text-foreground">{jobTitle}</span>. This is below the recommended threshold - you may be less competitive against other applicants.
            </DialogDescription>
          </DialogHeader>
          {selectedScore && (
            <div className="space-y-2 my-1 text-xs text-muted-foreground bg-muted/30 rounded-xl p-3 border border-border/40">
              <p className="font-semibold text-foreground text-xs uppercase tracking-wide mb-1.5">Score Breakdown</p>
              {[
                { label: "Skills", value: selectedScore.skill_match_pct },
                { label: "Experience", value: selectedScore.experience_match_pct },
                { label: "Projects", value: selectedScore.project_relevance_pct },
                { label: "Education", value: selectedScore.education_match_pct },
              ].map(item => (
                <div key={item.label} className="flex items-center gap-2">
                  <span className="w-20 shrink-0">{item.label}</span>
                  <div className="flex-1 h-1.5 rounded-full bg-muted overflow-hidden">
  <div className={cn("h-full rounded-full", item.value >= 70 ? "bg-emerald-400" : item.value >= 40 ? "bg-amber-400" : "bg-red-400")} style={{ width: `${item.value}%` }} />
                  </div>
                  <span className="w-8 text-right font-medium">{item.value.toFixed(0)}%</span>
                </div>
              ))}
            </div>
          )}
          <p className="text-xs text-muted-foreground">We suggest uploading a more tailored resume. You can still apply, but consider improving your match first.</p>
          <div className="flex gap-2 pt-1">
            <Button variant="outline" className="flex-1 rounded-xl" onClick={() => setShowConfirm(false)}>Go Back</Button>
            <Button className="flex-1 rounded-xl bg-amber-500 hover:bg-amber-600 text-white" onClick={() => handleApply()}>
              <CheckCheck className="h-3.5 w-3.5 mr-1.5" /> Apply Anyway
            </Button>
          </div>
        </DialogContent>
      </Dialog>
      {/* FIX F-1: AlertDialog replaces blocking window.confirm() */}
      <AlertDialog open={!!deleteConfirm} onOpenChange={v => { if (!v) setDeleteConfirm(null); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Remove Resume</AlertDialogTitle>
            <AlertDialogDescription>
              Remove "{deleteConfirm?.label}" from your vault. This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() => deleteConfirm && handleDelete(deleteConfirm.id)}
            >
              Remove
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}


