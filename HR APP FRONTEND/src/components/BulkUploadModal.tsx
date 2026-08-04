/**
 * BulkUploadModal â€” Chunked batch upload with per-file status tracking
 *
 * â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
 * BUG FIXES vs previous version
 * â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
 *
 * [BUG FIX #1 â€” CRITICAL: "No response from server" for some files]
 *   Root cause: idMap was keyed by `tf.file.name` (the browser File object
 *   name). The backend receives the file from multipart FormData and returns
 *   whatever `f.filename` FastAPI gives it. On Windows, File.name can contain
 *   backslashes or different Unicode normalization than what the server echoes.
 *   More critically: when two files with the same name (e.g. "AshishGangwar.pdf"
 *   and "AshishGangwar (1).pdf") are normalized differently client vs server,
 *   or when the server truncates long filenames, the map lookup fails and the
 *   file gets "No response from server".
 *
 *   Fix: assign a stable client-side UUID to each file and pass it as an
 *   additional FormData field `file_ids[]` (one per file, in the same order as
 *   `files[]`). The backend echoes `file_id` back in each success/fail record.
 *   Resolution is now O(1) and immune to any filename munging.
 *
 *   BACKEND CHANGE REQUIRED: resumes.py must echo `file_id` in success/failed
 *   entries. See the updated resumes.py for the matching backend change.
 *
 * [BUG FIX #2 â€” skipped_duplicates not surfaced to the user]
 *   The backend now returns a `skipped_duplicates` array for files that were
 *   already uploaded. Previously these were silently ignored by the frontend,
 *   which left those file rows stuck in "uploading" forever (or got mapped to
 *   "No response from server"). Now they're resolved to a "duplicate" status
 *   with a clear "Already uploaded" label.
 *
 * [BUG FIX #3 â€” BATCH_CONCURRENCY Ã— BATCH_SIZE overloads backend AI semaphore]
 *   BATCH_CONCURRENCY=2, BATCH_SIZE=20 â†’ 40 files in-flight at once.
 *   The backend AI semaphore is Semaphore(10), so 30 files are queuing behind
 *   it. Combined with Azure/Gemini rate limits this causes timeouts on the
 *   trailing files in a batch, producing "No response from server".
 *   Fix: reduced BATCH_SIZE to 10, BATCH_CONCURRENCY stays at 2 â†’ max 20
 *   files in-flight, well within the backend semaphore.
 *
 * [BUG FIX #4 â€” timeout: 0 can hang forever on network drop]
 *   The batch request had timeout:0 (no timeout at all) relying on AbortSignal.
 *   If the network drops silently (no TCP RST), the request hangs forever.
 *   Fix: 4-minute timeout per batch (240s). 10 files Ã— ~20s per AI call = 200s
 *   worst-case per batch. 240s gives 20% headroom without hanging indefinitely.
 */

import React, {
  useState, useRef, useCallback, useEffect, useMemo,
} from "react";
import { Button }        from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogHeader,
  DialogTitle,
}                        from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem,
  SelectTrigger, SelectValue,
}                        from "@/components/ui/select";
import { Label }         from "@/components/ui/label";
import {
  Upload, X, Layers, Briefcase, CheckCircle2,
  XCircle, Loader2, CloudUpload, AlertCircle,
  ChevronDown, ChevronUp, ShieldAlert, Copy, Minimize2, Maximize2,
}                        from "lucide-react";
import { cn }            from "@/lib/utils";
import api               from "@/services/api";
import { getJobs }       from "@/services/jobs";
import { toast }         from "sonner";
import { FileRow, FileStatus, TrackedFile } from "@/components/bulk-upload/FileRow";

// â”€â”€â”€ Constants â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

const POOL_VALUE = "__pool__";

/**
 * BUG FIX #3: Reduced from 20 â†’ 10 to stay within backend AI semaphore(10).
 * 500 files Ã· 10 = 50 batches Ã— 2 concurrent = manageable load.
 */
const BATCH_SIZE = 10;

/** 2 concurrent batch chains â†’ max 20 files in-flight at once. */
const BATCH_CONCURRENCY = 2;

/**
 * BUG FIX #4: 4-minute timeout per batch request.
 * 10 files Ã— ~20s worst-case AI parse = 200s + 40s headroom.
 */
const BATCH_TIMEOUT_MS = 240_000;

const MAX_FILE_SIZE_MB = 20;
const MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024;

const ACCEPTED_EXTENSIONS = ".pdf,.doc,.docx,.png,.jpg,.jpeg,.webp,.tiff,.tif,.bmp,.gif";



const PROGRESS_THROTTLE_MS = 100;

// â”€â”€â”€ Types â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

interface BatchResult {
  // BUG FIX #1: backend now echoes file_id in each record
  success:           { filename: string; candidate_id: string; file_id?: string }[];
  failed:            { filename: string; error: string; file_id?: string }[];
  // BUG FIX #2: new field from updated backend
  skipped_duplicates?: { filename: string; reason: string; file_id?: string }[];
}

interface Job {
  id: string;
  title: string;
  is_active?: boolean;
}

interface BulkUploadModalProps {
  jobs: Job[];
  onUploadComplete?: () => void;
  trigger?: React.ReactElement;
}

// â”€â”€â”€ Validation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function validateFiles(incoming: File[]): { valid: File[]; tooLarge: File[]; badType: File[] } {
  const extSet = new Set(ACCEPTED_EXTENSIONS.split(","));
  const result = { valid: [] as File[], tooLarge: [] as File[], badType: [] as File[] };
  for (const f of incoming) {
    const ext = "." + (f.name.split(".").pop() ?? "").toLowerCase();
    if (f.size > MAX_FILE_SIZE_BYTES) { result.tooLarge.push(f); continue; }
    if (!extSet.has(ext)) { result.badType.push(f); continue; }
    result.valid.push(f);
  }
  return result;
}

// â”€â”€â”€ Batch upload â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

async function uploadBatch(
  trackedBatch: TrackedFile[],
  jobId: string | null,
  onProgress: (pct: number) => void,
  signal: AbortSignal,
): Promise<BatchResult> {
  const formData = new FormData();
  const url = jobId ? "/resumes/upload-bulk" : "/resumes/upload-bulk-pool";
  if (jobId) formData.append("job_id", jobId);

  // BUG FIX #1: attach each file AND its stable client ID so the backend
  // can echo it back. Both arrays are in the same order.
  for (const tf of trackedBatch) {
    formData.append("files", tf.file);
    formData.append("file_ids", tf.id);  // new field â€” backend echoes this back
  }

  let lastFlush = 0;
  const response = await api.post<BatchResult>(url, formData, {
    headers: { "Content-Type": "multipart/form-data" },
    signal,
    timeout: BATCH_TIMEOUT_MS,   // BUG FIX #4: was 0 (no timeout)
    onUploadProgress: (evt) => {
      if (!evt.total) return;
      const pct = Math.min(90, Math.round((evt.loaded / evt.total) * 90));
      const now = Date.now();
      if (pct < 90 && now - lastFlush < PROGRESS_THROTTLE_MS) return;
      lastFlush = now;
      onProgress(pct);
    },
  });
  return response.data;
}

function chunk<T>(arr: T[], size: number): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < arr.length; i += size) out.push(arr.slice(i, i + size));
  return out;
}

// â”€â”€â”€ Main component â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

export function BulkUploadModal({ jobs, onUploadComplete, trigger }: BulkUploadModalProps) {
  const [isOpen,        setIsOpen       ] = useState(false);
  const [isMinimized,   setIsMinimized  ] = useState(false);
  const [selectedJob,   setSelectedJob  ] = useState("");
  const [runtimeJobs,   setRuntimeJobs  ] = useState<Job[]>(jobs);
  const [trackedFiles,  setTrackedFiles ] = useState<TrackedFile[]>([]);
  const [isDragging,    setIsDragging   ] = useState(false);
  const [isUploading,   setIsUploading  ] = useState(false);
  const [isDone,        setIsDone       ] = useState(false);
  const [reviewConfirmed, setReviewConfirmed] = useState(false);
  // Auto-collapse when >50 files â€” rendering 500 rows is expensive and unhelpful
  const [listCollapsed, setListCollapsed] = useState(false);
  // FIX F-3: use a ref instead of state so the useCallback([], []) closure
  // in addFiles always reads the latest value without a stale closure.
  const userToggledCollapseRef = useRef(false);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const abortRef     = useRef<AbortController | null>(null);
  const mountedRef   = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  const isPoolUpload = selectedJob === POOL_VALUE;

  useEffect(() => {
    setRuntimeJobs(jobs);
  }, [jobs]);

  useEffect(() => {
    if (!isOpen || isUploading) return;
    let cancelled = false;
    (async () => {
      try {
        const allJobs = await getJobs(false);
        if (cancelled) return;
        const normalized = Array.isArray(allJobs) ? allJobs : [];
        const active = normalized.filter((job: Job) => job?.is_active !== false);
        setRuntimeJobs(active.length > 0 ? active : normalized);
      } catch {
        // Keep existing jobs snapshot from parent props.
      }
    })();
    return () => { cancelled = true; };
  }, [isOpen, isUploading]);

  // â”€â”€ Derived counts â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  const doneCount      = useMemo(() => trackedFiles.filter(f => f.status === "done").length,      [trackedFiles]);
  const errorCount     = useMemo(() => trackedFiles.filter(f => f.status === "error").length,     [trackedFiles]);
  const duplicateCount = useMemo(() => trackedFiles.filter(f => f.status === "duplicate").length, [trackedFiles]);
  const activeCount    = useMemo(() => trackedFiles.filter(f => f.status === "uploading").length, [trackedFiles]);
  const idleCount      = useMemo(() => trackedFiles.filter(f => f.status === "idle").length,      [trackedFiles]);
  const total          = trackedFiles.length;
  const overallPct     = total === 0 ? 0 : Math.round((doneCount + errorCount + duplicateCount) / total * 100);

  // â”€â”€ File management â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

  const addFiles = useCallback((incoming: File[]) => {
    const { valid, tooLarge, badType } = validateFiles(incoming);

    if (tooLarge.length > 0) {
      toast.error(
        `${tooLarge.length} file${tooLarge.length > 1 ? "s" : ""} exceed the ${MAX_FILE_SIZE_MB} MB limit and were skipped.`,
        { description: tooLarge.map(f => f.name).join(", ") }
      );
    }
    if (badType.length > 0) {
      toast.error(
        `${badType.length} unsupported file type${badType.length > 1 ? "s" : ""} skipped.`,
        { description: badType.map(f => f.name).join(", ") }
      );
    }
    if (valid.length === 0) return;

    setTrackedFiles(prev => {
      // Deduplicate by name+size â€” prevent double-adding the same file
      const seen = new Set(prev.map(x => `${x.file.name}-${x.file.size}`));
      const fresh: TrackedFile[] = valid
        .filter(f => !seen.has(`${f.name}-${f.size}`))
        .map(f => ({
          // BUG FIX #1: id is now a stable UUID, not derived from filename
          id:       crypto.randomUUID(),
          file:     f,
          status:   "idle",
          progress: 0,
        }));
      const next = [...prev, ...fresh];
      // Auto-collapse when total exceeds 50 files to avoid rendering hundreds of rows.
      // Only auto-collapse if the user has not manually toggled the list themselves.
      if (next.length > 50 && !userToggledCollapseRef.current) {
        setListCollapsed(true);
      }
      return next;
    });
  }, []);

  const removeFile = useCallback((id: string) => {
    setTrackedFiles(prev => prev.filter(f => f.id !== id));
  }, []);

  const patchFiles = useCallback(
    (updates: Map<string, Partial<TrackedFile>>) => {
      setTrackedFiles(prev =>
        prev.map(f => updates.has(f.id) ? { ...f, ...updates.get(f.id) } : f)
      );
    },
    []
  );

  // â”€â”€ Drag & drop â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  const handleDragOver  = (e: React.DragEvent) => { e.preventDefault(); setIsDragging(true); };
  const handleDragLeave = () => setIsDragging(false);
  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault(); setIsDragging(false);
    if (e.dataTransfer.files?.length) addFiles(Array.from(e.dataTransfer.files));
  };
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files?.length) { addFiles(Array.from(e.target.files)); e.target.value = ""; }
  };

  // â”€â”€ Upload engine â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

  const handleUpload = useCallback(async () => {
    const queue = trackedFiles.filter(f => f.status === "idle");
    if (!selectedJob || queue.length === 0) return;

    const controller = new AbortController();
    abortRef.current = controller;

    setIsUploading(true);
    setIsDone(false);

    const jobId   = isPoolUpload ? null : selectedJob;
    const batches: TrackedFile[][] = chunk<TrackedFile>(queue, BATCH_SIZE);
    let batchCursor = 0;

    const runNextBatch = async (): Promise<void> => {
      if (batchCursor >= batches.length || !mountedRef.current) return;
      if (controller.signal.aborted) return;

      const batch = batches[batchCursor++];

      // Mark batch as uploading
      patchFiles(new Map(batch.map(tf => [tf.id, { status: "uploading", progress: 0 }])));

      try {
        const result = await uploadBatch(
          batch,           // BUG FIX #1: pass full TrackedFile[] so file_ids can be sent
          jobId,
          (pct: number) => {
            if (!mountedRef.current || controller.signal.aborted) return;
            patchFiles(new Map(batch.map(tf => [tf.id, { progress: pct }])));
          },
          controller.signal,
        );

        if (!mountedRef.current) return;

        // BUG FIX #1: resolve by file_id, not filename
        const resolveUpdates = new Map<string, Partial<TrackedFile>>();
        const pendingByName = new Map<string, string[]>();
        for (const tf of batch) {
          const k = tf.file.name.trim().toLowerCase();
          const arr = pendingByName.get(k) ?? [];
          arr.push(tf.id);
          pendingByName.set(k, arr);
        }
        const pickByFilename = (filename?: string): string | undefined => {
          const k = (filename ?? "").trim().toLowerCase();
          if (!k) return undefined;
          const arr = pendingByName.get(k);
          if (!arr || arr.length === 0) return undefined;
          const picked = arr.shift();
          if (arr.length === 0) pendingByName.delete(k);
          return picked;
        };

        for (const ok of result.success) {
          const targetId = ok.file_id || pickByFilename(ok.filename);
          if (targetId) resolveUpdates.set(targetId, { status: "done", progress: 100 });
        }
        for (const fail of result.failed) {
          const targetId = fail.file_id || pickByFilename(fail.filename);
          if (targetId) resolveUpdates.set(targetId, { status: "error", error: fail.error, progress: 0 });
        }
        // BUG FIX #2: handle duplicates as a distinct status
        for (const dup of (result.skipped_duplicates ?? [])) {
          const targetId = dup.file_id || pickByFilename(dup.filename);
          if (targetId) resolveUpdates.set(targetId, { status: "duplicate", progress: 0 });
        }

        // Any file not mentioned: mark as error with a clear message
        for (const tf of batch) {
          if (!resolveUpdates.has(tf.id)) {
            resolveUpdates.set(tf.id, {
              status: "error",
              error:  "No response - will be retried",
              progress: 0,
            });
          }
        }
        patchFiles(resolveUpdates);

      } catch (err: any) {
        if (!mountedRef.current) return;
        const isAbort = err?.name === "CanceledError" || err?.name === "AbortError"
          || controller.signal.aborted;
        const msg = isAbort
          ? "Upload cancelled"
          : (err?.response?.data?.detail ?? err?.message ?? "Batch upload failed");

        patchFiles(new Map(batch.map(tf => [tf.id, {
          status:   isAbort ? "idle" : "error",
          error:    isAbort ? undefined : String(msg),
          progress: 0,
        }])));
        if (isAbort) return;
      }

      await runNextBatch();
    };

    // Launch BATCH_CONCURRENCY parallel chains
    await Promise.all(
      Array.from({ length: Math.min(BATCH_CONCURRENCY, batches.length) }, runNextBatch)
    );

    if (!mountedRef.current) return;

    setIsUploading(false);
    setIsDone(true);
    abortRef.current = null;

    setTrackedFiles(curr => {
      const ok   = curr.filter(f => f.status === "done").length;
      const dups = curr.filter(f => f.status === "duplicate").length;
      const bad  = curr.filter(f => f.status === "error").length;
      if (bad === 0 && dups === 0) {
        toast.success(`${ok} resume${ok > 1 ? "s" : ""} uploaded successfully`);
      } else if (bad === 0) {
        toast.success(`${ok} uploaded - ${dups} already existed (skipped)`);
      } else {
        toast.warning(`${ok} uploaded - ${dups} skipped - ${bad} failed`);
      }
      return curr;
    });

    onUploadComplete?.();
  }, [trackedFiles, selectedJob, isPoolUpload, patchFiles, onUploadComplete]);

  // â”€â”€ Close / cancel â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

  const handleClose = useCallback(() => {
    if (isUploading) abortRef.current?.abort();
    setIsOpen(false);
    setIsMinimized(false);
    setTimeout(() => {
      if (!mountedRef.current) return;
      setTrackedFiles([]);
      setSelectedJob("");
      setIsDone(false);
      setReviewConfirmed(false);
      setListCollapsed(false);
      userToggledCollapseRef.current = false;
    }, 200);
  }, [isUploading]);

  const handleMinimize = useCallback(() => {
    setIsOpen(false);
    setIsMinimized(true);
  }, []);

  const handleReopen = useCallback(() => {
    setIsMinimized(false);
    setIsOpen(true);
  }, []);

  const handleHeaderClose = useCallback(() => {
    if (isUploading) {
      handleMinimize();
      return;
    }
    handleClose();
  }, [isUploading, handleMinimize, handleClose]);

  // â”€â”€ Computed UI â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  const canUpload        = !!selectedJob && idleCount > 0 && !isUploading && reviewConfirmed;
  const selectedJobTitle = isPoolUpload
    ? "General Pool"
    : runtimeJobs.find(j => j.id === selectedJob)?.title ?? "";

  const batchInfo = useMemo(() => {
    const totalBatches = Math.ceil(total / BATCH_SIZE);
    return `${total} file${total !== 1 ? "s" : ""} -> ${totalBatches} batch${totalBatches !== 1 ? "es" : ""} of ${BATCH_SIZE}`;
  }, [total]);

  // ETA: ~20s per file worst-case, BATCH_CONCURRENCY parallel chains
  const etaSeconds = useMemo(() => {
    if (idleCount === 0) return 0;
    const filesPerSecond = BATCH_CONCURRENCY * (1 / 20); // 20s worst-case per file
    return Math.ceil(idleCount / filesPerSecond);
  }, [idleCount]);

  const etaLabel = useMemo(() => {
    if (etaSeconds <= 0) return "";
    if (etaSeconds < 60) return `~${etaSeconds}s`;
    const mins = Math.ceil(etaSeconds / 60);
    return `~${mins} min${mins > 1 ? "s" : ""}`;
  }, [etaSeconds]);

  // Whether to show the compact summary card instead of the full file list
  // (>50 files AND currently collapsed)
  const showSummaryCard = listCollapsed && total > 50;

  // â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  return (
    <>
      {trigger
        ? React.cloneElement(trigger, {
          onClick: (e: React.MouseEvent) => {
            trigger.props.onClick?.(e);
            handleReopen();
          }
        })
        : (
          <Button onClick={handleReopen}>
            <Upload className="h-4 w-4" /> Bulk Upload Resumes
          </Button>
        )
      }

    {isMinimized && (isUploading || isDone) && (
      <button
        onClick={handleReopen}
        className="fixed bottom-4 right-4 z-[60] rounded-full border bg-background px-4 py-2 shadow-md text-sm font-medium flex items-center gap-2 hover:bg-muted transition-colors"
      >
        <Maximize2 className="h-4 w-4" />
        {isUploading
          ? `Upload running ${doneCount + errorCount + duplicateCount}/${total}`
          : `Upload complete ${doneCount}/${total}`}
      </button>
    )}

      <Dialog
        open={isOpen}
        onOpenChange={open => {
        if (open) {
          handleReopen();
          return;
        }
        if (isUploading) {
          handleMinimize();
          return;
        }
        handleClose();
      }}
      >
      <DialogContent
        hideDefaultCloseButton
        className="sm:max-w-[540px] p-0 gap-0 overflow-hidden flex flex-col max-h-[90vh]"
        onInteractOutside={e => { if (isUploading) e.preventDefault(); }}
      >
        {/* â”€â”€ Header â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */}
        <DialogHeader className="px-6 pt-6 pb-4 border-b flex-shrink-0">
          <div className="flex items-center justify-between gap-3">
            <div className="p-2 rounded-lg bg-primary/10 flex-shrink-0">
              <CloudUpload className="h-5 w-5 text-primary" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="min-w-0">
                <DialogTitle className="text-base">Bulk Upload Resumes</DialogTitle>
                <p className="text-xs text-muted-foreground mt-0.5 truncate">
                  {isUploading
                    ? `Uploading ${doneCount + errorCount + duplicateCount} of ${total} files...`
                    : isDone
                      ? `Done - ${doneCount} uploaded${duplicateCount > 0 ? `, ${duplicateCount} skipped` : ""}${errorCount > 0 ? `, ${errorCount} failed` : ""}`
                      : "Upload multiple resumes with live progress"}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-1 shrink-0">
              {isUploading && (
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={handleMinimize}
                  className="h-8 w-8"
                  title="Minimize"
                  aria-label="Minimize upload dialog"
                >
                  <Minimize2 className="h-4 w-4" />
                </Button>
              )}
              <Button
                variant="ghost"
                size="icon"
                onClick={handleHeaderClose}
                className="h-8 w-8"
                title={isUploading ? "Minimize upload dialog" : "Close upload dialog"}
                aria-label={isUploading ? "Minimize upload dialog" : "Close upload dialog"}
              >
                <X className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </DialogHeader>

        <div className="px-6 py-5 space-y-5 flex-1 overflow-y-auto">

          {/* â”€â”€ Overall progress bar â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */}
          {(isUploading || isDone) && total > 0 && (
            <div className="space-y-1.5">
              <div className="flex justify-between text-xs text-muted-foreground">
                <span>
                  {isUploading
                    ? `${activeCount} uploading - ${idleCount} queued`
                    : isDone ? "Complete" : ""}
                </span>
                <span className="tabular-nums">{doneCount + errorCount + duplicateCount} / {total}</span>
              </div>
              <div className="h-2 w-full rounded-full bg-muted overflow-hidden">
                <div
                  className={cn(
                    "h-full rounded-full transition-all duration-500 ease-out",
                    errorCount > 0 && !isUploading ? "bg-amber-500" : "bg-emerald-500"
                  )}
                  style={{ width: `${overallPct}%` }}
                />
              </div>
              {(errorCount > 0 || duplicateCount > 0) && !isUploading && (
                <div className="flex flex-col gap-0.5">
                  {errorCount > 0 && (
                    <p className="text-[11px] text-amber-600 dark:text-amber-400 flex items-center gap-1">
                      <AlertCircle className="h-3 w-3" />
                      {errorCount} file{errorCount > 1 ? "s" : ""} failed - click "Retry Failed" below
                    </p>
                  )}
                  {duplicateCount > 0 && (
                    <p className="text-[11px] text-amber-500 dark:text-amber-400 flex items-center gap-1">
                      <Copy className="h-3 w-3" />
                      {duplicateCount} file{duplicateCount > 1 ? "s" : ""} already in the portal - skipped
                    </p>
                  )}
                </div>
              )}
            </div>
          )}

          {/* â”€â”€ Destination selector â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */}
          {!isUploading && !isDone && (
            <div className="space-y-1.5">
              <Label className="text-sm">Destination</Label>
              <Select value={selectedJob} onValueChange={setSelectedJob}>
                <SelectTrigger className={cn(
                  "transition-all",
                  isPoolUpload && "border-emerald-400 ring-1 ring-emerald-300 dark:ring-emerald-800"
                )}>
                  <SelectValue placeholder="Select a job or upload to general pool...">
                    {selectedJob && (
                      <span className="flex items-center gap-2">
                        {isPoolUpload
                          ? <Layers className="h-3.5 w-3.5 text-emerald-600" />
                          : <Briefcase className="h-3.5 w-3.5 text-muted-foreground" />}
                        {selectedJobTitle}
                      </span>
                    )}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  <SelectItem
                    value={POOL_VALUE}
                    className="bg-emerald-50 text-emerald-800 font-semibold rounded-md my-0.5
                      hover:bg-emerald-100 focus:bg-emerald-100
                      dark:bg-emerald-950/40 dark:text-emerald-300 dark:hover:bg-emerald-900/50"
                  >
                    <span className="flex items-center gap-2">
                      <Layers className="h-3.5 w-3.5 shrink-0" />
                      General Pool - no scoring
                    </span>
                  </SelectItem>
                  {runtimeJobs.length > 0 && (
                    <div className="relative my-2 mx-1">
                      <div className="border-t-2 border-dashed border-muted-foreground/20" />
                      <span className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2
                        bg-popover px-2 text-[10px] uppercase tracking-widest text-muted-foreground/50 whitespace-nowrap">
                        or score against a job
                      </span>
                    </div>
                  )}
                  {runtimeJobs.map(job => (
                    <SelectItem key={job.id} value={job.id}>
                      <span className="flex items-center gap-2">
                        <Briefcase className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                        {job.title}
                      </span>
                    </SelectItem>
                  ))}
                  {runtimeJobs.length === 0 && (
                    <div className="px-3 py-2 text-xs text-muted-foreground italic">No active jobs yet</div>
                  )}
                </SelectContent>
              </Select>
              {isPoolUpload && (
                <p className="text-xs text-muted-foreground flex items-start gap-1.5">
                  <Layers className="h-3 w-3 mt-0.5 shrink-0 text-emerald-500" />
                  Resumes parsed for contact info and skills only. Scoring applied when assigned to a job.
                </p>
              )}
            </div>
          )}

          {/* â”€â”€ Drop zone â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */}
          {!isUploading && !isDone && (
            <div className="space-y-1.5">
              <Label className="text-sm">
                Files
                {total > 0 && (
                  <span className="ml-1.5 text-xs font-normal text-muted-foreground">
                    {batchInfo}
                  </span>
                )}
              </Label>
              <div
                role="button"
                tabIndex={0}
                aria-label="Upload files"
                className={cn(
                  "border-2 border-dashed rounded-xl p-6 text-center transition-all cursor-pointer",
                  isDragging
                    ? "border-primary bg-primary/5 scale-[0.99]"
                    : isPoolUpload
                      ? "border-emerald-300 hover:border-emerald-400 hover:bg-emerald-50/30 dark:hover:bg-emerald-950/10"
                      : "border-muted-foreground/20 hover:border-primary/40 hover:bg-muted/30"
                )}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
                onClick={() => fileInputRef.current?.click()}
                onKeyDown={e => { if (e.key === "Enter" || e.key === " ") fileInputRef.current?.click(); }}
              >
                <input
                  ref={fileInputRef}
                  type="file"
                  multiple
                  hidden
                  accept={ACCEPTED_EXTENSIONS}
                  onChange={handleFileChange}
                />
                <div className="flex flex-col items-center gap-2">
                  <div className={cn("p-3 rounded-full transition-colors", isDragging ? "bg-primary/10" : "bg-muted")}>
                    <Upload className={cn("h-5 w-5", isDragging ? "text-primary" : "text-muted-foreground")} />
                  </div>
                  <p className="text-sm font-medium">Drop files here or click to browse</p>
                  <p className="text-xs text-muted-foreground">
                    PDF, DOC, DOCX, PNG, JPG, WEBP, TIFF - max {MAX_FILE_SIZE_MB} MB each - up to 500 files
                  </p>
                </div>
              </div>
              <p className="text-[11px] text-muted-foreground flex items-center gap-1">
                <ShieldAlert className="h-3 w-3 flex-shrink-0" />
                Files exceeding {MAX_FILE_SIZE_MB} MB or unsupported formats are rejected before upload.
                Duplicate resumes already in the portal are automatically skipped.
              </p>
            </div>
          )}

          {/* â”€â”€ File list â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */}
          {total > 0 && (
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium">
                    {isUploading || isDone ? "Files" : "Queue"}
                  </span>
                  <div className="flex items-center gap-1">
                    {doneCount > 0 && (
                      <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full
                        text-[10px] font-semibold bg-emerald-100 text-emerald-700
                        dark:bg-emerald-900/40 dark:text-emerald-300">
                        <CheckCircle2 className="h-2.5 w-2.5" />{doneCount}
                      </span>
                    )}
                    {duplicateCount > 0 && (
                      <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full
                        text-[10px] font-semibold bg-amber-100 text-amber-600
                        dark:bg-amber-900/40 dark:text-amber-400">
                        <Copy className="h-2.5 w-2.5" />{duplicateCount}
                      </span>
                    )}
                    {errorCount > 0 && (
                      <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full
                        text-[10px] font-semibold bg-red-100 text-red-600
                        dark:bg-red-900/40 dark:text-red-400">
                        <XCircle className="h-2.5 w-2.5" />{errorCount}
                      </span>
                    )}
                    {activeCount > 0 && (
                      <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full
                        text-[10px] font-semibold bg-blue-100 text-blue-600
                        dark:bg-blue-900/40 dark:text-blue-400">
                        <Loader2 className="h-2.5 w-2.5 animate-spin" />{activeCount}
                      </span>
                    )}
                    {idleCount > 0 && (
                      <span className="inline-flex px-1.5 py-0.5 rounded-full text-[10px]
                        font-semibold bg-muted text-muted-foreground">
                        {idleCount} pending
                      </span>
                    )}
                  </div>
                </div>
                <button
                  onClick={() => {
                    userToggledCollapseRef.current = true;
                    setListCollapsed(p => !p);
                  }}
                  className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
                >
                  {listCollapsed ? "Show" : "Hide"}
                  {listCollapsed
                    ? <ChevronDown className="h-3.5 w-3.5" />
                    : <ChevronUp className="h-3.5 w-3.5" />}
                </button>
              </div>

              {/* Compact summary card for large batches (>50 files, collapsed) */}
              {showSummaryCard && !isUploading && !isDone && (
                <div className="rounded-xl border border-border/60 bg-muted/20 px-4 py-3 flex items-center gap-4">
                  <div className="flex-1 grid grid-cols-3 gap-3 text-center">
                    <div>
                      <p className="text-xl font-bold text-foreground">{total}</p>
                      <p className="text-[10px] text-muted-foreground mt-0.5">Files queued</p>
                    </div>
                    <div>
                      <p className="text-xl font-bold text-foreground">{Math.ceil(total / BATCH_SIZE)}</p>
                      <p className="text-[10px] text-muted-foreground mt-0.5">Batches of {BATCH_SIZE}</p>
                    </div>
                    <div>
                      <p className="text-xl font-bold text-primary">{etaLabel}</p>
                      <p className="text-[10px] text-muted-foreground mt-0.5">Est. time</p>
                    </div>
                  </div>
                </div>
              )}

              {/* Compact summary during upload for large batches */}
              {showSummaryCard && (isUploading || isDone) && (
                <div className="rounded-xl border border-border/60 bg-muted/20 px-4 py-3">
                  <div className="grid grid-cols-4 gap-3 text-center">
                    <div>
                      <p className="text-lg font-bold text-emerald-600 dark:text-emerald-400">{doneCount}</p>
                      <p className="text-[10px] text-muted-foreground">Uploaded</p>
                    </div>
                    <div>
                      <p className="text-lg font-bold text-amber-600 dark:text-amber-400">{duplicateCount}</p>
                      <p className="text-[10px] text-muted-foreground">Skipped</p>
                    </div>
                    <div>
                      <p className="text-lg font-bold text-red-500 dark:text-red-400">{errorCount}</p>
                      <p className="text-[10px] text-muted-foreground">Failed</p>
                    </div>
                    <div>
                      <p className="text-lg font-bold text-muted-foreground">{idleCount}</p>
                      <p className="text-[10px] text-muted-foreground">Queued</p>
                    </div>
                  </div>
                </div>
              )}

              {/* Full file list â€” only when not summary-mode */}
              {!listCollapsed && (
                <div className="space-y-1.5 max-h-[240px] overflow-y-auto pr-0.5">
                  {trackedFiles.map(tf => (
                    <FileRow
                      key={tf.id}
                      tf={tf}
                      onRemove={removeFile}
                      isUploading={isUploading}
                    />
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* â”€â”€ Footer â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */}
        <div className="flex items-center justify-between gap-3 px-6 py-4 border-t bg-muted/30 flex-shrink-0">
          <div className="space-y-1">
            <span className="text-xs text-muted-foreground block">
              {isUploading && `${BATCH_CONCURRENCY} batches running · ${BATCH_SIZE} files each`}
              {!isUploading && !isDone && total > 0 && batchInfo}
              {!isUploading && !isDone && total === 0 && "No files selected yet"}
              {isDone && errorCount === 0 && duplicateCount === 0 && "All files uploaded"}
              {isDone && (errorCount > 0 || duplicateCount > 0) && `${doneCount} of ${total} uploaded`}
            </span>
            {!isUploading && !isDone && total > 0 && (
              <label className="inline-flex items-center gap-2 text-xs text-muted-foreground">
                <input
                  type="checkbox"
                  checked={reviewConfirmed}
                  onChange={(event) => setReviewConfirmed(event.target.checked)}
                  className="h-4 w-4 rounded border-border accent-primary"
                />
                <span>
                  I reviewed selected files and target <span className="font-medium text-foreground">{selectedJobTitle || "job/pool"}</span>.
                </span>
              </label>
            )}
          </div>

          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={handleClose}>
              {isUploading ? "Cancel Upload" : isDone ? "Close" : "Cancel"}
            </Button>

            {!isDone && (
              <Button
                size="sm"
                onClick={handleUpload}
                disabled={!canUpload}
                className={cn(
                  "min-w-[130px]",
                  isPoolUpload && !isUploading
                    ? "bg-emerald-600 hover:bg-emerald-700 text-white"
                    : ""
                )}
              >
                {isUploading ? (
                  <span className="flex items-center gap-2">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    Uploading...
                  </span>
                ) : (
                  <span className="flex items-center gap-2">
                    <Upload className="h-3.5 w-3.5" />
                    {isPoolUpload ? "Add to Pool" : "Upload & Score"}
                    {idleCount > 0 && ` (${idleCount})`}
                  </span>
                )}
              </Button>
            )}

            {isDone && errorCount > 0 && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  setTrackedFiles(prev =>
                    prev.map(f =>
                      f.status === "error"
                        ? { ...f, status: "idle", progress: 0, error: undefined }
                        : f
                    )
                  );
                  setIsDone(false);
                }}
              >
                Retry Failed ({errorCount})
              </Button>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
    </>
  );
}

