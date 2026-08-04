import { motion } from 'framer-motion';
import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { BrainCircuit, ArrowRight, Sparkles } from 'lucide-react';



export default function LandingB() {


  return (
    <div className="relative min-h-screen bg-zinc-50 dark:bg-[#0a0a0a] text-zinc-900 dark:text-white transition-colors duration-500 overflow-hidden pt-32 pb-20">
      {/* ── Geometric Background Grid ────────────────────────────────────────── */}
      <div className="absolute inset-0 z-0 pointer-events-none opacity-[0.03] dark:opacity-[0.05]" 
           style={{ backgroundImage: 'linear-gradient(to right, currentColor 1px, transparent 1px), linear-gradient(to bottom, currentColor 1px, transparent 1px)', backgroundSize: '60px 60px' }} />
      <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[1000px] h-[500px] bg-primary/20 dark:bg-primary/10 rounded-full blur-[120px] pointer-events-none -z-10" />

      {/* ── Navbar ────────────────────────────────────────────── */}
      <nav className="fixed top-0 w-full z-50">
        <div className="mx-auto max-w-7xl px-6 pt-6">
          <div className="flex h-14 items-center justify-between px-6 rounded-2xl border border-black/5 dark:border-white/10 bg-white/70 dark:bg-black/50 backdrop-blur-xl shadow-sm">
            <div className="flex items-center gap-2 font-bold text-lg tracking-tight">
              <BrainCircuit className="h-5 w-5" /> Jobora
            </div>
            <div className="flex items-center gap-4">
              <Button asChild variant="ghost" className="hover:bg-black/5 dark:hover:bg-white/10">
                <Link to="/login">Log in</Link>
              </Button>
              <Button asChild className="bg-zinc-900 text-white dark:bg-white dark:text-black hover:opacity-90 font-semibold rounded-xl">
                <Link to="/signup">Get Started</Link>
              </Button>
            </div>
          </div>
        </div>
      </nav>

      {/* ── Hero Content ──────────────────────────────────────── */}
      <div className="relative z-10 container mx-auto px-6 text-center max-w-6xl">
        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.8, ease: [0.16, 1, 0.3, 1] }} className="space-y-6">
          
          <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full border border-black/10 dark:border-white/10 bg-white dark:bg-white/5 text-sm font-medium shadow-sm">
            <Sparkles className="h-4 w-4 text-primary" /> The new standard for AI hiring
          </div>

          <h1 className="text-6xl sm:text-7xl lg:text-[7rem] font-extrabold tracking-tighter leading-[1]">
            Next Generation <br />
            <span className="text-zinc-400">Recruitment.</span>
          </h1>

          <div className="flex flex-wrap items-center justify-center gap-4 pt-4">
            <Link to="/signup" className="h-12 px-8 text-base font-semibold rounded-xl bg-zinc-900 text-white dark:bg-white dark:text-black hover:scale-105 transition-transform flex items-center justify-center shadow-lg">
              Start Hiring Free <ArrowRight className="ml-2 h-4 w-4" />
            </Link>
          </div>
        </motion.div>

        {/* ── Video Inside Browser Mockup ──────────────────────────────────────── */}
        <motion.div 
          initial={{ opacity: 0, y: 60 }} 
          animate={{ opacity: 1, y: 0 }} 
          transition={{ duration: 1, delay: 0.2, ease: [0.16, 1, 0.3, 1] }} 
          className="mt-16 sm:mt-24 mx-auto max-w-5xl rounded-2xl border border-black/10 dark:border-white/10 bg-white/50 dark:bg-zinc-900/50 backdrop-blur-xl shadow-[0_20px_50px_rgba(0,0,0,0.1)] dark:shadow-[0_20px_50px_rgba(0,0,0,0.5)] overflow-hidden"
        >
          {/* macOS window header */}
          <div className="h-12 border-b border-black/5 dark:border-white/5 flex items-center px-4 gap-2 bg-white/80 dark:bg-black/60">
            <div className="flex gap-2">
              <div className="w-3 h-3 rounded-full bg-rose-400" />
              <div className="w-3 h-3 rounded-full bg-amber-400" />
              <div className="w-3 h-3 rounded-full bg-emerald-400" />
            </div>
            <div className="mx-auto px-4 py-1 rounded-md bg-black/5 dark:bg-white/10 text-[10px] font-medium tracking-wide text-zinc-500 dark:text-zinc-400 w-64 text-center">
              jobora.app/dashboard
            </div>
          </div>
          {/* Video container */}
          <div className="aspect-[16/9] w-full relative bg-zinc-950 overflow-hidden">
            <video autoPlay loop muted playsInline className="w-full h-full object-cover">
              <source src="https://assets.mixkit.co/videos/preview/mixkit-business-people-working-together-in-an-office-4841-large.mp4" type="video/mp4" />
              <source src="/my-video.mp4" type="video/mp4" />
            </video>
            {/* Soft gradient bottom edge inside the video player to make it look premium */}
            <div className="absolute inset-0 bg-gradient-to-t from-black/40 via-transparent to-transparent pointer-events-none" />
          </div>
        </motion.div>
      </div>
    </div>
  );
}
