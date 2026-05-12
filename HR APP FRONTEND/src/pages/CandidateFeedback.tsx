import { useState, useEffect } from "react";
import { useParams } from "react-router-dom";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { BrainCircuit, Target, AlertCircle, TrendingUp, CheckCircle2, Lightbulb } from "lucide-react";
import { getMyFeedback, getMyResults } from "@/services/candidatePortal";
import { cn } from "@/lib/utils";

export default function CandidateFeedback() {
  const { id } = useParams<{ id: string }>();
  const [feedback, setFeedback] = useState<any[]>([]);
  const [results, setResults] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const loadData = async () => {
      try {
        const [feedbackData, resultsData] = await Promise.all([
          getMyFeedback(id),
          getMyResults()
        ]);

        if (feedbackData) {
          const missingSkills = (feedbackData.skill_feedback || [])
            .filter((sf: any) => !sf.candidate_has)
            .map((sf: any) => sf.skill);

          setFeedback([{
            job_title: feedbackData.job_title || "Job Application",
            missing_skills: missingSkills,
            recommended_courses: missingSkills.length > 0 ? missingSkills.join(", ") : null
          }]);
        } else {
          setFeedback([]);
        }

        setResults(Array.isArray(resultsData) ? resultsData : []);
      } catch (error) {
        console.error("Failed to load feedback");
      } finally {
        setLoading(false);
      }
    };
    loadData();
  }, [id]);

  if (loading) return (
    <div className="flex items-center justify-center h-64">
      <div className="flex flex-col items-center gap-3 text-muted-foreground">
        <div className="h-8 w-8 rounded-full border-2 border-primary border-t-transparent animate-spin" />
        <p className="text-sm">Loading your feedback...</p>
      </div>
    </div>
  );

  // BUG FIX: safe date formatter — avoids "Invalid Date" if field is undefined
  const fmtDate = (iso: string | undefined) => {
    if (!iso) return "—";
    const d = new Date(iso);
    if (isNaN(d.getTime())) return "—";
    return d.toLocaleDateString("en-GB", { day: "2-digit", month: "2-digit", year: "numeric" });
  };

  return (
    <div className="space-y-10 max-w-6xl mx-auto">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Performance & Feedback</h1>
        <p className="text-muted-foreground mt-1">Detailed insights from your assessments and applications.</p>
      </div>

      {/* ── Quiz Results ─────────────────────────────────────────────────────── */}
      <section className="space-y-4">
        <h2 className="text-xl font-semibold flex items-center gap-2">
          <BrainCircuit className="h-5 w-5 text-primary" /> Quiz Results
        </h2>
        {results.length === 0 ? (
          <Card className="bg-muted/20 border-dashed">
            <CardContent className="p-8 text-center text-muted-foreground">
              No quiz results available yet.
            </CardContent>
          </Card>
        ) : (
          <div className="grid gap-4 md:grid-cols-2">
            {results.map((res, idx) => {
              // BUG #13 FIX (MEDIUM): was hardcoded to 36 — broke for quizzes
              // with different max scores. Use dynamic value, default to 100
              // if null/zero to avoid NaN/Infinity.
              const maxScore = res.quiz_max_score && res.quiz_max_score > 0
                ? res.quiz_max_score
                : 100;
              const scorePct = res.quiz_score != null
                ? Math.round((res.quiz_score / maxScore) * 100)
                : null;
              return (
                // BUG FIX: use stable key — candidate_id may be absent, fall back to job_id + idx
                <Card key={res.candidate_id ?? `${res.job_id}-${idx}`}>
                  <CardHeader>
                    <div className="flex justify-between items-start">
                      <div>
                        <CardTitle>{res.job_title ?? "Assessment"}</CardTitle>
                        <CardDescription>
                          {/* created_at is canonical; applied_at remains a legacy alias from API */}
                          Applied on {fmtDate(res.created_at)}
                        </CardDescription>
                      </div>
                      <Badge variant={scorePct != null && scorePct >= 70 ? "default" : "secondary"}>
                        {scorePct != null ? (scorePct >= 70 ? "Passed" : "Needs Improvement") : "Pending"}
                      </Badge>
                    </div>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    {scorePct != null ? (
                      <div className="space-y-2">
                        <div className="flex justify-between text-sm">
                          <span>Quiz Score</span>
                          <span className="font-bold">{scorePct}% ({res.quiz_score}/{maxScore})</span>
                        </div>
                        <Progress value={scorePct} className={cn("h-2", scorePct >= 70 ? "bg-emerald-100" : "bg-amber-100")} />
                      </div>
                    ) : (
                      <p className="text-sm text-muted-foreground">Quiz not yet attempted.</p>
                    )}
                    <div className="grid grid-cols-3 gap-2 text-center text-sm">
                      <div className="bg-muted/30 p-2 rounded">
                        {/* BUG FIX: was `{res.resume_score ?? "—"}%` — renders "—%" when null
                            Now uses a proper conditional so null shows just "—" with no % */}
                        <div className="font-bold">
                          {res.resume_score != null ? `${res.resume_score}%` : "—"}
                        </div>
                        <div className="text-xs text-muted-foreground">Resume</div>
                      </div>
                      <div className="bg-muted/30 p-2 rounded">
                        <div className={cn("font-bold", res.final_score != null ? "text-primary" : "")}>
                          {res.final_score != null ? `${res.final_score}%` : "—"}
                        </div>
                        <div className="text-xs text-muted-foreground">Final</div>
                      </div>
                      <div className="bg-muted/30 p-2 rounded">
                        <div className={cn("font-bold text-xs",
                          res.tag === "Strong" ? "text-emerald-600" :
                          res.tag === "Medium" ? "text-amber-500" : "text-red-500"
                        )}>{res.tag ?? "—"}</div>
                        <div className="text-xs text-muted-foreground">Tag</div>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              );
            })}
          </div>
        )}
      </section>

      {/* ── Skill Analysis ────────────────────────────────────────────────────── */}
      <section className="space-y-4">
        <h2 className="text-xl font-semibold flex items-center gap-2">
          <Target className="h-5 w-5 text-primary" /> Skill Analysis
        </h2>

        {feedback.length === 0 ? (
          <Card className="bg-muted/20 border-dashed">
            <CardContent className="p-8 text-center text-muted-foreground">
              No feedback generated yet. Apply to jobs to get skill insights.
            </CardContent>
          </Card>
        ) : (
          feedback.map((item, idx) => {
            const total = item.missing_skills?.length ?? 0;
            const high   = item.missing_skills?.slice(0, Math.ceil(total / 3)) ?? [];
            const medium = item.missing_skills?.slice(Math.ceil(total / 3), Math.ceil(total * 2 / 3)) ?? [];
            const low    = item.missing_skills?.slice(Math.ceil(total * 2 / 3)) ?? [];

            return (
              <Card key={idx} className="overflow-hidden border shadow-sm">
                <div className="flex items-center gap-4 px-6 py-4 bg-muted/30 border-b">
                  <div className="h-10 w-10 rounded-full bg-primary/10 border border-primary/20 flex items-center justify-center shrink-0">
                    <Target className="h-5 w-5 text-primary" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <h3 className="font-semibold text-base leading-tight">{item.job_title}</h3>
                    <p className="text-xs text-muted-foreground mt-0.5">Based on your resume & quiz</p>
                  </div>
                  {total > 0 && (
                    <div className="flex items-center gap-2 shrink-0">
                      <div className="text-right">
                        <p className="text-2xl font-bold text-destructive leading-none">{total}</p>
                        <p className="text-[10px] text-muted-foreground uppercase tracking-wider mt-0.5">gaps found</p>
                      </div>
                    </div>
                  )}
                </div>

                {total === 0 ? (
                  <CardContent className="p-8 flex items-center justify-center gap-3 text-emerald-600">
                    <CheckCircle2 className="h-6 w-6" />
                    <p className="font-medium">No skill gaps detected — you're a great match!</p>
                  </CardContent>
                ) : (
                  <div className="grid grid-cols-1 lg:grid-cols-3 divide-y lg:divide-y-0 lg:divide-x divide-border">
                    <div className="lg:col-span-2 p-6 space-y-5">
                      <div className="flex items-center gap-2 text-sm font-semibold text-destructive">
                        <AlertCircle className="h-4 w-4" />
                        Missing Skills
                        <span className="ml-auto text-xs font-normal text-muted-foreground">
                          {total} skill{total !== 1 ? "s" : ""} to develop
                        </span>
                      </div>

                      <div className="space-y-4">
                        {high.length > 0 && (
                          <div className="space-y-2">
                            <p className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground flex items-center gap-1.5">
                              <span className="inline-block h-1.5 w-1.5 rounded-full bg-red-500" />
                              High Priority
                            </p>
                            <div className="flex flex-wrap gap-2">
                              {high.map((skill: string, si: number) => (
                                <Badge key={`high-${si}`} variant="outline"
                                  className="text-xs px-3 py-1 border-red-200 bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-300 dark:border-red-800 rounded-full">
                                  {skill}
                                </Badge>
                              ))}
                            </div>
                          </div>
                        )}
                        {medium.length > 0 && (
                          <div className="space-y-2">
                            <p className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground flex items-center gap-1.5">
                              <span className="inline-block h-1.5 w-1.5 rounded-full bg-amber-500" />
                              Medium Priority
                            </p>
                            <div className="flex flex-wrap gap-2">
                              {medium.map((skill: string, si: number) => (
                                <Badge key={`med-${si}`} variant="outline"
                                  className="text-xs px-3 py-1 border-amber-200 bg-amber-50 text-amber-700 dark:bg-amber-900/20 dark:text-amber-300 dark:border-amber-800 rounded-full">
                                  {skill}
                                </Badge>
                              ))}
                            </div>
                          </div>
                        )}
                        {low.length > 0 && (
                          <div className="space-y-2">
                            <p className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground flex items-center gap-1.5">
                              <span className="inline-block h-1.5 w-1.5 rounded-full bg-blue-400" />
                              Good to Know
                            </p>
                            <div className="flex flex-wrap gap-2">
                              {low.map((skill: string, si: number) => (
                                <Badge key={`low-${si}`} variant="outline"
                                  className="text-xs px-3 py-1 border-blue-200 bg-blue-50 text-blue-700 dark:bg-blue-900/20 dark:text-blue-300 dark:border-blue-800 rounded-full">
                                  {skill}
                                </Badge>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>

                      <div className="pt-2 space-y-1.5">
                        <div className="flex justify-between text-xs text-muted-foreground">
                          <span>Skill coverage estimate</span>
                          <span className="font-medium">
                            {Math.max(0, 100 - Math.round((total / Math.max(total + 3, 10)) * 100))}%
                          </span>
                        </div>
                        <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
                          <div
                            className="h-full rounded-full bg-gradient-to-r from-red-400 to-amber-400 transition-all"
                            style={{ width: `${Math.max(0, 100 - Math.round((total / Math.max(total + 3, 10)) * 100))}%` }}
                          />
                        </div>
                      </div>
                    </div>

                    <div className="p-6 bg-muted/10 flex flex-col gap-4">
                      <div className="flex items-center gap-2 text-sm font-semibold">
                        <Lightbulb className="h-4 w-4 text-amber-500" />
                        Recommended Focus
                      </div>
                      <p className="text-xs text-muted-foreground leading-relaxed">
                        To strengthen your application, prioritise upskilling in:
                      </p>
                      <ol className="space-y-2.5 flex-1">
                        {item.missing_skills?.slice(0, 6).map((skill: string, si: number) => (
                          <li key={si} className="flex items-start gap-2.5 text-sm">
                            <span className="flex-shrink-0 h-5 w-5 rounded-full bg-primary/10 text-primary text-[10px] font-bold flex items-center justify-center mt-0.5">
                              {si + 1}
                            </span>
                            <span className="text-foreground/80 leading-snug">{skill}</span>
                          </li>
                        ))}
                        {total > 6 && (
                          <li className="text-xs text-muted-foreground pl-7">
                            +{total - 6} more skills identified above
                          </li>
                        )}
                      </ol>
                      <div className="mt-auto pt-4 border-t border-border">
                        <div className="flex items-center gap-2 text-xs text-muted-foreground">
                          <TrendingUp className="h-3.5 w-3.5 text-emerald-500" />
                          Addressing these gaps can significantly improve your match score.
                        </div>
                      </div>
                    </div>
                  </div>
                )}
              </Card>
            );
          })
        )}
      </section>
    </div>
  );
}
