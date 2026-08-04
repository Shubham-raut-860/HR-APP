import { Info } from "lucide-react";
import { cn } from "@/lib/utils";

interface InfoHintProps {
  label: string;
  description: string;
  side?: "left" | "right";
  className?: string;
}

export function InfoHint({ label, description, side = "right", className }: InfoHintProps) {
  return (
    <span className={cn("group relative inline-flex", className)}>
      <button
        type="button"
        aria-label={label}
        className="inline-flex h-5 w-5 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <Info className="h-3.5 w-3.5" />
      </button>
      <span
        role="tooltip"
        className={cn(
          "pointer-events-none absolute top-6 z-50 w-56 rounded-xl border bg-popover px-3 py-2 text-left text-xs font-normal leading-relaxed text-popover-foreground opacity-0 shadow-xl transition-opacity group-hover:opacity-100 group-focus-within:opacity-100",
          side === "right" ? "left-0" : "right-0",
        )}
      >
        {description}
      </span>
    </span>
  );
}
