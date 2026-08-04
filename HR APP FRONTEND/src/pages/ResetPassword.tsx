/**
 * ResetPassword.tsx
 *
 * Reads the JWT reset token from the URL path (/reset-password/:token),
 * accepts a new password, and calls POST /auth/reset-password.
 */
import React, { useEffect, useState } from 'react';
import { Link, useParams, useNavigate } from 'react-router-dom';
import { resetPassword, verifyResetPasswordToken } from '@/services/auth';
import { toast } from 'sonner';
import { ArrowLeft, Lock, Eye, EyeOff, Loader2, Check } from 'lucide-react';

type ResetTokenVerification = { valid: boolean; message?: string };

const verificationCache = new Map<string, Promise<ResetTokenVerification>>();

const getResetTokenErrorMessage = (err: unknown): string => {
  const maybeError = err as { response?: { data?: { detail?: string } } };
  return maybeError?.response?.data?.detail || 'Invalid or expired reset link.';
};

const verifyResetTokenOnce = (token: string): Promise<ResetTokenVerification> => {
  const cached = verificationCache.get(token);
  if (cached) return cached;

  const verification = verifyResetPasswordToken(token)
    .then((): ResetTokenVerification => ({ valid: true }))
    .catch((err: unknown): ResetTokenVerification => ({
      valid: false,
      message: getResetTokenErrorMessage(err),
    }));
  verification.finally(() => verificationCache.delete(token));
  verificationCache.set(token, verification);
  return verification;
};

export default function ResetPassword() {
  const { token } = useParams<{ token: string }>();
  const navigate = useNavigate();
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [showPw, setShowPw] = useState(false);
  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState(false);
  const [tokenStatus, setTokenStatus] = useState<'checking' | 'valid' | 'invalid'>(
    token ? 'checking' : 'invalid'
  );
  const [tokenMessage, setTokenMessage] = useState('Verifying reset link...');

  const hasUpper = /[A-Z]/.test(password);
  const hasSpecial = /[^a-zA-Z0-9]/.test(password);
  const hasMinLen = password.length >= 8;
  const matches = password === confirm && confirm.length > 0;
  const canSubmit =
    tokenStatus === 'valid' &&
    hasUpper &&
    hasSpecial &&
    hasMinLen &&
    matches &&
    !loading;

  useEffect(() => {
    let cancelled = false;
    const verify = async () => {
      if (!token) {
        if (!cancelled) {
          setTokenStatus('invalid');
          setTokenMessage('This reset link is missing a token. Request a new link.');
        }
        return;
      }
      setTokenStatus('checking');
      setTokenMessage('Verifying reset link...');
      const result = await verifyResetTokenOnce(token);
      if (cancelled) return;

      if (result.valid) {
        setTokenStatus('valid');
        setTokenMessage('Reset link verified.');
      } else {
        setTokenStatus('invalid');
        setTokenMessage(result.message || 'Invalid or expired reset link.');
      }
    };
    void verify();
    return () => {
      cancelled = true;
    };
  }, [token]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit || !token || tokenStatus !== 'valid') return;
    setLoading(true);
    try {
      await resetPassword(token, password);
      setSuccess(true);
      toast.success('Password updated successfully');
      setTimeout(() => navigate('/login'), 2500);
    } catch (err: any) {
      const msg = err?.response?.data?.detail || 'Reset failed — the link may have expired.';
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  };

  if (!token) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background px-4">
        <div className="text-center space-y-3">
          <p className="text-lg font-semibold">Invalid reset link</p>
          <p className="text-muted-foreground text-sm">
            This link is missing the reset token. Please request a new one.
          </p>
          <Link to="/forgot-password" className="text-sm text-primary hover:underline">
            Request a new link
          </Link>
        </div>
      </div>
    );
  }

  if (tokenStatus === 'checking') {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background px-4">
        <div className="w-full max-w-md rounded-xl border bg-card p-6 text-center space-y-3">
          <Loader2 className="h-5 w-5 animate-spin mx-auto text-muted-foreground" />
          <p className="font-medium">Verifying reset link</p>
          <p className="text-sm text-muted-foreground">{tokenMessage}</p>
        </div>
      </div>
    );
  }

  if (tokenStatus === 'invalid') {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background px-4">
        <div className="w-full max-w-md rounded-xl border bg-card p-6 text-center space-y-3">
          <p className="text-lg font-semibold">Reset link is not valid</p>
          <p className="text-sm text-muted-foreground">{tokenMessage}</p>
          <Link to="/forgot-password" className="text-sm text-primary hover:underline">
            Request a new reset link
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="w-full max-w-md space-y-6">
        <Link
          to="/login"
          className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          <ArrowLeft className="h-4 w-4" /> Back to login
        </Link>

        <div className="space-y-2">
          <h1 className="text-2xl font-bold tracking-tight">Set a new password</h1>
          <p className="text-muted-foreground text-sm">
            Choose a strong password with at least 8 characters, one uppercase letter, and one special character.
          </p>
        </div>

        {success ? (
          <div className="rounded-xl border border-green-200 dark:border-green-900 bg-green-50 dark:bg-green-950/30 p-4 text-sm text-green-800 dark:text-green-300 space-y-1">
            <p className="font-medium flex items-center gap-1.5"><Check className="h-4 w-4" /> Password updated</p>
            <p>Redirecting you to login…</p>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            {/* New password */}
            <div className="space-y-1.5">
              <label htmlFor="reset-password" className="text-sm font-medium">
                New password
              </label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <input
                  id="reset-password"
                  type={showPw ? 'text' : 'password'}
                  required
                  autoFocus
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full rounded-xl border border-input bg-background pl-10 pr-10 py-2.5 text-sm outline-none focus:ring-2 focus:ring-primary/30 transition"
                />
                <button
                  type="button"
                  tabIndex={-1}
                  onClick={() => setShowPw(!showPw)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                >
                  {showPw ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
              {/* Strength indicators */}
              {password.length > 0 && (
                <ul className="mt-1.5 space-y-0.5 text-xs">
                  <li className={hasMinLen ? 'text-green-600 dark:text-green-400' : 'text-muted-foreground'}>
                    {hasMinLen ? '✓' : '○'} At least 8 characters
                  </li>
                  <li className={hasUpper ? 'text-green-600 dark:text-green-400' : 'text-muted-foreground'}>
                    {hasUpper ? '✓' : '○'} One uppercase letter
                  </li>
                  <li className={hasSpecial ? 'text-green-600 dark:text-green-400' : 'text-muted-foreground'}>
                    {hasSpecial ? '✓' : '○'} One special character
                  </li>
                </ul>
              )}
            </div>

            {/* Confirm password */}
            <div className="space-y-1.5">
              <label htmlFor="reset-confirm" className="text-sm font-medium">
                Confirm password
              </label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <input
                  id="reset-confirm"
                  type={showPw ? 'text' : 'password'}
                  required
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  className="w-full rounded-xl border border-input bg-background pl-10 pr-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-primary/30 transition"
                />
              </div>
              {confirm.length > 0 && !matches && (
                <p className="text-xs text-red-500">Passwords do not match</p>
              )}
            </div>

            <button
              type="submit"
              disabled={!canSubmit}
              className="w-full rounded-xl bg-zinc-900 dark:bg-zinc-50 text-white dark:text-black py-2.5 text-sm font-semibold hover:bg-zinc-800 dark:hover:bg-white disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2 transition-all"
            >
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              {loading ? 'Updating…' : 'Update password'}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
