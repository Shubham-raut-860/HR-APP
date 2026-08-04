import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Bot,
  Boxes,
  ClipboardList,
  Download,
  FileJson,
  Loader2,
  PlayCircle,
  RefreshCw,
  Send,
  ShieldCheck,
  Timer,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import {
  createA2ATask,
  downloadA2AArtifact,
  getA2AAudit,
  getA2AAgentCard,
  getA2AAgents,
  getA2ATask,
  getA2ATaskArtifacts,
  getADKShadowRecent,
  getADKShadowSummary,
  getADKPromotionStatus,
  type ADKPromotionStatus,
  runA2AResumeScreeningEvaluation,
  type ADKShadowEvent,
  type ADKShadowSummary,
  type A2AAuditEvent,
  type A2AAgentCard,
  type A2AArtifact,
  type A2ATask,
  type A2ATaskStatus,
} from "@/services/a2a";

function statusVariant(status: A2ATaskStatus | string): "success" | "warning" | "destructive" | "outline" {
  if (status === "completed") return "success";
  if (status === "running" || status === "queued" || status === "fallback") return "warning";
  if (status === "failed" || status === "canceled") return "destructive";
  return "outline";
}

function shadowResultLabel(event: ADKShadowEvent): string {
  if (event.workflow === "quiz_validation") {
    if (event.match === null) return "n/a";
    return event.match ? "pass" : "review";
  }
  if (event.match === null) return "n/a";
  return event.match ? "match" : "diff";
}

function shadowResultVariant(event: ADKShadowEvent): "success" | "destructive" | "outline" {
  if (event.match === true) return "success";
  if (event.match === false) return "destructive";
  return "outline";
}

function metadataValue(event: ADKShadowEvent, key: string): string {
  const raw = event.metadata?.[key];
  if (typeof raw === "number") return Number.isFinite(raw) ? raw.toFixed(key.includes("pct") ? 1 : 0) : "n/a";
  if (typeof raw === "string" && raw.trim()) return raw;
  if (typeof raw === "boolean") return raw ? "true" : "false";
  return "n/a";
}

function formatJson(value: unknown): string {
  try {
    return JSON.stringify(value ?? {}, null, 2);
  } catch {
    return String(value ?? "");
  }
}

function defaultContext(agentId: string): string {
  if (agentId === "resume_screening_orchestrator") {
    return formatJson({
      resume_text: "Candidate has 4 years of Python, FastAPI, React, PostgreSQL, REST API, testing, and cloud deployment experience.",
      jd_text: "We need a Full Stack Engineer with 3 to 6 years of experience in Python, FastAPI, React, PostgreSQL, REST APIs, testing, and cloud deployment.",
    });
  }
  if (agentId === "scoring_agent") {
    return formatJson({
      parsed_resume: {
        name: "Candidate",
        experience_years: 4,
        normalized_skills: ["Python", "FastAPI", "React"],
      },
      parsed_job: {
        title: "Full Stack Engineer",
        experience_min: 3,
        experience_max: 6,
        must_have_skills: ["Python", "React"],
        good_to_have_skills: ["FastAPI"],
        description: "Build and maintain hiring platform workflows.",
      },
    });
  }
  if (agentId === "quiz_agent") {
    return formatJson({
      operation: "generate",
      skills: ["Python", "FastAPI", "React"],
      easy: 2,
      medium: 2,
      hard: 1,
    });
  }
  if (agentId === "career_analyst_agent") {
    return formatJson({
      candidate_name: "Candidate",
      experience_years: 4,
      skills: ["Python", "FastAPI", "React"],
      work_history: [],
      education: [],
      career_breaks: [],
      target_role: "Senior Full Stack Engineer",
    });
  }
  return "{}";
}

function sampleContent(agentId: string): string {
  if (agentId === "resume_parser_agent") {
    return "Candidate has 4 years of Python, FastAPI, React, PostgreSQL, and cloud deployment experience.";
  }
  if (agentId === "jd_parser_agent" || agentId === "quiz_agent") {
    return "We need a Full Stack Engineer with 3 to 6 years of experience in Python, FastAPI, React, PostgreSQL, REST APIs, testing, and cloud deployment.";
  }
  if (agentId === "embedding_agent") {
    return "Full stack engineering role requiring Python, React, API design, and production ownership.";
  }
  if (agentId === "career_analyst_agent") {
    return "Senior Full Stack Engineer";
  }
  if (agentId === "resume_screening_orchestrator") {
    return "Run resume screening workflow";
  }
  return "";
}

export default function A2AConsole() {
  const [agents, setAgents] = useState<A2AAgentCard[]>([]);
  const [selectedAgentId, setSelectedAgentId] = useState("");
  const [selectedCard, setSelectedCard] = useState<A2AAgentCard | null>(null);
  const [messageContent, setMessageContent] = useState("");
  const [contextJson, setContextJson] = useState("{}");
  const [tasks, setTasks] = useState<A2ATask[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState("");
  const [selectedTask, setSelectedTask] = useState<A2ATask | null>(null);
  const [artifacts, setArtifacts] = useState<A2AArtifact[]>([]);
  const [auditEvents, setAuditEvents] = useState<A2AAuditEvent[]>([]);
  const [shadowSummary, setShadowSummary] = useState<ADKShadowSummary | null>(null);
  const [shadowEvents, setShadowEvents] = useState<ADKShadowEvent[]>([]);
  const [promotionStatus, setPromotionStatus] = useState<ADKPromotionStatus | null>(null);
  const [asyncExecution, setAsyncExecution] = useState(true);
  const [evalResumeText, setEvalResumeText] = useState(sampleContent("resume_parser_agent"));
  const [evalJdText, setEvalJdText] = useState(sampleContent("jd_parser_agent"));
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedAgent = useMemo(
    () => agents.find((agent) => agent.id === selectedAgentId) || null,
    [agents, selectedAgentId],
  );

  const loadAgents = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const nextAgents = await getA2AAgents(true);
      setAgents(nextAgents);
      const firstEnabled = nextAgents.find((agent) => agent.enabled);
      const nextSelected = selectedAgentId || firstEnabled?.id || "";
      setSelectedAgentId(nextSelected);
      if (nextSelected) {
        const card = await getA2AAgentCard(nextSelected);
        setSelectedCard(card);
      }
    } catch (err: any) {
      setError(err?.response?.data?.detail || err?.message || "Failed to load A2A agents");
    } finally {
      setLoading(false);
    }
  }, [selectedAgentId]);

  useEffect(() => {
    loadAgents();
  }, [loadAgents]);

  useEffect(() => {
    if (!selectedAgentId) return;
    setMessageContent(sampleContent(selectedAgentId));
    setContextJson(defaultContext(selectedAgentId));
    getA2AAgentCard(selectedAgentId)
      .then(setSelectedCard)
      .catch((err) => setError(err?.response?.data?.detail || err?.message || "Failed to load agent card"));
  }, [selectedAgentId]);

  const refreshTask = useCallback(async (taskId: string) => {
    if (!taskId) return;
    const task = await getA2ATask(taskId);
    const taskArtifacts = await getA2ATaskArtifacts(taskId);
    setSelectedTask(task);
    setArtifacts(taskArtifacts);
    setTasks((prev) => {
      const existing = prev.filter((item) => item.id !== task.id);
      return [task, ...existing].slice(0, 20);
    });
  }, []);

  useEffect(() => {
    if (!selectedTaskId) return;
    const active = selectedTask?.status === "queued" || selectedTask?.status === "running";
    if (!active) return;
    const timer = window.setInterval(() => {
      refreshTask(selectedTaskId).catch((err) => setError(err?.response?.data?.detail || err?.message || "Failed to poll task"));
    }, 1500);
    return () => window.clearInterval(timer);
  }, [refreshTask, selectedTask?.status, selectedTaskId]);

  const loadAudit = useCallback(async () => {
    try {
      setAuditEvents(await getA2AAudit(100));
    } catch (err: any) {
      setError(err?.response?.data?.detail || err?.message || "Failed to load A2A audit events");
    }
  }, []);

  const loadShadow = useCallback(async () => {
    try {
      const [summary, events] = await Promise.all([
        getADKShadowSummary(),
        getADKShadowRecent(50),
      ]);
      setShadowSummary(summary);
      setShadowEvents(events);
    } catch (err: any) {
      setError(err?.response?.data?.detail || err?.message || "Failed to load ADK shadow telemetry");
    }
  }, []);

  const loadPromotion = useCallback(async () => {
    try {
      setPromotionStatus(await getADKPromotionStatus(25));
    } catch (err: any) {
      setError(err?.response?.data?.detail || err?.message || "Failed to load ADK promotion status");
    }
  }, []);

  useEffect(() => {
    loadShadow();
    loadPromotion();
  }, [loadPromotion, loadShadow]);

  const refreshAdkTelemetry = useCallback(() => {
    loadShadow();
    loadPromotion();
  }, [loadPromotion, loadShadow]);

  const handleSend = async () => {
    if (!selectedAgentId) return;
    setSending(true);
    setError(null);
    try {
      let context: Record<string, unknown> = {};
      try {
        context = JSON.parse(contextJson || "{}");
      } catch {
        throw new Error("Context must be valid JSON");
      }
      const task = await createA2ATask(selectedAgentId, {
        role: "user",
        content: messageContent,
        context,
        metadata: { source: "a2a_console" },
      }, asyncExecution ? "async" : "sync");
      setTasks((prev) => [task, ...prev.filter((item) => item.id !== task.id)].slice(0, 20));
      setSelectedTaskId(task.id);
      await refreshTask(task.id);
      await loadAudit();
    } catch (err: any) {
      setError(err?.response?.data?.detail || err?.message || "A2A message failed");
    } finally {
      setSending(false);
    }
  };

  const handleRunEvaluation = async () => {
    setSending(true);
    setError(null);
    try {
      const task = await runA2AResumeScreeningEvaluation({
        resume_text: evalResumeText,
        jd_text: evalJdText,
        execution_mode: "async",
      });
      setTasks((prev) => [task, ...prev.filter((item) => item.id !== task.id)].slice(0, 20));
      setSelectedTaskId(task.id);
      await refreshTask(task.id);
      await loadAudit();
    } catch (err: any) {
      setError(err?.response?.data?.detail || err?.message || "Evaluation run failed");
    } finally {
      setSending(false);
    }
  };

  const completedCount = tasks.filter((task) => task.status === "completed").length;
  const failedCount = tasks.filter((task) => task.status === "failed").length;
  const avgLatency = tasks.length
    ? tasks.reduce((sum, task) => sum + Number(task.execution.latency_ms || 0), 0) / tasks.length
    : 0;

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
        <div>
          <h2 className="flex items-center gap-2 text-3xl font-bold tracking-tight">
            <Bot className="h-7 w-7 text-primary" />
            A2A Console
          </h2>
          <p className="text-sm text-muted-foreground">
            Agent cards, authenticated message delivery, task artifacts, and runtime traces.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" size="sm" onClick={loadAgents}>
            <RefreshCw className="mr-2 h-4 w-4" />
            Refresh
          </Button>
          <Badge variant="outline" className="h-9 px-3">
            {agents.filter((agent) => agent.enabled).length} exposed
          </Badge>
          <Badge variant="warning" className="h-9 px-3">
            {agents.filter((agent) => !agent.enabled).length} internal
          </Badge>
        </div>
      </div>

      {error && (
        <Card className="border-destructive/40">
          <CardContent className="flex items-start gap-2 pt-6 text-destructive">
            <AlertTriangle className="mt-0.5 h-4 w-4" />
            <span>{error}</span>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Card>
          <CardHeader className="pb-3">
            <CardDescription>Directory</CardDescription>
            <CardTitle className="flex items-center gap-2 text-lg">
              <Boxes className="h-5 w-5 text-primary" />
              Agent Cards
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">{agents.length}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-3">
            <CardDescription>Tasks</CardDescription>
            <CardTitle className="flex items-center gap-2 text-lg">
              <Activity className="h-5 w-5 text-primary" />
              Completed
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">{completedCount}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-3">
            <CardDescription>Failures</CardDescription>
            <CardTitle className="flex items-center gap-2 text-lg">
              <ShieldCheck className="h-5 w-5 text-primary" />
              Guardrails
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">{failedCount}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-3">
            <CardDescription>Latency</CardDescription>
            <CardTitle className="flex items-center gap-2 text-lg">
              <Timer className="h-5 w-5 text-primary" />
              Average
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">{avgLatency.toFixed(0)} ms</div>
          </CardContent>
        </Card>
      </div>

      <Tabs defaultValue="directory" className="space-y-4">
        <TabsList className="grid h-auto w-full grid-cols-2 md:inline-flex md:w-auto md:grid-cols-none">
          <TabsTrigger value="directory">Directory</TabsTrigger>
          <TabsTrigger value="message">Messaging</TabsTrigger>
          <TabsTrigger value="evaluation">Evaluation</TabsTrigger>
          <TabsTrigger value="tasks">Tasks</TabsTrigger>
          <TabsTrigger value="artifacts">Artifacts</TabsTrigger>
          <TabsTrigger value="shadow" onClick={refreshAdkTelemetry}>Shadow</TabsTrigger>
          <TabsTrigger value="audit" onClick={loadAudit}>Audit</TabsTrigger>
        </TabsList>

        <TabsContent value="directory" className="space-y-4">
          {loading ? (
            <Card>
              <CardContent className="flex items-center gap-2 pt-6 text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                Loading A2A directory...
              </CardContent>
            </Card>
          ) : (
            <div className="grid gap-4 xl:grid-cols-[minmax(280px,420px)_1fr]">
              <Card>
                <CardHeader>
                  <CardTitle className="text-xl">Agent Directory</CardTitle>
                  <CardDescription>{agents.filter((agent) => agent.enabled).length} externally callable agents</CardDescription>
                </CardHeader>
                <CardContent className="space-y-2">
                  {agents.map((agent) => (
                    <button
                      key={agent.id}
                      type="button"
                      onClick={() => agent.enabled && setSelectedAgentId(agent.id)}
                      disabled={!agent.enabled}
                      className={`w-full rounded-md border px-3 py-3 text-left transition-colors ${
                        selectedAgentId === agent.id ? "border-primary bg-primary/5" : "hover:bg-muted/50"
                      } ${!agent.enabled ? "cursor-not-allowed opacity-60" : ""}`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div className="font-medium">{agent.name}</div>
                        <Badge variant={agent.enabled ? "success" : "outline"}>{agent.enabled ? "exposed" : "internal"}</Badge>
                      </div>
                      <div className="mt-1 line-clamp-2 text-xs text-muted-foreground">{agent.description}</div>
                    </button>
                  ))}
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle className="text-xl">{selectedCard?.name || "Agent Card"}</CardTitle>
                  <CardDescription>{selectedCard?.id || "No agent selected"}</CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  {selectedCard && (
                    <>
                      <div className="grid gap-3 md:grid-cols-3">
                        <div>
                          <div className="text-xs text-muted-foreground">Protocol</div>
                          <div className="font-medium">{selectedCard.protocol_version}</div>
                        </div>
                        <div>
                          <div className="text-xs text-muted-foreground">Runtime</div>
                          <div className="font-medium">{String(selectedCard.metadata.runtime || "runtime")}</div>
                        </div>
                        <div>
                          <div className="text-xs text-muted-foreground">Visibility</div>
                          <Badge variant={selectedCard.visibility === "internal" ? "warning" : "success"}>{selectedCard.visibility}</Badge>
                        </div>
                      </div>
                      <div className="space-y-2">
                        <div className="text-sm font-medium">Skills</div>
                        <div className="grid gap-2 md:grid-cols-2">
                          {selectedCard.skills.map((skill) => (
                            <div key={skill.id} className="rounded-md border px-3 py-2">
                              <div className="font-medium text-sm">{skill.name}</div>
                              <div className="mt-1 text-xs text-muted-foreground">{skill.description}</div>
                            </div>
                          ))}
                        </div>
                      </div>
                      <pre className="max-h-[420px] overflow-auto rounded-md bg-muted p-3 text-xs">
                        {formatJson(selectedCard)}
                      </pre>
                    </>
                  )}
                </CardContent>
              </Card>
            </div>
          )}
        </TabsContent>

        <TabsContent value="message" className="space-y-4">
          <div className="grid gap-4 xl:grid-cols-[minmax(320px,480px)_1fr]">
            <Card>
              <CardHeader>
                <CardTitle className="text-xl">Message Console</CardTitle>
                <CardDescription>{selectedAgent?.name || "Select an agent"}</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <label className="text-sm font-medium" htmlFor="a2a-agent">Agent</label>
                  <select
                    id="a2a-agent"
                    value={selectedAgentId}
                    onChange={(event) => setSelectedAgentId(event.target.value)}
                    className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                  >
                    {agents.filter((agent) => agent.enabled).map((agent) => (
                      <option key={agent.id} value={agent.id}>{agent.name}</option>
                    ))}
                  </select>
                </div>
                <div className="space-y-2">
                  <label className="text-sm font-medium" htmlFor="a2a-content">Content</label>
                  <Textarea
                    id="a2a-content"
                    value={messageContent}
                    onChange={(event) => setMessageContent(event.target.value)}
                    className="min-h-[180px]"
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-sm font-medium" htmlFor="a2a-context">Context JSON</label>
                  <Textarea
                    id="a2a-context"
                    value={contextJson}
                    onChange={(event) => setContextJson(event.target.value)}
                    className="min-h-[220px] font-mono text-xs"
                  />
                </div>
                <label className="flex items-center gap-2 rounded-md border px-3 py-2 text-sm">
                  <input
                    type="checkbox"
                    checked={asyncExecution}
                    onChange={(event) => setAsyncExecution(event.target.checked)}
                    className="h-4 w-4"
                  />
                  Run asynchronously and poll task status
                </label>
                <Button onClick={handleSend} disabled={!selectedAgentId || sending} className="w-full">
                  {sending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Send className="mr-2 h-4 w-4" />}
                  Send Message
                </Button>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-xl">Task Result</CardTitle>
                <CardDescription>{selectedTask?.id || "No task selected"}</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {selectedTask ? (
                  <>
                    <div className="grid gap-3 md:grid-cols-4">
                      <div>
                        <div className="text-xs text-muted-foreground">Status</div>
                        <Badge variant={statusVariant(selectedTask.status)}>{selectedTask.status}</Badge>
                      </div>
                      <div>
                        <div className="text-xs text-muted-foreground">Agent</div>
                        <div className="font-medium">{selectedTask.agent_id}</div>
                      </div>
                      <div>
                        <div className="text-xs text-muted-foreground">Latency</div>
                        <div className="font-medium">{selectedTask.execution.latency_ms ?? 0} ms</div>
                      </div>
                      <div>
                        <div className="text-xs text-muted-foreground">Model</div>
                        <div className="font-medium truncate">{selectedTask.execution.model_used || "n/a"}</div>
                      </div>
                    </div>
                    <pre className="max-h-[520px] overflow-auto rounded-md bg-muted p-3 text-xs">
                      {formatJson(selectedTask.result?.output || selectedTask)}
                    </pre>
                  </>
                ) : (
                  <div className="flex h-[360px] items-center justify-center rounded-md border border-dashed text-sm text-muted-foreground">
                    Awaiting task output
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="evaluation" className="space-y-4">
          <div className="grid gap-4 xl:grid-cols-[minmax(320px,520px)_1fr]">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-xl">
                  <PlayCircle className="h-5 w-5 text-primary" />
                  Run Evaluation
                </CardTitle>
                <CardDescription>Runs the resume screening orchestrator as an async A2A workflow.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <label className="text-sm font-medium" htmlFor="eval-resume">Resume text</label>
                  <Textarea
                    id="eval-resume"
                    value={evalResumeText}
                    onChange={(event) => setEvalResumeText(event.target.value)}
                    className="min-h-[190px]"
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-sm font-medium" htmlFor="eval-jd">Job description text</label>
                  <Textarea
                    id="eval-jd"
                    value={evalJdText}
                    onChange={(event) => setEvalJdText(event.target.value)}
                    className="min-h-[190px]"
                  />
                </div>
                <Button
                  onClick={handleRunEvaluation}
                  disabled={sending || evalResumeText.length < 20 || evalJdText.length < 20}
                  className="w-full"
                >
                  {sending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <PlayCircle className="mr-2 h-4 w-4" />}
                  Run Evaluation
                </Button>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-xl">
                  <ClipboardList className="h-5 w-5 text-primary" />
                  Evaluation Output
                </CardTitle>
                <CardDescription>{selectedTask?.agent_id === "resume_screening_orchestrator" ? selectedTask.id : "No evaluation task selected"}</CardDescription>
              </CardHeader>
              <CardContent>
                {selectedTask?.agent_id === "resume_screening_orchestrator" ? (
                  <pre className="max-h-[620px] overflow-auto rounded-md bg-muted p-3 text-xs">
                    {formatJson(selectedTask.result?.output || selectedTask)}
                  </pre>
                ) : (
                  <div className="flex h-[420px] items-center justify-center rounded-md border border-dashed text-sm text-muted-foreground">
                    Run an evaluation to inspect orchestrated artifacts and trace metadata
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="tasks" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-xl">Task Explorer</CardTitle>
              <CardDescription>{tasks.length} task snapshots in this browser session</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex flex-col gap-2 md:flex-row">
                <Input
                  value={selectedTaskId}
                  onChange={(event) => setSelectedTaskId(event.target.value)}
                  placeholder="Task id"
                />
                <Button
                  variant="outline"
                  onClick={() => refreshTask(selectedTaskId).catch((err) => setError(err?.response?.data?.detail || err?.message || "Failed to refresh task"))}
                  disabled={!selectedTaskId}
                >
                  <RefreshCw className="mr-2 h-4 w-4" />
                  Refresh Task
                </Button>
              </div>
              <div className="overflow-hidden rounded-md border">
                <div className="grid grid-cols-[1fr_160px_120px_120px] gap-3 border-b bg-muted px-3 py-2 text-xs font-medium text-muted-foreground">
                  <div>Task</div>
                  <div>Agent</div>
                  <div>Status</div>
                  <div>Latency</div>
                </div>
                {tasks.map((task) => (
                  <button
                    key={task.id}
                    type="button"
                    onClick={() => {
                      setSelectedTaskId(task.id);
                      refreshTask(task.id).catch((err) => setError(err?.response?.data?.detail || err?.message || "Failed to load task"));
                    }}
                    className="grid w-full grid-cols-[1fr_160px_120px_120px] gap-3 border-b px-3 py-3 text-left text-sm last:border-b-0 hover:bg-muted/50"
                  >
                    <div className="truncate font-mono text-xs">{task.id}</div>
                    <div className="truncate">{task.agent_id}</div>
                    <div><Badge variant={statusVariant(task.status)}>{task.status}</Badge></div>
                    <div>{task.execution.latency_ms ?? 0} ms</div>
                  </button>
                ))}
                {tasks.length === 0 && (
                  <div className="px-3 py-8 text-center text-sm text-muted-foreground">No tasks yet</div>
                )}
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="artifacts" className="space-y-4">
          <div className="grid gap-4 xl:grid-cols-[360px_1fr]">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-xl">
                  <FileJson className="h-5 w-5 text-primary" />
                  Artifact Explorer
                </CardTitle>
                <CardDescription>{selectedTask?.id || "No task selected"}</CardDescription>
              </CardHeader>
              <CardContent className="space-y-2">
                {artifacts.map((artifact) => (
                  <div key={artifact.id} className="rounded-md border px-3 py-2">
                    <div className="flex items-center justify-between gap-2">
                      <div className="truncate text-sm font-medium">{artifact.name}</div>
                      <div className="flex items-center gap-2">
                        <Badge variant={artifact.redacted ? "warning" : "outline"}>{artifact.artifact_type}</Badge>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => downloadA2AArtifact(artifact.task_id, artifact.id).catch((err) => setError(err?.response?.data?.detail || err?.message || "Download failed"))}
                        >
                          <Download className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    </div>
                    <div className="mt-1 truncate text-xs text-muted-foreground">{artifact.id}</div>
                  </div>
                ))}
                {artifacts.length === 0 && (
                  <div className="rounded-md border border-dashed px-3 py-8 text-center text-sm text-muted-foreground">
                    No artifacts loaded
                  </div>
                )}
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle className="text-xl">Artifact Payloads</CardTitle>
                <CardDescription>{artifacts.length} artifacts</CardDescription>
              </CardHeader>
              <CardContent>
                <pre className="max-h-[620px] overflow-auto rounded-md bg-muted p-3 text-xs">
                  {formatJson(artifacts)}
                </pre>
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="audit" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-xl">A2A Audit Events</CardTitle>
              <CardDescription>In-memory developer-console audit trail for task, evaluation, and artifact actions.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <Button variant="outline" size="sm" onClick={loadAudit}>
                <RefreshCw className="mr-2 h-4 w-4" />
                Refresh Audit
              </Button>
              <div className="overflow-hidden rounded-md border">
                <div className="grid grid-cols-[190px_170px_1fr_160px] gap-3 border-b bg-muted px-3 py-2 text-xs font-medium text-muted-foreground">
                  <div>Action</div>
                  <div>Actor</div>
                  <div>Resource</div>
                  <div>Time</div>
                </div>
                {auditEvents.map((event) => (
                  <div key={event.id} className="grid grid-cols-[190px_170px_1fr_160px] gap-3 border-b px-3 py-3 text-sm last:border-b-0">
                    <div className="font-medium">{event.action}</div>
                    <div><Badge variant={event.actor_type === "service_token" ? "warning" : "outline"}>{event.actor_type}</Badge></div>
                    <div className="truncate font-mono text-xs">{event.resource_id || event.resource}</div>
                    <div className="text-xs text-muted-foreground">{new Date(event.created_at).toLocaleTimeString()}</div>
                  </div>
                ))}
                {auditEvents.length === 0 && (
                  <div className="px-3 py-8 text-center text-sm text-muted-foreground">No audit events yet</div>
                )}
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="shadow" className="space-y-4">
          <Card>
            <CardHeader>
              <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                <div>
                  <CardTitle className="text-xl">Promotion Readiness</CardTitle>
                  <CardDescription>Release controls for promoted agent workflows. Changes are managed through environment configuration.</CardDescription>
                </div>
                <Button variant="outline" size="sm" onClick={refreshAdkTelemetry}>
                  <RefreshCw className="mr-2 h-4 w-4" />
                  Refresh ADK
                </Button>
              </div>
            </CardHeader>
            <CardContent className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              <div className="rounded-md border px-3 py-3">
                <div className="text-xs text-muted-foreground">Promotion</div>
                <div className="mt-2 flex items-center gap-2">
                  <Badge variant={promotionStatus?.enabled ? "success" : "outline"}>
                    {promotionStatus?.enabled ? "enabled" : "disabled"}
                  </Badge>
                  <span className="text-sm text-muted-foreground">
                    {promotionStatus?.fallback_to_legacy ? "legacy fallback on" : "strict mode"}
                  </span>
                </div>
              </div>
              <div className="rounded-md border px-3 py-3">
                <div className="text-xs text-muted-foreground">Allowlist</div>
                <div className="mt-2 flex flex-wrap gap-2">
                  {(promotionStatus?.allowlist || []).map((workflow) => (
                    <Badge key={workflow} variant={promotionStatus?.effective_workflows?.[workflow] ? "success" : "outline"}>
                      {workflow}
                    </Badge>
                  ))}
                  {(!promotionStatus || promotionStatus.allowlist.length === 0) && (
                    <span className="text-sm text-muted-foreground">No promoted workflows</span>
                  )}
                </div>
              </div>
              <div className="rounded-md border px-3 py-3">
                <div className="text-xs text-muted-foreground">Quality Gate</div>
                <div className="mt-2 text-2xl font-bold">
                  {promotionStatus?.min_quiz_quality_score?.toFixed(0) || "70"}
                </div>
                <div className="text-xs text-muted-foreground">minimum quiz score</div>
              </div>
              <div className="rounded-md border px-3 py-3">
                <div className="text-xs text-muted-foreground">Recent promoted events</div>
                <div className="mt-2 flex flex-wrap gap-2">
                  <Badge variant="success">{promotionStatus?.recent_counts.completed || 0} completed</Badge>
                  <Badge variant="warning">{promotionStatus?.recent_counts.fallback || 0} fallback</Badge>
                  <Badge variant="destructive">{promotionStatus?.recent_counts.failed || 0} failed</Badge>
                </div>
              </div>
            </CardContent>
          </Card>

          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <Card>
              <CardHeader className="pb-3">
                <CardDescription>ADK shadow</CardDescription>
                <CardTitle className="flex items-center gap-2 text-lg">
                  <Bot className="h-5 w-5 text-primary" />
                  Mode
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                <Badge variant={shadowSummary?.enabled ? "success" : "outline"}>
                  {shadowSummary?.enabled ? "enabled" : "disabled"}
                </Badge>
                <div className="truncate text-sm text-muted-foreground">
                  {shadowSummary?.execution_mode || "record_only"}
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-3">
                <CardDescription>Observed</CardDescription>
                <CardTitle className="flex items-center gap-2 text-lg">
                  <Activity className="h-5 w-5 text-primary" />
                  Events
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-3xl font-bold">{shadowSummary?.events ?? 0}</div>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-3">
                <CardDescription>Runtime compare</CardDescription>
                <CardTitle className="flex items-center gap-2 text-lg">
                  <ShieldCheck className="h-5 w-5 text-primary" />
                  Match Rate
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-3xl font-bold">
                  {shadowSummary?.match_rate_pct == null ? "n/a" : `${shadowSummary.match_rate_pct.toFixed(1)}%`}
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-3">
                <CardDescription>Failures</CardDescription>
                <CardTitle className="flex items-center gap-2 text-lg">
                  <AlertTriangle className="h-5 w-5 text-primary" />
                  Errors
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-3xl font-bold">{shadowSummary?.failed ?? 0}</div>
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                <div>
                  <CardTitle className="text-xl">Recent Shadow Observations</CardTitle>
                  <CardDescription>Production output hashes, shadow comparison status, and failure reasons.</CardDescription>
                </div>
                <Button variant="outline" size="sm" onClick={refreshAdkTelemetry}>
                  <RefreshCw className="mr-2 h-4 w-4" />
                  Refresh ADK
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              <div className="overflow-auto rounded-md border">
                <div className="min-w-[840px]">
                  <div className="grid grid-cols-[170px_120px_110px_110px_120px_1fr_170px] gap-3 border-b bg-muted px-3 py-2 text-xs font-medium text-muted-foreground">
                    <div>Workflow</div>
                    <div>Status</div>
                    <div>Result</div>
                    <div>Quality</div>
                    <div>Latency</div>
                    <div>Entity</div>
                    <div>Time</div>
                  </div>
                  {shadowEvents.map((event, index) => (
                    <div key={`${event.workflow}-${event.started_at}-${index}`} className="border-b px-3 py-3 text-sm last:border-b-0">
                      <div className="grid grid-cols-[170px_120px_110px_110px_120px_1fr_170px] gap-3">
                        <div className="truncate font-medium">{event.workflow}</div>
                        <div><Badge variant={statusVariant(event.status)}>{event.status}</Badge></div>
                        <div>
                          <Badge variant={shadowResultVariant(event)}>{shadowResultLabel(event)}</Badge>
                        </div>
                        <div>{event.workflow === "quiz_validation" ? metadataValue(event, "quality_score") : "n/a"}</div>
                        <div>{Number(event.latency_ms || 0).toFixed(0)} ms</div>
                        <div className="truncate font-mono text-xs">{event.entity_id || event.actor_id || "n/a"}</div>
                        <div className="text-xs text-muted-foreground">{new Date(event.started_at).toLocaleString()}</div>
                      </div>
                      {event.error && (
                        <div className="mt-2 rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive">
                          {event.error}
                        </div>
                      )}
                    </div>
                  ))}
                  {shadowEvents.length === 0 && (
                    <div className="px-3 py-8 text-center text-sm text-muted-foreground">No ADK shadow observations yet</div>
                  )}
                </div>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-xl">Recent Promoted Workflow Events</CardTitle>
              <CardDescription>Completed, fallback, and failed promoted-runtime attempts.</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="overflow-auto rounded-md border">
                <div className="min-w-[760px]">
                  <div className="grid grid-cols-[180px_120px_120px_120px_1fr_170px] gap-3 border-b bg-muted px-3 py-2 text-xs font-medium text-muted-foreground">
                    <div>Workflow</div>
                    <div>Status</div>
                    <div>Quality</div>
                    <div>Latency</div>
                    <div>Entity</div>
                    <div>Time</div>
                  </div>
                  {(promotionStatus?.recent || []).map((event, index) => (
                    <div key={`${event.workflow}-${event.started_at}-${index}`} className="border-b px-3 py-3 text-sm last:border-b-0">
                      <div className="grid grid-cols-[180px_120px_120px_120px_1fr_170px] gap-3">
                        <div className="truncate font-medium">{event.workflow}</div>
                        <div><Badge variant={statusVariant(event.status)}>{event.status}</Badge></div>
                        <div>{metadataValue(event, "quality_score")}</div>
                        <div>{Number(event.latency_ms || 0).toFixed(0)} ms</div>
                        <div className="truncate font-mono text-xs">{event.entity_id || event.actor_id || "n/a"}</div>
                        <div className="text-xs text-muted-foreground">{new Date(event.started_at).toLocaleString()}</div>
                      </div>
                      {event.error && (
                        <div className="mt-2 rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive">
                          {event.error}
                        </div>
                      )}
                    </div>
                  ))}
                  {(!promotionStatus || promotionStatus.recent.length === 0) && (
                    <div className="px-3 py-8 text-center text-sm text-muted-foreground">No promoted workflow events yet</div>
                  )}
                </div>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
