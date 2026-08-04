import React, { useState, useEffect, useMemo, useRef, useCallback } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Search, Filter, Download, Upload, LayoutList, LayoutGrid, Database, Archive } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
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

import { getJobs } from "@/services/jobs";
import { getCandidates, archiveCandidates } from "@/services/candidates";
import { toast } from "sonner";
import { ShortlistTable } from "@/components/ShortlistTable";
import { CandidateKanban } from "@/components/CandidateKanban";
import { BulkUploadModal } from "@/components/BulkUploadModal";
import { AllDataModal } from "@/components/AllDataModal";

export default function Candidates() {
  const [candidates, setCandidates] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [viewMode, setViewMode] = useState<'list' | 'kanban'>('list');
  const [deleting, setDeleting] = useState(false);
  const [archiveConfirmOpen, setArchiveConfirmOpen] = useState(false);
  const [allDataOpen, setAllDataOpen] = useState(false);
  const activeLoadsRef = useRef(0);

  const isCancelledRequest = (error: any) =>
    error?.name === "AbortError" || error?.code === "ERR_CANCELED";

  const loadData = useCallback(async (isBackground = false, signal?: AbortSignal) => {
    if (isBackground && activeLoadsRef.current > 0) return;
    activeLoadsRef.current += 1;
    try {
      const [jobsRes, candidatesRes] = await Promise.allSettled([
        getJobs(false, signal),
        getCandidates(undefined, undefined, signal)
      ]);

      if (jobsRes.status === "fulfilled") {
        const allJobs = Array.isArray(jobsRes.value) ? jobsRes.value : [];
        const activeJobs = allJobs.filter((job: any) => job?.is_active !== false);
        setJobs(activeJobs.length > 0 ? activeJobs : allJobs);
      } else if (!isBackground && !isCancelledRequest(jobsRes.reason)) {
        toast.error("Failed to load jobs");
      }

      if (candidatesRes.status === "fulfilled") {
        setCandidates(candidatesRes.value);
      } else if (!isBackground && !isCancelledRequest(candidatesRes.reason)) {
        toast.error("Failed to load candidates");
      }
    } catch (error: any) {
      if (isCancelledRequest(error)) return;
      if (!isBackground) toast.error("Failed to load data");
    } finally {
      activeLoadsRef.current = Math.max(0, activeLoadsRef.current - 1);
      if (!isBackground) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    loadData(false, controller.signal);

    // Poll every 30 s, but pause automatically when the tab is not visible.
    // The previous 10 s interval was firing even when the user had switched
    // tabs, causing unnecessary background re-renders and network requests.
    const POLL_MS = 30_000;
    let intervalId: ReturnType<typeof setInterval> | null = null;

    const start = () => {
      if (intervalId) return;
      intervalId = setInterval(() => loadData(true), POLL_MS);
    };

    const stop = () => {
      if (intervalId) { clearInterval(intervalId); intervalId = null; }
    };

    const onVisibility = () => {
      if (document.visibilityState === 'visible') {
        loadData(true); // immediate refresh on focus
        start();
      } else {
        stop();
      }
    };

    start();
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      stop();
      controller.abort();
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [loadData]);

  // Filter Logic
  const filteredCandidates = useMemo(() => {
    const needle = searchQuery.toLowerCase();
    return candidates.filter((candidate: any) => {
      const matchesSearch =
        candidate.name?.toLowerCase().includes(needle) ||
        (candidate.role && candidate.role.toLowerCase().includes(needle));

      const matchesStatus =
        statusFilter.length === 0 || statusFilter.includes(candidate.tag);

      return matchesSearch && matchesStatus;
    });
  }, [candidates, searchQuery, statusFilter]);

  const handleStatusFilterChange = (status: string) => {
    setStatusFilter((prev) =>
      prev.includes(status)
        ? prev.filter((s) => s !== status)
        : [...prev, status]
    );
  };

  const handleClearResumes = async () => {
    if (filteredCandidates.length === 0) {
      toast.info("No candidates to archive.");
      return;
    }
    // Open the AlertDialog instead of using the blocking window.confirm().
    // window.confirm() is unstyled, freezes the JS thread, and can't be
    // dismissed via Escape on some browsers. The AlertDialog is already used
    // throughout the app (e.g. job delete) — keep the pattern consistent.
    setArchiveConfirmOpen(true);
  };

  const confirmArchive = async () => {
    setArchiveConfirmOpen(false);
    setDeleting(true);
    try {
      const idsToArchive = filteredCandidates.map((c: any) => c.id);
      await archiveCandidates(idsToArchive);
      toast.success(`${filteredCandidates.length} candidate(s) archived to master database. View them in All Data.`);
      loadData();
    } catch (error) {
      toast.error("Failed to archive candidates");
    } finally {
      setDeleting(false);
    }
  };

  // Export Logic
  const handleExport = () => {
    const escapeCSV = (val: any) => {
      const s = val == null ? "" : String(val);
      return s.includes(",") || s.includes('"') || s.includes("\n")
        ? `"${s.replace(/"/g, '""')}"`
        : s;
    };
    const headers = ["ID", "Name", "Role", "Resume Score", "Quiz Score", "Final Score", "Status", "Applied Date"];
    const csvContent = [
      headers.join(","),
      ...filteredCandidates.map((c: any) =>
        [c.id, c.name, c.role, c.resume_score, c.quiz_score, c.final_score, c.tag, c.created_at]
          .map(escapeCSV).join(",")
      )
    ].join("\n");

    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const link = document.createElement("a");
    const url = URL.createObjectURL(blob);
    link.setAttribute("href", url);
    link.setAttribute("download", "candidates_export.csv");
    link.style.visibility = "hidden";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    toast.success("Candidates exported successfully");
  };

  return (
    <div className="h-full flex flex-col gap-4">
      <div className="shrink-0 flex items-center justify-between">
        <div>
          <h2 className="text-3xl font-bold tracking-tight">Candidates</h2>
          <p className="text-muted-foreground">View and manage candidate applications.</p>
        </div>
        <div className="flex items-center gap-2">
          <BulkUploadModal 
            jobs={jobs} 
            onUploadComplete={loadData} 
            trigger={
              <Button onClick={() => loadData(true)}>
                <Upload className="mr-2 h-4 w-4" /> Bulk Upload Resume
              </Button>
            }
          />

          <Button variant="outline" onClick={handleExport}>
            <Download className="mr-2 h-4 w-4" /> Export
          </Button>

          <Button variant="secondary" onClick={() => setAllDataOpen(true)}>
            <Database className="mr-2 h-4 w-4" /> All Data
          </Button>
        </div>
      </div>

      <div className="shrink-0 flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="relative flex-1 max-w-sm">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              type="search"
              placeholder="Search candidates..."
              className="pl-8"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>
          {!loading && (
            <span className="text-xs text-muted-foreground whitespace-nowrap">
              <span className="font-semibold text-foreground">{filteredCandidates.length}</span>
              {filteredCandidates.length !== candidates.length && (
                <> of <span className="font-semibold text-foreground">{candidates.length}</span></>
              )}{' '}candidates
            </span>
          )}
        </div>
        
        <div className="flex items-center gap-2">
          <div className="flex items-center border rounded-lg p-1">
            <Button 
              variant={viewMode === 'list' ? 'secondary' : 'ghost'} 
              size="sm" 
              onClick={() => setViewMode('list')}
              className="h-8 w-8 p-0"
            >
              <LayoutList className="h-4 w-4" />
            </Button>
            <Button 
              variant={viewMode === 'kanban' ? 'secondary' : 'ghost'} 
              size="sm" 
              onClick={() => setViewMode('kanban')}
              className="h-8 w-8 p-0"
            >
              <LayoutGrid className="h-4 w-4" />
            </Button>
          </div>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" className="ml-auto">
                <Filter className="mr-2 h-4 w-4" /> Filter
                {statusFilter.length > 0 && (
                  <Badge variant="secondary" className="ml-2 rounded-sm px-1 font-normal lg:hidden">
                    {statusFilter.length}
                  </Badge>
                )}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-[200px]">
              <DropdownMenuLabel>Filter by Status</DropdownMenuLabel>
              <DropdownMenuSeparator />
              {["Strong", "Medium", "Reject"].map((status) => (
                <DropdownMenuCheckboxItem
                  key={status}
                  checked={statusFilter.includes(status)}
                  onCheckedChange={() => handleStatusFilterChange(status)}
                >
                  {status}
                </DropdownMenuCheckboxItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>

          <Button variant="outline" size="default" onClick={handleClearResumes} disabled={deleting || filteredCandidates.length === 0} className="border-amber-300 text-amber-700 hover:bg-amber-50 hover:border-amber-400 dark:border-amber-700 dark:text-amber-400 dark:hover:bg-amber-900/20">
            <Archive className="mr-2 h-4 w-4" /> {deleting ? "Archiving..." : "Clear Displayed"}
          </Button>
        </div>
      </div>

      {/* Table / Kanban — fills all remaining vertical space */}
      <div className="flex-1 min-h-0">
        {viewMode === 'list' ? (
          <ShortlistTable candidates={filteredCandidates} jobs={jobs} isLoading={loading} onRefresh={loadData} />
        ) : loading ? (
          <div className="flex h-40 items-center justify-center">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
          </div>
        ) : (
          <CandidateKanban candidates={filteredCandidates} onRefresh={loadData} />
        )}
      </div>

      <AllDataModal open={allDataOpen} onOpenChange={setAllDataOpen} jobs={jobs} />

      {/* Archive confirmation — replaces window.confirm() (issue #3) */}
      <AlertDialog open={archiveConfirmOpen} onOpenChange={setArchiveConfirmOpen}>
        <AlertDialogContent className="rounded-2xl">
          <AlertDialogHeader>
            <AlertDialogTitle>Archive {filteredCandidates.length} candidate{filteredCandidates.length !== 1 ? 's' : ''}?</AlertDialogTitle>
            <AlertDialogDescription>
              They will be removed from this pipeline view but permanently kept in the{' '}
              <strong>All Data</strong> master archive — nothing is deleted. You can restore them
              from All Data at any time.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel className="rounded-full">Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={confirmArchive}
              className="bg-amber-600 text-white hover:bg-amber-700 rounded-full"
            >
              Archive
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
