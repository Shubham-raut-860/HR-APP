import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Bell, BellOff, CheckCheck, Clock, RefreshCw, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import {
  clearAllNotifications,
  dismissNotification,
  getNotifications,
  markAllRead,
  markNotificationRead,
  setSnooze,
  type Notification,
  type NotificationsResponse,
} from "@/services/notifications";
import { SegmentedTabs } from "@/components/ui/segmented-tabs";

const actionableTypes = new Set(["quiz_result", "tag_updated", "shortlisted", "quiz_link", "email_sent"]);
const interviewTypes = new Set(["quiz_link", "quiz_result"]);
const systemTypes = new Set(["system"]);
const snoozeOptions = [
  { label: "30 minutes", getMs: () => 30 * 60 * 1000 },
  { label: "1 hour", getMs: () => 60 * 60 * 1000 },
  { label: "2 hours", getMs: () => 2 * 60 * 60 * 1000 },
  {
    label: "Until tomorrow",
    getMs: () => {
      const target = new Date();
      target.setHours(9, 0, 0, 0);
      target.setDate(target.getDate() + 1);
      return target.getTime() - Date.now();
    },
  },
];

function timeAgo(dateStr: string) {
  const normalized = /(Z|[+-]\d{2}:?\d{2})$/i.test(dateStr.trim()) ? dateStr : `${dateStr}Z`;
  const seconds = Math.floor((Date.now() - new Date(normalized).getTime()) / 1000);
  if (seconds < 60) return "Just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

function getTypeLabel(type: string): string {
  if (interviewTypes.has(type)) return "Interview";
  if (actionableTypes.has(type)) return "Action";
  if (systemTypes.has(type)) return "System";
  return "Update";
}

function getTypeTone(type: string): string {
  if (type === "quiz_result") return "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300";
  if (type === "quiz_link" || type === "shortlisted") return "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300";
  if (type === "tag_updated") return "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300";
  if (systemTypes.has(type)) return "bg-muted text-muted-foreground";
  return "bg-primary/10 text-primary";
}

export default function NotificationsCenter() {
  const [data, setData] = useState<NotificationsResponse>({
    notifications: [],
    unread_count: 0,
    is_snoozed: false,
    snooze_until: null,
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<"all" | "action" | "interview" | "system">("all");

  const fetchData = useCallback(async () => {
    setError(null);
    try {
      const result = await getNotifications();
      setData(result);
    } catch {
      setError("Unable to load notifications right now.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData().catch(() => undefined);
  }, [fetchData]);

  const visible = useMemo(() => {
    if (tab === "all") return data.notifications;
    if (tab === "action") return data.notifications.filter((n) => actionableTypes.has(n.type));
    if (tab === "interview") return data.notifications.filter((n) => interviewTypes.has(n.type));
    if (tab === "system") return data.notifications.filter((n) => systemTypes.has(n.type));
    return data.notifications;
  }, [data.notifications, tab]);

  const counts = useMemo(() => ({
    all: data.notifications.length,
    action: data.notifications.filter((n) => actionableTypes.has(n.type)).length,
    interview: data.notifications.filter((n) => interviewTypes.has(n.type)).length,
    system: data.notifications.filter((n) => systemTypes.has(n.type)).length,
  }), [data.notifications]);
  const tabOptions = useMemo(() => ([
    { value: "all" as const, label: "All", badge: counts.all },
    { value: "action" as const, label: "Action Required", badge: counts.action },
    { value: "interview" as const, label: "Interview/Quiz", badge: counts.interview },
    { value: "system" as const, label: "System", badge: counts.system },
  ]), [counts.all, counts.action, counts.interview, counts.system]);

  const onRead = async (id: string) => {
    setData((d) => ({
      ...d,
      notifications: d.notifications.map((n) => (n.id === id ? { ...n, is_read: true } : n)),
      unread_count: Math.max(0, d.unread_count - 1),
    }));
    await markNotificationRead(id).catch(() => undefined);
  };

  const onDismiss = async (id: string) => {
    setData((d) => ({
      ...d,
      notifications: d.notifications.filter((n) => n.id !== id),
      unread_count: d.notifications.find((n) => n.id === id && !n.is_read)
        ? Math.max(0, d.unread_count - 1)
        : d.unread_count,
    }));
    await dismissNotification(id).catch(() => undefined);
  };

  const onReadAll = async () => {
    setData((d) => ({
      ...d,
      notifications: d.notifications.map((n) => ({ ...n, is_read: true })),
      unread_count: 0,
    }));
    await markAllRead().catch(() => undefined);
  };

  const onClearAll = async () => {
    setData((d) => ({ ...d, notifications: [], unread_count: 0 }));
    await clearAllNotifications().catch(() => undefined);
  };

  const onSnooze = async (getMs: () => number) => {
    const until = new Date(Date.now() + getMs()).toISOString();
    setData((d) => ({ ...d, is_snoozed: true, snooze_until: until }));
    await setSnooze(until).catch(() => undefined);
  };

  const onUnsnooze = async () => {
    setData((d) => ({ ...d, is_snoozed: false, snooze_until: null }));
    await setSnooze(null).catch(() => undefined);
  };

  return (
    <div className="space-y-4 max-w-7xl mx-auto">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-3xl font-bold tracking-tight">Notifications</h2>
          <p className="text-muted-foreground">Unified updates feed across applications, quizzes, interviews, and system events.</p>
        </div>
        <div className="flex w-full items-center gap-2 sm:w-auto">
          <Button size="sm" variant="outline" className="flex-1 sm:flex-none" onClick={() => { setLoading(true); void fetchData(); }}>
            <RefreshCw className="mr-2 h-4 w-4" />Refresh
          </Button>
          <Button size="sm" variant="outline" className="flex-1 sm:flex-none" onClick={onReadAll}>
            <CheckCheck className="mr-2 h-4 w-4" />All read
          </Button>
          <Button size="sm" variant="outline" className="flex-1 sm:flex-none" onClick={onClearAll}>
            <Trash2 className="mr-2 h-4 w-4" />Clear all
          </Button>
          {data.is_snoozed ? (
            <Button size="sm" variant="outline" className="flex-1 sm:flex-none" onClick={onUnsnooze}>
              <Bell className="mr-2 h-4 w-4" />Unsnooze
            </Button>
          ) : (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button size="sm" variant="outline" className="flex-1 sm:flex-none">
                  <Clock className="mr-2 h-4 w-4" />Snooze
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                {snoozeOptions.map((option) => (
                  <DropdownMenuItem key={option.label} onSelect={() => void onSnooze(option.getMs)}>
                    {option.label}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>
      </div>

      {data.is_snoozed && (
        <div className="flex flex-col gap-2 rounded-2xl border border-amber-200 bg-amber-50/70 px-4 py-3 text-sm text-amber-900 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-200 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-2">
            <BellOff className="h-4 w-4 shrink-0" />
            <span>
              Notifications are snoozed{data.snooze_until ? ` until ${new Date(data.snooze_until).toLocaleString()}` : ""}.
            </span>
          </div>
          <Button size="sm" variant="outline" className="rounded-xl bg-background/70" onClick={onUnsnooze}>
            Unsnooze now
          </Button>
        </div>
      )}

      <div className="flex items-center gap-2 flex-wrap">
        <SegmentedTabs value={tab} onChange={setTab} options={tabOptions} size="sm" className="w-full sm:w-auto" />
        {data.unread_count > 0 && <Badge>{data.unread_count} unread</Badge>}
      </div>

      <div className="rounded-2xl border bg-card overflow-hidden">
        {loading ? (
          <div className="p-6 space-y-3">
            {[1, 2, 3, 4].map((row) => (
              <div key={row} className="rounded-2xl border p-4 space-y-2">
                <Skeleton className="h-4 w-1/3" />
                <Skeleton className="h-3 w-5/6" />
                <Skeleton className="h-3 w-1/4" />
              </div>
            ))}
          </div>
        ) : error ? (
          <div className="p-10 text-center text-muted-foreground space-y-3">
            <p>{error}</p>
            <Button variant="outline" onClick={() => { setLoading(true); void fetchData(); }}>
              Retry
            </Button>
          </div>
        ) : visible.length === 0 ? (
          <div className="p-6">
            <EmptyState
              icon={data.is_snoozed ? BellOff : Bell}
              title={data.is_snoozed ? "Notifications are snoozed" : "No notifications in this view"}
              description={data.is_snoozed ? "New updates are paused for now. Unsnooze when you are ready." : "Application, quiz, interview, and system updates will appear here."}
              className="border-0 bg-transparent"
            />
            {tab === "interview" && (
              <Button asChild size="sm" variant="outline" className="rounded-lg">
                <Link to="/candidate/mock-test">Go to Mock Test</Link>
              </Button>
            )}
            {tab === "action" && (
              <Button asChild size="sm" variant="outline" className="rounded-lg">
                <Link to="/candidate/progress">View Application Progress</Link>
              </Button>
            )}
          </div>
        ) : (
          <div className="divide-y">
            {visible.map((n: Notification) => (
              <div key={n.id} className={`p-4 flex items-start justify-between gap-3 ${n.is_read ? "opacity-75" : "bg-primary/5"}`}>
                <div className="min-w-0">
                  <div className="flex items-center gap-2 mb-1.5">
                    {!n.is_read && <span className="h-2 w-2 rounded-full bg-primary shrink-0" />}
                    <span className={`text-sm ${n.is_read ? "font-medium" : "font-semibold"}`}>{n.title}</span>
                    <Badge className={`text-[10px] font-medium px-2 py-0.5 ${getTypeTone(n.type)}`}>{getTypeLabel(n.type)}</Badge>
                  </div>
                  <p className="text-xs text-muted-foreground mt-1">{n.message}</p>
                  <p className="text-[11px] text-muted-foreground mt-2">{timeAgo(n.created_at)}</p>
                </div>
                <div className="flex items-center gap-1">
                  {!n.is_read && <Button size="sm" variant="outline" onClick={() => void onRead(n.id)}>Read</Button>}
                  <Button size="sm" variant="ghost" onClick={() => void onDismiss(n.id)}>Dismiss</Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
