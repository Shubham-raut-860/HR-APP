import * as React from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { AnimatePresence, motion } from "framer-motion";
import {
  BrainCircuit,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Code2,
  Filter,
  RefreshCw,
  Search,
  ShieldAlert,
  Users,
  XCircle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import {
  CandidateAnswerSheet,
  getQuizAnswerSheet,
  QuizMasterAnswerSheet,
} from "@/services/quiz";
import { toast } from "sonner";

type QuizLite = {
  id: string;
  title: string;
  question_count: number;
  duration_minutes: number;
  is_active: boolean;
  created_at: string;
};

type Props = {
  quizzes: QuizLite[];
};

function toPct(v: number | null | undefined): number {
  if (typeof v !== "number" || Number.isNaN(v)) return 0;
  return Math.max(0, Math.min(100, Math.round(v)));
}

function summarizeAnswerCell(answer: unknown): string {
  if (answer == null) return "No answer";
  if (typeof answer === "string") return answer;
  if (typeof answer === "number") return String(answer);
  if (typeof answer === "boolean") return answer ? "True" : "False";
  if (Array.isArray(answer)) return `${answer.length} item(s)`;
  if (typeof answer === "object") return "Structured response";
  return "Response";
}

export function InterviewKitPanel({ quizzes }: Props) {
  const [selectedQuizId, setSelectedQuizId] = React.useState<string>("");
  const [passedOnly, setPassedOnly] = React.useState(true);
  const [loading, setLoading] = React.useState(false);
  const [sheet, setSheet] = React.useState<QuizMasterAnswerSheet | null>(null);
  const [expandedAttemptId, setExpandedAttemptId] = React.useState<string | null>(null);
  const [search, setSearch] = React.useState("");

  React.useEffect(() => {
    if (!selectedQuizId && quizzes.length > 0) {
      setSelectedQuizId(quizzes[0].id);
    }
  }, [quizzes, selectedQuizId]);

  const loadSheet = React.useCallback(async () => {
    if (!selectedQuizId) return;
    setLoading(true);
    try {
      const data = await getQuizAnswerSheet(selectedQuizId, passedOnly);
      setSheet(data);
      if (!data.candidates.some(c => c.attempt_id === expandedAttemptId)) {
        setExpandedAttemptId(data.candidates[0]?.attempt_id ?? null);
      }
    } catch (e: any) {
      toast.error(e?.response?.data?.detail || "Failed to load interview kit");
      setSheet(null);
      setExpandedAttemptId(null);
    } finally {
      setLoading(false);
    }
  }, [expandedAttemptId, passedOnly, selectedQuizId]);

  React.useEffect(() => {
    if (!selectedQuizId) return;
    loadSheet();
  }, [selectedQuizId, passedOnly, loadSheet]);

  const filteredCandidates = React.useMemo(() => {
    const q = search.trim().toLowerCase();
    const all = sheet?.candidates ?? [];
    if (!q) return all;
    return all.filter((c) =>
      (c.candidate_name || "").toLowerCase().includes(q) ||
      (c.candidate_email || "").toLowerCase().includes(q),
    );
  }, [search, sheet]);

  const scoreData = React.useMemo(() => {
    return filteredCandidates
      .slice()
      .sort((a, b) => b.percentage - a.percentage)
      .slice(0, 12)
      .map((c, idx) => ({
        name: c.candidate_name || c.candidate_email || `Candidate ${idx + 1}`,
        score: toPct(c.percentage),
      }));
  }, [filteredCandidates]);

  const skillData = React.useMemo(() => {
    const skillMap = new Map<string, { correct: number; total: number }>();
    for (const cand of filteredCandidates) {
      for (const ans of cand.answers || []) {
        if (ans.question_type !== "mcq") continue;
        const skill = ans.skill_tag || "General";
        const row = skillMap.get(skill) || { correct: 0, total: 0 };
        row.total += 1;
        if (ans.is_correct === true) row.correct += 1;
        skillMap.set(skill, row);
      }
    }
    return Array.from(skillMap.entries())
      .map(([skill, v]) => ({
        skill,
        accuracy: v.total > 0 ? Math.round((v.correct / v.total) * 100) : 0,
        total: v.total,
      }))
      .sort((a, b) => b.total - a.total)
      .slice(0, 8);
  }, [filteredCandidates]);

  const stat = React.useMemo(() => {
    const candidates = filteredCandidates;
    if (!candidates.length) {
      return { avgScore: 0, passed: 0, failed: 0, codingSubs: 0 };
    }
    let scoreTotal = 0;
    let passedCount = 0;
    let failedCount = 0;
    let codingSubs = 0;
    for (const c of candidates) {
      scoreTotal += c.percentage || 0;
      if (c.passed === true) passedCount += 1;
      if (c.passed === false) failedCount += 1;
      if ((c.answers || []).some((a) => a.question_type === "coding")) codingSubs += 1;
    }
    return {
      avgScore: Math.round(scoreTotal / candidates.length),
      passed: passedCount,
      failed: failedCount,
      codingSubs,
    };
  }, [filteredCandidates]);

  const selectedQuiz = quizzes.find((q) => q.id === selectedQuizId);

  return (
    <div className="space-y-5">
      <Card className="border-border/60">
        <CardHeader className="pb-3">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <CardTitle className="text-base flex items-center gap-2">
                <BrainCircuit className="h-4 w-4 text-primary" />
                Interview Kit
              </CardTitle>
              <CardDescription>
                Master answer sheet for recruiter interviews: candidate responses, correctness, and coding artifacts.
              </CardDescription>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Select value={selectedQuizId} onValueChange={setSelectedQuizId}>
                <SelectTrigger className="w-[280px]">
                  <SelectValue placeholder="Select a quiz" />
                </SelectTrigger>
                <SelectContent>
                  {quizzes.map((quiz) => (
                    <SelectItem key={quiz.id} value={quiz.id}>
                      {quiz.title}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button variant="outline" size="sm" onClick={loadSheet} disabled={loading || !selectedQuizId}>
                {loading ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
                Refresh
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex items-center gap-2 text-sm">
              <Filter className="h-4 w-4 text-muted-foreground" />
              <Label htmlFor="passed-only">Passed candidates only</Label>
              <Switch id="passed-only" checked={passedOnly} onCheckedChange={setPassedOnly} />
            </div>
            <div className="relative w-full lg:w-[320px]">
              <Search className="h-4 w-4 text-muted-foreground absolute left-2.5 top-2.5" />
              <Input
                className="pl-8"
                placeholder="Search candidate name/email"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
          </div>

          {selectedQuiz && (
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <Badge variant="outline">{selectedQuiz.question_count} questions</Badge>
              <Badge variant="outline">{selectedQuiz.duration_minutes} min</Badge>
              <Badge variant="outline">{sheet?.total_candidates ?? 0} candidate rows</Badge>
            </div>
          )}
        </CardContent>
      </Card>

      {!selectedQuizId ? (
        <Card className="p-12 text-center border-dashed text-muted-foreground">
          Create a quiz first to open interview kit.
        </Card>
      ) : loading ? (
        <Card className="p-12 text-center text-muted-foreground">
          <div className="h-6 w-6 rounded-full border-2 border-primary border-t-transparent animate-spin mx-auto mb-3" />
          Loading answer sheet...
        </Card>
      ) : !sheet || filteredCandidates.length === 0 ? (
        <Card className="p-12 text-center border-dashed text-muted-foreground">
          No candidate answer sheet rows for this selection.
        </Card>
      ) : (
        <>
          <div className="grid gap-4 md:grid-cols-4">
            <Card><CardContent className="pt-5"><p className="text-xs text-muted-foreground">Candidates</p><p className="text-2xl font-semibold">{filteredCandidates.length}</p></CardContent></Card>
            <Card><CardContent className="pt-5"><p className="text-xs text-muted-foreground">Average Score</p><p className="text-2xl font-semibold">{stat.avgScore}%</p></CardContent></Card>
            <Card><CardContent className="pt-5"><p className="text-xs text-muted-foreground">Passed</p><p className="text-2xl font-semibold text-emerald-600">{stat.passed}</p></CardContent></Card>
            <Card><CardContent className="pt-5"><p className="text-xs text-muted-foreground">Coding Submissions</p><p className="text-2xl font-semibold text-blue-600">{stat.codingSubs}</p></CardContent></Card>
          </div>

          <div className="grid gap-4 xl:grid-cols-2">
            <Card className="min-h-[320px]">
              <CardHeader className="pb-1">
                <CardTitle className="text-sm">Candidate Score Distribution</CardTitle>
              </CardHeader>
              <CardContent className="h-[260px]">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={scoreData}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="name" tick={{ fontSize: 11 }} interval={0} angle={-20} textAnchor="end" height={65} />
                    <YAxis domain={[0, 100]} />
                    <Tooltip />
                    <Bar dataKey="score" radius={[8, 8, 0, 0]}>
                      {scoreData.map((r, idx) => (
                        <Cell key={idx} fill={r.score >= 70 ? "#16a34a" : r.score >= 55 ? "#f59e0b" : "#ef4444"} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>

            <Card className="min-h-[320px]">
              <CardHeader className="pb-1">
                <CardTitle className="text-sm">Skill Accuracy Heat</CardTitle>
              </CardHeader>
              <CardContent className="h-[260px]">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={skillData} layout="vertical" margin={{ left: 20, right: 10 }}>
                    <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                    <XAxis type="number" domain={[0, 100]} />
                    <YAxis type="category" dataKey="skill" width={120} tick={{ fontSize: 11 }} />
                    <Tooltip formatter={(value: any) => [`${value}%`, "Accuracy"]} />
                    <Bar dataKey="accuracy" radius={[0, 8, 8, 0]}>
                      {skillData.map((r, idx) => (
                        <Cell key={idx} fill={r.accuracy >= 70 ? "#16a34a" : r.accuracy >= 55 ? "#f59e0b" : "#ef4444"} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm">Candidate Answer Ledger</CardTitle>
              <CardDescription>Expand a candidate to inspect exact answers, correctness, and coding submission evidence.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {filteredCandidates.map((c) => {
                const isOpen = expandedAttemptId === c.attempt_id;
                const mcq = c.answers.filter((a) => a.question_type === "mcq");
                const correct = mcq.filter((a) => a.is_correct === true).length;
                const accuracy = mcq.length > 0 ? Math.round((correct / mcq.length) * 100) : 0;
                const hasCoding = c.answers.some((a) => a.question_type === "coding");
                return (
                  <div key={c.attempt_id} className="rounded-lg border border-border/60 overflow-hidden">
                    <button
                      type="button"
                      onClick={() => setExpandedAttemptId((prev) => prev === c.attempt_id ? null : c.attempt_id)}
                      className="w-full px-4 py-3 bg-muted/20 hover:bg-muted/40 transition-colors text-left flex items-center justify-between gap-3"
                    >
                      <div className="min-w-0">
                        <p className="font-medium truncate">{c.candidate_name || c.candidate_email || "Candidate"}</p>
                        <p className="text-xs text-muted-foreground truncate">{c.candidate_email || "No email"}</p>
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        <Badge className={cn(c.passed ? "bg-emerald-600" : "bg-amber-600")}>
                          {c.percentage.toFixed(0)}%
                        </Badge>
                        <Badge variant="outline">MCQ {accuracy}%</Badge>
                        {hasCoding && <Badge variant="outline"><Code2 className="h-3 w-3 mr-1" />Coding</Badge>}
                        {isOpen ? <ChevronUp className="h-4 w-4 text-muted-foreground" /> : <ChevronDown className="h-4 w-4 text-muted-foreground" />}
                      </div>
                    </button>
                    <AnimatePresence initial={false}>
                      {isOpen && (
                        <motion.div
                          initial={{ height: 0, opacity: 0 }}
                          animate={{ height: "auto", opacity: 1 }}
                          exit={{ height: 0, opacity: 0 }}
                          transition={{ duration: 0.2 }}
                          className="overflow-hidden"
                        >
                          <div className="p-4 space-y-2">
                            {c.answers.map((a, idx) => (
                              <div key={`${a.question_id}-${idx}`} className="rounded-md border border-border/60 p-3">
                                <div className="flex items-start justify-between gap-3">
                                  <p className="text-sm font-medium leading-snug">{a.question_text}</p>
                                  {a.question_type === "coding" ? (
                                    <Badge variant="outline"><Code2 className="h-3 w-3 mr-1" />Coding</Badge>
                                  ) : a.is_correct ? (
                                    <Badge className="bg-emerald-600"><CheckCircle2 className="h-3 w-3 mr-1" />Correct</Badge>
                                  ) : (
                                    <Badge variant="destructive"><XCircle className="h-3 w-3 mr-1" />Incorrect</Badge>
                                  )}
                                </div>
                                <div className="mt-2 grid gap-2 md:grid-cols-2 text-xs">
                                  <div className="rounded bg-muted/30 p-2">
                                    <p className="text-muted-foreground mb-0.5">Candidate answer</p>
                                    <p className="font-medium">{a.selected_option_text || summarizeAnswerCell(a.selected_answer)}</p>
                                  </div>
                                  <div className={cn("rounded p-2", a.question_type === "coding" ? "bg-blue-50/60 dark:bg-blue-950/20" : "bg-emerald-50/60 dark:bg-emerald-950/20")}>
                                    <p className="text-muted-foreground mb-0.5">
                                      {a.question_type === "coding" ? "Evaluation" : "Correct answer"}
                                    </p>
                                    <p className="font-medium">
                                      {a.question_type === "coding"
                                        ? `Score ${a.score_awarded ?? 0}/${a.max_score ?? 10}`
                                        : (a.correct_option_text || "Not available")}
                                    </p>
                                  </div>
                                </div>
                              </div>
                            ))}
                          </div>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </div>
                );
              })}
            </CardContent>
          </Card>
        </>
      )}

      {sheet && filteredCandidates.some(c => c.passed !== true) && !passedOnly && (
        <Card className="border-amber-300/50 bg-amber-50/40 dark:bg-amber-950/10">
          <CardContent className="py-3 text-sm flex items-center gap-2 text-amber-800 dark:text-amber-200">
            <ShieldAlert className="h-4 w-4" />
            Showing failed/unrated attempts too. For interview focus mode, enable "Passed candidates only".
          </CardContent>
        </Card>
      )}
    </div>
  );
}

