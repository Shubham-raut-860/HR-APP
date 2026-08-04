import { motion } from 'framer-motion';
import { Link, useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { BrainCircuit, ArrowRight, Sparkles, Play } from 'lucide-react';

import { toast } from 'sonner';

export default function LandingA() {
  const navigate = useNavigate();

  const handleDemo = () => {
    toast.info("Sign up for a free account to explore the full platform.");
    navigate("/signup");
  };

  return (
    <div className="relative min-h-screen bg-black text-white overflow-hidden selection:bg-white/30">
      {/* ── Navbar ────────────────────────────────────────────── */}
      <nav className="fixed top-0 w-full z-50">
        <div className="mx-auto max-w-7xl px-6 pt-6">
          <div className="flex h-14 items-center justify-between px-6 rounded-2xl border border-white/10 bg-white/5 backdrop-blur-2xl shadow-2xl">
            <div className="flex items-center gap-2 font-bold text-lg tracking-tight">
              <BrainCircuit className="h-5 w-5" /> Jobora
            </div>
            <div className="flex items-center gap-4">
              <Button asChild variant="ghost" className="text-white hover:bg-white/10">
                <Link to="/login">Log in</Link>
              </Button>
              <Button asChild className="bg-white text-black hover:bg-white/90 font-semibold rounded-xl">
                <Link to="/signup">Get Started</Link>
              </Button>
            </div>
          </div>
        </div>
      </nav>

      {/* ── Atmospheric Video Glow ──────────────────────────────────────── */}
      {/* The video is used purely as a dynamic, blurry aura glowing behind the text */}
      <div className="absolute inset-0 z-0 flex items-center justify-center pointer-events-none opacity-[0.9]">
        <div className="w-[800px] h-[800px] overflow-hidden rounded-full blur-[120px] opacity-70">
            <video autoPlay loop muted playsInline className="w-full h-full object-cover scale-150 grayscale mix-blend-screen">
            <source src="https://assets.mixkit.co/videos/preview/mixkit-business-people-working-together-in-an-office-4841-large.mp4" type="video/mp4" />
            <source src="/my-video.mp4" type="video/mp4" />
            </video>
        </div>
        <div className="absolute inset-0 bg-gradient-to-t from-black via-black/40 to-black/80" />
      </div>
      
      {/* ── Hero Content ──────────────────────────────────────── */}
      <div className="relative z-10 flex min-h-screen items-center justify-center pt-20">
        <div className="container mx-auto px-6 text-center max-w-5xl">
          <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.8, ease: [0.16, 1, 0.3, 1] }} className="space-y-8">
            
            <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full border border-white/10 bg-white/5 backdrop-blur-md text-sm font-medium text-white/80">
              <Sparkles className="h-4 w-4 text-primary" /> v2.0 Now Live
            </div>

            <h1 className="text-6xl sm:text-8xl lg:text-[8rem] font-extrabold tracking-tighter leading-[0.9]">
              Match Talent <br />
              <span className="bg-gradient-to-r from-zinc-300 to-zinc-600 bg-clip-text text-transparent">In Seconds.</span>
            </h1>

            <p className="mx-auto max-w-2xl text-xl text-zinc-400 font-light leading-relaxed">
              Automate your hiring pipeline with AI. From resume parsing to candidate ranking, we handle the heavy lifting.
            </p>

            <div className="flex flex-wrap items-center justify-center gap-4 pt-8">
              <Link to="/signup" className="h-14 px-8 text-lg font-semibold rounded-2xl bg-white text-black hover:scale-105 transition-transform flex items-center justify-center shadow-[0_0_40px_rgba(255,255,255,0.2)]">
                Start Hiring Free <ArrowRight className="ml-2 h-5 w-5" />
              </Link>
              <button onClick={handleDemo} className="h-14 px-8 text-lg font-medium rounded-2xl border border-white/10 bg-white/5 text-white hover:bg-white/10 backdrop-blur-md transition-all flex items-center justify-center">
                <Play className="mr-2 h-5 w-5 text-zinc-300" /> View Demo
              </button>
            </div>

          </motion.div>
        </div>
      </div>
    </div>
  );
}
