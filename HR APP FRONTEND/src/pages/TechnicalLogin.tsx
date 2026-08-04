import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Bot, Eye, EyeOff, Loader2, LockKeyhole, ShieldCheck } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/context/AuthContext";
import { isTechnicalAdmin, TECHNICAL_ADMIN_EMAIL } from "@/lib/technicalAdmin";

export default function TechnicalLogin() {
  const navigate = useNavigate();
  const { login, logout } = useAuth();
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setLoading(true);
    try {
      const user = await login(TECHNICAL_ADMIN_EMAIL, password);
      if (!isTechnicalAdmin(user)) {
        logout();
        toast.error("This login is reserved for the technical admin account.");
        return;
      }
      toast.success("Technical admin session started");
      navigate("/developer/a2a");
    } catch (error: any) {
      toast.error(error?.message || "Technical admin login failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-4 py-8 text-foreground">
      <section className="grid w-full max-w-5xl overflow-hidden rounded-[2rem] border border-border bg-card shadow-[0_24px_80px_rgba(0,0,0,0.08)] lg:grid-cols-[0.9fr_1.1fr]">
        <div className="flex min-h-[620px] flex-col justify-center p-6 sm:p-10 lg:p-12">
          <div className="mb-8 flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary text-primary-foreground">
              <Bot className="h-5 w-5" />
            </div>
            <div>
              <p className="text-xl font-bold tracking-tight">Developer Control</p>
              <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">Technical admin only</p>
            </div>
          </div>

          <div className="mb-7 space-y-3">
            <div className="inline-flex w-fit items-center gap-2 rounded-full border border-border bg-background px-3 py-1.5 text-xs font-medium text-muted-foreground">
              <ShieldCheck className="h-3.5 w-3.5" />
              Restricted console
            </div>
            <div>
              <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">Technical admin login</h1>
              <p className="mt-2 max-w-md text-sm leading-6 text-muted-foreground">
                Sign in as the dedicated developer-control account to access A2A, Harness, traces, artifacts, and runtime controls.
              </p>
            </div>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <label className="text-xs font-semibold text-muted-foreground">Technical user id</label>
              <div className="flex h-12 items-center rounded-2xl border border-input bg-muted/40 px-4 text-sm font-semibold text-foreground">
                {TECHNICAL_ADMIN_EMAIL}
              </div>
            </div>

            <div className="space-y-2">
              <label htmlFor="technical-admin-password" className="text-xs font-semibold text-muted-foreground">Password</label>
              <div className="relative flex h-12 items-center rounded-2xl border border-input bg-background shadow-sm transition focus-within:ring-2 focus-within:ring-ring/20">
                <LockKeyhole className="ml-4 h-4 w-4 text-muted-foreground" />
                <input
                  id="technical-admin-password"
                  aria-label="Technical admin password"
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder="Enter technical password"
                  className="h-full min-w-0 flex-1 rounded-2xl bg-transparent px-3 text-sm font-medium text-foreground placeholder:text-muted-foreground focus:outline-none"
                  autoFocus
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
              </div>
            </div>

            <Button type="submit" className="h-12 w-full rounded-2xl" disabled={!password || loading}>
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4" />}
              Enter developer console
            </Button>
          </form>
        </div>

        <div className="hidden min-h-[620px] bg-zinc-950 p-8 text-white lg:flex lg:flex-col lg:justify-between">
          <div className="flex items-center justify-between">
            <span className="rounded-full border border-white/15 bg-white/10 px-3 py-1.5 text-xs font-semibold">A2A</span>
            <span className="rounded-full border border-white/15 bg-white/10 px-3 py-1.5 text-xs font-semibold">Harness</span>
          </div>
          <div>
            <p className="text-sm font-semibold uppercase tracking-[0.18em] text-white/45">Developer surface</p>
            <h2 className="mt-3 text-4xl font-bold tracking-tight">Protocol, agents, tasks, artifacts, traces.</h2>
            <p className="mt-4 max-w-lg text-sm leading-6 text-white/65">
              This area is intentionally separated from recruiter workflows so technical controls stay out of the normal hiring UI.
            </p>
          </div>
          <div className="grid grid-cols-3 gap-3">
            {["Agent Cards", "Messages", "Traces"].map((label) => (
              <div key={label} className="rounded-2xl border border-white/10 bg-white/10 p-4">
                <p className="text-sm font-semibold">{label}</p>
              </div>
            ))}
          </div>
        </div>
      </section>
    </main>
  );
}
