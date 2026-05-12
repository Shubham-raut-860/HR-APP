import React from "react";
import { X, CheckCircle2, XCircle, Copy } from "lucide-react";
import { cn } from "@/lib/utils";

export type FileStatus = "idle" | "uploading" | "done" | "error" | "duplicate";

export interface TrackedFile {
  id: string;
  file: File;
  status: FileStatus;
  progress: number;
  error?: string;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function FileStatusIcon({ status, progress }: { status: FileStatus; progress: number }) {
  if (status === "uploading") {
    const r = 8;
    const circ = 2 * Math.PI * r;
    return (
      <div className="relative h-5 w-5 flex-shrink-0">
        <svg className="absolute inset-0 -rotate-90" viewBox="0 0 20 20">
          <circle cx="10" cy="10" r={r} fill="none" stroke="currentColor"
            strokeWidth="2" className="text-muted-foreground/20" />
          <circle cx="10" cy="10" r={r} fill="none" stroke="currentColor"
            strokeWidth="2.5" strokeLinecap="round"
            strokeDasharray={`${circ}`}
            strokeDashoffset={`${circ * (1 - progress / 100)}`}
            className="text-blue-500 transition-all duration-100"
          />
        </svg>
      </div>
    );
  }
  if (status === "done")
    return <CheckCircle2 className="h-5 w-5 flex-shrink-0 text-emerald-500" />;
  if (status === "duplicate")
    return <Copy className="h-5 w-5 flex-shrink-0 text-amber-500" />;
  if (status === "error")
    return <XCircle className="h-5 w-5 flex-shrink-0 text-red-500" />;
  return <div className="h-5 w-5 flex-shrink-0 rounded-full border-2 border-muted-foreground/25" />;
}

export function FileRow({
  tf, onRemove, isUploading,
}: {
  key?: React.Key;
  tf: TrackedFile;
  onRemove: (id: string) => void;
  isUploading: boolean;
}) {
  const ext = tf.file.name.split(".").pop()?.toUpperCase().slice(0, 4) ?? "FILE";

  return (
    <div className={cn(
      "group h-[52px] flex items-center gap-2.5 px-3 rounded-lg border transition-colors duration-200 overflow-hidden",
      tf.status === "done"      && "border-emerald-200 bg-emerald-50/50 dark:border-emerald-800 dark:bg-emerald-950/20",
      tf.status === "duplicate" && "border-amber-200 bg-amber-50/40 dark:border-amber-800 dark:bg-amber-950/20",
      tf.status === "error"     && "border-red-200 bg-red-50/40 dark:border-red-800 dark:bg-red-950/20",
      tf.status === "uploading" && "border-blue-200 bg-blue-50/40 dark:border-blue-800 dark:bg-blue-950/20",
      tf.status === "idle"      && "border-border bg-muted/30 hover:bg-muted/50",
    )}>
      <div className={cn(
        "flex items-center justify-center h-8 w-8 rounded-md shrink-0 text-[10px] font-bold tracking-tight",
        tf.status === "done"        ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/50 dark:text-emerald-300"
        : tf.status === "duplicate" ? "bg-amber-100 text-amber-700 dark:bg-amber-900/50 dark:text-amber-300"
        : tf.status === "error"     ? "bg-red-100 text-red-600 dark:bg-red-900/50 dark:text-red-400"
        : tf.status === "uploading" ? "bg-blue-100 text-blue-600 dark:bg-blue-900/50 dark:text-blue-400"
        : "bg-muted text-muted-foreground",
      )}>
        {ext}
      </div>

      <div className="flex-1 min-w-0 flex flex-col justify-center gap-0.5 overflow-hidden">
        <div className="relative overflow-hidden">
          <p className="text-sm font-medium leading-none whitespace-nowrap"
             style={{ maskImage: "linear-gradient(to right, black 70%, transparent 100%)",
                      WebkitMaskImage: "linear-gradient(to right, black 70%, transparent 100%)" }}>
            {tf.file.name}
          </p>
        </div>

        <div className="flex items-center gap-1.5 overflow-hidden">
          {tf.status === "uploading" && (
            <>
              <div className="flex-1 h-1 rounded-full bg-blue-100 dark:bg-blue-900/30 overflow-hidden">
                <div
                  className="h-full rounded-full bg-blue-500 transition-[width] duration-100 ease-out"
                  style={{ width: `${tf.progress}%` }}
                />
              </div>
              <span className="text-[10px] text-blue-500 font-semibold tabular-nums shrink-0">
                {tf.progress}%
              </span>
            </>
          )}
          {tf.status === "idle" && (
            <span className="text-[10px] text-muted-foreground leading-none">
              {formatBytes(tf.file.size)}
            </span>
          )}
          {tf.status === "done" && (
            <span className="text-[10px] text-emerald-600 dark:text-emerald-400 font-medium leading-none">
              Uploaded
            </span>
          )}
          {tf.status === "duplicate" && (
            <span className="text-[10px] text-amber-600 dark:text-amber-400 font-medium leading-none">
              Already uploaded — skipped
            </span>
          )}
          {tf.status === "error" && (
            <span className="text-[10px] text-red-500 leading-tight line-clamp-2" title={tf.error}>
              {tf.error ?? "Upload failed"}
            </span>
          )}
        </div>
      </div>

      <div className="shrink-0 w-6 flex items-center justify-center">
        {!isUploading && tf.status === "idle" ? (
          <button
            onClick={() => onRemove(tf.id)}
            className="opacity-0 group-hover:opacity-100 transition-opacity p-0.5 rounded hover:bg-muted"
            aria-label={`Remove ${tf.file.name}`}
          >
            <X className="h-3.5 w-3.5 text-muted-foreground" />
          </button>
        ) : (
          <FileStatusIcon status={tf.status} progress={tf.progress} />
        )}
      </div>
    </div>
  );
}
