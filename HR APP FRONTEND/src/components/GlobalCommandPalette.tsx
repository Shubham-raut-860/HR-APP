import { useEffect, useMemo, useState } from "react";
import type { ComponentType, KeyboardEvent as ReactKeyboardEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  BarChart3,
  Bell,
  Bot,
  Briefcase,
  Command,
  FileText,
  LayoutDashboard,
  Search,
  Settings,
  Sparkles,
  Target,
  Users,
} from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { useAuth } from "@/context/AuthContext";
import { cn } from "@/lib/utils";

type CommandRole = "hr" | "admin" | "candidate";

type CommandItem = {
  id: string;
  title: string;
  description: string;
  path: string;
  roles: CommandRole[];
  keywords: string[];
  shortcut?: string;
  icon: ComponentType<{ className?: string }>;
};

const COMMANDS: CommandItem[] = [
  {
    id: "hr-dashboard",
    title: "Open recruiter dashboard",
    description: "Hiring overview, funnel, and recent activity",
    path: "/dashboard",
    roles: ["hr", "admin"],
    keywords: ["home", "today", "overview", "funnel"],
    shortcut: "Alt+1",
    icon: LayoutDashboard,
  },
  {
    id: "hr-jobs",
    title: "Manage jobs",
    description: "Create, edit, publish, and inspect job posts",
    path: "/jobs",
    roles: ["hr", "admin"],
    keywords: ["jd", "job", "create", "publish"],
    shortcut: "Alt+2",
    icon: Briefcase,
  },
  {
    id: "hr-candidates",
    title: "Review candidates",
    description: "Pipeline, comparison, scoring, and quick actions",
    path: "/candidates",
    roles: ["hr", "admin"],
    keywords: ["resume", "shortlist", "compare", "pipeline"],
    shortcut: "Alt+3",
    icon: Users,
  },
  {
    id: "hr-analytics",
    title: "View analytics",
    description: "Hiring metrics, rankings, and skill gaps",
    path: "/analytics",
    roles: ["hr", "admin"],
    keywords: ["metrics", "reports", "rankings"],
    shortcut: "Alt+4",
    icon: BarChart3,
  },
  {
    id: "candidate-dashboard",
    title: "Open my dashboard",
    description: "Application summary, profile strength, and recommendations",
    path: "/candidate/dashboard",
    roles: ["candidate"],
    keywords: ["home", "profile", "recommendations"],
    shortcut: "Alt+1",
    icon: LayoutDashboard,
  },
  {
    id: "candidate-progress",
    title: "Track my progress",
    description: "Application timeline and status updates",
    path: "/candidate/progress",
    roles: ["candidate"],
    keywords: ["timeline", "status", "applications"],
    shortcut: "Alt+2",
    icon: FileText,
  },
  {
    id: "candidate-coach",
    title: "Open candidate coach",
    description: "Get read-only guidance from your applications and resumes",
    path: "/candidate/coach",
    roles: ["candidate"],
    keywords: ["coach", "assistant", "next steps", "applications"],
    shortcut: "Alt+6",
    icon: Bot,
  },
  {
    id: "candidate-jobs",
    title: "Browse jobs",
    description: "Find open roles and apply with your resume vault",
    path: "/candidate/jobs",
    roles: ["candidate"],
    keywords: ["roles", "apply", "job board"],
    shortcut: "Alt+3",
    icon: Briefcase,
  },
  {
    id: "candidate-mock-test",
    title: "Practice mock test",
    description: "Prepare for assessment rounds",
    path: "/candidate/mock-test",
    roles: ["candidate"],
    keywords: ["quiz", "exam", "practice"],
    shortcut: "Alt+4",
    icon: Target,
  },
  {
    id: "candidate-career-tools",
    title: "Open career tools",
    description: "Resume builder, enhancer, cover letter, and career analysis",
    path: "/candidate/career-tools",
    roles: ["candidate"],
    keywords: ["resume", "cover letter", "builder", "ai"],
    shortcut: "Alt+5",
    icon: Sparkles,
  },
  {
    id: "notifications",
    title: "Open notifications",
    description: "Read hiring updates and actionable alerts",
    path: "/notifications",
    roles: ["hr", "admin"],
    keywords: ["alerts", "bell", "updates"],
    shortcut: "Alt+N",
    icon: Bell,
  },
  {
    id: "candidate-notifications",
    title: "Open notifications",
    description: "Read candidate updates and reminders",
    path: "/candidate/notifications",
    roles: ["candidate"],
    keywords: ["alerts", "bell", "updates"],
    shortcut: "Alt+N",
    icon: Bell,
  },
  {
    id: "settings",
    title: "Open settings",
    description: "Profile, email, security, and preferences",
    path: "/settings",
    roles: ["hr", "admin"],
    keywords: ["profile", "security", "email"],
    shortcut: "Alt+S",
    icon: Settings,
  },
  {
    id: "candidate-settings",
    title: "Open settings",
    description: "Profile, resume vault, KYC, and preferences",
    path: "/candidate/settings",
    roles: ["candidate"],
    keywords: ["profile", "resume", "kyc", "security"],
    shortcut: "Alt+S",
    icon: Settings,
  },
];

const SHORTCUT_ROUTES: Record<string, Partial<Record<CommandRole, string>>> = {
  "1": { hr: "/dashboard", admin: "/dashboard", candidate: "/candidate/dashboard" },
  "2": { hr: "/jobs", admin: "/jobs", candidate: "/candidate/progress" },
  "3": { hr: "/candidates", admin: "/candidates", candidate: "/candidate/jobs" },
  "4": { hr: "/analytics", admin: "/analytics", candidate: "/candidate/mock-test" },
  "5": { candidate: "/candidate/career-tools", hr: "/settings", admin: "/settings" },
  "6": { candidate: "/candidate/coach" },
  n: { hr: "/notifications", admin: "/notifications", candidate: "/candidate/notifications" },
  s: { hr: "/settings", admin: "/settings", candidate: "/candidate/settings" },
};

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName.toLowerCase();
  return tag === "input" || tag === "textarea" || tag === "select" || target.isContentEditable;
}

export function openCommandPalette() {
  window.dispatchEvent(new Event("jobora:open-command-palette"));
}

export function GlobalCommandPalette() {
  const { user, isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);

  const role = user?.role as CommandRole | undefined;

  const availableCommands = useMemo(() => {
    if (!role) return [];
    return COMMANDS.filter((item) => item.roles.includes(role));
  }, [role]);

  const filteredCommands = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return availableCommands;
    return availableCommands.filter((item) => {
      const haystack = [item.title, item.description, item.path, ...item.keywords].join(" ").toLowerCase();
      return haystack.includes(q);
    });
  }, [availableCommands, query]);

  useEffect(() => {
    setActiveIndex(0);
  }, [query, open]);

  useEffect(() => {
    const openHandler = () => {
      if (isAuthenticated) setOpen(true);
    };
    window.addEventListener("jobora:open-command-palette", openHandler);
    return () => window.removeEventListener("jobora:open-command-palette", openHandler);
  }, [isAuthenticated]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (!isAuthenticated || !role) return;

      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen((value) => !value);
        return;
      }

      if (event.altKey && !event.ctrlKey && !event.metaKey && !isTypingTarget(event.target)) {
        const route = SHORTCUT_ROUTES[event.key.toLowerCase()]?.[role];
        if (route) {
          event.preventDefault();
          navigate(route);
        }
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [isAuthenticated, navigate, role]);

  const runCommand = (item: CommandItem) => {
    setOpen(false);
    setQuery("");
    if (location.pathname !== item.path) navigate(item.path);
  };

  const onDialogKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((value) => Math.min(value + 1, Math.max(0, filteredCommands.length - 1)));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((value) => Math.max(0, value - 1));
    } else if (event.key === "Enter" && filteredCommands[activeIndex]) {
      event.preventDefault();
      runCommand(filteredCommands[activeIndex]);
    }
  };

  if (!isAuthenticated || !role) return null;

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="max-w-2xl overflow-hidden p-0" onKeyDown={onDialogKeyDown}>
        <DialogHeader className="border-b px-4 py-3">
          <DialogTitle className="flex items-center gap-2 text-base">
            <Command className="h-4 w-4" /> Command Palette
          </DialogTitle>
        </DialogHeader>
        <div className="border-b px-4 py-3">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              autoFocus
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search pages, actions, and shortcuts..."
              className="h-11 rounded-xl pl-9"
            />
          </div>
        </div>
        <div className="max-h-[420px] overflow-y-auto p-2">
          {filteredCommands.length === 0 ? (
            <div className="px-4 py-10 text-center text-sm text-muted-foreground">
              No commands found. Try dashboard, jobs, candidates, quiz, or settings.
            </div>
          ) : (
            filteredCommands.map((item, index) => {
              const Icon = item.icon;
              const active = index === activeIndex;
              return (
                <button
                  key={item.id}
                  type="button"
                  onMouseEnter={() => setActiveIndex(index)}
                  onClick={() => runCommand(item)}
                  className={cn(
                    "flex w-full items-center gap-3 rounded-xl px-3 py-3 text-left transition-colors",
                    active ? "bg-primary text-primary-foreground" : "hover:bg-muted"
                  )}
                >
                  <span className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-lg", active ? "bg-white/15" : "bg-muted")}>
                    <Icon className="h-4 w-4" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-semibold">{item.title}</span>
                    <span className={cn("block truncate text-xs", active ? "text-primary-foreground/75" : "text-muted-foreground")}>{item.description}</span>
                  </span>
                  {item.shortcut && (
                    <Badge variant={active ? "secondary" : "outline"} className="shrink-0 rounded-md text-[10px]">
                      {item.shortcut}
                    </Badge>
                  )}
                </button>
              );
            })
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2 border-t bg-muted/20 px-4 py-2 text-[11px] text-muted-foreground">
          <span>Ctrl/Cmd+K opens search</span>
          <span>Alt+1-5 jumps between core pages</span>
          <span>Alt+N notifications</span>
          <span>Enter opens selected item</span>
        </div>
      </DialogContent>
    </Dialog>
  );
}
