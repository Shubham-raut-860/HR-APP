import React, { useState, useEffect, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import {
  Bell, User, FileText, Upload, Trash2,
  Star, Pencil, CheckCircle2, X, Plus, Loader2,
  AlertCircle, Download, Shield
} from 'lucide-react';
import { toast } from "sonner";
import { useAuth } from "@/context/AuthContext";
import { updateProfile } from "@/services/auth";
import {
  uploadStoredResume, updateStoredResume,
  deleteStoredResume, StoredResume,
  getKycChecklist, getKycDocuments, downloadKycDocument,
  CandidateKycChecklist, CandidateKycDocument, KycDocType, listKycConsents, setKycConsent, getMyApplications, CandidateOut
} from "@/services/candidatePortal";
import { assertBlobResponseSuccess, throwBlobRequestError } from "@/services/blobError";
import { cn } from "@/lib/utils";
import api from "@/services/api";
import { CandidateDataProvider, useCandidateData } from "@/context/CandidateDataProvider";
import { SegmentedTabs } from "@/components/ui/segmented-tabs";

const RESUME_VAULT_MAX_BYTES = 10 * 1024 * 1024;

// Resume Vault sub-component
function ResumeVault() {
  const { storedResumes, fetchStoredResumes, invalidateResumes } = useCandidateData();
  const [resumes, setResumes]       = useState<StoredResume[]>([]);
  const [loading, setLoading]       = useState(true);
  const [uploading, setUploading]   = useState(false);
  const [uploadPct, setUploadPct]   = useState(0);
  const [dragOver, setDragOver]     = useState(false);
  const [editingId, setEditingId]   = useState<string | null>(null);
  const [editLabel, setEditLabel]   = useState("");
  const [newLabel, setNewLabel]     = useState("");
  const [showUpload, setShowUpload] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => { loadVault(); }, []);
  useEffect(() => { setResumes(storedResumes); }, [storedResumes]);

  const loadVault = async () => {
    setLoading(true);
    try { await fetchStoredResumes(); }
    catch { toast.error("Failed to load resume vault"); }
    finally { setLoading(false); }
  };

  const handleFiles = async (files: FileList | null) => {
    if (!files?.[0]) return;
    const file = files[0];
    if (file.size > RESUME_VAULT_MAX_BYTES) { toast.error("File must be under 10 MB"); return; }
    const label = newLabel.trim() || file.name.replace(/\.[^.]+$/, "");
    setUploading(true); setUploadPct(0);
    const prog = setInterval(() => setUploadPct(p => Math.min(p + 15, 88)), 180);
    try {
      const isFirst = resumes.length === 0;
      const uploaded = await uploadStoredResume(file, label, isFirst);
      clearInterval(prog); setUploadPct(100);
      await new Promise(r => setTimeout(r, 300));
      setResumes(prev => [uploaded, ...prev.map(r => isFirst ? { ...r, is_default: false } : r)]);
      setShowUpload(false); setNewLabel("");
      invalidateResumes().catch(() => {});
      toast.success(`"${label}" saved to your vault`);
    } catch (err: any) {
      clearInterval(prog);
      toast.error(err.response?.data?.detail || "Upload failed");
    } finally { setUploading(false); setUploadPct(0); }
  };

  const handleSetDefault = async (id: string) => {
    try {
      await updateStoredResume(id, { is_default: true });
      setResumes(prev => prev.map(r => ({ ...r, is_default: r.id === id })));
      toast.success("Default resume updated");
      invalidateResumes().catch(() => {});
    } catch { toast.error("Failed to update default"); }
  };

  const handleRename = async (id: string) => {
    if (!editLabel.trim()) return;
    try {
      const updated = await updateStoredResume(id, { label: editLabel.trim() });
      setResumes(prev => prev.map(r => r.id === id ? { ...r, label: updated.label } : r));
      setEditingId(null);
      toast.success("Renamed");
      invalidateResumes().catch(() => {});
    } catch { toast.error("Rename failed"); }
  };

  const handleDelete = async (id: string, label: string) => {
    if (!confirm(`Remove "${label}" from your vault?`)) return;
    try {
      await deleteStoredResume(id);
      setResumes(prev => {
        const remaining = prev.filter(r => r.id !== id);
        const wasDefault = prev.find(r => r.id === id)?.is_default;
        if (wasDefault && remaining.length > 0) remaining[0] = { ...remaining[0], is_default: true };
        return remaining;
      });
      toast.success("Resume removed");
      invalidateResumes().catch(() => {});
    } catch { toast.error("Failed to delete"); }
  };

  const handleDownload = async (id: string, label: string) => {
    try {
      const res = await api.get(`/candidate/my-resumes/${id}/download`, { responseType: "blob" });
      const blob: Blob = res.data;
      await assertBlobResponseSuccess(blob, "Resume download failed.");
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = label; a.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      try {
        await throwBlobRequestError(error, "Download failed");
      } catch (parsedError) {
        const message = parsedError instanceof Error ? parsedError.message : "Download failed";
        toast.error(message);
      }
    }
  };

  const fmt = {
    size: (kb: number) => kb < 1024 ? `${kb} KB` : `${(kb / 1024).toFixed(1)} MB`,
    date: (iso: string) => new Date(iso).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" }),
  };

  const SLOTS = 5;
  const filled = resumes.length;

  if (loading) return (
    <div className="flex items-center justify-center py-16 gap-2 text-muted-foreground">
      <Loader2 className="h-4 w-4 animate-spin" />
      <span className="text-sm">Loading vault...</span>
    </div>
  );

  return (
    <div className="space-y-5">
      {/* Capacity bar */}
      <div className="flex items-center gap-4 p-4 bg-muted/20 rounded-xl border border-border/50">
        <div className="flex-1 space-y-2">
          <div className="flex items-center justify-between text-sm">
            <span className="font-medium">Slots used: <span className="font-semibold text-foreground">{filled}/{SLOTS}</span></span>
            <span className="text-muted-foreground text-xs">
              {SLOTS - filled === 0 ? "Vault full" : `${SLOTS - filled} slot${SLOTS - filled === 1 ? "" : "s"} free`}
            </span>
          </div>
          <div className="flex gap-1.5">
            {Array.from({ length: SLOTS }).map((_, i) => (
              <div key={i} className={cn(
                "h-2 flex-1 rounded-full transition-colors duration-300",
                i < filled
                  ? resumes[i]?.is_default ? "bg-amber-400" : "bg-primary"
                  : "bg-muted"
              )} />
            ))}
          </div>
        </div>
      </div>

      {/* Resume list */}
      {resumes.length > 0 && (
        <div className="space-y-2">
          {resumes.map((r, idx) => (
            <div key={r.id} className={cn(
              "group flex items-center gap-4 p-4 rounded-xl border transition-colors",
              r.is_default
                ? "border-amber-300/70 bg-amber-50/50 dark:bg-amber-900/10 dark:border-amber-800/60"
                : "border-border/50 bg-muted/10 hover:bg-muted/30"
            )}>
              <div className={cn(
                "shrink-0 h-10 w-10 rounded-xl flex items-center justify-center text-sm font-bold",
                r.is_default
                  ? "bg-amber-100 text-amber-600 dark:bg-amber-900/40 dark:text-amber-400"
                  : "bg-background border border-border/60 text-muted-foreground"
              )}>
                {r.is_default ? <Star className="h-4 w-4 fill-current" /> : idx + 1}
              </div>

              <div className="flex-1 min-w-0">
                {editingId === r.id ? (
                  <div className="flex items-center gap-2">
                    <Input
                      aria-label="Resume label"
                      value={editLabel}
                      onChange={e => setEditLabel(e.target.value)}
                      onKeyDown={e => {
                        if (e.key === "Enter") handleRename(r.id);
                        if (e.key === "Escape") setEditingId(null);
                      }}
                      className="h-8 text-sm rounded-xl"
                      autoFocus
                    />
                    <button type="button" aria-label={`Save resume name for ${r.label}`} onClick={() => handleRename(r.id)} className="text-primary hover:text-primary/80">
                      <CheckCircle2 className="h-4 w-4" />
                    </button>
                    <button type="button" aria-label={`Cancel renaming ${r.label}`} onClick={() => setEditingId(null)} className="text-muted-foreground hover:text-foreground">
                      <X className="h-4 w-4" />
                    </button>
                  </div>
                ) : (
                  <>
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-sm font-semibold truncate">{r.label}</span>
                      {r.is_default && (
                        <Badge className="text-[10px] h-4 px-1.5 bg-amber-100 text-amber-700 border-amber-200 dark:bg-amber-900/30 dark:text-amber-400">
                          Default
                        </Badge>
                      )}
                      {r.is_parsed && (
                        <Badge className="text-[10px] h-4 px-1.5 bg-emerald-100 text-emerald-700 border-emerald-200 dark:bg-emerald-900/30 dark:text-emerald-400">
                          Parsed
                        </Badge>
                      )}
                    </div>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      {r.file_size_kb ? fmt.size(r.file_size_kb) : ""}
                      {r.uploaded_at ? ` | ${fmt.date(r.uploaded_at)}` : ""}
                    </p>
                    <p className="text-[11px] text-muted-foreground mt-1 flex flex-wrap gap-x-3 gap-y-1">
                      <span>{r.experience_years != null ? `${r.experience_years.toFixed(1)} yrs` : "Experience pending"}</span>
                      <span>{(r.normalized_skills?.length || 0) > 0 ? `${r.normalized_skills?.length} skills parsed` : "Skills pending"}</span>
                      {r.parsed_name ? <span>Name: {r.parsed_name}</span> : null}
                    </p>
                  </>
                )}
              </div>

              {editingId !== r.id && (
                <div className="shrink-0 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                  {!r.is_default && (
                    <button type="button" title="Set as default" aria-label={`Set ${r.label} as default`} onClick={() => handleSetDefault(r.id)}
                      className="h-8 w-8 rounded-lg flex items-center justify-center text-muted-foreground hover:text-amber-500 hover:bg-amber-50 dark:hover:bg-amber-900/20 transition-colors">
                      <Star className="h-3.5 w-3.5" />
                    </button>
                  )}
                  <button type="button" title="Rename" aria-label={`Rename ${r.label}`} onClick={() => { setEditingId(r.id); setEditLabel(r.label); }}
                    className="h-8 w-8 rounded-lg flex items-center justify-center text-muted-foreground hover:text-blue-500 hover:bg-blue-50 dark:hover:bg-blue-900/20 transition-colors">
                    <Pencil className="h-3.5 w-3.5" />
                  </button>
                  <button type="button" title="Download" aria-label={`Download ${r.label}`} onClick={() => handleDownload(r.id, r.original_filename)}
                    className="h-8 w-8 rounded-lg flex items-center justify-center text-muted-foreground hover:text-primary hover:bg-primary/10 transition-colors">
                    <Download className="h-3.5 w-3.5" />
                  </button>
                  <button type="button" title="Delete" aria-label={`Delete ${r.label}`} onClick={() => handleDelete(r.id, r.label)}
                    className="h-8 w-8 rounded-lg flex items-center justify-center text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors">
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {filled >= SLOTS && (
        <div className="flex items-start gap-2.5 p-3.5 rounded-xl bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 text-sm text-amber-700 dark:text-amber-400">
          <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
          <span>Vault full - delete a resume to add a new one.</span>
        </div>
      )}

      {filled < SLOTS && (
        !showUpload ? (
          <button
            type="button"
            aria-label={resumes.length === 0 ? "Upload your first resume" : "Add another resume"}
            onClick={() => setShowUpload(true)}
            className="w-full flex items-center justify-center gap-2 py-4 rounded-xl border-2 border-dashed border-border/50 text-sm text-muted-foreground hover:border-primary/50 hover:text-primary hover:bg-primary/5 transition-all duration-150"
          >
            <Plus className="h-4 w-4" />
            {resumes.length === 0 ? "Upload your first resume" : "Add another resume"}
          </button>
        ) : (
          <div className="rounded-xl border border-border/60 p-5 space-y-4 bg-muted/10">
            <div className="flex items-center justify-between">
              <p className="text-sm font-semibold">Add to vault</p>
              <button type="button" aria-label="Close resume upload form" onClick={() => { setShowUpload(false); setNewLabel(""); }}
                className="h-7 w-7 rounded-lg flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-muted transition-colors">
                <X className="h-4 w-4" />
              </button>
            </div>
            <Label htmlFor="resume-vault-label">Resume label</Label>
            <Input
              id="resume-vault-label"
              placeholder="Label (e.g. Backend Engineer)"
              value={newLabel}
              onChange={e => setNewLabel(e.target.value)}
              className="text-sm rounded-xl"
            />
            <div
              role="button"
              tabIndex={0}
              aria-label="Choose resume file"
              onDragOver={e => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={e => { e.preventDefault(); setDragOver(false); handleFiles(e.dataTransfer.files); }}
              onClick={() => fileRef.current?.click()}
              onKeyDown={e => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  fileRef.current?.click();
                }
              }}
              className={cn(
                "border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-all",
                dragOver ? "border-primary bg-primary/5" : "border-border/40 hover:border-primary/40 hover:bg-muted/30"
              )}
            >
              <input
                id="resume-vault-file-input"
                ref={fileRef}
                type="file"
                className="sr-only"
                aria-label="Resume file"
                data-testid="resume-vault-file-input"
                accept=".pdf,.doc,.docx,.png,.jpg,.jpeg,.webp,.tiff,.tif,.bmp,.gif"
                onChange={e => handleFiles(e.target.files)}
              />
              {uploading ? (
                <div className="space-y-3">
                  <Loader2 className="h-7 w-7 animate-spin text-primary mx-auto" />
                  <p className="text-sm text-muted-foreground">Uploading and encrypting...</p>
                  <Progress value={uploadPct} className="h-1.5 max-w-[160px] mx-auto" />
                </div>
              ) : (
                <>
                  <Upload className="h-7 w-7 text-muted-foreground mx-auto mb-3" />
                  <p className="text-sm font-medium">Drop or click to browse</p>
                  <p className="text-xs text-muted-foreground mt-1">PDF, DOC, DOCX or image | Max 10 MB</p>
                </>
              )}
            </div>
          </div>
        )
      )}

      {resumes.length === 0 && !showUpload && (
        <p className="text-xs text-center text-muted-foreground pt-2">
          Save resumes once, reuse across all applications.
        </p>
      )}
    </div>
  );
}

// Main Settings Page
function CandidateKycDocuments() {
  const [checklist, setChecklist] = useState<CandidateKycChecklist | null>(null);
  const [documents, setDocuments] = useState<CandidateKycDocument[]>([]);
  const [applications, setApplications] = useState<CandidateOut[]>([]);
  const [consentByCandidateId, setConsentByCandidateId] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(true);
  const [downloading, setDownloading] = useState<KycDocType | null>(null);
  const [consentBusyFor, setConsentBusyFor] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      const [nextChecklist, nextDocuments, nextApplications, nextConsents] = await Promise.all([
        getKycChecklist(),
        getKycDocuments(),
        getMyApplications(),
        listKycConsents(),
      ]);
      setChecklist(nextChecklist);
      setDocuments(nextDocuments);
      setApplications(Array.isArray(nextApplications) ? nextApplications : []);
      const nextMap: Record<string, boolean> = {};
      (Array.isArray(nextConsents) ? nextConsents : []).forEach((row) => {
        nextMap[row.candidate_id] = !!row.granted;
      });
      setConsentByCandidateId(nextMap);
    } catch {
      toast.error("Failed to load KYC documents");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const byType = (docType: KycDocType) => documents.find((doc) => doc.doc_type === docType);

  const handleDownload = async (docType: KycDocType) => {
    setDownloading(docType);
    try {
      const blob = await downloadKycDocument(docType);
      const doc = byType(docType);
      const filename = doc?.original_filename || `${docType}.pdf`;
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err: any) {
      toast.error(err?.message || "KYC download failed");
    } finally {
      setDownloading(null);
    }
  };

  const handleConsentToggle = async (candidateId: string, granted: boolean) => {
    setConsentBusyFor(candidateId);
    try {
      const updated = await setKycConsent(candidateId, granted);
      setConsentByCandidateId((prev) => ({ ...prev, [candidateId]: !!updated.granted }));
      toast.success(granted ? "Consent granted for recruiter access" : "Consent revoked");
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || "Failed to update consent");
    } finally {
      setConsentBusyFor(null);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-14 gap-2 text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        <span className="text-sm">Loading documents...</span>
      </div>
    );
  }

  const items = checklist?.items || [];
  const shortlistedApps = applications.filter((a) => {
    const tag = (a?.tag || "").toLowerCase();
    return tag === "strong" || tag === "medium";
  });
  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-border/60 bg-muted/10 p-4">
        <p className="text-sm font-medium">Mandatory verification documents</p>
        <p className="text-xs text-muted-foreground mt-1">
          KYC uploads are accepted only through the one-time secure link sent after shortlist/pre-offer.
          This page shows upload status and lets you manage recruiter consent.
        </p>
        <Badge variant={checklist?.all_mandatory_uploaded ? "default" : "secondary"} className="mt-3">
          {checklist?.all_mandatory_uploaded ? "All mandatory documents uploaded" : "Mandatory documents pending"}
        </Badge>
      </div>

      {items.map((item) => {
        const doc = byType(item.doc_type);
        const isDownloading = downloading === item.doc_type;
        return (
          <div key={item.doc_type} className="rounded-xl border border-border/60 bg-background p-4 flex flex-col md:flex-row md:items-center md:justify-between gap-4">
            <div className="min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <p className="font-semibold text-sm">{item.label}</p>
                <Badge variant={item.uploaded ? "default" : "outline"}>
                  {item.uploaded ? "Uploaded" : "Pending"}
                </Badge>
              </div>
              <p className="text-xs text-muted-foreground mt-1">
                Accepted: PDF, PNG, JPG, JPEG, WEBP
              </p>
              {doc?.original_filename ? (
                <p className="text-xs text-muted-foreground mt-1 truncate">
                  Current file: {doc.original_filename}
                </p>
              ) : null}
            </div>
            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="ghost"
                className="rounded-xl"
                onClick={() => void handleDownload(item.doc_type)}
                disabled={!item.uploaded || isDownloading}
              >
                {isDownloading ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Download className="h-4 w-4 mr-2" />}
                Download
              </Button>
            </div>
          </div>
        );
      })}

      <div className="rounded-xl border border-border/60 bg-muted/10 p-4">
        <p className="text-sm font-medium">Recruiter access consent</p>
        <p className="text-xs text-muted-foreground mt-1">
          Recruiters can view your secure documents only for shortlisted applications where they also mark approval to hire.
        </p>
        <div className="mt-3 space-y-2">
          {shortlistedApps.length === 0 ? (
            <p className="text-xs text-muted-foreground">No shortlisted applications yet.</p>
          ) : shortlistedApps.map((app) => {
            const checked = !!consentByCandidateId[app.id];
            const busy = consentBusyFor === app.id;
            return (
              <div key={app.id} className="flex items-center justify-between rounded-lg border border-border/50 bg-background px-3 py-2">
                <div className="min-w-0">
                  <p className="text-sm font-medium truncate">{app.job_title || "Job Application"}</p>
                  <p className="text-[11px] text-muted-foreground truncate">
                    {app.tag ? `Status: ${app.tag}` : "Shortlisted"}
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  {busy ? <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" /> : null}
                  <Switch
                    checked={checked}
                    onCheckedChange={(v) => { void handleConsentToggle(app.id, !!v); }}
                    disabled={busy}
                  />
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
type TabId = "profile" | "security" | "notifications" | "vault" | "documents";

const SETTINGS_TABS: TabId[] = ["profile", "security", "notifications", "vault", "documents"];

const normalizeSettingsTab = (tab: string | null): TabId =>
  SETTINGS_TABS.includes(tab as TabId) ? (tab as TabId) : "profile";

function CandidateSettingsContent() {
  const { user } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();
  const tabFromUrl = normalizeSettingsTab(searchParams.get("tab"));
  const [activeTab, setActiveTab] = useState<TabId>(tabFromUrl);
  const settingsTabOptions: ReadonlyArray<{ value: TabId; label: string; icon: React.ElementType }> = [
    { value: "profile", label: "Profile", icon: User },
    { value: "security", label: "Security", icon: Shield },
    { value: "notifications", label: "Notifications", icon: Bell },
    { value: "vault", label: "Resume Vault", icon: FileText },
    { value: "documents", label: "Documents", icon: Shield },
  ];

  const [profile, setProfile] = useState({ firstName: "", lastName: "", bio: "" });
  const [preferences, setPreferences] = useState({ jobAlerts: true, applicationUpdates: true, marketingEmails: false });
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setActiveTab(tabFromUrl);
  }, [tabFromUrl]);

  useEffect(() => {
    if (!user) return;
    const [firstName, ...rest] = (user.full_name || "").split(" ");
    setProfile({ firstName: firstName || "", lastName: rest.join(" ") || "", bio: (user as any).bio || "" });
    if ((user as any).preferences) {
      setPreferences({
        jobAlerts: (user as any).preferences.jobAlerts ?? true,
        applicationUpdates: (user as any).preferences.applicationUpdates ?? true,
        marketingEmails: (user as any).preferences.marketingEmails ?? false,
      });
    }
  }, [user]);

  const handleSaveProfile = async () => {
    setLoading(true);
    try {
      await updateProfile({ full_name: `${profile.firstName} ${profile.lastName}`.trim(), bio: profile.bio });
      toast.success("Profile updated");
    } catch { toast.error("Failed to update profile"); }
    finally { setLoading(false); }
  };

  const handleSavePreferences = async () => {
    setLoading(true);
    try {
      await updateProfile({ preferences });
      toast.success("Preferences saved");
    } catch { toast.error("Failed to save preferences"); }
    finally { setLoading(false); }
  };

  const handleTabChange = (nextTab: TabId) => {
    setActiveTab(nextTab);
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      if (nextTab === "profile") next.delete("tab");
      else next.set("tab", nextTab);
      return next;
    });
  };

  const initials = `${profile.firstName.charAt(0)}${profile.lastName.charAt(0)}`.toUpperCase() || "?";

  return (
    <div className="max-w-5xl mx-auto space-y-6 animate-in fade-in duration-500">

      {/* Page header */}
      <div>
        <h2 className="text-3xl font-bold tracking-tight">Settings</h2>
        <p className="text-muted-foreground">Manage your profile, security, and preferences.</p>
      </div>

      <div>
        <SegmentedTabs
          value={activeTab}
          onChange={handleTabChange}
          options={settingsTabOptions}
          className="w-full sm:w-auto"
        />
      </div>

      <div className="grid gap-8">

        {/* PROFILE */}
        {activeTab === "profile" && (
          <Card className="animate-in slide-in-from-right-4 duration-300">
            <CardHeader>
              <CardTitle className="text-xl">Profile Information</CardTitle>
              <CardDescription>Your name and headline visible to recruiters.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="flex items-center gap-4 p-4 rounded-xl bg-muted/20 border border-border/40">
                <Avatar className="h-14 w-14 border-2 border-border/60 shrink-0">
                  <AvatarImage src={`https://api.dicebear.com/7.x/initials/svg?seed=${profile.firstName}`} />
                  <AvatarFallback className="text-lg font-bold">{initials}</AvatarFallback>
                </Avatar>
                <div className="min-w-0">
                  <p className="font-semibold truncate">{profile.firstName} {profile.lastName}</p>
                  <p className="text-sm text-muted-foreground truncate">{(user as any)?.email}</p>
                  {profile.bio && <p className="text-xs text-muted-foreground mt-0.5 italic truncate">{profile.bio}</p>}
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="candidate-first-name">First Name</Label>
                  <Input id="candidate-first-name" value={profile.firstName} onChange={e => setProfile({ ...profile, firstName: e.target.value })} placeholder="John" className="rounded-xl bg-muted/20" />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="candidate-last-name">Last Name</Label>
                  <Input id="candidate-last-name" value={profile.lastName} onChange={e => setProfile({ ...profile, lastName: e.target.value })} placeholder="Doe" className="rounded-xl bg-muted/20" />
                </div>
              </div>
              <div className="space-y-2">
                <Label htmlFor="candidate-headline">Headline</Label>
                <Input id="candidate-headline" value={profile.bio} onChange={e => setProfile({ ...profile, bio: e.target.value })} placeholder="Senior Frontend Engineer | React Enthusiast" className="rounded-xl bg-muted/20" />
                <p className="text-xs text-muted-foreground">Shown to recruiters on your profile.</p>
              </div>
            </CardContent>
            <CardFooter className="bg-muted/10 border-t justify-end p-4">
              <Button onClick={handleSaveProfile} disabled={loading} className="rounded-full px-6">
                {loading ? <><Loader2 className="h-4 w-4 mr-2 animate-spin" />Saving...</> : "Save Changes"}
              </Button>
            </CardFooter>
          </Card>
        )}

        {/* SECURITY */}
        {activeTab === "security" && (
          <Card className="animate-in slide-in-from-right-4 duration-300">
            <CardHeader>
              <CardTitle className="text-xl">Security & Account</CardTitle>
              <CardDescription>Manage your password and account access.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-start gap-3 p-4 rounded-xl bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 text-sm text-amber-700 dark:text-amber-400">
                <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
                <span>Password management is coming soon. To reset your password, use the <strong>Forgot password</strong> link on the login page.</span>
              </div>
              <div className="space-y-4 opacity-40 pointer-events-none select-none">
                {[
                  { id: "candidate-current-password", label: "Current Password" },
                  { id: "candidate-new-password", label: "New Password" },
                  { id: "candidate-confirm-password", label: "Confirm New Password" },
                ].map(({ id, label }) => (
                  <div key={id} className="space-y-2">
                    <Label htmlFor={id}>{label}</Label>
                    <Input id={id} type="password" disabled placeholder="********" className="rounded-xl bg-muted/20" />
                  </div>
                ))}
              </div>
            </CardContent>
            <CardFooter className="bg-muted/10 border-t justify-end p-4">
              <Button disabled className="rounded-full px-6">Update Password</Button>
            </CardFooter>
          </Card>
        )}

        {/* NOTIFICATIONS */}
        {activeTab === "notifications" && (
          <Card className="animate-in slide-in-from-right-4 duration-300">
            <CardHeader>
              <CardTitle className="text-xl">Notification Preferences</CardTitle>
              <CardDescription>Choose what you want to be notified about.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              {[
                { id: "job-alerts",  key: "jobAlerts",          label: "Job Alerts",          desc: "New jobs matching your profile."      },
                { id: "app-updates", key: "applicationUpdates", label: "Application Updates", desc: "Status changes on your applications." },
                { id: "marketing",   key: "marketingEmails",    label: "Marketing Emails",    desc: "Product news and promotional updates."},
              ].map(item => (
                <div key={item.id} className="flex items-center justify-between">
                  <div className="space-y-0.5">
                    <Label htmlFor={item.id} className="cursor-pointer">{item.label}</Label>
                    <p className="text-xs text-muted-foreground">{item.desc}</p>
                  </div>
                  <Switch
                    id={item.id}
                    checked={(preferences as any)[item.key]}
                    onCheckedChange={v => setPreferences({ ...preferences, [item.key]: v })}
                  />
                </div>
              ))}
            </CardContent>
            <CardFooter className="bg-muted/10 border-t justify-end p-4">
              <Button onClick={handleSavePreferences} disabled={loading} className="rounded-full px-6">
                {loading ? <><Loader2 className="h-4 w-4 mr-2 animate-spin" />Saving...</> : "Save Preferences"}
              </Button>
            </CardFooter>
          </Card>
        )}

        {/* RESUME VAULT */}
        {activeTab === "vault" && (
          <Card className="animate-in slide-in-from-right-4 duration-300">
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle className="text-xl">Resume Vault</CardTitle>
                  <CardDescription className="mt-1">
                    Store up to 5 resumes. The starred one is used for Easy Apply.
                  </CardDescription>
                </div>
                <Badge variant="secondary" className="text-xs font-normal self-start">up to 5</Badge>
              </div>
            </CardHeader>
            <CardContent>
              <ResumeVault />
            </CardContent>
          </Card>
        )}

        {activeTab === "documents" && (
          <Card className="animate-in slide-in-from-right-4 duration-300">
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle className="text-xl">KYC Documents</CardTitle>
                  <CardDescription className="mt-1">
                    Upload mandatory and supporting verification documents securely.
                  </CardDescription>
                </div>
                <Badge variant="secondary" className="text-xs font-normal self-start">candidate only</Badge>
              </div>
            </CardHeader>
            <CardContent>
              <CandidateKycDocuments />
            </CardContent>
          </Card>
        )}

      </div>
    </div>
  );
}

export default function CandidateSettings() {
  return (
    <CandidateDataProvider>
      <CandidateSettingsContent />
    </CandidateDataProvider>
  );
}


