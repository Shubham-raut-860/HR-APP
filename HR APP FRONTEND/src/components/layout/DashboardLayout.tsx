import React, { useState, useEffect } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { useTheme } from "@/context/ThemeContext";
import { Button } from "@/components/ui/button";
import { NotificationBell } from "@/components/NotificationBell";
import {
  LayoutDashboard,
  Briefcase,
  Users,
  BarChart,
  Settings,
  LogOut,
  Moon,
  Sun,
  PanelLeftClose,
  PanelLeftOpen
} from "lucide-react";
import { cn } from "@/lib/utils";
import { getUntaggedMetrics } from "@/services/analytics";

export function DashboardLayout({ children }: { children: React.ReactNode }) {
  const { user, logout } = useAuth();
  const { theme, setTheme } = useTheme();
  const location = useLocation();
  const navigate = useNavigate();

  const [isCollapsed, setIsCollapsed] = useState(() => {
    return JSON.parse(localStorage.getItem('hr_sidebar_collapsed') || 'false');
  });
  const [untaggedCount, setUntaggedCount] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    const load = async () => {
      try {
        const data = await getUntaggedMetrics(controller.signal);
        setUntaggedCount(data.untagged_count || 0);
      } catch (err: any) {
        const isCancelled = err?.name === "AbortError" || err?.code === "ERR_CANCELED";
        const isTransientNetwork = err?.code === "ERR_NETWORK" || err?.message === "Network Error";
        if (!isCancelled && !isTransientNetwork) {
          console.error("Polling error:", err);
        }
      }
    };
    load();
    const id = setInterval(load, 60_000);
    return () => { controller.abort(); clearInterval(id); };
  }, []);

  const toggleSidebar = () => {
    const next = !isCollapsed;
    setIsCollapsed(next);
    localStorage.setItem('hr_sidebar_collapsed', JSON.stringify(next));
  };

  const handleLogout = () => { logout(); navigate('/login'); };

  const navItems = [
    { label: "Dashboard", path: "/dashboard",  icon: LayoutDashboard },
    { label: "Jobs",      path: "/jobs",        icon: Briefcase       },
    { label: "Candidates",path: "/candidates",  icon: Users           },
    { label: "Analytics", path: "/analytics",   icon: BarChart        },
    { label: "Settings",  path: "/settings",    icon: Settings        },
  ];

  return (
    <div className="flex h-screen bg-background overflow-hidden selection:bg-primary/10">

      {/* ── SIDEBAR ──────────────────────────────────────────────────────────
          PERF: Only transition `width` — `transition-all` was repainting every
          CSS property on every frame, stalling the main thread. Width change
          is the only geometric shift; everything else snaps instantly.       */}
      <aside
        className={cn(
          "flex flex-col shrink-0 border-r border-border/50 bg-card/50 z-20",
          // transition-[width] hits the compositor, not the layout engine
          "transition-[width] duration-200 ease-in-out",
          isCollapsed ? "w-[72px]" : "w-60"
        )}
      >
        {/* Brand */}
        <div className="h-16 flex items-center justify-between px-3 border-b border-border/50 shrink-0">
          {/* PERF: opacity-only transition — never triggers layout recalc   */}
          <div className={cn(
            "flex items-center gap-2.5 overflow-hidden",
            "transition-opacity duration-150",
            isCollapsed ? "opacity-0 pointer-events-none w-0" : "opacity-100"
          )}>
            <div className="h-8 w-8 rounded-lg bg-primary text-primary-foreground flex items-center justify-center shrink-0">
              <Briefcase className="h-4 w-4" />
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
                  // PERF: transition-colors only — no layout properties change on hover
                  "flex items-center gap-3 px-2.5 py-2.5 rounded-xl transition-colors duration-150",
                  isCollapsed ? "justify-center" : "justify-start",
                  isActive
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                )}
              >
                <Icon className="h-5 w-5 shrink-0" />
                <span className={cn(
                  "font-medium text-sm whitespace-nowrap transition-opacity duration-150 flex-1",
                  isCollapsed ? "opacity-0 w-0 overflow-hidden" : "opacity-100"
                )}>
                  {label}
                </span>
                {!isCollapsed && label === 'Candidates' && untaggedCount > 0 && (
                  <span className="h-[18px] min-w-[18px] px-1 rounded-full bg-destructive text-destructive-foreground text-[10px] font-bold flex items-center justify-center">
                    {untaggedCount > 99 ? '99+' : untaggedCount}
                  </span>
                )}
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

        {/* Header
            PERF: removed backdrop-blur-xl — blur filters are rasterised on
            the CPU and repaint on every scroll event. bg-background/95 gives
            the same frosted appearance at zero GPU cost.                     */}
        <header className="h-16 shrink-0 flex items-center justify-between px-6 md:px-8 border-b border-border/50 bg-background/95 sticky top-0 z-10">
          <div className="font-medium text-lg text-foreground tracking-tight line-clamp-1">
            Welcome back, {user?.full_name?.trim()?.split(' ')?.[0] || user?.email?.split('@')?.[0] || "User"}
          </div>

          <div className="flex items-center gap-2 md:gap-4 pl-4">
            <NotificationBell className="rounded-full" />
            <Button variant="ghost" size="icon" className="rounded-full text-muted-foreground" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>
              {theme === 'dark' ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
            </Button>

            <div className="flex items-center gap-3 border-l border-border/50 pl-2 md:pl-4 ml-2">
              <div className="h-9 w-9 rounded-full bg-primary/10 flex items-center justify-center text-primary font-bold border border-primary/20 shrink-0">
                {(user?.full_name?.trim()?.charAt(0) || user?.email?.charAt(0) || "U").toUpperCase()}
              </div>
              <div className="hidden md:block text-sm">
                <p className="font-medium leading-none">{user?.full_name?.trim() || user?.email?.split('@')?.[0] || "User"}</p>
                <p className="text-xs text-muted-foreground mt-1.5 capitalize">
                  {user?.role === 'hr' ? 'Recruiter' : user?.role === 'admin' ? 'Admin' : 'Candidate'}
                </p>
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
