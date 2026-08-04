import React, { useEffect, useMemo, useState } from "react";
import { motion, useReducedMotion } from "framer-motion";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { register } from "@/services/auth";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  ArrowRight,
  Briefcase,
  Check,
  Eye,
  EyeOff,
  Loader2,
  LockKeyhole,
  Mail,
  ShieldCheck,
  UserRound,
  X,
} from "lucide-react";

type Role = "candidate" | "hr";
type Mode = "login" | "signup";

interface Props {
  initialMode: Mode;
}

const roleContent: Record<Role, {
  label: string;
  shortLabel: string;
  title: string;
  subtitle: string;
}> = {
  candidate: {
    label: "Candidate workspace",
    shortLabel: "Candidate",
    title: "Welcome back",
    subtitle: "Track jobs, quiz links, results, and recruiter updates from one workspace.",
  },
  hr: {
    label: "Recruiter workspace",
    shortLabel: "Recruiter",
    title: "Welcome back",
    subtitle: "Manage jobs, candidates, quizzes, analytics, and hiring decisions clearly.",
  },
};

function LogoMark({ className = "" }: { className?: string }) {
  return (
    <div className={`flex h-9 w-9 items-center justify-center rounded-xl bg-primary text-primary-foreground ${className}`}>
      <Briefcase className="h-4 w-4" />
    </div>
  );
}

function Field({
  label,
  htmlFor,
  error,
  action,
  children,
}: {
  label: string;
  htmlFor?: string;
  error?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-3">
        <label htmlFor={htmlFor} className="text-xs font-semibold text-muted-foreground">{label}</label>
        {action}
      </div>
      {children}
      {error && <p className="text-xs font-medium text-destructive">{error}</p>}
    </div>
  );
}

function InputShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="relative flex h-12 items-center rounded-2xl border border-input bg-background shadow-sm transition focus-within:ring-2 focus-within:ring-ring/20">
      {children}
    </div>
  );
}

function StyledInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className="h-full min-w-0 flex-1 rounded-2xl bg-transparent px-3 text-sm font-medium text-foreground placeholder:text-muted-foreground focus:outline-none"
      {...props}
    />
  );
}

function PasswordStrength({ password }: { password: string }) {
  if (!password) return null;

  let score = 0;
  if (password.length > 8) score++;
  if (/[A-Z]/.test(password)) score++;
  if (/[0-9]/.test(password)) score++;
  if (/[^A-Za-z0-9]/.test(password)) score++;

  const strong = score >= 3;

  return (
    <div className="mt-2 space-y-1.5">
      <div className="flex h-1 gap-1.5">
        {[1, 2, 3, 4].map((level) => (
          <div
            key={level}
            className={`flex-1 rounded-full transition-colors ${
              score >= level ? (score <= 2 ? "bg-amber-500" : "bg-emerald-500") : "bg-muted"
            }`}
          />
        ))}
      </div>
      <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
        {strong ? <Check className="h-3 w-3 text-emerald-500" /> : <X className="h-3 w-3 text-amber-500" />}
        {strong ? "Strong password" : "Use uppercase, numbers, and symbols for a stronger password"}
      </p>
    </div>
  );
}

function RoleToggle({ role, setRole }: { role: Role; setRole: (role: Role) => void }) {
  const items: Array<{ role: Role; icon: typeof UserRound }> = [
    { role: "candidate", icon: UserRound },
    { role: "hr", icon: Briefcase },
  ];

  return (
    <div className="grid grid-cols-2 gap-1 rounded-2xl border border-border bg-muted/40 p-1">
      {items.map(({ role: itemRole, icon: Icon }) => {
        const selected = role === itemRole;
        return (
          <button
            key={itemRole}
            type="button"
            aria-pressed={selected}
            onClick={() => setRole(itemRole)}
            className={`flex items-center justify-center gap-2 rounded-xl px-3 py-2 text-sm font-medium transition-colors ${
              selected ? "bg-primary text-primary-foreground shadow-sm" : "text-muted-foreground hover:bg-card hover:text-foreground"
            }`}
          >
            <Icon className="h-4 w-4" />
            {roleContent[itemRole].shortLabel}
          </button>
        );
      })}
    </div>
  );
}

function WorkspacePreview({ role }: { role: Role }) {
  const content = roleContent[role];
  const imageSrc = "/candidate_auth.png";

  return (
    <div className="hidden min-h-[640px] p-3 lg:block">
      <div className="relative h-full overflow-hidden rounded-[1.8rem] border border-border bg-zinc-950">
        <img
          src={imageSrc}
          alt={content.label}
          className="h-full w-full object-cover"
          loading="eager"
          decoding="async"
        />
      </div>
    </div>
  );
}

export default function UnifiedAuth({ initialMode }: Props) {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { login } = useAuth();
  const prefersReducedMotion = useReducedMotion();

  const paramRole = searchParams.get("role");
  const [role, setRole] = useState<Role>(
    paramRole === "candidate" ? "candidate" : paramRole === "hr" ? "hr" : "candidate",
  );
  const [mode, setMode] = useState<Mode>(initialMode);

  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [emailError, setEmailError] = useState("");
  const [loading, setLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  const content = roleContent[role];
  const formTitle = mode === "signup" ? "Create your Jobora account" : content.title;
  const formSubtitle = useMemo(() => {
    if (mode === "signup" && role === "hr") return "Create a recruiter workspace for job posts, candidate review, and quiz flow management.";
    if (mode === "signup") return "Create a candidate workspace to track applications, exams, and feedback.";
    return content.subtitle;
  }, [content.subtitle, mode, role]);

  useEffect(() => {
    const emailParam = searchParams.get("email");
    if (emailParam) {
      setEmail(emailParam);
      setRole("candidate");
    }
  }, [searchParams]);

  useEffect(() => {
    setMode(initialMode);
  }, [initialMode]);

  const validateEmail = (value: string) => {
    setEmail(value);
    const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    setEmailError(value && !re.test(value) ? "Please enter a valid email address" : "");
  };

  const toggleMode = () => {
    const next: Mode = mode === "login" ? "signup" : "login";
    setMode(next);
    setFirstName("");
    setLastName("");
    setEmail("");
    setPassword("");
    setEmailError("");
    setShowPassword(false);
    const preserved = new URLSearchParams();
    const keepKeys = ["role", "email", "redirect"];
    for (const key of keepKeys) {
      const value = searchParams.get(key);
      if (value) preserved.set(key, value);
    }
    const path = next === "login" ? "/login" : "/signup";
    const search = preserved.toString();
    navigate(search ? `${path}?${search}` : path, { replace: true });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (emailError) return;
    setLoading(true);

    try {
      if (mode === "signup") {
        const fullName = `${firstName} ${lastName}`.trim();
        try {
          await register(fullName, email, password, role);
        } catch (regError: any) {
          const detail = regError?.response?.data?.detail;
          let regMessage = "Registration failed. Please check your details.";
          if (typeof detail === "string") {
            regMessage = detail;
          } else if (Array.isArray(detail) && detail[0]?.msg) {
            regMessage = detail
              .map((err: any) => {
                const field = String(err.loc?.slice(-1) ?? "");
                const cleanMsg = err.msg.replace("Value error, ", "");
                const displayField = field ? field.charAt(0).toUpperCase() + field.slice(1) : "";
                return displayField ? `${displayField}: ${cleanMsg}` : cleanMsg;
              })
              .join(" - ");
          } else if (regError?.message) {
            regMessage = regError.message;
          }
          toast.error(regMessage);
          return;
        }
      }

      const user = await login(email.trim(), password);
      toast.success(mode === "signup" ? "Account created - welcome!" : "Welcome back!");

      const rawRedirect = searchParams.get("redirect") || sessionStorage.getItem("magic_link_redirect");
      const redirectTarget = rawRedirect && rawRedirect.startsWith("/") && !rawRedirect.includes("://") ? rawRedirect : null;
      if (redirectTarget) {
        sessionStorage.removeItem("magic_link_redirect");
        navigate(redirectTarget);
      } else if (user.role === "candidate") {
        navigate("/candidate/dashboard");
      } else {
        navigate("/dashboard");
      }
    } catch (error: any) {
      const message = error?.message || (mode === "login" ? "Invalid credentials. Please try again." : "Something went wrong.");
      toast.error(message);
    } finally {
      setLoading(false);
    }
  };

  const isSubmitDisabled = loading || !!emailError || !email || !password || (mode === "signup" && (!firstName || !lastName));

  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-4 py-8 text-foreground">
      <motion.section
        initial={prefersReducedMotion ? false : { opacity: 0, y: 14 }}
        animate={prefersReducedMotion ? undefined : { opacity: 1, y: 0 }}
        transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
        className="grid w-full max-w-6xl overflow-hidden rounded-[2rem] border border-border bg-card shadow-[0_24px_80px_rgba(0,0,0,0.08)] lg:grid-cols-[0.86fr_1.14fr]"
      >
        <div className="flex min-h-[640px] flex-col justify-center p-6 sm:p-10 lg:p-12">
          <Link
            to="/"
            className="mb-9 flex w-fit items-center gap-3 rounded-2xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30"
            aria-label="Go to Jobora home"
          >
            <LogoMark />
            <div>
              <p className="text-xl font-bold tracking-tight">Jobora</p>
              <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">Hiring OS</p>
            </div>
          </Link>

          <div className="mb-7 space-y-3">
            <div className="inline-flex items-center gap-2 rounded-full border border-border bg-background px-3 py-1.5 text-xs font-medium text-muted-foreground">
              <ShieldCheck className="h-3.5 w-3.5" />
              {content.label}
            </div>
            <div>
              <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">{formTitle}</h1>
              <p className="mt-2 max-w-md text-sm leading-6 text-muted-foreground">{formSubtitle}</p>
            </div>
          </div>

          <div className="mb-5">
            <RoleToggle role={role} setRole={setRole} />
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            {mode === "signup" && (
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <Field label="First name" htmlFor="auth-first-name">
                  <InputShell>
                    <UserRound className="ml-4 h-4 w-4 text-muted-foreground" />
                    <StyledInput
                      id="auth-first-name"
                      aria-label="First name"
                      value={firstName}
                      onChange={(e) => setFirstName(e.target.value)}
                      placeholder="First name"
                      required
                    />
                  </InputShell>
                </Field>
                <Field label="Last name" htmlFor="auth-last-name">
                  <InputShell>
                    <UserRound className="ml-4 h-4 w-4 text-muted-foreground" />
                    <StyledInput
                      id="auth-last-name"
                      aria-label="Last name"
                      value={lastName}
                      onChange={(e) => setLastName(e.target.value)}
                      placeholder="Last name"
                      required
                    />
                  </InputShell>
                </Field>
              </div>
            )}

            <Field label="Email address" htmlFor="auth-email" error={emailError}>
              <InputShell>
                <Mail className="ml-4 h-4 w-4 text-muted-foreground" />
                <StyledInput
                  id="auth-email"
                  aria-label="Email address"
                  type="email"
                  placeholder="[email-redacted]"
                  value={email}
                  onChange={(e) => validateEmail(e.target.value)}
                  autoFocus={mode === "login"}
                  required
                />
              </InputShell>
            </Field>

            <Field
              label="Password"
              htmlFor="auth-password"
              action={
                mode === "login" ? (
                  <button
                    type="button"
                    className="text-xs font-semibold text-muted-foreground hover:text-foreground hover:underline"
                    onClick={() => navigate("/forgot-password")}
                  >
                    Forgot password?
                  </button>
                ) : null
              }
            >
              <InputShell>
                <LockKeyhole className="ml-4 h-4 w-4 text-muted-foreground" />
                <StyledInput
                  id="auth-password"
                  aria-label="Password"
                  type={showPassword ? "text" : "password"}
                  placeholder={mode === "signup" ? "Create a strong password" : "Enter your password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  minLength={mode === "signup" ? 8 : undefined}
                  required
                />
                <button
                  type="button"
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  onClick={() => setShowPassword((value) => !value)}
                  className="mr-3 rounded-xl p-2 text-muted-foreground transition hover:bg-muted hover:text-foreground"
                >
                  {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </InputShell>
              {mode === "signup" && <PasswordStrength password={password} />}
            </Field>

            <Button type="submit" className="h-12 w-full rounded-2xl" disabled={isSubmitDisabled}>
              {loading ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Processing...
                </>
              ) : mode === "signup" ? (
                <>
                  Create account
                  <ArrowRight className="h-4 w-4" />
                </>
              ) : (
                <>
                  Sign in
                  <ArrowRight className="h-4 w-4" />
                </>
              )}
            </Button>
          </form>

          <div className="mt-7 text-center">
            <p className="text-sm text-muted-foreground">
              {mode === "signup" ? "Already have an account?" : "Don't have an account?"}{" "}
              <button type="button" onClick={toggleMode} className="font-semibold text-foreground hover:underline">
                {mode === "signup" ? "Sign in" : "Create account"}
              </button>
            </p>
          </div>

        </div>

        <WorkspacePreview role={role} />
      </motion.section>
    </main>
  );
}
