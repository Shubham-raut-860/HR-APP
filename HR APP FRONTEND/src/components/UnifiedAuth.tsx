/**
 * UnifiedAuth.tsx
 *
 * Shared split-screen authentication UI used by both Login.tsx and Signup.tsx.
 * – Left pane: form fields (email / password / full name) wired to AuthContext
 * – Right pane: cinematic role image that is ALWAYS dark-themed (bg-zinc-950)
 *   so it renders perfectly in both light AND dark mode without washout.
 * - Public signup is candidate-only; HR/admin accounts are provisioned via admin flow.
 */
import React, { useState, useEffect } from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '@/context/AuthContext';
import { register } from '@/services/auth';
import { toast } from 'sonner';
import { Sparkles, Check, X, Loader2 } from 'lucide-react';

type Role = 'candidate' | 'hr';
type Mode = 'login' | 'signup';

interface Props {
  initialMode: Mode;
}

// ── Tiny inline primitives so we don't break existing shadcn components ───────

const Btn = ({
  children,
  className = '',
  variant = 'primary',
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary' }) => (
  <button
    className={[
      'px-4 py-2 rounded-xl font-semibold text-sm transition-all duration-200 flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed',
      variant === 'primary'
        ? 'bg-zinc-900 dark:bg-zinc-50 text-white dark:text-black hover:bg-zinc-800 dark:hover:bg-white'
        : 'bg-white dark:bg-transparent border border-black/10 dark:border-white/10 text-zinc-900 dark:text-zinc-50 hover:bg-zinc-50 dark:hover:bg-white/5',
      className,
    ].join(' ')}
    {...props}
  >
    {children}
  </button>
);

const Field = ({
  label,
  error,
  children,
}: {
  label: string;
  error?: string;
  children: React.ReactNode;
}) => (
  <div className="space-y-1.5">
    <label className="text-xs font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
      {label}
    </label>
    {children}
    {error && <p className="text-xs text-rose-500 mt-1">{error}</p>}
  </div>
);

const StyledInput = (props: React.InputHTMLAttributes<HTMLInputElement>) => (
  <input
    className="w-full bg-white dark:bg-zinc-950 border border-black/10 dark:border-white/10 rounded-xl px-3 py-2.5 text-sm text-zinc-900 dark:text-zinc-50 placeholder:text-zinc-400 dark:placeholder:text-zinc-500 focus:outline-none focus:border-zinc-400 dark:focus:border-white/30 focus:ring-1 focus:ring-zinc-300 dark:focus:ring-white/20 transition-all duration-200"
    {...props}
  />
);

// ── Image panels ──────────────────────────────────────────────────────────────

const CANDIDATE_IMG = '/candidate_auth.png';

const RECRUITER_IMG = '/recruiter_auth.png';

function ImagePanel({ role, reducedMotion }: { role: Role; reducedMotion: boolean }) {
  const isCandidate = role === 'candidate';
  return (
    <AnimatePresence mode="wait">
      <motion.div
        key={role}
        initial={reducedMotion ? false : { opacity: 0, x: 24 }}
        animate={{ opacity: 1, x: 0 }}
        exit={reducedMotion ? { opacity: 0 } : { opacity: 0, x: -24 }}
        transition={{ duration: reducedMotion ? 0.12 : 0.24, ease: [0.23, 1, 0.32, 1] }}
        className="absolute inset-0 flex flex-col"
      >
        {/*
          Use natural styling in light mode, and a rich darkened styling in dark mode.
        */}
        <div className="absolute inset-0 bg-zinc-100 dark:bg-zinc-950">
          <img
            src={isCandidate ? CANDIDATE_IMG : RECRUITER_IMG}
            alt={isCandidate ? 'Candidate' : 'Recruiter'}
            loading="eager"
            decoding="async"
            className="w-full h-full object-cover transition-opacity duration-500 opacity-100 dark:opacity-45 dark:grayscale"
            onError={(e) => {
              // Fallback if CDN is unreachable or image is removed
              (e.target as HTMLImageElement).style.display = 'none';
            }}
          />
          {/* Bottom gradient to ensure text contrast */}
          <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-black/20 to-transparent dark:from-zinc-950/95 dark:via-zinc-950/30" />
        </div>

        <div className="relative z-10 mt-auto p-12 pb-14">
          <h3 className="text-2xl font-bold tracking-tight text-zinc-50 mb-3">
            {isCandidate ? 'Welcome, Candidate!' : 'Welcome, Hiring Partner!'}
          </h3>
          <p className="text-zinc-300 font-light text-sm leading-relaxed">
            {isCandidate
              ? "Let's build your future. Discover roles tailored to your unique skills and aspirations."
              : 'Discover top talent. Leverage AI-driven insights to build your dream team faster.'}
          </p>
        </div>
      </motion.div>
    </AnimatePresence>
  );
}

// ── Password strength meter ───────────────────────────────────────────────────

function PasswordStrength({ password }: { password: string }) {
  // Early return BEFORE computing score to avoid running regex on empty string
  if (!password) return null;

  let score = 0;
  if (password.length > 8) score++;
  if (/[A-Z]/.test(password)) score++;
  if (/[0-9]/.test(password)) score++;
  if (/[^A-Za-z0-9]/.test(password)) score++;

  const strong = score >= 3;

  return (
    <div className="mt-2 space-y-1.5">
      <div className="flex gap-1.5 h-1">
        {[1, 2, 3, 4].map((level) => (
          <div
            key={level}
            className={`flex-1 rounded-full transition-colors duration-500 ${
              score >= level
                ? score <= 2
                  ? 'bg-amber-500'
                  : 'bg-emerald-500'
                : 'bg-black/10 dark:bg-white/10'
            }`}
          />
        ))}
      </div>
      <p className="text-[10px] font-medium text-zinc-500 dark:text-zinc-400 flex items-center gap-1.5">
        {strong ? (
          <Check className="w-3 h-3 text-emerald-500" />
        ) : (
          <X className="w-3 h-3 text-amber-500" />
        )}
        {strong ? 'Strong password' : 'Use uppercase, numbers and symbols for a stronger password'}
      </p>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export default function UnifiedAuth({ initialMode }: Props) {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { login } = useAuth();
  const prefersReducedMotion = useReducedMotion();

  // Derive initial role from ?role= param (supports the landing page CTAs)
  const paramRole = searchParams.get('role');
  const [role, setRole] = useState<Role>(
    paramRole === 'candidate' ? 'candidate' : paramRole === 'hr' ? 'hr' : 'candidate',
  );
  const [mode, setMode] = useState<Mode>(initialMode);

  // Form state
  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [emailError, setEmailError] = useState('');
  const [loading, setLoading] = useState(false);

  // Pre-fill email from magic-link ?email= param
  useEffect(() => {
    const emailParam = searchParams.get('email');
    if (emailParam) {
      setEmail(emailParam);
      setRole('candidate');
    }
  }, [searchParams]);

  // Keep mode in sync when the parent route changes (Login ↔ Signup)
  useEffect(() => {
    setMode(initialMode);
  }, [initialMode]);

  const validateEmail = (v: string) => {
    setEmail(v);
    const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    setEmailError(v && !re.test(v) ? 'Please enter a valid email address' : '');
  };

  const toggleMode = () => {
    const next: Mode = mode === 'login' ? 'signup' : 'login';
    setMode(next);
    setFirstName('');
    setLastName('');
    setEmail('');
    setPassword('');
    setEmailError('');
    const preserved = new URLSearchParams();
    const keepKeys = ['role', 'email', 'redirect'];
    for (const key of keepKeys) {
      const value = searchParams.get(key);
      if (value) preserved.set(key, value);
    }
    const path = next === 'login' ? '/login' : '/signup';
    const search = preserved.toString();
    navigate(search ? `${path}?${search}` : path, { replace: true });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (emailError) return;
    setLoading(true);

    try {
      if (mode === 'signup') {
        const fullName = `${firstName} ${lastName}`.trim();
        // register() throws an Axios error — extract detail here before AuthContext wraps it
        try {
          await register(fullName, email, password, role);
        } catch (regError: any) {
          const detail = regError?.response?.data?.detail;
          let regMessage = 'Registration failed. Please check your details.';
          if (typeof detail === 'string') {
            regMessage = detail;
          } else if (Array.isArray(detail) && detail[0]?.msg) {
            // FastAPI 422: flatten pydantic validation errors into a readable string
            regMessage = detail
              .map((err: any) => {
                const field = String(err.loc?.slice(-1) ?? '');
                const cleanMsg = err.msg.replace('Value error, ', '');
                const displayField = field ? field.charAt(0).toUpperCase() + field.slice(1) : '';
                return displayField ? `${displayField}: ${cleanMsg}` : cleanMsg;
              })
              .join(' · ');
          } else if (regError?.message) {
            regMessage = regError.message;
          }
          toast.error(regMessage);
          return; // stop — do not attempt login if registration failed
        }
      }

      // login() is from AuthContext — it re-throws as new Error(message string)
      // so error.message is the correct place to read, not error.response.data.detail
      const user = await login(email.trim(), password);

      // Login mode: no role enforcement. Backend determines the user's actual role.
      // Simply route to the correct dashboard based on what the server returned.
      toast.success(mode === 'signup' ? 'Account created — welcome!' : 'Welcome back!');

      // Respect magic-link redirect — validate to prevent open redirects.
      const rawRedirect =
        searchParams.get('redirect') || sessionStorage.getItem('magic_link_redirect');
      // Only allow relative paths (starts with /) and block protocol-based URLs.
      const redirectTarget =
        rawRedirect && rawRedirect.startsWith('/') && !rawRedirect.includes('://')
          ? rawRedirect
          : null;
      if (redirectTarget) {
        sessionStorage.removeItem('magic_link_redirect');
        navigate(redirectTarget);
      } else if (user.role === 'candidate') {
        navigate('/candidate/dashboard');
      } else {
        navigate('/dashboard');
      }
    } catch (error: any) {
      // This catch handles login() failures only (registration errors are handled above)
      // AuthContext.login() always throws new Error(message), so use error.message
      const message =
        error?.message ||
        (mode === 'login' ? 'Invalid credentials. Please try again.' : 'Something went wrong.');
      toast.error(message);
    } finally {
      setLoading(false);
    }
  };

  const isSubmitDisabled =
    loading ||
    !!emailError ||
    !email ||
    !password ||
    (mode === 'signup' && (!firstName || !lastName));

  return (
    <div className="min-h-screen relative flex items-center justify-center p-4 transition-colors duration-300 bg-background overflow-x-hidden">
      {/* Premium Atmospheric Glow Background */}
      <div className="absolute inset-0 z-0 pointer-events-none">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_20%_25%,rgba(99,102,241,0.12),transparent_40%),radial-gradient(circle_at_80%_75%,rgba(59,130,246,0.10),transparent_42%),linear-gradient(to_bottom,transparent,rgba(0,0,0,0.03))] dark:bg-[radial-gradient(circle_at_20%_25%,rgba(99,102,241,0.16),transparent_40%),radial-gradient(circle_at_80%_75%,rgba(59,130,246,0.12),transparent_42%),linear-gradient(to_bottom,transparent,rgba(255,255,255,0.02))]" />
      </div>

      <motion.div
        initial={prefersReducedMotion ? false : { opacity: 0, y: 16 }}
        animate={prefersReducedMotion ? undefined : { opacity: 1, y: 0 }}
        transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1] }}
        className="w-full max-w-5xl grid grid-cols-1 md:grid-cols-2 bg-white/90 dark:bg-black/75 backdrop-blur-sm border border-black/10 dark:border-white/10 rounded-[2rem] overflow-hidden shadow-2xl min-h-[680px] relative z-10"
      >
        {/* ── Left: Form pane ─────────────────────────────────────────────── */}
        <div className="p-8 md:p-12 flex flex-col justify-center relative z-10 bg-transparent">
          {/* Logo */}
          <div
            className="flex items-center gap-2 mb-10 cursor-pointer group w-fit"
            onClick={() => navigate('/')}
          >
            <div className="w-9 h-9 bg-zinc-900 dark:bg-zinc-50 rounded-lg flex items-center justify-center group-hover:scale-105 transition-transform">
              <Sparkles className="w-5 h-5 text-white dark:text-black" />
            </div>
            <span className="text-xl font-bold tracking-tight text-zinc-900 dark:text-zinc-50">
              HireAI
            </span>
          </div>

          {/* Heading */}
          <div className="mb-8">
            <h2 className="text-2xl font-bold tracking-tight text-zinc-900 dark:text-zinc-50 mb-1">
              {mode === 'signup' ? 'Create an account' : 'Welcome back'}
            </h2>
            <p className="text-sm text-zinc-500 dark:text-zinc-400">
              {mode === 'signup'
                ? 'Enter your details to get started.'
                : 'Sign in to your account to continue.'}
            </p>
          </div>

          {/* Form */}
          <form onSubmit={handleSubmit} className="space-y-4">
            {mode === 'signup' && (
              <div className="grid grid-cols-2 gap-3">
                <Field label="First Name">
                  <StyledInput
                    placeholder=""
                    value={firstName}
                    onChange={(e) => setFirstName(e.target.value)}
                    required
                  />
                </Field>
                <Field label="Last Name">
                  <StyledInput
                    placeholder=""
                    value={lastName}
                    onChange={(e) => setLastName(e.target.value)}
                    required
                  />
                </Field>
              </div>
            )}

            <Field label="Email Address" error={emailError}>
              <StyledInput
                type="email"
                placeholder=""
                value={email}
                onChange={(e) => validateEmail(e.target.value)}
                required
              />
            </Field>

            <Field label="Password">
              <div>
                <div className="flex justify-between items-center mb-1.5">
                  <span /> {/* spacer */}
                  {mode === 'login' && (
                    <button
                      type="button"
                      className="text-xs font-medium text-zinc-500 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-50 hover:underline"
                      onClick={() => navigate('/forgot-password')}
                    >
                      Forgot password?
                    </button>
                  )}
                </div>
                <StyledInput
                  type="password"
                  placeholder=""
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  minLength={mode === 'signup' ? 8 : undefined}
                  required
                />
                {mode === 'signup' && <PasswordStrength password={password} />}
              </div>
            </Field>

            <Btn type="submit" className="w-full h-12 text-sm mt-2" disabled={isSubmitDisabled}>
              {loading ? (
                <><Loader2 className="w-4 h-4 animate-spin" /> Processing…</>
              ) : mode === 'signup' ? (
                'Create Account'
              ) : (
                'Sign In'
              )}
            </Btn>
          </form>

          {/* Toggle login / signup */}
          <div className="mt-8 text-center">
            <p className="text-sm text-zinc-500 dark:text-zinc-400">
              {mode === 'signup' ? 'Already have an account?' : "Don't have an account?"}{' '}
              <button
                type="button"
                onClick={toggleMode}
                className="font-bold text-zinc-900 dark:text-zinc-50 hover:underline transition-colors"
              >
                {mode === 'signup' ? 'Sign in' : 'Create account'}
              </button>
            </p>
          </div>
        </div>

        {/* ── Right: Image pane ────────────────────────────────────────────── */}
        {/*
          Intentionally always dark (bg-zinc-950) so the cinematic image
          never "washes out" regardless of the app's light/dark theme.
        */}
        <div className="hidden md:block relative bg-zinc-950 overflow-hidden border-l border-black/10 dark:border-white/10">
          <ImagePanel role={role} reducedMotion={!!prefersReducedMotion} />
        </div>
      </motion.div>
    </div>
  );
}
