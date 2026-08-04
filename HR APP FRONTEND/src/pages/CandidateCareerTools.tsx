import React, { useEffect, useRef, useState } from "react";
import {
  FileText, Wand2, PenTool, TrendingUp, Sparkles, Loader2, Plus, Trash2,
  Download, CheckCircle2, User, Briefcase, GraduationCap, FolderGit2, Star,
  FileUp, Palette, Zap, ChevronRight, ChevronLeft, Upload,
  Eye,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { toast } from "sonner";
import { SegmentedTabs } from "@/components/ui/segmented-tabs";
import {
  enhanceCandidateResume,
  buildCandidateResume,
  generateCoverLetter,
  getCareerAnalysis,
  parseResumeForBuilder,
  generateResumePDF,
  uploadStoredResume,
} from "@/services/candidatePortal";

function isValidJobId(id: string): boolean {
  return id.trim().length >= 4 && !/\s/.test(id.trim());
}

const cleanMd = (str: any) => {
  if (typeof str !== 'string') return str || "";
  return str.replace(/\*\*/g, '').replace(/__/g, '').replace(/`/g, '');
};

// ─── Types ────────────────────────────────────────────────────────────────────
interface Contact { name: string; email: string; phone: string; location: string; linkedin: string; github: string; }
interface WorkEntry { id: string; company: string; role: string; start_date: string; end_date: string; location: string; bullets: string[]; }
interface EduEntry { id: string; degree: string; institution: string; year: string; gpa: string; }
interface Project { id: string; title: string; description: string; technologies: string; link: string; }

const uid = () => Math.random().toString(36).slice(2, 9);
const emptyContact = (): Contact => ({ name: "", email: "", phone: "", location: "", linkedin: "", github: "" });
const emptyWork = (): WorkEntry => ({ id: uid(), company: "", role: "", start_date: "", end_date: "", location: "", bullets: [""] });
const emptyEdu = (): EduEntry => ({ id: uid(), degree: "", institution: "", year: "", gpa: "" });
const emptyProject = (): Project => ({ id: uid(), title: "", description: "", technologies: "", link: "" });

// ─── Theme definitions ────────────────────────────────────────────────────────
const THEMES = [
  { id: "classic",     label: "Classic",     color: "#004f9f", font: "serif" },
  { id: "engineering", label: "Engineering", color: "#0a7c4b", font: "sans" },
  { id: "sb2nov",      label: "Modern",      color: "#6d28d9", font: "serif" },
  { id: "moderncv",    label: "Minimal",     color: "#1a1a1a", font: "sans" },
];

// ─── Main Page ─────────────────────────────────────────────────────────────────
const TABS = [
  { id: "builder",  label: "Resume Builder",  icon: PenTool,    badge: "AI" },
  { id: "enhance",  label: "AI Enhancer",     icon: Sparkles,   badge: "AI" },
  { id: "cover",    label: "Cover Letter",    icon: FileText,   badge: null },
  { id: "analysis", label: "Career Analysis", icon: TrendingUp, badge: null },
];
type CareerToolsTab = (typeof TABS)[number]["id"];

const BUILDER_DRAFT_STORAGE_KEY = "candidate_resume_builder_draft_v1";

export default function CandidateCareerTools() {
  const [activeTab, setActiveTab] = useState<CareerToolsTab>("builder");
  const toolTabOptions = TABS.map((tab) => ({
    value: tab.id,
    label: tab.label,
    icon: tab.icon,
    badge: tab.badge ?? undefined,
  }));

  return (
    <div className="min-h-screen bg-muted/30">
      {/* Top bar */}
      <div className="bg-background border-b border-border/60 px-4 md:px-6 py-3">
        <div className="max-w-6xl mx-auto flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-2.5">
            <div className="p-1.5 rounded-lg bg-primary/10">
              <Wand2 className="h-5 w-5 text-primary" />
            </div>
            <span className="font-bold text-base tracking-tight">AI Career Studio</span>
          </div>
          <div className="w-full sm:w-auto">
            <SegmentedTabs
              value={activeTab}
              onChange={setActiveTab}
              options={toolTabOptions}
              size="sm"
              className="w-full sm:w-auto"
            />
          </div>
        </div>
      </div>

      {/* Page content */}
      <div className="max-w-6xl mx-auto px-4 md:px-6 py-6 md:py-8">
        {activeTab === "builder"  && <ResumeBuilderTool />}
        {activeTab === "enhance"  && <ResumeEnhancerTool />}
        {activeTab === "cover"    && <CoverLetterTool />}
        {activeTab === "analysis" && <GapAnalysisTool />}
      </div>
    </div>
  );
}

// ─── Resume Builder (step wizard) ─────────────────────────────────────────────
const STEPS = [
  { id: "contact",    label: "Personal Info",   icon: User },
  { id: "summary",   label: "Summary",          icon: FileText },
  { id: "experience",label: "Experience",       icon: Briefcase },
  { id: "education", label: "Education",        icon: GraduationCap },
  { id: "skills",    label: "Skills",           icon: Star },
  { id: "projects",  label: "Projects",         icon: FolderGit2 },
  { id: "finalize",  label: "Finalize & Export",icon: Download },
];

function ResumeBuilderTool() {
  const [step, setStep]           = useState(0);
  const [entryMode, setEntryMode] = useState<"pick" | "import" | "scratch">("pick");
  const [contact, setContact]     = useState<Contact>(emptyContact());
  const [summary, setSummary]     = useState("");
  const [work, setWork]           = useState<WorkEntry[]>([emptyWork()]);
  const [edu, setEdu]             = useState<EduEntry[]>([emptyEdu()]);
  const [skillsRaw, setSkillsRaw] = useState("");
  const [projects, setProjects]   = useState<Project[]>([emptyProject()]);
  const [theme, setTheme]         = useState("classic");
  const [targetRole, setTargetRole] = useState("");
  const [bulletEnhanceJobId, setBulletEnhanceJobId] = useState("");
  const [showAdvancedEnhance, setShowAdvancedEnhance] = useState(false);
  const [building, setBuilding]   = useState(false);
  const [pdfLoading, setPdfLoading] = useState(false);
  const [importLoading, setImportLoading] = useState(false);
  const [builtResume, setBuiltResume] = useState<any>(null);
  const [showPreview, setShowPreview] = useState(false);
  const [saveLoading, setSaveLoading] = useState(false);
  const [enhancingBullet, setEnhancingBullet] = useState<string | null>(null);
  const [hasHydratedDraft, setHasHydratedDraft] = useState(false);
  const importRef = useRef<HTMLInputElement>(null);

  const currentTheme = THEMES.find(t => t.id === theme)!;

  useEffect(() => {
    try {
      const raw = localStorage.getItem(BUILDER_DRAFT_STORAGE_KEY);
      if (!raw) return;
      const draft = JSON.parse(raw) as any;
      if (draft && typeof draft === "object") {
        if (draft.entryMode === "import" || draft.entryMode === "scratch") setEntryMode(draft.entryMode);
        if (draft.contact && typeof draft.contact === "object") setContact({ ...emptyContact(), ...draft.contact });
        if (typeof draft.summary === "string") setSummary(draft.summary);
        if (Array.isArray(draft.work) && draft.work.length > 0) setWork(draft.work);
        if (Array.isArray(draft.edu) && draft.edu.length > 0) setEdu(draft.edu);
        if (typeof draft.skillsRaw === "string") setSkillsRaw(draft.skillsRaw);
        if (Array.isArray(draft.projects) && draft.projects.length > 0) setProjects(draft.projects);
        if (typeof draft.theme === "string") setTheme(draft.theme);
        if (typeof draft.targetRole === "string") setTargetRole(draft.targetRole);
        if (typeof draft.bulletEnhanceJobId === "string") setBulletEnhanceJobId(draft.bulletEnhanceJobId);
        if (typeof draft.showAdvancedEnhance === "boolean") setShowAdvancedEnhance(draft.showAdvancedEnhance);
        if (typeof draft.step === "number") setStep(Math.max(0, Math.min(STEPS.length - 1, draft.step)));
      }
    } catch {
      localStorage.removeItem(BUILDER_DRAFT_STORAGE_KEY);
    } finally {
      setHasHydratedDraft(true);
    }
  }, []);

  useEffect(() => {
    if (!hasHydratedDraft) return;
    const draft = {
      step,
      entryMode,
      contact,
      summary,
      work,
      edu,
      skillsRaw,
      projects,
      theme,
      targetRole,
      bulletEnhanceJobId,
      showAdvancedEnhance,
    };
    localStorage.setItem(BUILDER_DRAFT_STORAGE_KEY, JSON.stringify(draft));
  }, [hasHydratedDraft, step, entryMode, contact, summary, work, edu, skillsRaw, projects, theme, targetRole, bulletEnhanceJobId, showAdvancedEnhance]);

  const clearBuilderDraft = () => {
    localStorage.removeItem(BUILDER_DRAFT_STORAGE_KEY);
    toast.success("Draft cleared");
  };

  // Import existing resume
  const handleImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setImportLoading(true);
    try {
      const data = await parseResumeForBuilder(file);
      const c = data.contact || {};
      setContact({ name: c.name||"", email: c.email||"", phone: c.phone||"", location: c.location||"", linkedin: c.linkedin||"", github: c.github||"" });
      setSummary(data.summary || "");
      if (data.work_experience?.length) setWork(data.work_experience.map((w: any) => ({ id: uid(), company: w.company||"", role: w.role||"", start_date: w.start_date||"", end_date: w.end_date||"Present", location: w.location||"", bullets: Array.isArray(w.bullets) && w.bullets.length > 0 ? w.bullets : [""] })));
      if (data.education?.length) setEdu(data.education.map((e: any) => ({ id: uid(), degree: e.degree||"", institution: e.institution||"", year: e.year||"", gpa: e.gpa||"" })));
      if (data.skills) {
        const all = Object.values(data.skills).flat().filter(Boolean);
        setSkillsRaw((all as string[]).join(", "));
      }
      if (data.projects?.length) setProjects(data.projects.map((p: any) => ({ id: uid(), title: p.title||"", description: p.description||"", technologies: Array.isArray(p.technologies) ? p.technologies.join(", ") : "", link: p.link||"" })));
      setEntryMode("import");
      toast.success("Resume imported! Start from Step 1 or jump ahead.");
    } catch (error: any) {
      const detail = error?.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : "Import failed. Please use a valid document or image file.");
    } finally {
      setImportLoading(false);
      e.target.value = "";
    }
  };

  const handleBuild = async () => {
    const payload = {
      target_role: targetRole,
      personal_info: contact,
      work_experience: work.filter(w => w.company || w.role).map(w => ({ company: w.company, role: w.role, start_date: w.start_date, end_date: w.end_date || "Present", location: w.location, achievements: w.bullets.filter(Boolean) })),
      education: edu.filter(e => e.degree || e.institution).map(e => ({ raw: `${e.degree} - ${e.institution} ${e.year}`.trim() })),
      skills: skillsRaw.split(",").map(s => s.trim()).filter(Boolean),
      projects: projects.filter(p => p.title).map(p => ({ title: p.title, description: p.description, technologies: p.technologies.split(",").map(t => t.trim()).filter(Boolean), link: p.link })),
      summary: summary || undefined,
    };
    setBuilding(true);
    try {
      const data = await buildCandidateResume(payload);
      setBuiltResume(data.resume ?? data);
      setShowPreview(true);
      toast.success("Resume generated!");
    } catch {
      toast.error("Build failed. Please try again.");
    } finally {
      setBuilding(false);
    }
  };

  const handleEnhanceBullet = async (workIdx: number, bulletIdx: number) => {
    const bullet = work[workIdx].bullets[bulletIdx];
    if (!bullet.trim()) return;
    if (!isValidJobId(bulletEnhanceJobId)) {
      toast.error("Enter a valid Job ID before using AI bullet enhancement.");
      return;
    }
    const key = `${workIdx}-${bulletIdx}`;
    setEnhancingBullet(key);
    try {
      const enhanced = await enhanceCandidateResume(
        bulletEnhanceJobId.trim(),
        { resumeText: `Target role: ${targetRole || work[workIdx].role}\n\nBullet:\n${bullet}` }
      );
      const rewrites = enhanced?.bullet_rewrites;
      if (Array.isArray(rewrites) && rewrites.length > 0) {
        const improved = rewrites[0]?.improved || rewrites[0]?.enhanced_bullets?.[0];
        if (improved) {
          setWork(prev => prev.map((w, wi) => wi === workIdx ? { ...w, bullets: w.bullets.map((b, bi) => bi === bulletIdx ? improved : b) } : w));
          toast.success("Bullet enhanced!");
        }
      }
    } catch { toast.error("Enhancement failed."); }
    finally { setEnhancingBullet(null); }
  };

  const handleDownloadPDF = async () => {
    if (!builtResume) { toast.error("Generate your resume first."); return; }
    setPdfLoading(true);
    try {
      const blob = await generateResumePDF(builtResume, theme as any);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = `${contact.name || "resume"}_resume.pdf`; a.click();
      URL.revokeObjectURL(url);
      toast.success("PDF downloaded!");
    } catch (error: any) {
      const detail = error?.response?.data?.detail || error?.message;
      toast.error(typeof detail === "string" ? detail : "PDF generation failed.");
    }
    finally { setPdfLoading(false); }
  };

  const handleSaveToVault = async () => {
    if (!builtResume) { toast.error("Generate your resume first."); return; }
    setSaveLoading(true);
    try {
      const blob = await generateResumePDF(builtResume, theme as any);
      const file = new File([blob], `${contact.name || "resume"}_ai_built.pdf`, { type: "application/pdf" });
      const label = `AI Built: ${targetRole || contact.name || "Resume"}`;
      await uploadStoredResume(file, label.slice(0, 50), false);
      toast.success("Resume saved to your vault! Check Settings > Resume Vault.");
    } catch (error: any) {
      const detail = error?.response?.data?.detail || error?.message;
      toast.error(typeof detail === "string" ? detail : "Failed to save to vault.");
    } finally {
      setSaveLoading(false);
    }
  };

  const phaseProgressPct = Math.round(((step + 1) / STEPS.length) * 100);
  const hasAnyBulletText = work.some((entry) => entry.bullets.some((bullet) => bullet.trim().length > 0));
  const canUseEnhancer = hasAnyBulletText && isValidJobId(bulletEnhanceJobId);

  return (
    <div className="space-y-6">
      <input ref={importRef} type="file" accept=".pdf,.docx,.doc,.png,.jpg,.jpeg,.webp,.tiff,.tif,.bmp,.gif" className="hidden" onChange={handleImport} />

      {entryMode === "pick" ? (
        <Card className="border border-border/70 shadow-sm">
          <CardContent className="p-6 md:p-8 space-y-6">
            <div>
              <h2 className="text-lg font-semibold">How do you want to start?</h2>
              <p className="text-sm text-muted-foreground mt-1">Choose one path. You can edit every section before exporting.</p>
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <button
                type="button"
                onClick={() => importRef.current?.click()}
                className="group text-left rounded-2xl border-2 border-primary/40 bg-primary/10 hover:bg-primary/15 hover:border-primary/60 p-5 transition-all"
              >
                <div className="flex items-center gap-2">
                  {importLoading ? <Loader2 className="h-5 w-5 text-primary animate-spin" /> : <FileUp className="h-5 w-5 text-primary" />}
                  <span className="font-semibold">Import Existing Resume</span>
                </div>
                <p className="text-sm text-muted-foreground mt-2">Upload PDF, DOC, DOCX or image and auto-fill the builder.</p>
              </button>
              <button
                type="button"
                onClick={() => setEntryMode("scratch")}
                className="group text-left rounded-2xl border border-border/70 hover:border-primary/40 p-5 bg-background hover:bg-muted/20 transition-all"
              >
                <div className="flex items-center gap-2">
                  <PenTool className="h-5 w-5 text-primary" />
                  <span className="font-semibold">Start From Scratch</span>
                </div>
                <p className="text-sm text-muted-foreground mt-2">Use a guided form to craft a resume section-by-section.</p>
              </button>
            </div>
            <div className="flex flex-col items-start gap-2 rounded-xl border border-border/60 bg-muted/20 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-xs text-muted-foreground">Your progress is auto-saved locally while you build.</p>
              <button
                type="button"
                className="text-xs text-muted-foreground hover:text-foreground underline-offset-2 hover:underline"
                onClick={clearBuilderDraft}
              >
                Clear draft
              </button>
            </div>
          </CardContent>
        </Card>
      ) : (
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_280px]">
        <div className="space-y-5 pb-16 sm:pb-6">
          <div className="rounded-2xl border border-border/60 bg-background/70 p-4 md:p-5 space-y-4">
            <div className="md:hidden space-y-2">
              <div className="flex items-center justify-between text-xs gap-2">
                <span className="font-semibold text-foreground">Step {step + 1} of {STEPS.length}</span>
                <span className="text-muted-foreground max-w-[58%] text-right truncate">{STEPS[step].label}</span>
              </div>
              <div className="h-1.5 rounded-full bg-muted overflow-hidden">
                <div className="h-full bg-primary transition-all" style={{ width: `${phaseProgressPct}%` }} />
              </div>
            </div>
            <div className="hidden md:block space-y-2">
              <div className="flex items-center justify-between text-xs">
                <span className="font-semibold text-foreground">Step {step + 1} of {STEPS.length}</span>
                <span className="text-muted-foreground truncate">{STEPS[step].label}</span>
              </div>
              <div className="h-1.5 rounded-full bg-muted overflow-hidden">
                <div className="h-full bg-primary transition-all" style={{ width: `${phaseProgressPct}%` }} />
              </div>
            </div>
            {step < 6 && (
              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider block">Target Role</label>
                <Input placeholder="e.g. Senior Software Engineer" value={targetRole} onChange={e => setTargetRole(e.target.value)} className="max-w-2xl" />
              </div>
            )}
          </div>

      {/* ─── Step content ─── */}
      <Card className="border border-border shadow-sm">
        <CardContent className="p-4 sm:p-6">

          {/* STEP 0: Personal Info */}
          {step === 0 && (
            <div className="space-y-4">
              <h2 className="text-base font-semibold flex items-center gap-2"><User className="h-4 w-4 text-primary" />Personal Information</h2>
              <div className="grid sm:grid-cols-2 gap-3">
                <div className="sm:col-span-2">
                  <label className="text-xs text-muted-foreground mb-1 block">Full Name *</label>
                  <Input placeholder="Your Full Name" value={contact.name} onChange={e => setContact(c => ({ ...c, name: e.target.value }))} />
                </div>
                <div>
                  <label className="text-xs text-muted-foreground mb-1 block">Email *</label>
                  <Input placeholder="Email Address" value={contact.email} onChange={e => setContact(c => ({ ...c, email: e.target.value }))} />
                </div>
                <div>
                  <label className="text-xs text-muted-foreground mb-1 block">Phone</label>
                  <Input placeholder="Phone Number" value={contact.phone} onChange={e => setContact(c => ({ ...c, phone: e.target.value }))} />
                </div>
                <div className="sm:col-span-2">
                  <label className="text-xs text-muted-foreground mb-1 block">Location</label>
                  <Input placeholder="City, Country" value={contact.location} onChange={e => setContact(c => ({ ...c, location: e.target.value }))} />
                </div>
                <div>
                  <label className="text-xs text-muted-foreground mb-1 block">LinkedIn</label>
                  <Input placeholder="LinkedIn Profile URL" value={contact.linkedin} onChange={e => setContact(c => ({ ...c, linkedin: e.target.value }))} />
                </div>
                <div>
                  <label className="text-xs text-muted-foreground mb-1 block">GitHub</label>
                  <Input placeholder="GitHub Profile URL" value={contact.github} onChange={e => setContact(c => ({ ...c, github: e.target.value }))} />
                </div>
              </div>
            </div>
          )}

          {/* STEP 1: Summary */}
          {step === 1 && (
            <div className="space-y-4">
              <h2 className="text-base font-semibold flex items-center gap-2"><FileText className="h-4 w-4 text-primary" />Professional Summary</h2>
              <p className="text-sm text-muted-foreground">2–3 compelling sentences that position you for your target role. Leave blank to let AI write one for you.</p>
              <Textarea rows={6} className="resize-none" placeholder="Results-driven software engineer with 5+ years of experience building scalable distributed systems..." value={summary} onChange={e => setSummary(e.target.value)} />
              <p className="text-xs text-muted-foreground bg-muted/40 border rounded-lg px-3 py-2 flex items-start gap-2">
                <Sparkles className="h-3.5 w-3.5 text-primary shrink-0 mt-0.5" />
                <span>AI will generate or refine your summary when you click <strong>Generate Resume</strong>, pulling from your experience and target role.</span>
              </p>
            </div>
          )}

          {/* STEP 2: Experience */}
          {step === 2 && (
            <div className="space-y-5">
              <h2 className="text-base font-semibold flex items-center gap-2"><Briefcase className="h-4 w-4 text-primary" />Work Experience</h2>
              <div className="space-y-4">
                {work.map((entry, i) => (
                  <div key={entry.id} className="border rounded-xl p-4 bg-muted/20 space-y-3 group relative">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-bold text-primary uppercase tracking-wider">Position {i + 1}</span>
                      {work.length > 1 && (
                        <button onClick={() => setWork(p => p.filter((_, idx) => idx !== i))} className="text-muted-foreground hover:text-destructive opacity-0 group-hover:opacity-100 transition-opacity">
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      )}
                    </div>
                    <div className="grid sm:grid-cols-2 gap-2.5">
                      <Input placeholder="Company name" value={entry.company} onChange={e => setWork(p => p.map((w, idx) => idx === i ? { ...w, company: e.target.value } : w))} />
                      <Input placeholder="Job title" value={entry.role} onChange={e => setWork(p => p.map((w, idx) => idx === i ? { ...w, role: e.target.value } : w))} />
                      <Input placeholder="Start (e.g. Jan 2022)" value={entry.start_date} onChange={e => setWork(p => p.map((w, idx) => idx === i ? { ...w, start_date: e.target.value } : w))} />
                      <Input placeholder="End (e.g. Present)" value={entry.end_date} onChange={e => setWork(p => p.map((w, idx) => idx === i ? { ...w, end_date: e.target.value } : w))} />
                      <div className="sm:col-span-2">
                        <Input placeholder="Location (optional)" value={entry.location} onChange={e => setWork(p => p.map((w, idx) => idx === i ? { ...w, location: e.target.value } : w))} />
                      </div>
                    </div>
                    <div className="space-y-2">
                      <div className="flex items-center justify-between">
                        <label className="text-xs font-medium text-muted-foreground">Key Achievements (bullets)</label>
                        <button onClick={() => setWork(p => p.map((w, idx) => idx === i ? { ...w, bullets: [...w.bullets, ""] } : w))} className="text-xs text-primary hover:underline flex items-center gap-1">
                          <Plus className="h-3 w-3" />Add bullet
                        </button>
                      </div>
                      {hasAnyBulletText && (
                        <div className="rounded-lg border border-border/60 bg-background/80 px-3 py-2 space-y-2">
                          <button
                            type="button"
                            className="text-xs font-medium text-primary hover:underline"
                            onClick={() => setShowAdvancedEnhance(v => !v)}
                          >
                            {showAdvancedEnhance ? "Hide advanced AI bullet tuning" : "Show advanced AI bullet tuning"}
                          </button>
                          {showAdvancedEnhance && (
                            <div className="space-y-1.5">
                              <label className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wide block">
                                Job ID for AI bullet enhancement
                              </label>
                              <Input
                                placeholder="Paste Job ID from listing URL"
                                value={bulletEnhanceJobId}
                                onChange={e => setBulletEnhanceJobId(e.target.value)}
                                className="h-8 text-xs"
                              />
                              {!canUseEnhancer && (
                                <p className="text-[11px] text-muted-foreground">
                                  Add a valid Job ID to enable bullet enhancement.
                                </p>
                              )}
                            </div>
                          )}
                        </div>
                      )}
                      {entry.bullets.map((bullet, bi) => (
                        <div key={bi} className="flex gap-2 items-start">
                          <span className="text-muted-foreground mt-2.5 text-xs select-none">•</span>
                          <Textarea rows={2} className="text-xs flex-1 resize-none" placeholder="Led a team of 5 to deliver X, resulting in Y% improvement..." value={bullet}
                            onChange={e => setWork(p => p.map((w, wi) => wi === i ? { ...w, bullets: w.bullets.map((b, bii) => bii === bi ? e.target.value : b) } : w))}
                          />
                          <button
                            title={!showAdvancedEnhance || !canUseEnhancer ? "Enable advanced AI bullet tuning and add a valid Job ID" : "AI enhance"}
                            onClick={() => handleEnhanceBullet(i, bi)}
                            disabled={!bullet.trim() || enhancingBullet !== null || !canUseEnhancer}
                            className="mt-1.5 p-1.5 rounded-lg bg-primary/10 text-primary hover:bg-primary/20 disabled:opacity-40 transition-colors shrink-0">
                            {enhancingBullet === `${i}-${bi}` ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Zap className="h-3.5 w-3.5" />}
                          </button>
                          {entry.bullets.length > 1 && (
                            <button onClick={() => setWork(p => p.map((w, wi) => wi === i ? { ...w, bullets: w.bullets.filter((_, bii) => bii !== bi) } : w))} className="mt-1.5 p-1.5 text-muted-foreground hover:text-destructive shrink-0">
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
              <button onClick={() => setWork(p => [...p, emptyWork()])} className="w-full flex items-center justify-center gap-2 py-3 border-2 border-dashed border-border rounded-xl text-sm text-muted-foreground hover:border-primary/40 hover:text-primary transition-colors">
                <Plus className="h-4 w-4" />Add another position
              </button>
            </div>
          )}

          {/* STEP 3: Education */}
          {step === 3 && (
            <div className="space-y-4">
              <h2 className="text-base font-semibold flex items-center gap-2"><GraduationCap className="h-4 w-4 text-primary" />Education</h2>
              {edu.map((entry, i) => (
                <div key={entry.id} className="border rounded-xl p-4 bg-muted/20 space-y-3 group relative">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-primary uppercase tracking-wider">Qualification {i + 1}</span>
                    {edu.length > 1 && <button onClick={() => setEdu(p => p.filter((_, idx) => idx !== i))} className="text-muted-foreground hover:text-destructive opacity-0 group-hover:opacity-100"><Trash2 className="h-3.5 w-3.5" /></button>}
                  </div>
                  <div className="grid sm:grid-cols-2 gap-2.5">
                    <div className="sm:col-span-2"><Input placeholder="Degree & Major (e.g. B.Tech Computer Science)" value={entry.degree} onChange={e => setEdu(p => p.map((ed, idx) => idx === i ? { ...ed, degree: e.target.value } : ed))} /></div>
                    <Input placeholder="University / Institution" value={entry.institution} onChange={e => setEdu(p => p.map((ed, idx) => idx === i ? { ...ed, institution: e.target.value } : ed))} />
                    <Input placeholder="Graduation Year" value={entry.year} onChange={e => setEdu(p => p.map((ed, idx) => idx === i ? { ...ed, year: e.target.value } : ed))} />
                  </div>
                </div>
              ))}
              <button onClick={() => setEdu(p => [...p, emptyEdu()])} className="w-full flex items-center justify-center gap-2 py-3 border-2 border-dashed border-border rounded-xl text-sm text-muted-foreground hover:border-primary/40 hover:text-primary transition-colors">
                <Plus className="h-4 w-4" />Add qualification
              </button>
            </div>
          )}

          {/* STEP 4: Skills */}
          {step === 4 && (
            <div className="space-y-4">
              <h2 className="text-base font-semibold flex items-center gap-2"><Star className="h-4 w-4 text-primary" />Skills</h2>
              <p className="text-sm text-muted-foreground">List everything — AI will organize them into clean categories for you.</p>
              <Textarea rows={7} className="resize-none" placeholder="React, TypeScript, Node.js, Python, PostgreSQL, Docker, AWS, Kubernetes, Figma, Git..." value={skillsRaw} onChange={e => setSkillsRaw(e.target.value)} />
              {skillsRaw && (
                <div className="flex flex-wrap gap-1.5">
                  {skillsRaw.split(",").map(s => s.trim()).filter(Boolean).map((s, i) => (
                    <Badge key={i} variant="secondary" className="text-xs font-normal">{s}</Badge>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* STEP 5: Projects */}
          {step === 5 && (
            <div className="space-y-4">
              <h2 className="text-base font-semibold flex items-center gap-2"><FolderGit2 className="h-4 w-4 text-primary" />Projects</h2>
              {projects.map((proj, i) => (
                <div key={proj.id} className="border rounded-xl p-4 bg-muted/20 space-y-3 group relative">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-primary uppercase tracking-wider">Project {i + 1}</span>
                    {projects.length > 1 && <button onClick={() => setProjects(p => p.filter((_, idx) => idx !== i))} className="text-muted-foreground hover:text-destructive opacity-0 group-hover:opacity-100"><Trash2 className="h-3.5 w-3.5" /></button>}
                  </div>
                  <Input placeholder="Project name" value={proj.title} onChange={e => setProjects(p => p.map((pr, idx) => idx === i ? { ...pr, title: e.target.value } : pr))} />
                  <Textarea rows={2} className="text-sm resize-none" placeholder="What you built and what impact it had..." value={proj.description} onChange={e => setProjects(p => p.map((pr, idx) => idx === i ? { ...pr, description: e.target.value } : pr))} />
                  <Input placeholder="Technologies used (comma-separated)" value={proj.technologies} onChange={e => setProjects(p => p.map((pr, idx) => idx === i ? { ...pr, technologies: e.target.value } : pr))} />
                  <Input placeholder="Link (GitHub / live demo)" value={proj.link} onChange={e => setProjects(p => p.map((pr, idx) => idx === i ? { ...pr, link: e.target.value } : pr))} />
                </div>
              ))}
              <button onClick={() => setProjects(p => [...p, emptyProject()])} className="w-full flex items-center justify-center gap-2 py-3 border-2 border-dashed border-border rounded-xl text-sm text-muted-foreground hover:border-primary/40 hover:text-primary transition-colors">
                <Plus className="h-4 w-4" />Add project
              </button>
            </div>
          )}

          {/* STEP 6: Finalize */}
          {step === 6 && (
            <div className="space-y-6">
              <h2 className="text-base font-semibold flex items-center gap-2"><Download className="h-4 w-4 text-primary" />Finalize & Export</h2>

              {/* Theme picker */}
              <div>
                <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider block mb-3">
                  <Palette className="inline h-3.5 w-3.5 mr-1" />PDF Theme
                </label>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                  {THEMES.map(t => (
                    <button key={t.id} onClick={() => setTheme(t.id)}
                      className={`flex flex-col items-center gap-2 p-3 rounded-xl border-2 transition-all
                        ${theme === t.id ? "border-primary shadow-md scale-[1.02]" : "border-border hover:border-primary/30"}`}>
                      <div className="w-10 h-10 rounded-lg" style={{ backgroundColor: t.color }} />
                      <span className="text-xs font-semibold">{t.label}</span>
                      <span className="text-[10px] text-muted-foreground capitalize">{t.font}</span>
                    </button>
                  ))}
                </div>
              </div>

              {/* Generate & Download */}
              <div className="flex gap-3 flex-wrap">
                <Button onClick={handleBuild} disabled={building} size="lg" className="gap-2">
                  {building ? <><Loader2 className="h-4 w-4 animate-spin" />Generating...</> : <><Sparkles className="h-4 w-4" />AI Generate Resume</>}
                </Button>
                {builtResume && (
                  <Button onClick={handleDownloadPDF} disabled={pdfLoading} variant="outline" size="lg" className="gap-2">
                    {pdfLoading ? <><Loader2 className="h-4 w-4 animate-spin" />Exporting...</> : <><Download className="h-4 w-4" />Download PDF</>}
                  </Button>
                )}
                {builtResume && (
                  <Button onClick={handleSaveToVault} disabled={saveLoading} variant="secondary" size="lg" className="gap-2">
                    {saveLoading ? <><Loader2 className="h-4 w-4 animate-spin" />Saving...</> : <><FolderGit2 className="h-4 w-4" />Save to Vault</>}
                  </Button>
                )}
                {builtResume && (
                  <Button variant="ghost" size="lg" className="gap-2" onClick={() => setShowPreview(true)}>
                    <Eye className="h-4 w-4" />Preview
                  </Button>
                )}
              </div>

              {builtResume && !showPreview && (
                <p className="text-xs text-emerald-600 flex items-center gap-1.5"><CheckCircle2 className="h-3.5 w-3.5" />Resume generated! Click Preview to review or Download PDF to export.</p>
              )}
            </div>
          )}

        </CardContent>
      </Card>

      {/* Step navigation */}
      <div className="sticky bottom-2 z-10 rounded-xl border border-border/70 bg-background/95 backdrop-blur px-3 py-2.5 grid grid-cols-[auto_1fr_auto] items-center gap-2 sm:flex sm:justify-between sm:items-center">
        <Button variant="ghost" size="sm" className="gap-1.5" disabled={step === 0} onClick={() => setStep(s => s - 1)}>
          <ChevronLeft className="h-4 w-4" />Back
        </Button>
        <div className="flex items-center justify-center gap-2 sm:gap-3 min-w-0">
          <button
            type="button"
            className="hidden sm:inline text-xs text-muted-foreground hover:text-foreground underline-offset-2 hover:underline"
            onClick={clearBuilderDraft}
          >
            Save/Clear draft
          </button>
          <button
            type="button"
            className="sm:hidden text-xs text-muted-foreground hover:text-foreground underline-offset-2 hover:underline"
            onClick={clearBuilderDraft}
          >
            Draft
          </button>
          <span className="text-[11px] sm:text-xs text-muted-foreground text-center">Step {step + 1} of {STEPS.length}</span>
        </div>
        {step < STEPS.length - 1 ? (
          <Button size="sm" className="gap-1.5" onClick={() => setStep(s => s + 1)}>
            Next<ChevronRight className="h-4 w-4" />
          </Button>
        ) : (
          <Button size="sm" variant="outline" onClick={() => setStep(0)}>Restart</Button>
        )}
      </div>
      </div>

      <aside className="hidden lg:block">
        <div className="sticky top-6 space-y-4">
          <Card className="border border-border/70 shadow-sm">
            <CardContent className="p-4 space-y-2.5">
              <div className="flex items-center justify-between border-b border-border/60 pb-2">
                <p className="text-xs uppercase tracking-wide text-muted-foreground font-semibold">Quick Actions</p>
                <span className="text-xs font-semibold">{phaseProgressPct}%</span>
              </div>
              <button type="button" onClick={() => importRef.current?.click()} className="w-full text-left text-xs font-medium hover:text-primary transition-colors">
                Import another resume
              </button>
              <button type="button" onClick={() => setEntryMode("pick")} className="w-full text-left text-xs font-medium hover:text-primary transition-colors">
                Switch start mode
              </button>
              <button type="button" onClick={clearBuilderDraft} className="w-full text-left text-xs font-medium hover:text-primary transition-colors">
                Clear local draft
              </button>
            </CardContent>
          </Card>
        </div>
      </aside>
      </div>
      )}

      {/* Preview modal */}
      {builtResume && (
        <Dialog open={showPreview} onOpenChange={setShowPreview}>
          <DialogContent className="max-w-2xl max-h-[90vh] overflow-hidden p-0 gap-0">
            <DialogHeader className="px-5 py-3 border-b bg-background">
              <div className="flex items-center justify-between gap-3">
                <DialogTitle className="flex items-center gap-2 text-sm">
                  <span className="w-3 h-3 rounded-full" style={{ backgroundColor: currentTheme.color }} />
                  {currentTheme.label} Theme Preview
                </DialogTitle>
                <Button size="sm" onClick={handleDownloadPDF} disabled={pdfLoading} className="gap-1.5 h-8">
                  {pdfLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}Download PDF
                </Button>
              </div>
            </DialogHeader>
            <div className={`overflow-y-auto p-8 space-y-5 text-zinc-900 text-sm ${currentTheme.font === 'serif' ? 'font-serif' : 'font-sans'}`}>
              {builtResume.contact && (
                <div className="text-center border-b pb-4 mb-4" style={{ borderColor: currentTheme.color + "33" }}>
                  <h1 className="text-2xl font-bold uppercase tracking-widest" style={{ color: currentTheme.color }}>{builtResume.contact.name}</h1>
                  <p className="text-zinc-500 text-xs mt-1">{[builtResume.contact.email, builtResume.contact.phone, builtResume.contact.location].filter(Boolean).join(" · ")}</p>
                  <p className="text-xs mt-0.5" style={{ color: currentTheme.color }}>{[builtResume.contact.linkedin && `LinkedIn: ${builtResume.contact.linkedin}`, builtResume.contact.github && `GitHub: ${builtResume.contact.github}`].filter(Boolean).join(" · ")}</p>
                </div>
              )}
              {(["Summary","Skills","Experience","Education","Projects"] as const).map(sec => {
                if (sec === "Summary" && builtResume.summary) return (
                  <section key={sec}>
                    <h2 className="text-xs font-bold uppercase tracking-widest border-b pb-1 mb-2" style={{ color: currentTheme.color, borderColor: currentTheme.color + "40" }}>{sec}</h2>
                    <p className="text-xs leading-relaxed text-zinc-700">{builtResume.summary}</p>
                  </section>
                );
                if (sec === "Skills" && builtResume.skills) return (
                  <section key={sec}>
                    <h2 className="text-xs font-bold uppercase tracking-widest border-b pb-1 mb-2" style={{ color: currentTheme.color, borderColor: currentTheme.color + "40" }}>{sec}</h2>
                    {Object.entries(builtResume.skills).map(([cat, items]: [string, any]) => Array.isArray(items) && items.length > 0 ? <p key={cat} className="text-xs"><strong className="capitalize">{cat}:</strong> {items.join(", ")}</p> : null)}
                  </section>
                );
                if (sec === "Experience" && builtResume.work_experience?.length > 0) return (
                  <section key={sec}>
                    <h2 className="text-xs font-bold uppercase tracking-widest border-b pb-1 mb-3" style={{ color: currentTheme.color, borderColor: currentTheme.color + "40" }}>{sec}</h2>
                    {builtResume.work_experience.map((job: any, idx: number) => (
                      <div key={idx} className="mb-3">
                        <div className="flex justify-between"><span className="font-bold text-xs">{job.company}</span><span className="text-[10px] text-zinc-500">{job.start_date} – {job.end_date}</span></div>
                        <div className="italic text-xs text-zinc-500 mb-1">{job.role}{job.location ? ` · ${job.location}` : ""}</div>
                        <ul className="list-disc pl-4 space-y-0.5">{(job.bullets || []).map((b: string, i: number) => <li key={i} className="text-[11px] text-zinc-700 leading-relaxed">{b}</li>)}</ul>
                      </div>
                    ))}
                  </section>
                );
                if (sec === "Education" && builtResume.education?.length > 0) return (
                  <section key={sec}>
                    <h2 className="text-xs font-bold uppercase tracking-widest border-b pb-1 mb-2" style={{ color: currentTheme.color, borderColor: currentTheme.color + "40" }}>{sec}</h2>
                    {builtResume.education.map((e: any, idx: number) => <div key={idx} className="flex justify-between text-xs mb-1"><span><strong>{e.degree}</strong> — {e.institution}</span><span className="text-zinc-500">{e.year}</span></div>)}
                  </section>
                );
                if (sec === "Projects" && builtResume.projects?.length > 0) return (
                  <section key={sec}>
                    <h2 className="text-xs font-bold uppercase tracking-widest border-b pb-1 mb-2" style={{ color: currentTheme.color, borderColor: currentTheme.color + "40" }}>{sec}</h2>
                    {builtResume.projects.map((p: any, idx: number) => (
                      <div key={idx} className="mb-2">
                        <span className="font-bold text-xs">{p.title}</span>
                        {p.link && <a href={p.link} className="text-xs ml-2" style={{ color: currentTheme.color }}>{p.link}</a>}
                        <p className="text-[11px] text-zinc-700">{p.description}</p>
                        {p.technologies?.length > 0 && <p className="text-[10px] italic text-zinc-500">Tech: {p.technologies.join(", ")}</p>}
                      </div>
                    ))}
                  </section>
                );
                return null;
              })}
            </div>
          </DialogContent>
        </Dialog>
      )}
    </div>
  );
}

// ─── Resume Enhancer Tool ─────────────────────────────────────────────────────
function ResumeEnhancerTool() {
  const [jobId, setJobId]             = useState("");
  const [resumeText, setResumeText]   = useState("");
  const [loading, setLoading]         = useState(false);
  const [enhancement, setEnhancement] = useState<any>(null);
  const importRef = useRef<HTMLInputElement>(null);

  const handleFileImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const data = await parseResumeForBuilder(file);
      const parts = [data.summary || "", ...(data.work_experience || []).map((w: any) => `${w.role} at ${w.company}\n${(w.bullets || []).join("\n")}`)];
      setResumeText(parts.filter(Boolean).join("\n\n"));
      toast.success("Resume imported!");
    } catch (error: any) {
      const detail = error?.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : "Import failed.");
    }
    e.target.value = "";
  };

  const handleEnhance = async () => {
    if (!jobId.trim() || !resumeText.trim()) { toast.error("Both fields are required"); return; }
    if (!isValidJobId(jobId)) { toast.error("Invalid Job ID"); return; }
    setLoading(true);
    try {
      const data = await enhanceCandidateResume(jobId.trim(), { resumeText });
      setEnhancement(data);
      toast.success("Done!");
    } catch { toast.error("Enhancement failed."); }
    finally { setLoading(false); }
  };

  return (
    <div className="space-y-5 max-w-3xl">
      <div>
        <h1 className="text-xl font-bold">AI Resume Enhancer</h1>
        <p className="text-sm text-muted-foreground mt-1">Paste your resume and a Job ID — AI rewrites your bullets to match the exact role requirements and boost your ATS score.</p>
      </div>

      <Card className="border border-border">
        <CardContent className="p-5 space-y-4">
          <div className="grid sm:grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Target Job ID</label>
              <Input placeholder="Copy from the job listing URL" value={jobId} onChange={e => setJobId(e.target.value)} />
              <p className="text-[11px] text-muted-foreground">AI fetches the full JD automatically.</p>
            </div>
            <div className="flex items-end">
              <Button variant="outline" size="sm" className="gap-2" onClick={() => importRef.current?.click()}>
                <Upload className="h-3.5 w-3.5" />Import resume file
              </Button>
              <input ref={importRef} type="file" accept=".pdf,.docx,.doc,.png,.jpg,.jpeg,.webp,.tiff,.tif,.bmp,.gif" className="hidden" onChange={handleFileImport} />
            </div>
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Your Current Resume Text</label>
            <Textarea className="min-h-44 font-mono text-xs resize-none" placeholder="Paste your resume content here, or use the import button above..." value={resumeText} onChange={e => setResumeText(e.target.value)} />
          </div>
          <Button onClick={handleEnhance} disabled={loading} className="gap-2">
            {loading ? <><Loader2 className="h-4 w-4 animate-spin" />Analyzing your resume...</> : <><Sparkles className="h-4 w-4" />Enhance Resume</>}
          </Button>
        </CardContent>
      </Card>

      {enhancement && (
        <div className="space-y-4 animate-in slide-in-from-bottom-4 duration-500">
          {/* Score banner */}
          <div className="grid sm:grid-cols-3 gap-3">
            <div className="bg-emerald-50 dark:bg-emerald-950/20 border border-emerald-200 dark:border-emerald-800 rounded-xl p-4">
              <p className="text-xs text-emerald-700 dark:text-emerald-400 font-medium">ATS Score Boost</p>
              <p className="text-3xl font-bold text-emerald-600">+{enhancement.estimated_ats_score_increase || enhancement.estimated_score_after || 15}%</p>
            </div>
            <div className="sm:col-span-2 bg-muted/30 border rounded-xl p-4">
              <p className="text-xs font-semibold mb-2">Missing Keywords to Add</p>
              <div className="flex flex-wrap gap-1.5">
                {(enhancement.missing_keywords || enhancement.keyword_additions || []).slice(0, 12).map((k: string, i: number) => (
                  <span key={i} className="px-2 py-0.5 bg-background border rounded-full text-xs font-mono">{k}</span>
                ))}
              </div>
            </div>
          </div>

          {enhancement.enhanced_summary && (
            <Card className="border border-emerald-200 dark:border-emerald-800 bg-emerald-50/30 dark:bg-emerald-950/10">
              <CardContent className="p-4">
                <p className="text-[11px] font-bold uppercase tracking-wider text-emerald-700 dark:text-emerald-400 mb-2">Enhanced Summary</p>
                <p className="text-sm leading-relaxed">{cleanMd(enhancement.enhanced_summary)}</p>
              </CardContent>
            </Card>
          )}

          {(enhancement.bullet_rewrites || []).length > 0 && (
            <div className="space-y-3">
              <h4 className="font-semibold text-sm">Bullet Rewrites</h4>
              {(enhancement.bullet_rewrites || []).map((b: any, i: number) => (
                <Card key={i} className="border border-border">
                  <CardContent className="p-4 space-y-2.5">
                    <div>
                      <span className="text-[10px] font-bold text-red-500 uppercase tracking-wider">Before</span>
                      <p className="text-xs text-zinc-600 bg-red-50 dark:bg-red-950/20 rounded-lg px-3 py-2 mt-1 leading-relaxed">{b.original}</p>
                    </div>
                    <div>
                      <span className="text-[10px] font-bold text-emerald-600 uppercase tracking-wider">After ✓</span>
                      <p className="text-xs bg-emerald-50 dark:bg-emerald-950/20 rounded-lg px-3 py-2 mt-1 font-medium leading-relaxed">{cleanMd(b.improved)}</p>
                    </div>
                    {b.reasoning && <p className="text-[11px] text-muted-foreground italic border-t pt-2">{b.reasoning}</p>}
                  </CardContent>
                </Card>
              ))}
            </div>
          )}

          {enhancement.ats_improvements?.length > 0 && (
            <Card>
              <CardContent className="p-4">
                <p className="text-[11px] font-bold uppercase tracking-wider text-primary mb-3">ATS Tips</p>
                <ul className="space-y-1.5">
                  {enhancement.ats_improvements.map((tip: string, i: number) => (
                    <li key={i} className="flex gap-2 text-xs"><CheckCircle2 className="h-3.5 w-3.5 text-emerald-500 mt-0.5 shrink-0" />{tip}</li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Cover Letter Tool ────────────────────────────────────────────────────────
function CoverLetterTool() {
  const [jobId, setJobId]   = useState("");
  const [loading, setLoading] = useState(false);
  const [letter, setLetter] = useState<any>(null);

  const handleGenerate = async () => {
    if (!isValidJobId(jobId)) { toast.error("Please enter a valid Job ID"); return; }
    setLoading(true);
    try {
      const data = await generateCoverLetter(jobId.trim());
      setLetter(data);
      toast.success("Cover letter ready!");
    } catch { toast.error("Generation failed. Check the Job ID."); }
    finally { setLoading(false); }
  };

  return (
    <div className="space-y-5 max-w-2xl">
      <div>
        <h1 className="text-xl font-bold">Cover Letter Generator</h1>
        <p className="text-sm text-muted-foreground mt-1">Generate a tailored, ATS-optimized cover letter in seconds using your profile and the job description.</p>
      </div>
      <Card className="border border-border">
        <CardContent className="p-5 space-y-4">
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Target Job ID</label>
            <Input placeholder="e.g. jdb_12345 — copy from the job listing URL" value={jobId} onChange={e => setJobId(e.target.value)} />
            <p className="text-[11px] text-muted-foreground">AI uses your latest profile data to tailor the letter.</p>
          </div>
          <Button onClick={handleGenerate} disabled={loading} className="gap-2">
            {loading ? <><Loader2 className="h-4 w-4 animate-spin" />Generating...</> : <><FileText className="h-4 w-4" />Generate Cover Letter</>}
          </Button>
        </CardContent>
      </Card>

      {letter && (
        <Card className="border border-primary/20 animate-in slide-in-from-bottom-4">
          <CardHeader className="flex flex-row items-start justify-between pb-2">
            <div>
              <CardTitle className="text-base">Your Cover Letter</CardTitle>
              {letter.word_count && <p className="text-xs text-muted-foreground mt-0.5">{letter.word_count} words</p>}
            </div>
            <Button size="sm" variant="outline" onClick={() => { navigator.clipboard.writeText(`${letter.subject_line || ""}\n\n${letter.body || letter.cover_letter_body || ""}`); toast.success("Copied!"); }}>
              Copy
            </Button>
          </CardHeader>
          <CardContent className="pt-0">
            <div className="bg-muted/20 border rounded-xl p-5">
              <p className="text-xs font-semibold border-b pb-2 mb-3">Subject: {letter.subject_line}</p>
              <p className="text-sm leading-relaxed whitespace-pre-wrap text-muted-foreground">{cleanMd(letter.body || letter.cover_letter_body)}</p>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// ─── Career Analysis Tool ─────────────────────────────────────────────────────
function GapAnalysisTool() {
  const [targetRole, setTargetRole] = useState("");
  const [loading, setLoading]       = useState(false);
  const [analysis, setAnalysis]     = useState<any>(null);

  const handleAnalyze = async () => {
    setLoading(true);
    try {
      const data = await getCareerAnalysis(targetRole || undefined);
      setAnalysis(data);
      toast.success("Analysis complete");
    } catch { toast.error("Analysis failed. Upload a resume or apply to a job first."); }
    finally { setLoading(false); }
  };

  return (
    <div className="space-y-5 max-w-3xl">
      <div>
        <h1 className="text-xl font-bold">Career Trajectory Analysis</h1>
        <p className="text-sm text-muted-foreground mt-1">Deep AI analysis of your profile with skill gap identification and a personalized 6-month upskilling roadmap.</p>
      </div>
      <Card className="border border-border">
        <CardContent className="p-5 space-y-4">
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Target Role <span className="normal-case font-normal">(optional)</span></label>
            <Input placeholder="Where do you want to be? e.g. Staff Engineer, Engineering Manager, ML Lead" value={targetRole} onChange={e => setTargetRole(e.target.value)} />
          </div>
          <Button onClick={handleAnalyze} disabled={loading} className="gap-2">
            {loading ? <><Loader2 className="h-4 w-4 animate-spin" />Analyzing your trajectory...</> : <><TrendingUp className="h-4 w-4" />Run Deep Analysis</>}
          </Button>
        </CardContent>
      </Card>

      {analysis && (
        <div className="space-y-4 animate-in slide-in-from-bottom-4">
          <div className="grid sm:grid-cols-2 gap-4">
            <Card className="border border-primary/20 bg-primary/5">
              <CardContent className="p-4">
                <p className="text-xs text-primary font-medium">Career Stage</p>
                <p className="text-2xl font-bold capitalize mt-0.5">{analysis.career_stage}</p>
                <p className="text-xs text-muted-foreground mt-2 leading-relaxed">{cleanMd(analysis.trajectory_assessment)}</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-4">
                <p className="text-xs font-medium">Market Positioning</p>
                <p className="text-sm text-muted-foreground mt-1 leading-relaxed">{analysis.market_positioning}</p>
              </CardContent>
            </Card>
          </div>

          {analysis.skill_gaps?.length > 0 && (
            <div>
              <h4 className="font-semibold text-sm mb-3">Critical Skill Gaps</h4>
              <div className="grid sm:grid-cols-2 gap-3">
                {analysis.skill_gaps.map((gap: any, i: number) => (
                  <Card key={i} className="border border-border">
                    <CardContent className="p-4 space-y-2">
                      <div className="flex justify-between items-center">
                        <span className="font-semibold text-sm">{gap.skill}</span>
                        <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full uppercase ${gap.priority === "high" ? "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400" : "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400"}`}>{gap.priority}</span>
                      </div>
                      <p className="text-xs text-muted-foreground">{gap.why_important}</p>
                      <p className="text-xs border-t pt-2"><span className="font-medium">How:</span> {gap.how_to_learn} <span className="text-muted-foreground">({gap.time_to_competency})</span></p>
                    </CardContent>
                  </Card>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
