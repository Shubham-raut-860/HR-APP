import * as React from "react";
import { cn } from "@/lib/utils";

export type SegmentedTabOption<T extends string> = {
  value: T;
  label: string;
  icon?: React.ElementType;
  badge?: React.ReactNode;
};

type SegmentedTabsProps<T extends string> = {
  value: T;
  onChange: (value: T) => void;
  options: ReadonlyArray<SegmentedTabOption<T>>;
  className?: string;
  size?: "sm" | "md";
};

export function SegmentedTabs<T extends string>({
  value,
  onChange,
  options,
  className,
  size = "md",
}: SegmentedTabsProps<T>) {
  const tabPadding =
    size === "sm"
      ? "px-2.5 py-1.5 text-xs"
      : "px-2.5 py-1.5 text-xs sm:px-4 sm:py-2 sm:text-sm";

  return (
    <div
      className={cn(
        "inline-flex max-w-full flex-wrap items-center gap-1 rounded-2xl border border-border/50 bg-muted/20 p-1.5",
        className
      )}
      role="tablist"
      aria-orientation="horizontal"
    >
      {options.map((option) => {
        const Icon = option.icon;
        const active = value === option.value;
        return (
          <button
            key={option.value}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(option.value)}
            className={cn(
              "inline-flex items-center gap-1.5 whitespace-nowrap rounded-xl font-medium transition-colors",
              tabPadding,
              active
                ? "bg-primary text-primary-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground hover:bg-muted"
            )}
          >
            {Icon ? <Icon className={size === "sm" ? "h-3.5 w-3.5" : "h-3.5 w-3.5 sm:h-4 sm:w-4"} /> : null}
            <span>{option.label}</span>
            {option.badge ? (
              <span
                className={cn(
                  "rounded-full px-1.5 py-0.5 text-[10px] font-semibold tabular-nums",
                  active ? "bg-white/20 text-primary-foreground" : "bg-primary/10 text-primary"
                )}
              >
                {option.badge}
              </span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}
