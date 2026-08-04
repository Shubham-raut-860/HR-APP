import { BookOpen, Clock, Eye, Link2, Send } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

function difficultyPillClass(label: string): string {
  const normalized = label.trim().toLowerCase();
  if (normalized.includes("easy")) {
    return "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400";
  }
  if (normalized.includes("medium")) {
    return "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400";
  }
  if (normalized.includes("hard")) {
    return "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400";
  }
  return "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300";
}

interface QuizDifficultyCardProps {
  quiz: {
    id: string;
    title: string;
    question_count: number;
    duration_minutes: number;
    is_active: boolean;
    created_at: string;
  };
  difficultyEntries: Array<[string, number]>;
  loadingQuestions: boolean;
  shortlistedCount: number;
  sendingQuiz: boolean;
  onShowQuiz: () => void;
  onShareMagicLink: () => void;
  onSendToShortlisted: () => void;
}

export function QuizDifficultyCard({
  quiz,
  difficultyEntries,
  loadingQuestions,
  shortlistedCount,
  sendingQuiz,
  onShowQuiz,
  onShareMagicLink,
  onSendToShortlisted,
}: QuizDifficultyCardProps) {
  return (
    <Card className="overflow-hidden">
      <CardHeader className="pb-3 border-b border-border/50">
        <div className="flex items-start justify-between gap-3">
          <div className="flex-1 min-w-0">
            <CardTitle className="text-base leading-snug">{quiz.title}</CardTitle>
            <div className="flex items-center gap-3 mt-1 text-xs text-muted-foreground">
              <span className="flex items-center gap-1"><BookOpen className="h-3 w-3" />{quiz.question_count} questions</span>
              <span className="flex items-center gap-1"><Clock className="h-3 w-3" />{quiz.duration_minutes} min</span>
              <span>{new Date(quiz.created_at).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" })}</span>
            </div>
          </div>
          <Badge variant={quiz.is_active ? "default" : "secondary"} className="shrink-0 text-xs">
            {quiz.is_active ? "Active" : "Inactive"}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="pt-4 space-y-4">
        <div className="flex gap-2">
          {difficultyEntries.length > 0 ? difficultyEntries.map(([label, count]) => (
            <span key={label} className={cn("inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold", difficultyPillClass(label))}>
              {count} {label}
            </span>
          )) : (
            <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold bg-muted text-muted-foreground">
              Distribution unavailable
            </span>
          )}
        </div>

        <div className="flex flex-wrap gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={onShowQuiz}
            disabled={loadingQuestions}
            className="gap-1.5"
          >
            {loadingQuestions
              ? <div className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" />
              : <Eye className="h-3.5 w-3.5" />
            }
            Show Quiz
          </Button>

          <Button
            variant="outline"
            size="sm"
            onClick={onShareMagicLink}
            disabled={sendingQuiz || shortlistedCount === 0}
            className="gap-1.5"
          >
            {sendingQuiz
              ? <div className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" />
              : <Link2 className="h-3.5 w-3.5" />
            }
            Share magic link
            {shortlistedCount > 0 && (
              <span className="ml-0.5 px-1.5 py-0.5 bg-primary/10 text-primary text-[10px] font-bold rounded-full">{shortlistedCount}</span>
            )}
          </Button>

          <Button
            size="sm"
            onClick={onSendToShortlisted}
            disabled={sendingQuiz || shortlistedCount === 0}
            className="ml-auto gap-1.5"
          >
            {sendingQuiz
              ? <><div className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" />Sendingâ€¦</>
              : <><Send className="h-3.5 w-3.5" />Send to {shortlistedCount} shortlisted</>
            }
          </Button>
        </div>

        {shortlistedCount === 0 && (
          <p className="text-xs text-muted-foreground text-center py-1 border border-dashed rounded-lg">
            Shortlist candidates first (in the Shortlist tab) before sending quiz links.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
