import React, { ReactNode } from 'react';

interface AuroraLayoutProps {
  children: ReactNode;
}

export default function AuroraLayout({ children }: AuroraLayoutProps) {
  return (
    <div className="relative min-h-screen bg-slate-950 text-slate-50 overflow-hidden font-sans">
      {/* Deep, Vibrant Aurora Orbs */}
      <div className="fixed inset-0 z-0 pointer-events-none">
        <div
          className="absolute -top-[20%] -left-[10%] w-[60vw] h-[60vw] rounded-full mix-blend-screen filter blur-[140px] opacity-50 bg-violet-600"
          style={{ animation: 'aurora-drift 20s infinite alternate ease-in-out' }}
        />
        <div
          className="absolute top-[10%] -right-[10%] w-[50vw] h-[50vw] rounded-full mix-blend-screen filter blur-[140px] opacity-40 bg-rose-600"
          style={{ animation: 'aurora-drift 25s infinite alternate-reverse ease-in-out' }}
        />
        <div
          className="absolute -bottom-[20%] left-[20%] w-[70vw] h-[70vw] rounded-full mix-blend-screen filter blur-[140px] opacity-40 bg-cyan-600"
          style={{ animation: 'aurora-drift 30s infinite alternate ease-in-out' }}
        />
      </div>

      <style>{`
        @keyframes aurora-drift {
          0%   { transform: translate(0px, 0px) scale(1); }
          33%  { transform: translate(40px, -60px) scale(1.1); }
          66%  { transform: translate(-30px, 30px) scale(0.9); }
          100% { transform: translate(0px, 0px) scale(1); }
        }
      `}</style>

      <main className="relative z-10">
        {children}
      </main>
    </div>
  );
}
