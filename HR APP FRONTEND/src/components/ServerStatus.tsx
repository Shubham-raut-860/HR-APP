import { useState, useEffect, useRef } from 'react';
import { Wifi, WifiOff } from 'lucide-react';
import api from '@/services/api';
import { cn } from '@/lib/utils';
import { toast } from 'sonner';

export function ServerStatus() {
  const [isOnline, setIsOnline] = useState<boolean | null>(null);
  // FIX F-2: track previous status via ref so toast transitions work
  // without including isOnline in the useEffect dep array (which caused
  // re-runs and doubled health-checks on every state change).
  const prevOnline = useRef<boolean | null>(null);

  useEffect(() => {
    const checkStatus = async () => {
      try {
        await api.get('/health');
        if (prevOnline.current === false) {
          toast.success("Backend connection restored");
        }
        prevOnline.current = true;
        setIsOnline(true);
      } catch (error) {
        if (prevOnline.current === true) {
          toast.error("Backend connection lost");
        }
        prevOnline.current = false;
        setIsOnline(false);
      }
    };

    // Check immediately
    checkStatus();

    // Poll every 30 seconds
    const interval = setInterval(checkStatus, 30000);
    return () => clearInterval(interval);
  }, []);

  if (isOnline === null) return null;

  return (
    <div className={cn(
      "fixed bottom-4 right-4 px-3 py-1.5 rounded-full text-xs font-medium flex items-center gap-2 shadow-lg transition-all z-50",
      isOnline 
        ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400 border border-green-200 dark:border-green-800" 
        : "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400 border border-red-200 dark:border-red-800"
    )}>
      {isOnline ? (
        <>
          <Wifi className="h-3 w-3" />
          <span>System Online</span>
        </>
      ) : (
        <>
          <WifiOff className="h-3 w-3" />
          <span>Backend Offline</span>
        </>
      )}
    </div>
  );
}
