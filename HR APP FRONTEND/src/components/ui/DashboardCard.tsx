import React, { ComponentType } from 'react';
import { motion } from 'framer-motion';

interface DashboardCardProps {
  title: string;
  value: string | number;
  trend: number;
  icon: ComponentType<{ className?: string }>;
}

export default function DashboardCard({ title, value, trend, icon: Icon }: DashboardCardProps) {
  const isPositive = trend >= 0;

  return (
    <motion.div
      whileHover={{ y: -6, scale: 1.02 }}
      whileTap={{ scale: 0.97 }}
      transition={{ type: 'spring', stiffness: 400, damping: 25 }}
      className="relative overflow-hidden p-6 rounded-3xl border border-white/10 bg-white/5 backdrop-blur-3xl shadow-[0_8px_32px_rgb(0,0,0,0.4)]"
    >
      {/* Subtle light sweep on hover */}
      <div className="absolute -inset-px bg-gradient-to-br from-white/20 to-transparent opacity-0 hover:opacity-100 transition-opacity duration-500 rounded-3xl pointer-events-none" />

      <div className="flex items-start justify-between relative z-10">
        <div>
          <p className="text-xs font-semibold text-slate-400 mb-1 tracking-widest uppercase">{title}</p>
          <h3 className="text-4xl font-bold text-white tracking-tight">{value}</h3>
        </div>
        <div className="p-3 bg-white/10 rounded-2xl text-white shadow-inner border border-white/10 backdrop-blur-md">
          <Icon className="w-6 h-6 stroke-[1.5]" />
        </div>
      </div>

      <div className="mt-6 flex items-center text-sm font-medium relative z-10">
        <span className={`px-2 py-1 rounded-lg border ${isPositive ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/20' : 'bg-rose-500/20 text-rose-300 border-rose-500/20'}`}>
          {isPositive ? '+' : ''}{trend}%
        </span>
        <span className="ml-3 text-slate-500">vs last month</span>
      </div>
    </motion.div>
  );
}
