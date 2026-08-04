import { useState, useEffect } from 'react';
import type { ElementType } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { SegmentedTabs } from "@/components/ui/segmented-tabs";

import { BrainCircuit, AlertCircle, FileText, Target, BookOpen, Award, CheckCircle2, XCircle } from 'lucide-react';
import { toast } from "sonner";
import { generateMockTest, getProfileResume } from '@/services/candidatePortal';
import { cn } from "@/lib/utils";

export default function CandidateMockTest() {
  type TestMode = 'resume' | 'topic';
  const [loading, setLoading]           = useState(false);
  const [testStarted, setTestStarted]   = useState(false);
  const [questions, setQuestions]       = useState<any[]>([]);
  const [currentQuestion, setCurrentQuestion] = useState(0);
  const [answers, setAnswers]           = useState<Record<number, string>>({});
  const [submitted, setSubmitted]       = useState(false);
  const [score, setScore]               = useState(0);

  const [resume, setResume]             = useState<any>(null);
  const [checkingResume, setCheckingResume] = useState(true);
  const [testMode, setTestMode]         = useState<TestMode>('resume');
  const [selectedTopic, setSelectedTopic] = useState<string>('');
  const modeOptions: ReadonlyArray<{
    value: TestMode;
    label: string;
    icon?: ElementType;
  }> = [
    { value: 'resume', label: 'Profile / Resume', icon: FileText },
    { value: 'topic', label: 'Specific Topic', icon: BookOpen },
  ];

  useEffect(() => {
    checkResume();
  }, []);

  // BUG FIX: was missing try/catch + finally — if getProfileResume() threw,
  // checkingResume stayed `true` forever, showing an infinite pulse skeleton.
  const checkResume = async () => {
    try {
      const data = await getProfileResume();
      setResume(data);
    } catch {
      setResume(null);
    } finally {
      setCheckingResume(false);
    }
  };

  const handleStartTest = async () => {
    if (testMode === 'topic' && !selectedTopic) {
      toast.error("Please select a topic first!");
      return;
    }
    setLoading(true);
    try {
      const mockContext = testMode === 'topic'
        ? `Topic: ${selectedTopic}. Generate a strict 10-question MCQ test on this specific subject.`
        : resume
          ? `Resume: ${resume.name}. Skills: Extract key skills from resume.`
          : undefined;
      const data = await generateMockTest(mockContext);
      if (!Array.isArray(data) || data.length === 0) {
        throw new Error("No questions were generated. Please try again.");
      }
      setQuestions(data);
      setCurrentQuestion(0);
      setAnswers({});
      setSubmitted(false);
      setScore(0);
      setTestStarted(true);
    } catch (error: any) {
      toast.error(error.response?.data?.detail || error.message || "Failed to generate test. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const handleAnswer = (value: string) => {
    setAnswers({ ...answers, [currentQuestion]: value });
  };

  const handleNext = () => {
    if (currentQuestion < questions.length - 1) {
      setCurrentQuestion(currentQuestion + 1);
    } else {
      handleSubmit();
    }
  };

  const handleSubmit = () => {
    let calculatedScore = 0;
    questions.forEach((q, index) => {
      if (answers[index] === q.correctAnswer) calculatedScore++;
    });
    setScore(calculatedScore);
    setSubmitted(true);
  };

  const handleRetake = () => {
    setTestStarted(false);
    setSubmitted(false);
    setQuestions([]);
    setAnswers({});
    setCurrentQuestion(0);
    setScore(0);
  };

  // ─── STAGE 1: CONFIGURATION ─────────────────────────────────────────────────
  if (!testStarted) {
    return (
      <div className="max-w-6xl mx-auto space-y-8">
        <div>
          <h2 className="text-3xl font-bold tracking-tight">Mock Skill Assessment</h2>
          <p className="text-muted-foreground">Configure and practice with AI-generated questions.</p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">

          {/* Main Launcher Panel */}
          <div className="lg:col-span-2 space-y-6">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-xl">
                  <BrainCircuit className="h-5 w-5 text-primary" />
                  Test Configuration
                </CardTitle>
                <CardDescription>
                  Choose how you want the AI to generate your practice questions.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-6">

                <SegmentedTabs
                  value={testMode}
                  onChange={setTestMode}
                  options={modeOptions}
                  className="w-full"
                />

                <div className="min-h-[120px] flex flex-col justify-center">
                  {testMode === 'resume' ? (
                    !resume && !checkingResume ? (
                      <div className="p-5 border border-amber-200 bg-amber-50 dark:bg-amber-900/20 dark:border-amber-800 rounded-2xl flex items-start gap-3 text-amber-800 dark:text-amber-200">
                        <AlertCircle className="h-5 w-5 shrink-0 mt-0.5" />
                        <div className="space-y-2">
                          <p className="font-semibold">No resume profile found</p>
                          <p className="text-sm opacity-90">You can still take a general mock test now, or upload/apply later for personalized questions.</p>
                        </div>
                      </div>
                    ) : resume ? (
                      <div className="p-5 border border-border bg-muted/20 rounded-2xl flex items-center gap-4">
                        <div className="h-10 w-10 rounded-full bg-primary text-primary-foreground flex items-center justify-center shrink-0 shadow-sm">
                          <Target className="h-5 w-5" />
                        </div>
                        <div>
                          <p className="font-semibold text-foreground">AI Profile Active</p>
                          <p className="text-sm text-muted-foreground">Test will strictly evaluate skills found in: <span className="font-medium">{resume.name}</span></p>
                        </div>
                      </div>
                    ) : (
                      // BUG FIX: this state only shown while checkingResume is true — no longer infinite
                      <div className="h-20 bg-muted/20 animate-pulse rounded-2xl" />
                    )
                  ) : (
                    <div className="space-y-3">
                      <Label className="text-sm font-semibold">Select Target Subject</Label>
                      <Select value={selectedTopic} onValueChange={setSelectedTopic}>
                        <SelectTrigger className="w-full h-12 rounded-xl border-border bg-muted/10">
                          <SelectValue placeholder="e.g. React.js, Python, System Design..." />
                        </SelectTrigger>
                        <SelectContent className="rounded-xl">
                          <SelectItem value="React.js">React.js & Frontend</SelectItem>
                          <SelectItem value="Python">Python Fundamentals</SelectItem>
                          <SelectItem value="Node.js">Node.js & Backend</SelectItem>
                          <SelectItem value="System Design">System Architecture</SelectItem>
                          <SelectItem value="Data Structures">Data Structures & Algorithms</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                  )}
                </div>

                <div className="grid gap-4 md:grid-cols-3 pt-4 border-t border-border">
                  {[
                    { value: "10",     label: "Questions"  },
                    { value: "15 min", label: "Duration"   },
                    { value: "Private",label: "Not Shared" },
                  ].map(item => (
                    <div key={item.label} className="p-4 rounded-2xl bg-muted/20 border border-border">
                      <div className="font-bold text-xl">{item.value}</div>
                      <div className="text-xs text-muted-foreground uppercase tracking-wider font-semibold mt-1">{item.label}</div>
                    </div>
                  ))}
                </div>
              </CardContent>
              <CardFooter className="bg-muted/10 border-t border-border p-6">
                <Button
                  size="lg"
                  onClick={handleStartTest}
                  disabled={loading || (testMode === 'topic' && !selectedTopic)}
                  className="w-full sm:w-auto rounded-full px-8"
                >
                  {loading ? "Generating Questions..." : "Launch Practice Environment"}
                </Button>
              </CardFooter>
            </Card>
          </div>

          {/* Sidebar */}
          <div className="space-y-6">
            {/* BUG FIX: removed hardcoded fake mockHistory. Showing empty state instead
                of fabricated scores that mislead users about their actual performance. */}
            <Card>
              <CardHeader>
                <CardTitle className="text-lg flex items-center gap-2">
                  <BrainCircuit className="h-5 w-5 text-muted-foreground" />
                  Recent Practice
                </CardTitle>
                <CardDescription>Your latest mock test performances.</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="py-6 text-center text-muted-foreground space-y-2">
                  <BrainCircuit className="h-8 w-8 mx-auto opacity-30" />
                  <p className="text-sm">No practice tests yet.</p>
                  <p className="text-xs">Complete your first test to see your history here.</p>
                </div>
              </CardContent>
            </Card>

            <Card className="bg-gradient-to-br from-muted/50 to-background border border-border shadow-sm">
              <CardContent className="p-6 space-y-4">
                <div className="h-10 w-10 rounded-full bg-primary/5 border border-primary/10 flex items-center justify-center shadow-sm">
                  <Award className="h-5 w-5 text-primary" />
                </div>
                <h3 className="font-semibold text-lg text-foreground tracking-tight">Why take mock tests?</h3>
                <p className="text-sm text-muted-foreground leading-relaxed">
                  Practice and assess your readiness. Mock test scores are for your reference only and do not affect your application ranking.
                </p>
              </CardContent>
            </Card>
          </div>

        </div>
      </div>
    );
  }

  // ─── STAGE 2: RESULTS ───────────────────────────────────────────────────────
  if (submitted) {
    const percentage = Math.round((score / questions.length) * 100);
    const passed = percentage >= 70;

    return (
      <div className="max-w-2xl mx-auto space-y-6 mt-8">
        <Card>
          <CardHeader className="text-center pb-2">
            <CardTitle>Test Results</CardTitle>
            <CardDescription>Here's how you performed</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col items-center space-y-6 pt-6">

            {/* BUG FIX: replaced broken clipPath circle with a clean SVG arc indicator */}
            <div className="relative flex items-center justify-center h-36 w-36">
              <svg className="absolute inset-0 w-full h-full -rotate-90" viewBox="0 0 36 36">
                <circle cx="18" cy="18" r="15.9" fill="none" stroke="currentColor"
                  strokeWidth="2.5" className="text-muted" />
                <circle cx="18" cy="18" r="15.9" fill="none"
                  stroke={passed ? "#10b981" : "hsl(var(--primary))"}
                  strokeWidth="2.5"
                  strokeDasharray={`${percentage} ${100 - percentage}`}
                  strokeLinecap="round"
                  className="transition-all duration-700"
                />
              </svg>
              <div className="text-center">
                <div className="text-3xl font-bold">{percentage}%</div>
                <div className={cn("text-xs font-semibold mt-0.5", passed ? "text-emerald-500" : "text-muted-foreground")}>
                  {passed ? "Passed" : "Keep going"}
                </div>
              </div>
            </div>

            <div className="text-center space-y-1">
              <p className="font-medium text-lg">You scored {score} out of {questions.length}</p>
              <p className="text-muted-foreground">
                {passed ? "Great job! You're ready for the real thing." : "Keep practicing to improve your skills."}
              </p>
            </div>

            <div className="w-full space-y-3">
              {questions.map((q, i) => {
                const isCorrect = answers[i] === q.correctAnswer;
                return (
                  <div key={i} className={cn(
                    "p-4 rounded-2xl border",
                    isCorrect
                      ? "bg-emerald-50 border-emerald-200 dark:bg-emerald-900/20 dark:border-emerald-800"
                      : "bg-red-50 border-red-200 dark:bg-red-900/20 dark:border-red-800"
                  )}>
                    <div className="flex items-start gap-2.5 mb-2">
                      {isCorrect
                        ? <CheckCircle2 className="h-4 w-4 text-emerald-600 dark:text-emerald-400 shrink-0 mt-0.5" />
                        : <XCircle className="h-4 w-4 text-red-500 shrink-0 mt-0.5" />
                      }
                      <p className="font-medium text-sm">{i + 1}. {q.question}</p>
                    </div>
                    <div className="text-sm space-y-1 pl-6">
                      <p className="text-muted-foreground">Your answer: <span className="font-semibold text-foreground">{answers[i] ?? <em>skipped</em>}</span></p>
                      {!isCorrect && (
                        <p className="text-emerald-600 dark:text-emerald-400">Correct: <span className="font-semibold">{q.correctAnswer}</span></p>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </CardContent>
          <CardFooter className="justify-center gap-4 bg-muted/10 border-t p-6">
            <Button variant="outline" className="rounded-full px-6" onClick={() => setTestStarted(false)}>Exit Setup</Button>
            <Button className="rounded-full px-6" onClick={handleRetake}>Retake Test</Button>
          </CardFooter>
        </Card>
      </div>
    );
  }

  // ─── STAGE 3: ACTIVE TEST ────────────────────────────────────────────────────
  const q = questions[currentQuestion];

  return (
    <div className="max-w-3xl mx-auto mt-4">
      <div className="mb-4 flex items-center justify-between text-sm font-medium text-muted-foreground bg-card py-3 px-6 rounded-full border shadow-sm">
        <span>Question {currentQuestion + 1} <span className="opacity-50">/ {questions.length}</span></span>
        <span className="flex items-center gap-2"><div className="h-2 w-2 bg-emerald-500 rounded-full animate-pulse" /> In Progress</span>
      </div>

      <Card className="shadow-lg">
        <CardHeader className="p-8 border-b border-border">
          <CardTitle className="text-xl leading-relaxed">{q.question}</CardTitle>
        </CardHeader>
        <CardContent className="p-8">
          <RadioGroup value={answers[currentQuestion] || ""} onValueChange={handleAnswer} className="space-y-3">
            {q.options.map((option: string, i: number) => {
              const isSelected = answers[currentQuestion] === option;
              return (
                <div
                  key={i}
                  className={cn(
                    "flex items-center space-x-3 border p-4 rounded-2xl cursor-pointer transition-all duration-150",
                    isSelected
                      ? "border-primary bg-primary text-primary-foreground shadow-md hover:bg-primary/90"
                      : "border-border bg-card hover:bg-muted/40 hover:border-primary/40"
                  )}
                >
                  <RadioGroupItem
                    value={option}
                    id={`opt-${i}`}
                    className={cn(isSelected ? "border-primary-foreground text-primary-foreground" : "")}
                  />
                  <Label
                    htmlFor={`opt-${i}`}
                    className={cn(
                      "flex-1 cursor-pointer font-medium text-base select-none",
                      isSelected ? "text-primary-foreground" : "text-foreground"
                    )}
                  >
                    {option}
                  </Label>
                </div>
              );
            })}
          </RadioGroup>
        </CardContent>
        <CardFooter className="justify-between bg-muted/10 p-6 border-t border-border">
          <Button variant="outline" className="rounded-full px-6"
            onClick={() => setCurrentQuestion(Math.max(0, currentQuestion - 1))}
            disabled={currentQuestion === 0}>
            Previous
          </Button>
          <Button className="rounded-full px-8" onClick={handleNext} disabled={!answers[currentQuestion]}>
            {currentQuestion === questions.length - 1 ? "Submit Exam" : "Next Question"}
          </Button>
        </CardFooter>
      </Card>
    </div>
  );
}
