import React, { useState, useMemo, memo } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { updateCandidate } from '@/services/candidates';
import { toast } from 'sonner';
import { Loader2 } from 'lucide-react';

interface Candidate {
  id: string;
  name: string;
  experience_years?: number;
  tag?: string | null;
  resume_score: number;
}

interface CandidateKanbanProps {
  candidates: Candidate[];
  onRefresh?: () => void;
}

const COLUMNS = [
  { id: 'Pending', title: 'Pending', color: 'bg-slate-100 dark:bg-slate-800/40 text-slate-700 dark:text-slate-400' },
  { id: 'Strong', title: 'Strong Match', color: 'bg-green-100 dark:bg-green-900/20 text-green-700 dark:text-green-400' },
  { id: 'Medium', title: 'Medium Match', color: 'bg-yellow-100 dark:bg-yellow-900/20 text-yellow-700 dark:text-yellow-400' },
  { id: 'Reject', title: 'Rejected', color: 'bg-red-100 dark:bg-red-900/20 text-red-700 dark:text-red-400' },
];

export const CandidateKanban = memo(function CandidateKanban({ candidates, onRefresh }: CandidateKanbanProps) {
  const navigate = useNavigate();
  const [updating, setUpdating] = useState<string | null>(null);
  const [optimisticTags, setOptimisticTags] = useState<Record<string, string | null>>({});

  const handleDragStart = (e: React.DragEvent, candidateId: string) => {
    e.dataTransfer.setData('candidateId', candidateId);
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
  };

  const handleDrop = async (e: React.DragEvent, status: string) => {
    e.preventDefault();
    const candidateId = e.dataTransfer.getData('candidateId');

    if (!candidateId) return;

    const candidate = candidates.find(c => c.id === candidateId);
    const currentTag = candidate?.tag || 'Pending';
    if (candidate && currentTag !== status) {
      setUpdating(candidateId);
      // Apply optimistic update immediately
      setOptimisticTags(prev => ({ ...prev, [candidateId]: status === 'Pending' ? null : status }));
      
      try {
        await updateCandidate(candidateId, { tag: status === 'Pending' ? null : status });
        toast.success(`Moved ${candidate.name} to ${status}`);
        onRefresh?.();
      } catch (error) {
        toast.error("Failed to update status");
        // Revert optimistic update on failure
        setOptimisticTags(prev => { const n = {...prev}; delete n[candidateId]; return n; });
      } finally {
        setUpdating(null);
      }
    }
  };

  // Merge server props with any inflight optimistic changes
  const displayCandidates = useMemo(
    () => candidates.map(c => (c.id in optimisticTags ? { ...c, tag: optimisticTags[c.id] } : c)),
    [candidates, optimisticTags]
  );

  const groupedCandidates = useMemo(() => {
    const grouped: Record<string, Candidate[]> = {
      Pending: [],
      Strong: [],
      Medium: [],
      Reject: [],
    };
    for (const c of displayCandidates) {
      const key = c.tag || 'Pending';
      if (grouped[key]) grouped[key].push(c);
    }
    return grouped;
  }, [displayCandidates]);

  const columnCounts = useMemo(() => {
    const counts: Record<string, number> = { Pending: 0, Strong: 0, Medium: 0, Reject: 0 };
    for (const c of candidates) {
      const key = c.tag || 'Pending';
      if (counts[key] != null) counts[key] += 1;
    }
    return counts;
  }, [candidates]);

  return (
    <div className="grid grid-cols-1 md:grid-cols-4 gap-6 h-[calc(100vh-200px)] overflow-hidden">
      {COLUMNS.map((col) => (
        <div 
          key={col.id} 
          className="flex flex-col h-full rounded-lg border bg-muted/50"
          onDragOver={handleDragOver}
          onDrop={(e) => handleDrop(e, col.id)}
        >
          <div className={`p-4 font-semibold border-b ${col.color} rounded-t-lg flex justify-between items-center`}>
            {col.title}
              <Badge variant="secondary" className="bg-background/50">
              {columnCounts[col.id] ?? 0}
              </Badge>
            </div>
          <div className="flex-1 p-4 space-y-3 overflow-y-auto">
            {(groupedCandidates[col.id] || []).map(candidate => (
                <Card 
                  key={candidate.id}
                  draggable
                  onDragStart={(e) => handleDragStart(e, candidate.id)}
                  onClick={() => navigate(`/candidates/${candidate.id}`)}
                  className={`cursor-grab active:cursor-grabbing hover:shadow-md transition-shadow ${updating === candidate.id ? 'opacity-50' : ''}`}
                >
                  <CardContent className="p-4">
                    <div className="flex justify-between items-start mb-2">
                      <div className="flex items-center gap-2">
                        <Avatar className="h-8 w-8">
                          <AvatarFallback>{(candidate.name || '??').substring(0, 2).toUpperCase()}</AvatarFallback>
                        </Avatar>
                        <div>
                          <div className="font-medium text-sm">{candidate.name}</div>
                          <div className="text-xs text-muted-foreground">{candidate.experience_years != null ? `${candidate.experience_years} yrs exp` : "N/A"}</div>
                        </div>
                      </div>
                      <Badge variant={candidate.resume_score > 75 ? "default" : "secondary"}>
                        {candidate.resume_score}%
                      </Badge>
                    </div>
                    {updating === candidate.id && (
                      <div className="flex justify-center py-2">
                        <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                      </div>
                    )}
                  </CardContent>
                </Card>
              ))}
          </div>
        </div>
      ))}
    </div>
  );
});
