import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '@/context/AuthContext';
import { claimQuizMagicLink, getQuizMagicLinkContext, type QuizMagicLinkContext } from '@/services/quiz';
import QuizEngine from '@/pages/QuizEngine';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { clearQuizToken, getQuizToken, setQuizRuntimeToken } from '@/services/tokenStore';

export default function QuizMagicEntry() {
  const navigate = useNavigate();
  const { user, isAuthenticated, loading: authLoading, logout } = useAuth();

  const token = useMemo(() => {
    return getQuizToken();
  }, []);

  const [ctxLoading, setCtxLoading] = useState(true);
  const [ctxData, setCtxData] = useState<QuizMagicLinkContext | null>(null);
  const [ctxError, setCtxError] = useState<string>('');
  const [claiming, setClaiming] = useState(false);
  const [claimed, setClaimed] = useState(false);

  useEffect(() => {
    if (!token) {
      setCtxError('Security Error: No assessment token found in this session.');
      setCtxLoading(false);
      return;
    }
    setQuizRuntimeToken(token);
  }, [token]);

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      if (!token) return;
      setCtxLoading(true);
      setCtxError('');
      try {
        const data = await getQuizMagicLinkContext(token);
        if (cancelled) return;
        if (data.status === 'completed') {
          setCtxError('This assessment is already completed.');
          setCtxLoading(false);
          return;
        }
        setCtxData(data);
      } catch (err: any) {
        if (cancelled) return;
        setCtxError(err?.response?.data?.detail || 'This assessment link is invalid or unavailable.');
      } finally {
        if (!cancelled) setCtxLoading(false);
      }
    };
    run();
    return () => {
      cancelled = true;
    };
  }, [token]);

  useEffect(() => {
    if (!token || authLoading || ctxLoading || ctxError || !ctxData) return;
    if (isAuthenticated) return;

    const redirectPath = `/take-quiz`;
    sessionStorage.setItem('magic_link_redirect', redirectPath);

    const mode = ctxData.has_existing_account ? 'login' : 'signup';
    const next = `/${mode}?role=candidate&redirect=${encodeURIComponent(redirectPath)}`;
    navigate(next, { replace: true });
  }, [token, authLoading, ctxLoading, ctxError, ctxData, isAuthenticated, navigate]);

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      if (!token || authLoading || ctxLoading || ctxError || !ctxData) return;
      if (!isAuthenticated || !user) return;
      if (user.role !== 'candidate') return;
      if (claimed || claiming) return;

      setClaiming(true);
      try {
        await claimQuizMagicLink(token);
        if (!cancelled) {
          setQuizRuntimeToken(token);
          clearQuizToken();
          setClaimed(true);
        }
      } catch (err: any) {
        if (!cancelled) {
          setCtxError(
            err?.response?.data?.detail ||
            'This assessment invite cannot be linked to your account.'
          );
        }
      } finally {
        if (!cancelled) setClaiming(false);
      }
    };
    run();
    return () => {
      cancelled = true;
    };
  }, [token, authLoading, ctxLoading, ctxError, ctxData, isAuthenticated, user, claimed]);

  if (
    ctxLoading ||
    authLoading ||
    (!ctxError && isAuthenticated && user?.role === 'candidate' && (claiming || !claimed))
  ) {
    return (
      <div className="p-12 text-center text-lg animate-pulse text-muted-foreground">
        Preparing your secure assessment session...
      </div>
    );
  }

  if (ctxError) {
    return (
      <div className="min-h-screen bg-muted/30 flex items-center justify-center p-4">
        <Card className="max-w-md w-full shadow-xl">
          <CardHeader>
            <CardTitle>Assessment Access</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-sm text-muted-foreground">{ctxError}</p>
            <Button onClick={() => navigate('/login')} className="w-full">Go to Login</Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (isAuthenticated && user && user.role !== 'candidate') {
    return (
      <div className="min-h-screen bg-muted/30 flex items-center justify-center p-4">
        <Card className="max-w-md w-full shadow-xl">
          <CardHeader>
            <CardTitle>Candidate Account Required</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-sm text-muted-foreground">
              This assessment link is only available for candidate accounts.
              Please sign in with your candidate profile.
            </p>
            <div className="flex gap-2">
              <Button
                variant="outline"
                className="flex-1"
                onClick={() => {
                  logout();
                  navigate('/login');
                }}
              >
                Switch Account
              </Button>
              <Button className="flex-1" onClick={() => navigate('/dashboard')}>
                Back
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (!isAuthenticated) {
    return (
      <div className="p-12 text-center text-lg animate-pulse text-muted-foreground">
        Redirecting to account access...
      </div>
    );
  }

  return <QuizEngine />;
}
