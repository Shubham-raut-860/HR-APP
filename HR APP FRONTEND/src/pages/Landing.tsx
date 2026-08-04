import { Link, useNavigate } from "react-router-dom";
import { motion, useReducedMotion } from "framer-motion";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  ArrowRight,
  BarChart3,
  Bell,
  Briefcase,
  CheckCircle2,
  FileText,
  Lock,
  Play,
  Send,
  ShieldCheck,
  Users,
} from "lucide-react";

const workflow = [
  {
    icon: Briefcase,
    title: "Open a role",
    body: "Create a job description, publish it, and keep every applicant tied to the right hiring context.",
  },
  {
    icon: FileText,
    title: "Review evidence",
    body: "Parse resumes, score fit against the JD, and see candidate strengths without spreadsheet drift.",
  },
  {
    icon: Send,
    title: "Run assessments",
    body: "Generate quiz links, send them securely, and bring scores back into the recruiter view.",
  },
  {
    icon: ShieldCheck,
    title: "Protect documents",
    body: "Keep candidate progress, KYC collection, and consent-gated documents in separated flows.",
  },
];

const metrics = [
  { value: "12", label: "active jobs" },
  { value: "38", label: "strong matches" },
  { value: "7", label: "assessments pending" },
];

function LogoMark({ className = "" }: { className?: string }) {
  return (
    <div className={`flex h-9 w-9 items-center justify-center rounded-xl bg-primary text-primary-foreground ${className}`}>
      <Briefcase className="h-4 w-4" />
    </div>
  );
}

export default function LandingPage() {
  const navigate = useNavigate();
  const prefersReducedMotion = useReducedMotion();

  const handleDemo = () => {
    toast.info("Create an account to explore the recruiter and candidate workspaces.");
    navigate("/signup");
  };

  const rise = prefersReducedMotion
    ? undefined
    : {
        initial: { opacity: 0, y: 14 },
        animate: { opacity: 1, y: 0 },
        transition: { duration: 0.35, ease: [0.16, 1, 0.3, 1] },
      };

  return (
    <main className="min-h-screen bg-background text-foreground selection:bg-primary/10">
      <nav className="fixed inset-x-0 top-0 z-50 border-b border-white/10 bg-black/35 text-white backdrop-blur-xl">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
          <Link to="/" className="flex items-center gap-2.5" aria-label="Jobora home">
            <LogoMark className="bg-white text-zinc-950" />
            <div>
              <p className="text-lg font-bold tracking-tight">Jobora</p>
              <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-white/60">Hiring OS</p>
            </div>
          </Link>

          <div className="hidden items-center gap-7 text-sm font-medium text-white/70 md:flex">
            <a href="#workflow" className="hover:text-white">Workflow</a>
            <a href="#features" className="hover:text-white">Features</a>
            <a href="#trust" className="hover:text-white">Trust</a>
          </div>

          <div className="flex items-center gap-2">
            <Button asChild variant="ghost" className="rounded-full text-white hover:bg-white/10 hover:text-white">
              <Link to="/login">Log in</Link>
            </Button>
            <Button asChild className="rounded-full bg-white text-zinc-950 hover:bg-white/90">
              <Link to="/signup">Get started</Link>
            </Button>
          </div>
        </div>
      </nav>

      <section className="relative min-h-[92vh] overflow-hidden bg-zinc-950">
        <img
          src="/recruiter_auth.png"
          alt="Recruiter reviewing talent analytics in a modern office"
          className="absolute inset-0 h-full w-full object-cover"
        />
        <div className="absolute inset-0 bg-[linear-gradient(90deg,rgba(0,0,0,0.82)_0%,rgba(0,0,0,0.54)_42%,rgba(0,0,0,0.18)_100%)]" />
        <div className="absolute inset-x-0 bottom-0 h-40 bg-gradient-to-t from-background to-transparent" />

        <div className="relative mx-auto flex min-h-[92vh] max-w-7xl items-center px-4 pb-20 pt-28 sm:px-6 lg:px-8">
          <motion.div {...rise} className="max-w-3xl text-white">
            <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-white/20 bg-white/10 px-3 py-1.5 text-sm font-medium text-white/85 backdrop-blur">
              <CheckCircle2 className="h-4 w-4" />
              Built for the real hiring lifecycle, not a disconnected demo.
            </div>
            <h1 className="max-w-4xl text-balance text-5xl font-bold tracking-tight sm:text-6xl lg:text-7xl">
              Hiring work, from first role to final result.
            </h1>
            <p className="mt-6 max-w-2xl text-lg leading-8 text-white/78">
              Jobora gives recruiters and candidates one operating system for jobs, resumes, scoring, assessments, notifications, and consent-gated documents.
            </p>

            <div className="mt-8 flex flex-col gap-3 sm:flex-row">
              <Button asChild size="lg" className="h-12 rounded-full bg-white px-6 text-zinc-950 hover:bg-white/90">
                <Link to="/signup?role=hr">
                  Start as recruiter <ArrowRight className="ml-2 h-4 w-4" />
                </Link>
              </Button>
              <Button asChild size="lg" variant="outline" className="h-12 rounded-full border-white/30 bg-white/10 px-6 text-white hover:bg-white/20 hover:text-white">
                <Link to="/signup?role=candidate">Continue as candidate</Link>
              </Button>
              <Button type="button" size="lg" variant="ghost" className="h-12 rounded-full px-5 text-white hover:bg-white/10 hover:text-white" onClick={handleDemo}>
                <Play className="mr-2 h-4 w-4" /> Demo
              </Button>
            </div>

            <div className="mt-10 grid max-w-xl gap-3 sm:grid-cols-3">
              {metrics.map((item) => (
                <div key={item.label} className="border-l border-white/25 pl-4">
                  <p className="text-3xl font-bold">{item.value}</p>
                  <p className="mt-1 text-sm text-white/62">{item.label}</p>
                </div>
              ))}
            </div>
          </motion.div>
        </div>
      </section>

      <section id="workflow" className="border-b border-border bg-background">
        <div className="mx-auto grid max-w-7xl gap-10 px-4 py-16 sm:px-6 lg:grid-cols-[0.72fr_1.28fr] lg:px-8">
          <div>
            <p className="text-sm font-semibold uppercase tracking-[0.16em] text-muted-foreground">Workflow</p>
            <h2 className="mt-3 text-3xl font-bold tracking-tight">A cleaner operating rhythm for hiring teams.</h2>
            <p className="mt-4 leading-7 text-muted-foreground">
              The product stays practical: create the role, review candidates, assign assessments, and keep the pipeline honest.
            </p>
          </div>
          <div id="features" className="grid gap-4 md:grid-cols-2">
            {workflow.map((item) => {
              const Icon = item.icon;
              return (
                <div key={item.title} className="rounded-2xl border border-border bg-card p-5">
                  <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10 text-primary">
                    <Icon className="h-5 w-5" />
                  </div>
                  <h3 className="font-semibold">{item.title}</h3>
                  <p className="mt-2 text-sm leading-6 text-muted-foreground">{item.body}</p>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      <section id="trust" className="bg-card/35">
        <div className="mx-auto grid max-w-7xl gap-4 px-4 py-16 sm:px-6 lg:grid-cols-[0.95fr_1.05fr] lg:px-8">
          <div className="rounded-2xl border border-border bg-card p-6">
            <Lock className="mb-4 h-6 w-6" />
            <h2 className="text-2xl font-bold tracking-tight">Trust stays visible.</h2>
            <p className="mt-3 leading-7 text-muted-foreground">
              Recruiter and candidate workspaces stay separated, assessment links are tokenized, and sensitive document collection is consent-gated.
            </p>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            {[
              [Users, "Role-aware access"],
              [Bell, "Clear notifications"],
              [BarChart3, "Traceable results"],
              [ShieldCheck, "Controlled documents"],
            ].map(([Icon, title]) => {
              const TrustIcon = Icon as typeof Users;
              return (
                <div key={String(title)} className="rounded-2xl border border-border bg-card p-6">
                  <TrustIcon className="mb-4 h-5 w-5 text-primary" />
                  <p className="font-semibold">{title as string}</p>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      <footer className="border-t border-border bg-background">
        <div className="mx-auto flex max-w-7xl flex-col gap-4 px-4 py-8 text-sm text-muted-foreground sm:flex-row sm:items-center sm:justify-between sm:px-6 lg:px-8">
          <div className="flex items-center gap-2.5">
            <LogoMark className="h-8 w-8" />
            <span className="font-semibold text-foreground">Jobora</span>
          </div>
          <p>Hiring OS for recruiters and candidates.</p>
        </div>
      </footer>
    </main>
  );
}
