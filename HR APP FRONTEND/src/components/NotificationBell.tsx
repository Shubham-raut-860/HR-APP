import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Bell, BellOff, BellRing, Check, CheckCheck, Trash2, X, ArrowRight, Briefcase, Mail, BrainCircuit, Tag, Trophy, Info, Clock } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuTrigger, DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu';
import {
  getNotifications, markNotificationRead, markAllRead,
  dismissNotification, clearAllNotifications, setSnooze,
  type Notification, type NotificationsResponse,
} from '@/services/notifications';
import { cn } from '@/lib/utils';

// ─── Helpers ──────────────────────────────────────────────────────────────────

const TYPE_META: Record<string, { icon: any; color: string; label: string }> = {
  job_posted:  { icon: Briefcase,    color: 'text-blue-500',    label: 'New Job'       },
  email_sent:  { icon: Mail,         color: 'text-purple-500',  label: 'Email'         },
  quiz_link:   { icon: BrainCircuit, color: 'text-amber-500',   label: 'Assessment'    },
  shortlisted: { icon: CheckCheck,   color: 'text-emerald-500', label: 'Shortlisted'   },
  tag_updated: { icon: Tag,          color: 'text-orange-500',  label: 'Status Update' },
  quiz_result: { icon: Trophy,       color: 'text-yellow-500',  label: 'Quiz Result'   },
  system:      { icon: Info,         color: 'text-slate-400',   label: 'System'        },
};

const SNOOZE_OPTIONS = [
  { label: '30 minutes',    getMs: () => 30 * 60 * 1000 },
  { label: '1 hour',        getMs: () => 60 * 60 * 1000 },
  { label: '2 hours',       getMs: () => 2 * 60 * 60 * 1000 },
  // Computed at click time — not at module load — so the target is always
  // tomorrow 9am relative to when the user actually clicks, not when the
  // JS bundle was first parsed.
  { label: 'Until tomorrow', getMs: () => {
    const t = new Date(); t.setHours(9, 0, 0, 0); t.setDate(t.getDate() + 1);
    return t.getTime() - Date.now();
  }},
];

const timeAgo = (dateStr: string) => {
  // Normalize: if the string has no timezone offset or Z suffix, append Z so
  // JS parses it as UTC rather than local time.  Prevents "12h ago" for a
  // notification that was just created when the user is in a non-UTC timezone.
  const normalized = /(Z|[+-]\d{2}:?\d{2})$/i.test(dateStr.trim()) ? dateStr : dateStr + 'Z';
  const seconds = Math.floor((Date.now() - new Date(normalized).getTime()) / 1000);
  if (seconds < 60)  return 'Just now';
  if (seconds < 3600) return `${Math.floor(seconds/60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds/3600)}h ago`;
  return `${Math.floor(seconds/86400)}d ago`;
};

// ─── NotificationItem ─────────────────────────────────────────────────────────

function getAction(notif: Notification): { label: string; href: string } | null {
  if (notif.type === 'quiz_result' && notif.related_id) return { label: 'View result', href: `/candidates/${notif.related_id}` };
  if (notif.type === 'tag_updated' && notif.related_id) return { label: 'View candidate', href: `/candidates/${notif.related_id}` };
  if (notif.type === 'shortlisted' && notif.related_id) return { label: 'View candidate', href: `/candidates/${notif.related_id}` };
  if (notif.type === 'quiz_link' && notif.related_id) return { label: 'View job', href: `/jobs/${notif.related_id}` };
  return null;
}

const NotifItem = React.memo(function NotifItem({ notif, onRead, onDismiss, onNavigate }: { key?: React.Key; notif: Notification; onRead: (id: string) => void; onDismiss: (id: string) => void; onNavigate: (href: string) => void }) {
  const meta = TYPE_META[notif.type] || TYPE_META.system;
  const Icon = meta.icon;
  const action = getAction(notif);

  const handleClick = () => {
    if (!notif.is_read) onRead(notif.id);
    // FIX F-23: Navigate to the linked entity when clicking a notification
    if (action) onNavigate(action.href);
  };

  return (
    <div
      className={cn(
        'group flex items-start gap-3 px-3 py-3 cursor-pointer transition-all border-b border-border/30 last:border-0',
        notif.is_read ? 'opacity-70 hover:opacity-100 hover:bg-muted/30' : 'bg-primary/5 hover:bg-primary/10',
      )}
      onClick={handleClick}
    >
      {/* Icon */}
      <div className={cn('mt-0.5 shrink-0 h-8 w-8 rounded-full flex items-center justify-center', notif.is_read ? 'bg-muted/50' : 'bg-background border border-border/50')}>
        <Icon className={cn('h-4 w-4', meta.color)} />
      </div>

      {/* Content */}
      <div className='flex-1 min-w-0'>
        <div className='flex items-start justify-between gap-2'>
          <p className={cn('text-sm leading-snug', notif.is_read ? 'font-normal text-foreground/80' : 'font-semibold text-foreground')}>
            {notif.title}
          </p>
          <div className='flex items-center gap-1 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity'>
            {!notif.is_read && (
              <button
                onClick={(e) => { e.stopPropagation(); onRead(notif.id); }}
                className='h-5 w-5 rounded flex items-center justify-center text-muted-foreground hover:text-emerald-500 hover:bg-emerald-50 dark:hover:bg-emerald-900/20 transition-colors'
                title='Mark as read'
              >
                <Check className='h-3 w-3' />
              </button>
            )}
            <button
              onClick={(e) => { e.stopPropagation(); onDismiss(notif.id); }}
              className='h-5 w-5 rounded flex items-center justify-center text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors'
              title='Dismiss'
            >
              <X className='h-3 w-3' />
            </button>
          </div>
        </div>
        <p className='text-xs text-muted-foreground line-clamp-2 mt-0.5 leading-relaxed'>{notif.message}</p>
        <div className='flex items-center gap-2 mt-1'>
          <Badge variant='outline' className={cn('text-[10px] px-1.5 py-0 font-normal border-0 bg-transparent', meta.color)}>
            {meta.label}
          </Badge>
          <span className='text-[10px] text-muted-foreground'>{timeAgo(notif.created_at)}</span>
          {!notif.is_read && <span className='h-1.5 w-1.5 rounded-full bg-primary shrink-0 ml-auto' />}
          {/* FIX F-23: Show navigate arrow if notification has an action */}
          {action && <span className='ml-auto flex items-center gap-0.5 text-[10px] text-primary font-medium'><ArrowRight className='h-2.5 w-2.5' />{action.label}</span>}
        </div>
      </div>
    </div>
  );
});

// ─── Main Component ───────────────────────────────────────────────────────────

interface NotificationBellProps {
  className?: string;
}

export function NotificationBell({ className }: NotificationBellProps) {
  const navigate = useNavigate();
  const [data, setData] = useState<NotificationsResponse>({
    notifications: [], unread_count: 0, is_snoozed: false, snooze_until: null,
  });
  const [tab, setTab] = useState<'all' | 'action'>('all');
  const [showSnoozeMenu, setShowSnoozeMenu] = useState(false);
  const [open, setOpen] = useState(false);
  const snoozeRef = useRef<HTMLDivElement>(null);
  const fetchInFlightRef = useRef(false);

  const fetchNotifs = useCallback(async () => {
    if (fetchInFlightRef.current) return;
    fetchInFlightRef.current = true;
    try {
      const res = await getNotifications();
      setData(res);
    } catch { /* silent */ }
    finally {
      fetchInFlightRef.current = false;
    }
  }, []);

  useEffect(() => {
    fetchNotifs();

    // Poll every 30 s, but pause when the tab is hidden — mirrors the
    // Candidates.tsx pattern. 12 s was too aggressive (5 API calls/min per tab).
    const POLL_MS = 30_000;
    let intervalId: ReturnType<typeof setInterval> | null = null;

    const start = () => {
      if (intervalId) return;
      intervalId = setInterval(fetchNotifs, POLL_MS);
    };

    const stop = () => {
      if (intervalId) { clearInterval(intervalId); intervalId = null; }
    };

    const onVisibility = () => {
      if (document.visibilityState === 'visible') {
        fetchNotifs(); // immediate refresh on tab focus
        start();
      } else {
        stop();
      }
    };

    start();
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      stop();
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [fetchNotifs]);

  // Close snooze menu on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (snoozeRef.current && !snoozeRef.current.contains(e.target as Node)) {
        setShowSnoozeMenu(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const handleRead = useCallback(async (id: string) => {
    setData(d => ({
      ...d,
      notifications: d.notifications.map(n => n.id === id ? { ...n, is_read: true } : n),
      unread_count: Math.max(0, d.unread_count - 1),
    }));
    await markNotificationRead(id).catch(() => {});
  }, []);

  const handleDismiss = useCallback(async (id: string) => {
    setData(d => ({
      ...d,
      notifications: d.notifications.filter(n => n.id !== id),
      unread_count: d.notifications.find(n => n.id === id && !n.is_read) ? Math.max(0, d.unread_count - 1) : d.unread_count,
    }));
    await dismissNotification(id).catch(() => {});
  }, []);

  const handleMarkAllRead = async () => {
    setData(d => ({
      ...d,
      notifications: d.notifications.map(n => ({ ...n, is_read: true })),
      unread_count: 0,
    }));
    await markAllRead().catch(() => {});
  };

  const handleClearAll = async () => {
    setData(d => ({ ...d, notifications: [], unread_count: 0 }));
    await clearAllNotifications().catch(() => {});
  };

  const handleSnooze = async (getMs: () => number) => {
    const until = new Date(Date.now() + getMs()).toISOString();
    setData(d => ({ ...d, is_snoozed: true, snooze_until: until }));
    setShowSnoozeMenu(false);
    await setSnooze(until).catch(() => {});
  };

  const handleUnsnooze = async () => {
    setData(d => ({ ...d, is_snoozed: false, snooze_until: null }));
    await setSnooze(null).catch(() => {});
  };

  const actionableTypes = new Set(['quiz_result', 'tag_updated', 'shortlisted', 'quiz_link']);
  const actionCount = React.useMemo(
    () => data.notifications.filter(n => actionableTypes.has(n.type) && !n.is_read).length,
    [data.notifications]
  );
  const visible = React.useMemo(
    () => (tab === 'action'
      ? data.notifications.filter(n => actionableTypes.has(n.type))
      : data.notifications),
    [tab, data.notifications]
  );

  const handleNavigate = useCallback((href: string) => {
    setOpen(false);
    navigate(href);
  }, [navigate]);

  const openCenter = useCallback(() => {
    setOpen(false);
    const isCandidatePath = window.location.pathname.startsWith('/candidate/');
    navigate(isCandidatePath ? '/candidate/notifications' : '/notifications');
  }, [navigate]);

  const isSnoozed = data.is_snoozed;

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger asChild>
        <Button variant='ghost' size='icon' className={cn('relative transition-all hover:bg-secondary', className)}>
          {isSnoozed
            ? <BellOff className='h-5 w-5 text-muted-foreground' />
            : data.unread_count > 0
              ? <BellRing className='h-5 w-5 text-primary animate-[wiggle_0.5s_ease-in-out]' />
              : <Bell className='h-5 w-5' />
          }
          {!isSnoozed && data.unread_count > 0 && (
            <span className='absolute -top-0.5 -right-0.5 min-w-[18px] h-[18px] rounded-full bg-destructive text-destructive-foreground text-[10px] font-bold flex items-center justify-center px-1 border-2 border-background'>
              {data.unread_count > 99 ? '99+' : data.unread_count}
            </span>
          )}
        </Button>
      </DropdownMenuTrigger>

      <DropdownMenuContent align='end' className='w-[380px] p-0 shadow-2xl rounded-2xl overflow-hidden' onCloseAutoFocus={e => e.preventDefault()}>

        {/* Header */}
        <div className='flex items-center justify-between px-4 py-3 border-b border-border/50 bg-muted/20'>
          <div className='flex items-center gap-2'>
            <span className='font-bold text-base'>Notifications</span>
            {data.unread_count > 0 && (
              <Badge variant='destructive' className='text-[10px] px-1.5 py-0.5 rounded-full'>
                {data.unread_count} new
              </Badge>
            )}
          </div>
          <div className='flex items-center gap-1'>
            {data.unread_count > 0 && (
              <button
                onClick={handleMarkAllRead}
                className='text-xs text-muted-foreground hover:text-foreground px-2 py-1 rounded-lg hover:bg-muted transition-colors flex items-center gap-1'
                title='Mark all as read'
              >
                <CheckCheck className='h-3.5 w-3.5' /> All read
              </button>
            )}
            <button
              onClick={handleClearAll}
              className='h-7 w-7 rounded-lg flex items-center justify-center text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors'
              title='Clear all'
            >
              <Trash2 className='h-4 w-4' />
            </button>
          </div>
        </div>

        {/* Tabs */}
        <div className='flex border-b border-border/30 bg-muted/10'>
          {(['all', 'action'] as const).map(t => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={cn(
                'flex-1 text-xs py-2 font-medium transition-colors capitalize',
                tab === t ? 'text-primary border-b-2 border-primary' : 'text-muted-foreground hover:text-foreground'
              )}
            >
              {t === 'all' ? `All (${data.notifications.length})` : (
                <>Needs action {actionCount > 0 && <span className='ml-1 bg-primary text-primary-foreground rounded-full text-[9px] px-1.5 py-0.5 font-bold'>{actionCount}</span>}</>
              )}
            </button>
          ))}
        </div>

        {/* Notification list */}
        <div className='max-h-[360px] overflow-y-auto'>
          {visible.length === 0 ? (
            <div className='p-8 text-center text-muted-foreground flex flex-col items-center gap-3'>
              {isSnoozed
                ? <><BellOff className='h-9 w-9 opacity-25' /><p className='font-medium text-sm'>Notifications snoozed</p><p className='text-xs'>You're in DND mode. No new pings.</p></>
                : tab === 'action' ? <><Bell className='h-9 w-9 opacity-20' /><p className='font-medium text-sm'>Nothing needs attention</p><p className='text-xs'>Quiz results and status updates will appear here.</p></> : <><Bell className='h-9 w-9 opacity-20' /><p className='font-medium text-sm'>No notifications yet</p><p className='text-xs'>Activities will appear here in real-time.</p></>
              }
            </div>
          ) : (
            visible.map(n => (
              <NotifItem key={n.id} notif={n} onRead={handleRead} onDismiss={handleDismiss} onNavigate={handleNavigate} />
            ))
          )}
        </div>

        <DropdownMenuSeparator className='m-0' />

        {/* Footer actions */}
        <div className='p-2 flex gap-2 bg-muted/20 relative' ref={snoozeRef}>
          <button
            onClick={() => isSnoozed ? handleUnsnooze() : setShowSnoozeMenu(v => !v)}
            className={cn(
              'flex-1 flex items-center justify-center gap-1.5 text-xs py-1.5 rounded-xl border transition-all font-medium',
              isSnoozed
                ? 'bg-primary/10 border-primary/20 text-primary hover:bg-primary/20'
                : 'bg-background border-border hover:bg-muted text-muted-foreground hover:text-foreground'
            )}
          >
            {isSnoozed
              ? <><Bell className='h-3.5 w-3.5' /> Un-snooze</>
              : <><Clock className='h-3.5 w-3.5' /> Snooze</>
            }
          </button>
          <button
            onClick={openCenter}
            className='flex-1 flex items-center justify-center gap-1.5 text-xs py-1.5 rounded-xl border bg-background border-border hover:bg-muted text-muted-foreground hover:text-foreground transition-all font-medium'
          >
            <ArrowRight className='h-3.5 w-3.5' /> Open Center
          </button>

          {/* Snooze duration picker */}
          {showSnoozeMenu && !isSnoozed && (
            <div className='absolute bottom-full left-2 mb-1 bg-popover border border-border rounded-xl shadow-xl py-1 z-50 min-w-[180px]'>
              {SNOOZE_OPTIONS.map(opt => (
                <button
                  key={opt.label}
                  onClick={() => handleSnooze(opt.getMs)}
                  className='w-full text-left text-sm px-4 py-2 hover:bg-muted transition-colors first:rounded-t-xl last:rounded-b-xl'
                >
                  {opt.label}
                </button>
              ))}
            </div>
          )}
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
