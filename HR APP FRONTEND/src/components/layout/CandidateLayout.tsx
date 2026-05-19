import React, { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { useTheme } from "@/context/ThemeContext";
import { Button } from "@/components/ui/button";
import { NotificationBell } from "@/components/NotificationBell";
import {
  LayoutDashboard,
  Briefcase,
  LineChart,
  Settings,
  LogOut,
  Moon,
  Sun,
  PanelLeftClose,
  PanelLeftOpen,
  Target,
  Sparkles
} from "lucide-react";
import { cn } from "@/lib/utils";

export function CandidateLayout({ children }: { children: React.ReactNode }) {
  const { user, logout } = useAuth();
  const { resolvedTheme, toggleTheme } = useTheme();
  const location = useLocation();
  const navigate = useNavigate();

  const [isCollapsed, setIsCollapsed] = useState(() => {
    return JSON.parse(localStorage.getItem('candidate_sidebar_collapsed') || 'false');
  });

  const toggleSidebar = () => {
    const next = !isCollapsed;
    setIsCollapsed(next);
    localStorage.setItem('candidate_sidebar_collapsed', JSON.stringify(next));
  };

  const handleLogout = () => { logout(); navigate('/login'); };

  const navItems = [
    { label: "My Dashboard", path: "/candidate/dashboard", icon: LayoutDashboard },
    { label: "My Progress",  path: "/candidate/progress",  icon: LineChart       },
    { label: "Browse Jobs",  path: "/candidate/jobs",      icon: Briefcase       },
    { label: "Mock Test",    path: "/candidate/mock-test",    icon: Target          },
    { label: "Career Tools", path: "/candidate/career-tools", icon: Sparkles        },
    { label: "Settings",     path: "/candidate/settings",     icon: Settings        },
  ];

  return (
    <div className="flex h-screen bg-background overflow-hidden selection:bg-primary/10">

      {/* ── SIDEBAR ──────────────────────────────────────────────────────────
          PERF: transition-[width] only — was transition-all which repainted
          every CSS property (border, bg, padding, shadow…) on each frame.   */}
      <aside
        className={cn(
          "flex flex-col shrink-0 border-r border-border/50 bg-card/50 z-20",
          "transition-[width] duration-200 ease-in-out",
          isCollapsed ? "w-[72px]" : "w-60"
        )}
      >
        {/* Brand */}
        <div className="h-16 flex items-center justify-between px-3 border-b border-border/50 shrink-0">
          <div className={cn(
            "flex items-center gap-2.5 overflow-hidden",
            "transition-opacity duration-150",
            isCollapsed ? "opacity-0 pointer-events-none w-0" : "opacity-100"
          )}>
            <div className="h-8 w-8 rounded-lg bg-primary/10 border border-primary/20 text-primary flex items-center justify-center shrink-0">
              <UserIcon className="h-5 w-5" />
            </div>
            <span className="font-bold text-lg tracking-tight whitespace-nowrap">HireAI</span>
          </div>
          <Button
            variant="ghost" size="icon"
            onClick={toggleSidebar}
            className={cn("rounded-full text-muted-foreground hover:text-foreground shrink-0", isCollapsed && "mx-auto")}
          >
            {isCollapsed ? <PanelLeftOpen className="h-5 w-5" /> : <PanelLeftClose className="h-5 w-5" />}
          </Button>
        </div>

        {/* Nav */}
        <nav className="flex-1 p-2.5 space-y-1 overflow-y-auto overflow-x-hidden">
          {navItems.map(({ label, path, icon: Icon }) => {
            const isActive = location.pathname.startsWith(path);
            return (
              <Link
                key={path}
                to={path}
                title={isCollapsed ? label : undefined}
                className={cn(
                  // PERF: transition-colors only — no geometry changes on hover
                  "flex items-center gap-3 px-2.5 py-2.5 rounded-xl transition-colors duration-150",
                  isCollapsed ? "justify-center" : "justify-start",
                  isActive
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                )}
              >
                <Icon className="h-5 w-5 shrink-0" />
                {/* PERF: opacity transition only — width:auto can't be composited */}
                <span className={cn(
                  "font-medium text-sm whitespace-nowrap transition-opacity duration-150",
                  isCollapsed ? "opacity-0 w-0 overflow-hidden" : "opacity-100"
                )}>
                  {label}
                </span>
              </Link>
            );
          })}
        </nav>

        {/* Logout */}
        <div className="p-2.5 border-t border-border/50 shrink-0">
          <button
            onClick={handleLogout}
            title={isCollapsed ? "Log out" : undefined}
            className={cn(
              "flex items-center gap-3 w-full px-2.5 py-2.5 rounded-xl",
              "transition-colors duration-150 text-muted-foreground",
              "hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-900/20 dark:hover:text-red-400",
              isCollapsed ? "justify-center" : "justify-start"
            )}
          >
            <LogOut className="h-5 w-5 shrink-0" />
            <span className={cn(
              "font-medium text-sm whitespace-nowrap transition-opacity duration-150",
              isCollapsed ? "opacity-0 w-0 overflow-hidden" : "opacity-100"
            )}>
              Log out
            </span>
          </button>
        </div>
      </aside>

      {/* ── MAIN CONTENT ─────────────────────────────────────────────────── */}
      <main className="flex-1 flex flex-col min-w-0">

        {/* Header — removed backdrop-blur-xl (expensive CPU filter) */}
        <header className="h-16 shrink-0 flex items-center justify-between px-6 md:px-8 border-b border-border/50 bg-background/95 sticky top-0 z-10">
          <div className="font-medium text-lg text-foreground tracking-tight line-clamp-1">
            Welcome back, {user?.full_name?.trim()?.split(" ")?.[0] || user?.email?.split('@')?.[0] || "Candidate"}
          </div>

          <div className="flex items-center gap-2 md:gap-4 pl-4">
            <NotificationBell />
            <Button
              variant="ghost"
              size="icon"
              className="rounded-full text-muted-foreground transition-transform duration-150 hover:scale-105"
              onClick={toggleTheme}
              aria-label={`Switch to ${resolvedTheme === 'dark' ? 'light' : 'dark'} mode`}
            >
              {resolvedTheme === 'dark' ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
            </Button>

            <div className="flex items-center gap-3 border-l border-border/50 pl-2 md:pl-4 ml-2">
              <div className="h-9 w-9 rounded-full bg-primary/10 flex items-center justify-center text-primary font-bold border border-primary/20 shrink-0">
                {(user?.full_name?.trim()?.charAt(0) || user?.email?.charAt(0) || "C").toUpperCase()}
              </div>
              <div className="hidden md:block text-sm">
                <p className="font-medium leading-none">{user?.full_name?.trim() || user?.email?.split("@")?.[0] || "Candidate"}</p>
                <p className="text-xs text-muted-foreground mt-1.5 capitalize">{user?.role || "Candidate"}</p>
              </div>
            </div>
          </div>
        </header>

        <div className="flex-1 overflow-auto p-6 md:p-8">
          {children}
        </div>
      </main>
    </div>
  );
}

function UserIcon(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg {...props} xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"
      fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2" />
      <circle cx="12" cy="7" r="4" />
    </svg>
  );
}
