import { useState } from 'react';
import { motion, useReducedMotion } from 'framer-motion';
import { toast } from 'sonner';
import { Link, useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { 
  BrainCircuit, CheckCircle2, ArrowRight, BarChart3, Users, 
  Zap, LayoutDashboard, Briefcase, Settings, LogOut, Sparkles, Play
} from 'lucide-react';


export default function LandingPage() {
  const navigate = useNavigate();
  const prefersReducedMotion = useReducedMotion();
  const [videoReady, setVideoReady] = useState(false);
  const [videoFailed, setVideoFailed] = useState(false);

  const handleDemo = () => {
    toast.info("Sign up for a free account to explore the full platform.");
    navigate("/signup");
  };

  return (
    <div className="relative min-h-screen w-full bg-background text-foreground overflow-x-clip selection:bg-primary/20 font-sans transition-colors duration-500">
      
      {/* ── Video Background ────────────────────────────────────────────── */}
      <div className="absolute inset-0 h-[100dvh] z-0 overflow-hidden pointer-events-none bg-zinc-950">
        <div className={`absolute inset-0 transition-opacity duration-500 ${(videoFailed || !videoReady) ? 'opacity-100' : 'opacity-0'}`}>
          <div className="absolute inset-0 bg-[radial-gradient(circle_at_20%_30%,rgba(120,119,198,0.35),transparent_40%),radial-gradient(circle_at_80%_20%,rgba(52,211,153,0.2),transparent_35%),radial-gradient(circle_at_50%_80%,rgba(59,130,246,0.25),transparent_40%),linear-gradient(to_bottom,#09090b,#111827)]" />
          <div className="absolute inset-0 bg-[url('/recruiter_auth.png')] bg-cover bg-center opacity-20" />
        </div>
        <video
          autoPlay 
          loop 
          muted 
          playsInline 
          preload="metadata"
          poster="/recruiter_auth.png"
          onLoadedData={() => setVideoReady(true)}
          onCanPlay={() => setVideoReady(true)}
          onError={() => setVideoFailed(true)}
          className={`w-full h-full object-cover transition-opacity duration-500 ${videoReady && !videoFailed ? 'opacity-100' : 'opacity-0'}`}
        >
          <source src="https://assets.mixkit.co/videos/preview/mixkit-business-people-working-together-in-an-office-4841-large.mp4" type="video/mp4" />
        </video>
        {/* Dark overlay to ensure white text is always sharp and cinematic, never washed out */}
        <div className="absolute inset-0 bg-black/60" />
        {/* Soft bottom transition into the system theme background */}
        <div className="absolute inset-0 bg-gradient-to-t from-background via-background/20 to-transparent" />
      </div>

      {/* ── Navbar ────────────────────────────────────────────── */}
      <nav className="absolute top-0 w-full z-50 transition-all duration-300 bg-gradient-to-b from-black/80 via-black/40 to-transparent">
        <div className="mx-auto w-full px-6 md:px-10 2xl:px-14">
          <div className="flex h-24 items-center justify-between">
            <div className="flex items-center gap-2 font-bold text-xl tracking-tight text-white drop-shadow-md">
              <BrainCircuit className="h-6 w-6" /> HireAI
            </div>
            <div className="flex items-center gap-6">
              <Button asChild variant="ghost" className="text-white/90 hover:bg-white/10 hover:text-white font-medium text-base tracking-wide">
                <Link to="/login">Log in</Link>
              </Button>
              <Button asChild className="bg-white text-zinc-900 hover:bg-zinc-200 font-bold rounded-xl px-7 shadow-xl transition-all hover:scale-105 border-0">
                <Link to="/signup">Get Started</Link>
              </Button>
            </div>
          </div>
        </div>
      </nav>

      <div className="relative z-10 flex flex-col items-center w-full">
        
        {/* ── Hero Section ──────────────────────────────────────── */}
        <section className="relative w-full flex flex-col items-center justify-center min-h-[100dvh] pt-32 pb-12">
          <div className="mx-auto w-full px-6 md:px-10 2xl:px-14 text-center">
            <motion.div
              initial={prefersReducedMotion ? false : { opacity: 0, y: 20 }}
              animate={prefersReducedMotion ? undefined : { opacity: 1, y: 0 }}
              transition={{ duration: 0.55, ease: [0.16, 1, 0.3, 1] }}
              className="space-y-8"
            >
              
              <div className="group relative inline-flex items-center gap-2 px-5 py-2 rounded-full border border-white/10 bg-white/5 backdrop-blur-md text-sm font-medium shadow-[0_0_20px_rgba(255,255,255,0.05)] text-white hover:bg-white/10 transition-colors cursor-default">
                <div className="absolute inset-0 rounded-full border border-white/20 opacity-0 group-hover:opacity-100 transition-opacity" />
                <Sparkles className="h-4 w-4 text-zinc-300 animate-pulse" /> v2.0 Now Live: AI Resume Parsing
              </div>

              <h1 className="text-5xl sm:text-7xl lg:text-[7.5rem] font-extrabold tracking-tighter leading-[0.9] text-white">
                Match Talent <br />
                <span className="bg-gradient-to-r from-zinc-300 to-zinc-500 bg-clip-text text-transparent">In Seconds.</span>
              </h1>

              <p className="mx-auto max-w-3xl text-lg sm:text-xl text-zinc-300 font-medium leading-relaxed drop-shadow-sm">
                Automate your hiring pipeline with AI. From resume parsing to candidate ranking, we handle the heavy lifting so you can focus on the interview.
              </p>

              <div className="flex flex-wrap items-center justify-center gap-5 pt-8">
                <Link to="/signup" className="group h-14 px-8 text-lg font-semibold rounded-2xl bg-white text-black hover:scale-105 transition-all duration-300 flex items-center justify-center shadow-[0_0_30px_rgba(255,255,255,0.15)] hover:shadow-[0_0_40px_rgba(255,255,255,0.3)] border border-transparent">
                  Start Hiring Free <ArrowRight className="ml-2 h-5 w-5 group-hover:translate-x-1 transition-transform" />
                </Link>
                <button onClick={handleDemo} className="h-14 px-8 text-lg font-medium rounded-2xl border border-white/10 bg-white/5 hover:bg-white/10 backdrop-blur-md text-white transition-all duration-300 flex items-center justify-center shadow-[0_0_20px_rgba(0,0,0,0.5)]">
                  <Play className="mr-2 h-5 w-5 text-white/80" /> View Demo
                </button>
              </div>
            </motion.div>
          </div>
        </section>

        {/* ── Dashboard Preview ──────────────────────────────────────── */}
        <section className="w-full relative pb-32">
          <div className="mx-auto w-full px-6 md:px-10 2xl:px-14">
            <motion.div
              initial={prefersReducedMotion ? false : { opacity: 0, y: 40 }}
              whileInView={prefersReducedMotion ? undefined : { opacity: 1, y: 0 }}
              viewport={{ once: true, margin: "-100px" }}
              transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
              className="relative mx-auto max-w-5xl rounded-3xl border border-white/20 dark:border-white/10 bg-white/10 dark:bg-black/40 backdrop-blur-2xl p-4 shadow-[0_30px_60px_rgba(0,0,0,0.5)] transition-colors duration-500"
            >
              <div className="absolute inset-0 bg-gradient-to-tr from-black/5 dark:from-white/5 via-transparent to-transparent rounded-2xl" />
              
              <div className="relative rounded-xl border border-black/5 dark:border-white/5 bg-zinc-50 dark:bg-[#0a0a0a] overflow-hidden aspect-[16/9] flex text-muted-foreground shadow-inner select-none pointer-events-none transition-colors duration-500">
                {/* Sidebar */}
                <div className="w-16 border-r border-black/5 dark:border-white/5 bg-zinc-100/50 dark:bg-black/50 flex flex-col items-center py-4 gap-6">
                  <div className="h-8 w-8 rounded-lg bg-black/5 dark:bg-white/10 flex items-center justify-center">
                    <BrainCircuit className="h-5 w-5 text-zinc-900 dark:text-white" />
                  </div>
                  <div className="flex flex-col gap-4 w-full items-center">
                    <div className="h-8 w-8 rounded-md bg-black/5 dark:bg-white/5 flex items-center justify-center text-zinc-900 dark:text-white">
                      <LayoutDashboard className="h-4 w-4" />
                    </div>
                    <div className="h-8 w-8 rounded-md flex items-center justify-center">
                      <BarChart3 className="h-4 w-4" />
                    </div>
                    <div className="h-8 w-8 rounded-md flex items-center justify-center">
                      <Briefcase className="h-4 w-4" />
                    </div>
                    <div className="h-8 w-8 rounded-md flex items-center justify-center">
                      <Settings className="h-4 w-4" />
                    </div>
                  </div>
                  <div className="mt-auto h-8 w-8 rounded-full flex items-center justify-center text-muted-foreground">
                    <LogOut className="h-4 w-4" />
                  </div>
                </div>
                
                {/* Main Content */}
                <div className="flex-1 flex flex-col min-w-0">
                  {/* Header */}
                  <div className="h-14 border-b border-black/5 dark:border-white/5 flex items-center px-6 justify-between bg-white/50 dark:bg-black/20">
                      <div className="text-sm font-semibold text-foreground">Dashboard Overview</div>
                      <div className="flex gap-3">
                          <div className="h-7 w-7 rounded-full bg-black/5 dark:bg-white/10" />
                          <div className="h-7 w-7 rounded-full bg-black/5 dark:bg-white/10" />
                      </div>
                  </div>
                  
                  {/* Dashboard Grid */}
                  <div className="p-6 grid grid-cols-3 gap-6 bg-zinc-100/30 dark:bg-black/10 flex-1 overflow-hidden text-left">
                      {/* Stats Cards */}
                      <div className="col-span-1 space-y-2 p-4 rounded-xl border border-black/5 dark:border-white/5 bg-white dark:bg-[#111] shadow-sm">
                          <div className="flex justify-between items-start">
                            <div className="h-8 w-8 rounded-lg bg-zinc-100 dark:bg-white/5 flex items-center justify-center">
                              <Users className="h-4 w-4 text-zinc-900 dark:text-white" />
                            </div>
                            <div className="h-5 px-2 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 rounded-full text-[10px] flex items-center justify-center font-bold tracking-wide">+12%</div>
                          </div>
                          <div className="space-y-1 pt-2">
                            <div className="text-2xl font-bold text-foreground">1,284</div>
                            <div className="text-xs text-muted-foreground font-medium">Total Candidates</div>
                          </div>
                      </div>
                      <div className="col-span-1 space-y-2 p-4 rounded-xl border border-black/5 dark:border-white/5 bg-white dark:bg-[#111] shadow-sm">
                          <div className="flex justify-between items-start">
                            <div className="h-8 w-8 rounded-lg bg-zinc-100 dark:bg-white/5 flex items-center justify-center">
                              <Zap className="h-4 w-4 text-zinc-900 dark:text-white" />
                            </div>
                            <div className="h-5 px-2 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 rounded-full text-[10px] flex items-center justify-center font-bold tracking-wide">+5%</div>
                          </div>
                          <div className="space-y-1 pt-2">
                            <div className="text-2xl font-bold text-foreground">86%</div>
                            <div className="text-xs text-muted-foreground font-medium">Avg. Match Rate</div>
                          </div>
                      </div>
                      <div className="col-span-1 space-y-2 p-4 rounded-xl border border-black/5 dark:border-white/5 bg-white dark:bg-[#111] shadow-sm">
                          <div className="flex justify-between items-start">
                            <div className="h-8 w-8 rounded-lg bg-zinc-100 dark:bg-white/5 flex items-center justify-center">
                              <CheckCircle2 className="h-4 w-4 text-zinc-900 dark:text-white" />
                            </div>
                            <div className="h-5 px-2 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 rounded-full text-[10px] flex items-center justify-center font-bold tracking-wide">+8%</div>
                          </div>
                          <div className="space-y-1 pt-2">
                            <div className="text-2xl font-bold text-foreground">24</div>
                            <div className="text-xs text-muted-foreground font-medium">Hired This Month</div>
                          </div>
                      </div>

                      {/* Main Chart Area */}
                      <div className="col-span-2 row-span-2 rounded-xl border border-black/5 dark:border-white/5 bg-white dark:bg-[#111] p-5 flex flex-col relative overflow-hidden shadow-sm">
                           <div className="absolute top-0 right-0 w-64 h-64 bg-primary/5 dark:bg-white/5 blur-3xl rounded-full translate-x-1/2 -translate-y-1/2 pointer-events-none" />
                           <div className="flex justify-between items-center relative z-10">
                              <div className="space-y-1">
                                <div className="text-sm font-semibold text-foreground">Application Velocity</div>
                                <div className="text-xs text-muted-foreground font-medium">Trailing 30 Days</div>
                              </div>
                           </div>
                           <div className="flex items-end gap-3 flex-1 pt-6 px-2 pb-2 z-10">
                              {[40, 70, 50, 85, 60, 75, 45, 65, 80].map((h, i) => (
                                <div key={i} className="w-full bg-zinc-200 dark:bg-white/10 rounded-t-sm relative group transition-all duration-500" style={{ height: `${h}%` }}>
                                  <div className="absolute inset-0 bg-gradient-to-t from-transparent to-primary/10 dark:to-white/20 opacity-0 group-hover:opacity-100 transition-opacity" />
                                </div>
                              ))}
                           </div>
                      </div>

                      {/* Side List */}
                      <div className="col-span-1 row-span-2 rounded-xl border border-black/5 dark:border-white/5 bg-white dark:bg-[#111] p-4 space-y-4 shadow-sm">
                          <div className="text-sm font-semibold text-foreground mb-2">Recent Pipeline</div>
                          {[
                            { name: "Alice J.", dept: "Frontend", time: "2m ago" },
                            { name: "Bob S.", dept: "Backend", time: "15m ago" },
                            { name: "Charlie", dept: "Design", time: "1h ago" }
                          ].map((item, i) => (
                              <div key={i} className="flex items-center gap-3">
                                  <div className="h-8 w-8 rounded-full bg-zinc-100 dark:bg-white/10 shrink-0 flex items-center justify-center text-[10px] font-bold text-foreground">
                                    {item.name[0]}
                                  </div>
                                  <div className="space-y-1 flex-1 min-w-0">
                                      <div className="text-xs font-semibold text-foreground truncate">{item.name} via {item.dept}</div>
                                      <div className="text-[10px] text-muted-foreground font-medium">{item.time}</div>
                                  </div>
                              </div>
                          ))}
                      </div>
                  </div>
                </div>
                
              </div>
            </motion.div>
          </div>
        </section>

        {/* ── Features Grid ──────────────────────────────────────── */}
        <section className="w-full py-24 bg-zinc-50 dark:bg-[#050505] relative border-y border-black/5 dark:border-white/5 transition-colors duration-500">
          <div className="absolute right-0 top-0 w-1/2 h-full bg-gradient-to-l from-white/40 dark:from-white/[0.02] to-transparent pointer-events-none" />
          <div className="mx-auto w-full px-6 md:px-10 2xl:px-14 relative z-10">
            <div className="mb-16">
              <h2 className="text-3xl sm:text-4xl font-extrabold tracking-tight mb-4">Scale your hiring, <br/><span className="text-zinc-400 dark:text-zinc-500">not your headcount.</span></h2>
            </div>
            
            <div className="grid md:grid-cols-3 gap-6">
              {[
                {
                  icon: Zap,
                  title: "Instant Parsing",
                  desc: "Extract structured data from unstructured PDF or DOCX resumes in milliseconds with near-perfect accuracy."
                },
                {
                  icon: BarChart3,
                  title: "Smart Ranking Algorithms",
                  desc: "Automatically rank thousands of candidates based on weighted technical skills, experience levels, and quiz performance."
                },
                {
                  icon: Users,
                  title: "Bias-Free Evaluation",
                  desc: "Enforce standardized assessments and blind screening modes to ensure a truly meritocratic hiring process."
                }
              ].map((feature, i) => (
                <motion.div
                  key={i}
                  initial={{ opacity: 0, y: 20 }}
                  whileInView={{ opacity: 1, y: 0 }}
                  viewport={{ once: true, margin: "-50px" }}
                  transition={{ delay: i * 0.1, duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
                  className="group p-8 rounded-3xl border border-black/5 dark:border-white/5 bg-white dark:bg-white/[0.02] shadow-md dark:shadow-none hover:shadow-xl dark:hover:bg-white/[0.04] hover:-translate-y-2 transition-all duration-300 relative overflow-hidden"
                >
                  <div className="absolute right-0 top-0 w-32 h-32 bg-primary/5 dark:bg-white/5 blur-3xl group-hover:bg-primary/10 dark:group-hover:bg-white/10 transition-colors pointer-events-none" />
                  <div className="mb-6 inline-flex h-12 w-12 items-center justify-center rounded-2xl bg-zinc-100 dark:bg-white/10 text-zinc-900 dark:text-white">
                    <feature.icon className="h-5 w-5" />
                  </div>
                  <h3 className="mb-3 text-xl font-bold tracking-tight">{feature.title}</h3>
                  <p className="text-muted-foreground font-medium text-sm leading-relaxed">{feature.desc}</p>
                </motion.div>
              ))}
            </div>
          </div>
        </section>

        {/* ── Footer ──────────────────────────────────────── */}
        <footer className="w-full py-10 bg-background border-t border-border transition-colors duration-500">
          <div className="mx-auto w-full px-6 md:px-10 2xl:px-14 flex flex-col md:flex-row justify-between items-center gap-6">
            <div className="flex items-center gap-2 font-bold text-lg tracking-tight">
              <BrainCircuit className="h-5 w-5 text-foreground" /> HireAI
            </div>
            <p className="text-sm text-muted-foreground font-medium">
              © {new Date().getFullYear()} HireAI Inc. Building the future of work.
            </p>
            <div className="flex gap-6 text-sm text-muted-foreground font-medium">
              <a href="#" className="hover:text-foreground transition-colors">Privacy</a>
              <a href="#" className="hover:text-foreground transition-colors">Terms</a>
              <a href="#" className="hover:text-foreground transition-colors">Twitter // X</a>
            </div>
          </div>
        </footer>

      </div>
    </div>
  );
}
