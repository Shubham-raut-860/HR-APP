import * as React from 'react';
import { useState, useEffect, useRef, useCallback } from 'react';
import { useSearchParams, useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '@/context/AuthContext';
import { Card, CardContent, CardHeader, CardTitle, CardFooter } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { toast } from "sonner";
import { Clock, CheckCircle, AlertTriangle } from 'lucide-react';
import { reportTabSwitch, startQuiz, submitQuiz } from '@/services/quiz';
import type { QuizResult } from '@/services/quiz';
import { cn } from '@/lib/utils';

const QUIZ_TOKEN_STORAGE_KEY = 'quiz_access_token';

const normalizeToken = (raw: string | null | undefined): string | null => {
  if (!raw || raw === 'null' || raw === 'undefined') return null;
  return raw;
};

export default function QuizEngine() {
  const [searchParams] = useSearchParams();
  const location = useLocation();
  const queryToken = normalizeToken(searchParams.get('token'));
  const stateToken = normalizeToken((location.state as { quizToken?: string } | null)?.quizToken);
  const storedToken = normalizeToken(sessionStorage.getItem(QUIZ_TOKEN_STORAGE_KEY));
  const token = stateToken || storedToken || queryToken;
  const { user, loading: authLoading } = useAuth();
  const navigate = useNavigate();

  const [loading, setLoading]       = useState(true);
  const [errorMsg, setErrorMsg]     = useState("");
  const [quizData, setQuizData]     = useState<any>(null);
  const [timeLeft, setTimeLeft]     = useState(0);
  const [mode, setMode]             = useState<'mcq' | 'result'>('mcq');
  const [currentQ, setCurrentQ]     = useState(0);
  const [answers, setAnswers]       = useState<Record<string, number>>({});
  const [tabSwitches, setTabSwitches] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult]         = useState<QuizResult | null>(null);
  const [confirmSubmitOpen, setConfirmSubmitOpen] = useState(false);

  // Synchronous guard — prevents timer auto-submit and button click from racing
  const isSubmittingRef = useRef(false);
  const endTimeRef = useRef<number | null>(null);

  // Compatibility path: if token came from URL query (old links), persist it in
  // session storage and scrub it from the address bar immediately.
  useEffect(() => {
    if (queryToken) {
      sessionStorage.setItem(QUIZ_TOKEN_STORAGE_KEY, queryToken);
      navigate('/take-quiz', {
        replace: true,
        state: { quizToken: queryToken },
      });
      return;
    }
    if (stateToken) {
      sessionStorage.setItem(QUIZ_TOKEN_STORAGE_KEY, stateToken);
    }
  }, [queryToken, stateToken, navigate]);

  // ── Load quiz ────────────────────────────────────────────────────────────────
  useEffect(() => {
    if (authLoading) return;
    if (!token) {
      setErrorMsg("Security Error: No assessment token found in the URL.");
      setLoading(false);
      return;
    }

    startQuiz(token).then(data => {
      setQuizData(data);
      // FIX (Bug #2 - HIGH): was `data.duration_minutes * 60`, which always reset
      // the countdown to the full duration even when resuming a partially-done quiz.
      // The backend now computes the true remaining seconds server-side.
      endTimeRef.current = Date.now() + data.time_remaining_seconds * 1000;
      setTimeLeft(data.time_remaining_seconds);
      setLoading(false);
    }).catch(err => {
      sessionStorage.removeItem(QUIZ_TOKEN_STORAGE_KEY);
      setErrorMsg(err.response?.data?.detail || "This assessment link is invalid, has expired, or was already submitted.");
      setLoading(false);
    });
  }, [token, user, authLoading, navigate]);

  // ── Timer countdown ──────────────────────────────────────────────────────────
  // BUG #12 FIX (MEDIUM): Removed `timeLeft` from the dependency array.
  // setTimeLeft(prev => prev - 1) uses functional form, so it always reads
  // the latest value via React's internal state. Including `timeLeft` caused
  // the interval to be torn down + recreated every second — wasteful and a
  // potential source of timer drift.
  useEffect(() => {
    if (timeLeft <= 0 || mode === 'result' || !quizData) return;
    const timer = setInterval(() => {
      if (!endTimeRef.current) return;
      const remaining = Math.max(0, Math.floor((endTimeRef.current - Date.now()) / 1000));
      setTimeLeft(remaining);
    }, 1000);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, quizData]);

  // ── Submit ───────────────────────────────────────────────────────────────────
  // Wrapped in useCallback so the auto-submit effect below always captures the
  // latest `answers` and `tabSwitches` values instead of the stale closure from
  // the first render. Without useCallback the effect dep array would include a
  // function reference that changes every render, causing excessive re-runs.
  const handleFinalSubmit = useCallback(async () => {
    if (!quizData?.attempt_id) return;
    if (isSubmittingRef.current) return;
    isSubmittingRef.current = true;
    setSubmitting(true);
    toast.info("Submitting your assessment…");
    try {
      const quizResult = await submitQuiz(String(quizData.attempt_id), answers, tabSwitches);
      setResult(quizResult);
        setMode('result');
        sessionStorage.removeItem(QUIZ_TOKEN_STORAGE_KEY);
      toast.success("Assessment submitted — the hiring team will be in touch soon.");
    } catch (error: any) {
      // 409 means the quiz was already submitted (e.g. a duplicate fire from the
      // auto-submit timer racing with a manual click). Treat it as success so the
      // candidate sees the result screen rather than a confusing error toast.
      if (error?.response?.status === 409 || error?.response?.status === 400) {
        const detail: string = error?.response?.data?.detail ?? "";
        if (detail.toLowerCase().includes("already") || detail.toLowerCase().includes("finalized") || detail.toLowerCase().includes("expired")) {
          toast.info("Assessment already submitted. Check your dashboard for results.");
            setMode('result');
            sessionStorage.removeItem(QUIZ_TOKEN_STORAGE_KEY);
          isSubmittingRef.current = true; // keep locked — don't allow retry
          setSubmitting(false);
          return;
        }
      }
      toast.error("Failed to submit assessment. Please try again.");
      // Only clear the ref on a real failure so the candidate can retry.
      // Don't clear it on a timeout/cancel — the request may still be
      // in-flight on the server and double-submitting would cause a 400.
      const isCancelled =
        error?.code === "ECONNABORTED" ||
        error?.name === "CanceledError" ||
        error?.message?.includes("timeout");
      if (!isCancelled) {
        isSubmittingRef.current = false;
      }
    } finally {
      setSubmitting(false);
    }
  }, [quizData, answers, tabSwitches]);

  // ── Auto-submit on timeout ───────────────────────────────────────────────────
  // handleFinalSubmit is now stable (useCallback) so including it here is safe
  // and ensures the effect always sees the latest answers/tabSwitches.
  useEffect(() => {
    if (quizData && timeLeft === 0 && mode !== 'result') {
      handleFinalSubmit();
    }
  }, [timeLeft, quizData, mode, handleFinalSubmit]);

  // ── Proctor: tab-switch detection ───────────────────────────────────────────
  useEffect(() => {
    if (!quizData || mode === 'result') return;
    const onHide = () => {
      // Always sync timer accuracy on visibility change
      if (endTimeRef.current) {
        const remaining = Math.max(0, Math.floor((endTimeRef.current - Date.now()) / 1000));
        setTimeLeft(remaining);
      }

      if (document.hidden) {
        setTabSwitches(prev => prev + 1);
        if (quizData?.attempt_id) {
          reportTabSwitch(String(quizData.attempt_id)).catch(() => {
            // Best-effort anti-cheat signal; quiz flow should continue if tracking fails.
          });
        }
        toast.warning("⚠️ PROCTOR WARNING: Please stay on this tab. Leaving the test environment is recorded.");
      }
    };
    document.addEventListener("visibilitychange", onHide);
    return () => document.removeEventListener("visibilitychange", onHide);
  }, [quizData, mode]);

  // ── Loading / error states ───────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="p-12 text-center text-lg animate-pulse text-muted-foreground">
        Initializing Secure Test Environment…
      </div>
    );
  }

  if (errorMsg) {
    return (
      <div className="min-h-screen bg-muted/30 flex items-center justify-center p-4">
        <Card className="max-w-md w-full shadow-2xl border-red-500/30">
          <CardHeader className="text-center pt-8">
            <div className="mx-auto w-16 h-16 bg-red-100 text-red-600 rounded-full flex items-center justify-center mb-4">
              <AlertTriangle className="h-8 w-8" />
            </div>
            <CardTitle className="text-2xl">Access Denied</CardTitle>
          </CardHeader>
          <CardContent className="text-center text-muted-foreground pb-6">{errorMsg}</CardContent>
          <CardFooter className="bg-muted/20 p-4 flex justify-center">
            <Button onClick={() => navigate('/candidate/dashboard')}>Return to Dashboard</Button>
          </CardFooter>
        </Card>
      </div>
    );
  }

  // FIX F-11: Guard against empty quiz — prevents blank countdown + silent empty submission
  const totalQ = quizData?.questions?.length ?? 0;
  if (quizData && totalQ === 0) {
    return (
      <div className="min-h-screen bg-muted/30 flex items-center justify-center p-4">
        <Card className="max-w-md w-full shadow-2xl border-amber-500/30">
          <CardHeader className="text-center pt-8">
            <div className="mx-auto w-16 h-16 bg-amber-100 text-amber-600 rounded-full flex items-center justify-center mb-4">
              <AlertTriangle className="h-8 w-8" />
            </div>
            <CardTitle className="text-2xl">No Questions Available</CardTitle>
          </CardHeader>
          <CardContent className="text-center text-muted-foreground pb-6">
            This assessment has no questions configured yet. Please contact the hiring team.
          </CardContent>
          <CardFooter className="bg-muted/20 p-4 flex justify-center">
            <Button onClick={() => navigate('/candidate/dashboard')}>Return to Dashboard</Button>
          </CardFooter>
        </Card>
      </div>
    );
  }

  const q            = quizData?.questions[currentQ];
  const answeredCount = Object.keys(answers).length;
  const unansweredCount = Math.max(0, totalQ - answeredCount);
  const isLastQ      = currentQ === totalQ - 1;
  const firstUnansweredIndex = quizData?.questions?.findIndex((question: any) => answers[question.id] == null) ?? -1;

  // ── Main render ──────────────────────────────────────────────────────────────
  return (
    <div
      className="min-h-screen bg-muted/30 p-4 sm:p-8 select-none"
      onCopy={e => e.preventDefault()}
      onPaste={e => e.preventDefault()}
    >
      <div className="max-w-3xl mx-auto space-y-6">

        {/* ── Header bar ────────────────────────────────────────────────────── */}
        {mode === 'mcq' && (
          <div className="flex items-center justify-between bg-background p-4 rounded-lg shadow-sm border border-border/50">
            <div>
              <h2 className="font-bold text-lg">Technical Assessment</h2>
              <p className="text-xs text-muted-foreground mt-0.5">
                {answeredCount} / {totalQ} answered
              </p>
              {unansweredCount > 0 && (
                <p className="text-xs text-amber-600 mt-1">
                  {unansweredCount} unanswered question{unansweredCount === 1 ? "" : "s"} remaining.
                </p>
              )}
            </div>
            <div className="text-right">
              <div className="text-sm font-medium flex items-center justify-end gap-1 text-muted-foreground">
                <Clock className="h-4 w-4" /> Time Remaining
              </div>
              <div className={cn(
                "text-xl font-mono font-bold",
                timeLeft < 300 ? "text-red-500 animate-pulse" : ""
              )}>
                {Math.floor(timeLeft / 60)}:{(timeLeft % 60).toString().padStart(2, '0')}
              </div>
            </div>
          </div>
        )}

        {mode === 'mcq' && unansweredCount > 0 && firstUnansweredIndex >= 0 && (
          <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm flex items-center justify-between gap-3">
            <span className="text-amber-800">
              Review incomplete answers before submitting for best result quality.
            </span>
            <Button
              size="sm"
              variant="outline"
              className="border-amber-300 text-amber-800 hover:bg-amber-100"
              onClick={() => setCurrentQ(firstUnansweredIndex)}
            >
              Go to next unanswered
            </Button>
          </div>
        )}

        {/* ── MCQ section ───────────────────────────────────────────────────── */}
        {mode === 'mcq' && q && (
          <Card className="border-t-4 border-t-primary shadow-lg">
            <CardHeader className="bg-muted/20 border-b pb-4">
              <div className="flex justify-between items-center mb-2">
                <Badge variant="outline">Multiple Choice</Badge>
                <span className="text-sm font-medium">
                  Question {currentQ + 1} of {totalQ}
                </span>
              </div>
              <Progress value={((currentQ + 1) / totalQ) * 100} className="h-2" />
              <div className="mt-3 flex flex-wrap gap-1.5">
                {quizData.questions.map((question: any, idx: number) => {
                  const isAnswered = answers[question.id] != null;
                  const isCurrent = idx === currentQ;
                  return (
                    <button
                      key={question.id}
                      type="button"
                      onClick={() => setCurrentQ(idx)}
                      className={cn(
                        "h-7 min-w-7 rounded-md border px-2 text-[11px] font-medium transition-colors",
                        isCurrent
                          ? "border-primary bg-primary text-primary-foreground"
                          : isAnswered
                            ? "border-emerald-300 bg-emerald-50 text-emerald-700 dark:border-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-300"
                            : "border-border bg-background text-muted-foreground hover:border-primary/40 hover:text-foreground",
                      )}
                    >
                      {idx + 1}
                    </button>
                  );
                })}
              </div>
            </CardHeader>

            <CardContent className="pt-6">
              <h3 className="text-lg font-medium mb-6 leading-relaxed">{q.question_text}</h3>
              <div className="space-y-3">
                {q.options.map((opt: string, i: number) => {
                  const selected = answers[q.id] === i;
                  return (
                    <button
                      key={i}
                      type="button"
                      onClick={() => setAnswers({ ...answers, [q.id]: i })}
                      className={cn(
                        "w-full flex items-center gap-3 p-4 rounded-lg border text-left transition-none",
                        selected
                          ? "border-primary bg-primary/5 text-foreground"
                          : "border-border bg-background hover:border-primary/40 hover:bg-muted/40 text-foreground"
                      )}
                    >
                      {/* Custom radio circle — no Radix animations */}
                      <span className={cn(
                        "flex-shrink-0 h-4 w-4 rounded-full border-2 flex items-center justify-center",
                        selected ? "border-primary" : "border-muted-foreground/40"
                      )}>
                        {selected && (
                          <span className="h-2 w-2 rounded-full bg-primary block" />
                        )}
                      </span>
                      <span className="flex-1 text-base leading-relaxed">{opt}</span>
                    </button>
                  );
                })}
              </div>
            </CardContent>

            <CardFooter className="bg-muted/20 border-t p-4 flex justify-between">
              <Button
                variant="outline"
                onClick={() => setCurrentQ(q => q - 1)}
                disabled={currentQ === 0}
              >
                Previous
              </Button>

              {isLastQ ? (
                <Button
                  onClick={() => {
                    if (unansweredCount > 0) {
                      setConfirmSubmitOpen(true);
                      return;
                    }
                    void handleFinalSubmit();
                  }}
                  disabled={submitting}
                  className="bg-emerald-600 hover:bg-emerald-700 text-white"
                >
                  {submitting ? "Submitting…" : "Submit Assessment"}
                </Button>
              ) : (
                <Button onClick={() => setCurrentQ(q => q + 1)}>
                  Next Question
                </Button>
              )}
            </CardFooter>
          </Card>
        )}

        <Dialog open={confirmSubmitOpen} onOpenChange={setConfirmSubmitOpen}>
          <DialogContent className="max-w-md">
            <DialogHeader>
              <DialogTitle>Submit with unanswered questions?</DialogTitle>
              <DialogDescription>
                You still have {unansweredCount} unanswered question{unansweredCount === 1 ? "" : "s"}.
                You can go back and complete them, or submit now.
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button variant="outline" onClick={() => setConfirmSubmitOpen(false)}>
                Review Answers
              </Button>
              <Button
                onClick={() => {
                  setConfirmSubmitOpen(false);
                  void handleFinalSubmit();
                }}
                className="bg-emerald-600 hover:bg-emerald-700 text-white"
              >
                Submit Anyway
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        {/* ── Result screen ─────────────────────────────────────────────────── */}
        {mode === 'result' && (
          <Card className="max-w-2xl mx-auto shadow-2xl border-primary/20">
            {/* Top colour band — always primary/brand, never red */}
            <div className="h-2 w-full rounded-t-xl bg-primary" />

            <CardHeader className="text-center pt-8 pb-4">
              <div className="mx-auto w-20 h-20 rounded-full flex items-center justify-center mb-4 bg-primary/10 text-primary">
                <CheckCircle className="h-10 w-10" />
              </div>

              <CardTitle className="text-3xl">Assessment Complete</CardTitle>

              <p className="text-muted-foreground mt-2 text-sm">
                Your responses have been securely recorded. The hiring team will
                review your results and be in touch — usually within a few business days.
              </p>
            </CardHeader>

            <CardContent className="px-8 pb-6 space-y-6">
              {/* Score — shown immediately, always */}
              {result && (
                <div className="flex flex-col items-center gap-1">
                  <span className="text-6xl font-black tabular-nums text-foreground">
                    {Math.round(result.percentage)}%
                  </span>
                  <span className="text-sm text-muted-foreground">
                    {result.raw_score} / {result.max_score} points
                  </span>
                  <Progress
                    value={result.percentage}
                    className="h-3 w-full mt-2 rounded-full"
                  />
                </div>
              )}

              {/* Skill breakdown if available */}
              {result?.skill_breakdown && Object.keys(result.skill_breakdown).length > 0 && (
                <div className="space-y-2">
                  <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    Score by topic
                  </p>
                  <div className="grid grid-cols-2 gap-2">
                    {Object.entries(result.skill_breakdown).map(([skill, data]: [string, any]) => (
                      <div key={skill} className="bg-muted/40 rounded-xl px-3 py-2 border">
                        <p className="text-[10px] uppercase tracking-wider text-muted-foreground truncate">{skill}</p>
                        <p className="font-semibold text-sm mt-0.5">
                          {data.earned ?? 0}/{data.max ?? 0} pts
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Status pill — always "Under Review" at this point */}
              <div className="flex justify-center">
                <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-amber-50 text-amber-800 border border-amber-200 dark:bg-amber-900/20 dark:text-amber-300 dark:border-amber-800 text-sm font-medium">
                  <Clock className="h-4 w-4" />
                  Under Review — HR will be in touch soon
                </div>
              </div>

              {/* 3-stage pipeline tracker */}
              <div className="space-y-1.5">
                <div className="flex justify-between text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                  <span className="text-primary">Screening ✓</span>
                  <span className="text-primary">Assessment ✓</span>
                  <span>Decision</span>
                </div>
                <div className="h-2 bg-secondary rounded-full overflow-hidden flex gap-px">
                  <div className="h-full w-1/3 bg-primary rounded-l-full" />
                  <div className="h-full w-1/3 bg-primary" />
                  <div className="h-full w-1/3 bg-muted rounded-r-full" />
                </div>
                <p className="text-xs text-center text-muted-foreground pt-0.5">
                  2 of 3 stages complete · awaiting HR review
                </p>
              </div>
            </CardContent>

            <CardFooter className="bg-muted/20 p-6 flex justify-center">
              <Button size="lg" onClick={() => navigate('/candidate/dashboard')}>
                Return to Dashboard
              </Button>
            </CardFooter>
          </Card>
        )}

      </div>
    </div>
  );
}
