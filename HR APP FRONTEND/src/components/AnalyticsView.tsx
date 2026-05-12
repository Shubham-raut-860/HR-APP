import React from 'react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

import { TrendingDown, RefreshCw, BarChart2 } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';

interface SkillGapItem {
  skill: string;
  required: boolean;
  candidate_match_pct: number;
  gap_pct: number;
}

interface AnalyticsViewProps {
  skillGaps: SkillGapItem[];
  jobTitle?: string;
  onRefresh?: () => void;
  className?: string;
}

function cleanSkillLabel(skill: string, maxLen = 20): string {
  const trimmed = skill.trim();
  if (trimmed.length <= maxLen) return trimmed;
  const shortened = trimmed.split(/[,(]/)[0].trim();
  if (shortened.length > 0 && shortened.length <= maxLen) return shortened;
  return trimmed.slice(0, maxLen - 1) + "…";
}

const CustomTooltip = ({ active, payload, label }: any) => {
  if (active && payload && payload.length) {
    const match = payload.find((p: any) => p.dataKey === 'Match')?.value ?? 0;
    const gap = payload.find((p: any) => p.dataKey === 'Gap')?.value ?? 0;
    return (
      <div style={{ borderRadius: 10, border: '1px solid var(--border)', background: 'var(--background)', padding: '10px 14px', fontSize: 13 }}>
        <p style={{ fontWeight: 700, marginBottom: 4 }}>{label}</p>
        <p style={{ color: '#10b981' }}>✓ Match: {match}%</p>
        <p style={{ color: '#f43f5e' }}>✗ Gap: {gap}%</p>
      </div>
    );
  }
  return null;
};

export function AnalyticsView({ skillGaps, jobTitle, onRefresh, className }: AnalyticsViewProps) {
  const seen = new Set<string>();
  const deduped = skillGaps.filter(item => {
    const key = cleanSkillLabel(item.skill).toLowerCase();
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });

  const sorted = [...deduped].sort((a, b) => b.gap_pct - a.gap_pct).slice(0, 10);
  const hasData = sorted.length > 0;
  const allGap100 = hasData && sorted.every(s => s.gap_pct === 100);

  const chartData = sorted.map(item => ({
    name: cleanSkillLabel(item.skill),
    Match: Math.round(item.candidate_match_pct),
    Gap: Math.round(item.gap_pct),
    required: item.required,
  }));

  return (
    <Card className={className}>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="flex items-center gap-2">
              <BarChart2 className="h-5 w-5 text-primary" />
              Skill Gap Dashboard
            </CardTitle>
            <CardDescription className="mt-1">
              {jobTitle ? `Candidate pool vs. "${jobTitle}" requirements` : "Candidate pool skill coverage vs. job requirements"}
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            {hasData && (
              <div className="flex items-center gap-3 text-xs text-muted-foreground">
                <span className="flex items-center gap-1"><span className="inline-block h-2.5 w-2.5 rounded-sm bg-[#10b981]" /> Match</span>
                <span className="flex items-center gap-1"><span className="inline-block h-2.5 w-2.5 rounded-sm bg-[#f43f5e]" /> Gap</span>
              </div>
            )}
            {onRefresh && (
              <Button variant="ghost" size="sm" onClick={onRefresh}>
                <RefreshCw className="h-4 w-4" />
              </Button>
            )}
          </div>
        </div>
      </CardHeader>

      <CardContent>
        {!hasData ? (
          <div className="flex flex-col items-center justify-center py-12 text-center text-muted-foreground">
            <TrendingDown className="h-10 w-10 mb-3 opacity-30" />
            <p className="font-medium">No skill gap data yet</p>
            <p className="text-sm">Upload and process resumes to populate the charts.</p>
          </div>
        ) : allGap100 ? (
           <div className="flex flex-col items-center justify-center py-8 text-center text-amber-500">
             <p className="font-bold">⚠️ 100% gap across all skills</p>
             <p className="text-sm text-muted-foreground mt-2">No uploaded resumes match this JD yet.</p>
           </div>
        ) : (
          <div className="h-[350px] w-full mt-2">
            <ResponsiveContainer width="100%" height="100%" minWidth={1}>
              <BarChart data={chartData} layout="vertical" margin={{ top: 5, right: 10, left: 40, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" horizontal={false} vertical={true} stroke="#555" opacity={0.15} />
                <XAxis type="number" domain={[0, 100]} tickFormatter={(v) => `${v}%`} tick={{ fontSize: 11 }} />
                <YAxis
                  dataKey="name"
                  type="category"
                  width={130}
                  tick={({ x, y, payload }) => {
                    const item = chartData.find(d => d.name === payload.value);
                    return (
                      <g transform={`translate(${x},${y})`}>
                        <text x={-4} y={0} dy={4} textAnchor="end" fontSize={12} fill="var(--foreground)">{payload.value}</text>
                        {item?.required && (
                          <circle cx={-120} cy={0} r={3} fill="#f43f5e" />
                        )}
                      </g>
                    );
                  }}
                />
                <Tooltip content={<CustomTooltip />} cursor={{ fill: 'var(--muted)', opacity: 0.4 }} />
                <Bar dataKey="Match" stackId="a" fill="#10b981" radius={[0, 0, 0, 0]} />
                <Bar dataKey="Gap" stackId="a" fill="#f43f5e" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </CardContent>
    </Card>
  );
}