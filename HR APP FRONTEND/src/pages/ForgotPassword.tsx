/**
 * ForgotPassword.tsx
 *
 * Accepts an email address and calls POST /auth/forgot-password.
 * Always shows a success message regardless of whether the email exists
 * (matches the backend's constant-time response to prevent enumeration).
 */
import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { forgotPassword } from '@/services/auth';
import { toast } from 'sonner';
import { ArrowLeft, Mail, Loader2 } from 'lucide-react';

export default function ForgotPassword() {
  const [email, setEmail] = useState('');
  const [emailTouched, setEmailTouched] = useState(false);
  const [loading, setLoading] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const trimmedEmail = email.trim();
  const emailError = !trimmedEmail
    ? emailTouched ? 'Enter the email address for your account.' : ''
    : /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmedEmail)
      ? ''
      : 'Enter a valid email address, for example [email-redacted].';

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setEmailTouched(true);
    if (emailError) return;
    setLoading(true);
    try {
      await forgotPassword(trimmedEmail);
      setSubmitted(true);
    } catch (err: any) {
      const msg =
        err?.response?.data?.detail ||
        err?.message ||
        'Could not send reset link right now. Please try again.';
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  };

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
          <h1 className="text-2xl font-bold tracking-tight">Reset your password</h1>
          <p className="text-muted-foreground text-sm">
            Enter the email address associated with your account and we'll send you a secure reset link.
          </p>
        </div>

        {submitted ? (
          <div className="rounded-xl border border-green-200 dark:border-green-900 bg-green-50 dark:bg-green-950/30 p-4 text-sm text-green-800 dark:text-green-300 space-y-1">
            <p className="font-medium">Check your inbox</p>
            <p>
              If <strong>{email}</strong> is registered, you'll receive a password
              reset link within a few minutes.
            </p>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4" noValidate>
            <div className="space-y-1.5">
              <label htmlFor="forgot-email" className="text-sm font-medium">
                Email address
              </label>
              <div className="relative">
                <Mail className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <input
                  id="forgot-email"
                  type="email"
                  required
                  autoFocus
                  placeholder="[email-redacted]"
                  value={email}
                  onBlur={() => setEmailTouched(true)}
                  onChange={(e) => setEmail(e.target.value)}
                  aria-invalid={!!emailError}
                  aria-describedby={emailError ? 'forgot-email-error' : undefined}
                  className="w-full rounded-xl border border-input bg-background pl-10 pr-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-primary/30 transition"
                />
              </div>
              {emailError ? (
                <p id="forgot-email-error" className="text-xs font-medium text-destructive">
                  {emailError}
                </p>
              ) : null}
            </div>
            <button
              type="submit"
              disabled={loading || !trimmedEmail}
              className="w-full rounded-xl bg-zinc-900 dark:bg-zinc-50 text-white dark:text-black py-2.5 text-sm font-semibold hover:bg-zinc-800 dark:hover:bg-white disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2 transition-all"
            >
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              {loading ? 'Sending...' : 'Send reset link'}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
