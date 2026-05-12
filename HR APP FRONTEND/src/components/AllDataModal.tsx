import React, { useState, useEffect, useCallback, useRef } from "react";
import { Link } from "react-router-dom";
import {
  Dialog,
  DialogContent,
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
} from "@/components/ui/alert-dialog";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Search,
  Database,
  Briefcase,
  ChevronLeft,
  ChevronRight,
  Download,
  RefreshCw,
  Trash2,
  RotateCcw,
  Archive,
  CheckSquare,
  Square,
  Minus,
  ShieldAlert,
  Info,
  Loader2,
} from "lucide-react";
import { getAllCandidatesData, deleteCandidates, restoreCandidates } from "@/services/candidates";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 50;

const tagColor: Record<string, string> = {
  Strong: "bg-emerald-100 text-emerald-700 border-emerald-200 dark:bg-emerald-900/30 dark:text-emerald-400 dark:border-emerald-800",
  Medium: "bg-amber-100 text-amber-700 border-amber-200 dark:bg-amber-900/30 dark:text-amber-400 dark:border-amber-800",
  Reject: "bg-red-100 text-red-700 border-red-200 dark:bg-red-900/30 dark:text-red-400 dark:border-red-800",
};

// ─── Types ─────────────────────────────────────────────────────────────────────

type DeleteMode = "selected" | "archived-only" | "all" | null;

interface AllDataModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  jobs: any[];
}

// ─── Component ────────────────────────────────────────────────────────────────

export function AllDataModal({ open, onOpenChange, jobs }: AllDataModalProps) {
  const [allData, setAllData]             = useState<any[]>([]);
  const [loading, setLoading]             = useState(false);
  const [searchQuery, setSearchQuery]     = useState("");
  const [page, setPage]                   = useState(0);
  const [archiveMenuOpen, setArchiveMenuOpen] = useState(false);

  // Selection state
  const [selected, setSelected]           = useState<Set<string>>(new Set());

  // Confirm dialog state
  const [deleteMode, setDeleteMode]       = useState<DeleteMode>(null);
  const [actionLoading, setActionLoading] = useState(false);

  const searchTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);
  const jobMap = Object.fromEntries(jobs.map((j: any) => [j.id, j.title]));

  // ── Data fetching ──────────────────────────────────────────────────────────

  const fetchData = useCallback(async (search: string, pageNum: number) => {
    setLoading(true);
    try {
      const data = await getAllCandidatesData(search || undefined, pageNum * PAGE_SIZE, PAGE_SIZE);
      setAllData(data);
      setSelected(new Set()); // clear selection on every fetch
    } catch {
      toast.error("Failed to load master archive");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) {
      setPage(0);
      fetchData(searchQuery, 0);
      setArchiveMenuOpen(false);
    }
  }, [open]);

  const handleSearch = (value: string) => {
    setSearchQuery(value);
    if (searchTimeout.current) clearTimeout(searchTimeout.current);
    searchTimeout.current = setTimeout(() => {
      setPage(0);
      fetchData(value, 0);
    }, 350);
  };

  const handlePageChange = (newPage: number) => {
    setPage(newPage);
    fetchData(searchQuery, newPage);
  };

  // ── Selection ──────────────────────────────────────────────────────────────

  const allPageIds   = allData.map((c) => c.id);
  const allSelected  = allPageIds.length > 0 && allPageIds.every((id) => selected.has(id));
  const someSelected = allPageIds.some((id) => selected.has(id)) && !allSelected;

  const toggleAll = () => {
    if (allSelected) {
      setSelected((prev) => {
        const next = new Set(prev);
        allPageIds.forEach((id) => next.delete(id));
        return next;
      });
    } else {
      setSelected((prev) => new Set([...prev, ...allPageIds]));
    }
  };

  const toggleOne = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  // ── Delete / Restore actions ───────────────────────────────────────────────

  const getConfirmConfig = (): { title: string; description: React.ReactNode; actionLabel: string; actionClass: string } => {
    switch (deleteMode) {
      case "selected":
        return {
          title: `Permanently delete ${selected.size} record(s)?`,
          description: (
            <span>
              This will <strong>permanently remove</strong> the selected {selected.size} candidate record(s) from the master archive including their quiz attempts and uploaded resume files. <strong>This cannot be undone.</strong>
            </span>
          ),
          actionLabel: `Delete ${selected.size} record(s)`,
          actionClass: "bg-red-600 hover:bg-red-700 text-white",
        };
      case "archived-only":
        return {
          title: "Delete all archived records?",
          description: (
            <span>
              This will <strong>permanently remove</strong> all candidates that were archived from the pipeline ("Clear Displayed") from the master database. Active pipeline candidates are not affected. <strong>This cannot be undone.</strong>
            </span>
          ),
          actionLabel: "Delete archived only",
          actionClass: "bg-red-600 hover:bg-red-700 text-white",
        };
      case "all":
        return {
          title: "⚠️ Delete ENTIRE master archive?",
          description: (
            <span>
              This will <strong>permanently destroy every single candidate record</strong> in the master database — active pipeline candidates, archived candidates, pool candidates, all quiz attempts, and all resume files. <strong>There is no recovery. This cannot be undone.</strong>
            </span>
          ),
          actionLabel: "Delete entire archive",
          actionClass: "bg-red-700 hover:bg-red-800 text-white",
        };
      default:
        return { title: "", description: "", actionLabel: "", actionClass: "" };
    }
  };

  const executeDelete = async () => {
    setActionLoading(true);
    try {
      let ids: string[] = [];

      if (deleteMode === "selected") {
        ids = Array.from(selected);
      } else if (deleteMode === "archived-only") {
        // FIX F-4: paginate to collect ALL archived IDs, not just first 1000
        let offset = 0;
        const PAGE = 1000;
        while (true) {
          const batch = await getAllCandidatesData(undefined, offset, PAGE);
          if (!batch || batch.length === 0) break;
          ids.push(...batch.filter((c: any) => c.is_archived).map((c: any) => c.id));
          if (batch.length < PAGE) break;
          offset += PAGE;
        }
        if (ids.length === 0) {
          toast.info("No archived records found to delete.");
          setDeleteMode(null);
          setActionLoading(false);
          return;
        }
      } else if (deleteMode === "all") {
        // FIX F-4: paginate to collect ALL IDs
        let offset = 0;
        const PAGE = 1000;
        while (true) {
          const batch = await getAllCandidatesData(undefined, offset, PAGE);
          if (!batch || batch.length === 0) break;
          ids.push(...batch.map((c: any) => c.id));
          if (batch.length < PAGE) break;
          offset += PAGE;
        }
        if (ids.length === 0) {
          toast.info("Archive is already empty.");
          setDeleteMode(null);
          setActionLoading(false);
          return;
        }
      }

      // Chunk large deletes into 500-item batches
      const CHUNK = 500;
      for (let i = 0; i < ids.length; i += CHUNK) {
        await deleteCandidates(ids.slice(i, i + CHUNK));
      }

      const label =
        deleteMode === "selected" ? `${ids.length} record(s)` :
        deleteMode === "archived-only" ? `${ids.length} archived record(s)` :
        `${ids.length} record(s) (entire archive)`;

      toast.success(`Permanently deleted ${label}.`);
      setDeleteMode(null);
      setSelected(new Set());
      fetchData(searchQuery, page);
    } catch {
      toast.error("Delete failed. Please try again.");
    } finally {
      setActionLoading(false);
    }
  };

  const handleRestore = async (ids: string[]) => {
    try {
      await restoreCandidates(ids);
      toast.success(`${ids.length} candidate(s) restored to active pipeline.`);
      setSelected(new Set());
      fetchData(searchQuery, page);
    } catch {
      toast.error("Restore failed.");
    }
  };

  // FIX Finding F-9: Paginate through ALL records for CSV export, not just current page
  const [exporting, setExporting] = useState(false);

  const handleExportCSV = async () => {
    setExporting(true);
    try {
      const escapeCSV = (val: any) => {
        const s = val == null ? "" : String(val);
        return s.includes(",") || s.includes('"') || s.includes("\n")
          ? `"${s.replace(/"/g, '""')}"` : s;
      };

      // Fetch ALL records by paginating
      let allRecords: any[] = [];
      let offset = 0;
      const PAGE = 1000;
      while (true) {
        const batch = await getAllCandidatesData(searchQuery || undefined, offset, PAGE);
        if (!batch || batch.length === 0) break;
        allRecords.push(...batch);
        if (batch.length < PAGE) break;
        offset += PAGE;
      }

      if (allRecords.length === 0) {
        toast.info("No records to export.");
        return;
      }

      const headers = ["Name", "Email", "Phone", "Job", "Skills", "Experience (yrs)", "Resume Score", "Tag", "Status", "Uploaded"];
      const rows = allRecords.map((c: any) => [
        c.name,
        c.email,
        c.phone,
        c.job_id ? (jobMap[c.job_id] || c.job_id) : "Pool",
        Array.isArray(c.skills) ? c.skills.join("; ") : c.skills,
        c.experience_years,
        c.resume_score,
        c.tag,
        c.is_archived ? "Archived" : "Active",
        c.created_at ? new Date(c.created_at).toLocaleDateString() : "",
      ]);
      const csv = [headers, ...rows].map((r) => r.map(escapeCSV).join(",")).join("\n");
      const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = "master_resume_archive.csv";
      document.body.appendChild(a); a.click(); document.body.removeChild(a);
      toast.success(`Exported ${allRecords.length} records to CSV`);
    } catch {
      toast.error("CSV export failed.");
    } finally {
      setExporting(false);
    }
  };

  // ── Derived ────────────────────────────────────────────────────────────────

  const hasPrev = page > 0;
  const hasNext = allData.length === PAGE_SIZE;

  const archivedOnPage = allData.filter((c) => c.is_archived).length;
  const selectedList   = Array.from(selected) as string[];

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="max-w-[92vw] w-full h-[88vh] flex flex-col p-0 gap-0 rounded-2xl overflow-hidden">

          {/* ── Header ──────────────────────────────────────────────────────── */}
          <DialogHeader className="px-6 py-4 border-b flex-shrink-0 bg-background">
            <div className="flex items-start justify-between gap-4">
              <div className="flex items-center gap-3">
                <div className="flex items-center justify-center w-10 h-10 rounded-xl bg-primary/10 shrink-0">
                  <Database className="h-5 w-5 text-primary" />
                </div>
                <div>
                  <DialogTitle className="text-lg font-semibold leading-tight">
                    Master Resume Archive
                  </DialogTitle>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    Complete backup of every resume ever uploaded — including archived pipeline candidates
                  </p>
                </div>
              </div>

              {/* Action buttons */}
              <div className="flex items-center gap-2 shrink-0 mr-6 flex-wrap justify-end">
                <Button variant="outline" size="sm" className="rounded-lg h-8" onClick={() => fetchData(searchQuery, page)}>
                  <RefreshCw className="h-3.5 w-3.5 mr-1.5" /> Refresh
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  className="rounded-lg h-8"
                  onClick={handleExportCSV}
                  disabled={allData.length === 0 || exporting}
                >
                  {exporting ? (
                    <><Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" /> Exporting...</>
                  ) : (
                    <><Download className="h-3.5 w-3.5 mr-1.5" /> Export CSV</>
                  )}
                </Button>

                {/* Restore selected */}
                {selected.size > 0 && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="rounded-lg h-8 border-emerald-300 text-emerald-700 hover:bg-emerald-50 dark:border-emerald-700 dark:text-emerald-400"
                    onClick={() => handleRestore(selectedList)}
                  >
                    <RotateCcw className="h-3.5 w-3.5 mr-1.5" />
                    Restore {selected.size}
                  </Button>
                )}

                {/* Delete selected */}
                {selected.size > 0 && (
                  <Button
                    variant="destructive"
                    size="sm"
                    className="rounded-lg h-8"
                    onClick={() => setDeleteMode("selected")}
                  >
                    <Trash2 className="h-3.5 w-3.5 mr-1.5" />
                    Delete {selected.size} selected
                  </Button>
                )}

                {/* Delete menu — archived only & delete all */}
                <div className="relative">
                  <Button
                    variant="outline"
                    size="sm"
                    className="rounded-lg h-8 border-red-200 text-red-600 hover:bg-red-50 hover:border-red-300 dark:border-red-900 dark:text-red-400"
                    onClick={() => setArchiveMenuOpen((prev) => !prev)}
                    aria-haspopup="menu"
                    aria-expanded={archiveMenuOpen}
                  >
                    <Trash2 className="h-3.5 w-3.5 mr-1.5" /> Clear Archive ▾
                  </Button>
                  <div className={cn(
                    "absolute right-0 top-full mt-1 w-52 bg-background border rounded-xl shadow-lg z-50 py-1",
                    archiveMenuOpen ? "block" : "hidden"
                  )}>
                    <button
                      className="w-full text-left px-4 py-2.5 text-sm hover:bg-muted flex items-center gap-2 text-amber-700 dark:text-amber-400"
                      onClick={() => {
                        setArchiveMenuOpen(false);
                        setDeleteMode("archived-only");
                      }}
                    >
                      <Archive className="h-3.5 w-3.5" />
                      Delete archived only
                    </button>
                    <div className="border-t my-1" />
                    <button
                      className="w-full text-left px-4 py-2.5 text-sm hover:bg-red-50 dark:hover:bg-red-950/30 flex items-center gap-2 text-red-600 dark:text-red-400 font-medium"
                      onClick={() => {
                        setArchiveMenuOpen(false);
                        setDeleteMode("all");
                      }}
                    >
                      <ShieldAlert className="h-3.5 w-3.5" />
                      Delete entire archive
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </DialogHeader>

          {/* ── Info banner ────────────────────────────────────────────────── */}
          <div className="px-6 py-2.5 bg-blue-50/60 dark:bg-blue-950/20 border-b border-blue-100 dark:border-blue-900/40 flex-shrink-0">
            <div className="flex items-start gap-2 text-xs text-blue-700 dark:text-blue-300">
              <Info className="h-3.5 w-3.5 mt-0.5 shrink-0" />
              <span>
                <strong>This is the master database.</strong> "Clear Displayed" on the Candidates page archives records here — they are never deleted from this view.
                Use the delete controls above to permanently remove entries when needed. <strong>Archived</strong> records were removed from the active pipeline but are safely stored here.
              </span>
            </div>
          </div>

          {/* ── Toolbar ────────────────────────────────────────────────────── */}
          <div className="px-6 py-3 border-b flex-shrink-0 bg-muted/20 flex items-center gap-3">
            <div className="relative flex-1 max-w-sm">
              <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Search by name or email..."
                className="pl-8 bg-background h-9 rounded-lg"
                value={searchQuery}
                onChange={(e) => handleSearch(e.target.value)}
              />
            </div>
            {selected.size > 0 && (
              <span className="text-xs text-muted-foreground">
                {selected.size} record(s) selected
                <button className="ml-2 text-primary underline" onClick={() => setSelected(new Set())}>clear</button>
              </span>
            )}
          </div>

          {/* ── Table ──────────────────────────────────────────────────────── */}
          <div className="flex-1 overflow-auto">
            {loading ? (
              <div className="flex items-center justify-center h-full">
                <div className="flex flex-col items-center gap-3 text-muted-foreground">
                  <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
                  <span className="text-sm">Loading master archive...</span>
                </div>
              </div>
            ) : allData.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-full gap-3 text-muted-foreground">
                <Database className="h-12 w-12 opacity-20" />
                <p className="text-sm font-medium">No records found</p>
                {searchQuery && <p className="text-xs">Try clearing your search</p>}
              </div>
            ) : (
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-muted/80 backdrop-blur border-b z-10">
                  <tr>
                    {/* Checkbox header */}
                    <th className="px-4 py-3 w-10">
                      <button
                        className="flex items-center justify-center w-5 h-5 rounded text-muted-foreground hover:text-foreground transition-colors"
                        onClick={toggleAll}
                        title={allSelected ? "Deselect all" : "Select all on this page"}
                      >
                        {allSelected ? (
                          <CheckSquare className="h-4 w-4 text-primary" />
                        ) : someSelected ? (
                          <Minus className="h-4 w-4" />
                        ) : (
                          <Square className="h-4 w-4" />
                        )}
                      </button>
                    </th>
                    <th className="text-left px-4 py-3 font-medium text-muted-foreground text-xs uppercase tracking-wide w-8">#</th>
                    <th className="text-left px-4 py-3 font-medium text-muted-foreground text-xs uppercase tracking-wide">Candidate</th>
                    <th className="text-left px-4 py-3 font-medium text-muted-foreground text-xs uppercase tracking-wide">Contact</th>
                    <th className="text-left px-4 py-3 font-medium text-muted-foreground text-xs uppercase tracking-wide">Job</th>
                    <th className="text-left px-4 py-3 font-medium text-muted-foreground text-xs uppercase tracking-wide">Skills</th>
                    <th className="text-left px-4 py-3 font-medium text-muted-foreground text-xs uppercase tracking-wide">Exp</th>
                    <th className="text-left px-4 py-3 font-medium text-muted-foreground text-xs uppercase tracking-wide">Score</th>
                    <th className="text-left px-4 py-3 font-medium text-muted-foreground text-xs uppercase tracking-wide">Tag</th>
                    <th className="text-left px-4 py-3 font-medium text-muted-foreground text-xs uppercase tracking-wide">Status</th>
                    <th className="text-left px-4 py-3 font-medium text-muted-foreground text-xs uppercase tracking-wide">Uploaded</th>
                    <th className="text-left px-4 py-3 font-medium text-muted-foreground text-xs uppercase tracking-wide w-20">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {allData.map((c: any, idx: number) => {
                    const isSelected  = selected.has(c.id);
                    const isArchived  = !!c.is_archived;
                    const initials    = (c.name || "??").substring(0, 2).toUpperCase();
                    const skillsList: string[] = Array.isArray(c.skills)
                      ? c.skills
                      : typeof c.skills === "string"
                        ? (() => { try { return JSON.parse(c.skills); } catch { return []; } })()
                        : [];
                    const jobTitle  = c.job_id ? (jobMap[c.job_id] || "Unknown Job") : null;
                    const uploadDate = c.created_at
                      ? new Date(c.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })
                      : "—";

                    return (
                      <tr
                        key={c.id}
                        className={cn(
                          "transition-colors",
                          isSelected
                            ? "bg-primary/5 hover:bg-primary/10"
                            : isArchived
                              ? "bg-amber-50/40 dark:bg-amber-950/10 hover:bg-amber-50/70 dark:hover:bg-amber-950/20"
                              : "hover:bg-muted/40"
                        )}
                      >
                        {/* Checkbox */}
                        <td className="px-4 py-3">
                          <button
                            className="flex items-center justify-center w-5 h-5 rounded text-muted-foreground hover:text-foreground transition-colors"
                            onClick={() => toggleOne(c.id)}
                          >
                            {isSelected
                              ? <CheckSquare className="h-4 w-4 text-primary" />
                              : <Square className="h-4 w-4" />
                            }
                          </button>
                        </td>

                        {/* Row number */}
                        <td className="px-4 py-3 text-muted-foreground text-xs">
                          {page * PAGE_SIZE + idx + 1}
                        </td>

                        {/* Candidate */}
                        <td className="px-4 py-3">
                          <Link
                            to={`/candidates/${c.id}`}
                            className="flex items-center gap-2.5 group"
                            onClick={() => onOpenChange(false)}
                          >
                            <div className={cn(
                              "flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-xs font-semibold",
                              isArchived
                                ? "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400"
                                : "bg-primary/10 text-primary"
                            )}>
                              {initials}
                            </div>
                            <span className="font-medium group-hover:text-primary group-hover:underline transition-colors truncate max-w-[120px]">
                              {c.name || <span className="text-muted-foreground italic text-xs">Unnamed</span>}
                            </span>
                          </Link>
                        </td>

                        {/* Contact */}
                        <td className="px-4 py-3 text-muted-foreground">
                          <div className="truncate max-w-[150px] text-xs">{c.email || "—"}</div>
                          {c.phone && <div className="text-xs truncate max-w-[150px] text-muted-foreground/70">{c.phone}</div>}
                        </td>

                        {/* Job */}
                        <td className="px-4 py-3">
                          {jobTitle ? (
                            <div className="flex items-center gap-1.5 text-xs">
                              <Briefcase className="h-3 w-3 text-muted-foreground flex-shrink-0" />
                              <span className="truncate max-w-[120px]">{jobTitle}</span>
                            </div>
                          ) : (
                            <Badge variant="outline" className="text-xs font-normal text-muted-foreground">Pool</Badge>
                          )}
                        </td>

                        {/* Skills */}
                        <td className="px-4 py-3">
                          <div className="flex flex-wrap gap-1 max-w-[160px]">
                            {skillsList.slice(0, 3).map((s: string) => (
                              <span key={s} className="text-xs bg-secondary px-1.5 py-0.5 rounded truncate max-w-[70px]">{s}</span>
                            ))}
                            {skillsList.length > 3 && (
                              <span className="text-xs text-muted-foreground">+{skillsList.length - 3}</span>
                            )}
                            {skillsList.length === 0 && <span className="text-muted-foreground text-xs">—</span>}
                          </div>
                        </td>

                        {/* Experience */}
                        <td className="px-4 py-3 text-sm">
                          {c.experience_years != null
                            ? <span>{Number(c.experience_years).toFixed(1)} <span className="text-muted-foreground text-xs">yrs</span></span>
                            : <span className="text-muted-foreground">—</span>}
                        </td>

                        {/* Score */}
                        <td className="px-4 py-3">
                          {c.resume_score != null ? (
                            <div className="flex items-center gap-1.5">
                              <div className="w-14 h-1.5 bg-muted rounded-full overflow-hidden">
                                <div className="h-full rounded-full bg-primary" style={{ width: `${Math.min(100, c.resume_score)}%` }} />
                              </div>
                              <span className="text-xs font-medium tabular-nums">{Number(c.resume_score).toFixed(1)}%</span>
                            </div>
                          ) : (
                            <span className="text-muted-foreground text-xs">—</span>
                          )}
                        </td>

                        {/* Tag */}
                        <td className="px-4 py-3">
                          {c.tag ? (
                            <span className={cn("inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border", tagColor[c.tag] || "bg-secondary text-secondary-foreground")}>
                              {c.tag}
                            </span>
                          ) : (
                            <span className="text-muted-foreground text-xs">—</span>
                          )}
                        </td>

                        {/* Archive status */}
                        <td className="px-4 py-3">
                          {isArchived ? (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-amber-100 text-amber-700 border border-amber-200 dark:bg-amber-900/30 dark:text-amber-400 dark:border-amber-800">
                              <Archive className="h-2.5 w-2.5" /> Archived
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-50 text-emerald-600 border border-emerald-200 dark:bg-emerald-900/20 dark:text-emerald-400 dark:border-emerald-800">
                              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" /> Active
                            </span>
                          )}
                        </td>

                        {/* Date */}
                        <td className="px-4 py-3 text-xs text-muted-foreground whitespace-nowrap">{uploadDate}</td>

                        {/* Row actions */}
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-1">
                            {isArchived ? (
                              <button
                                title="Restore to active pipeline"
                                className="p-1.5 rounded-lg hover:bg-emerald-100 dark:hover:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400 transition-colors"
                                onClick={() => handleRestore([c.id])}
                              >
                                <RotateCcw className="h-3.5 w-3.5" />
                              </button>
                            ) : null}
                            <button
                              title="Permanently delete this record"
                              className="p-1.5 rounded-lg hover:bg-red-100 dark:hover:bg-red-900/30 text-red-500 dark:text-red-400 transition-colors"
                              onClick={() => { setSelected(new Set([c.id])); setDeleteMode("selected"); }}
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>

          {/* ── Footer / Pagination ─────────────────────────────────────────── */}
          <div className="px-6 py-3 border-t flex-shrink-0 flex items-center justify-between bg-muted/10">
            <div className="flex items-center gap-4">
              <span className="text-sm text-muted-foreground">
                {loading ? "Loading..." : `Showing ${page * PAGE_SIZE + 1}–${page * PAGE_SIZE + allData.length}`}
              </span>
              {archivedOnPage > 0 && (
                <span className="text-xs text-amber-600 dark:text-amber-400 flex items-center gap-1">
                  <Archive className="h-3 w-3" /> {archivedOnPage} archived on this page
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              <Button variant="outline" size="sm" onClick={() => handlePageChange(page - 1)} disabled={!hasPrev || loading}>
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <span className="text-sm px-2 tabular-nums">Page {page + 1}</span>
              <Button variant="outline" size="sm" onClick={() => handlePageChange(page + 1)} disabled={!hasNext || loading}>
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* ── Confirm delete dialog ─────────────────────────────────────────────── */}
      <AlertDialog open={deleteMode !== null} onOpenChange={(o) => { if (!o && !actionLoading) setDeleteMode(null); }}>
        <AlertDialogContent className="rounded-2xl max-w-md">
          <AlertDialogHeader>
            <AlertDialogTitle className="flex items-center gap-2 text-red-600">
              <ShieldAlert className="h-5 w-5" />
              {getConfirmConfig().title}
            </AlertDialogTitle>
            <AlertDialogDescription asChild>
              <div className="text-sm text-muted-foreground leading-relaxed">
                {getConfirmConfig().description}
              </div>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel className="rounded-full" disabled={actionLoading}>
              Cancel
            </AlertDialogCancel>
            <AlertDialogAction
              className={cn("rounded-full", getConfirmConfig().actionClass)}
              disabled={actionLoading}
              onClick={(e) => { e.preventDefault(); executeDelete(); }}
            >
              {actionLoading ? (
                <span className="flex items-center gap-2">
                  <span className="h-4 w-4 rounded-full border-2 border-white/30 border-t-white animate-spin" />
                  Deleting...
                </span>
              ) : (
                getConfirmConfig().actionLabel
              )}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
