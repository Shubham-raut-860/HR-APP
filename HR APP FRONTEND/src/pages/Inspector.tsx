import React, { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, Loader2, RefreshCw, ShieldCheck } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { getHrInspectorOverview, type InspectorOverview } from "@/services/hrInspector";

function statusBadgeVariant(status: string): "success" | "warning" | "destructive" | "outline" {
  const s = (status || "").toLowerCase();
  if (s === "good" || s === "production_ready" || s === "ok") return "success";
  if (s === "watch") return "warning";
  if (s === "not_ready" || s === "needs_attention" || s === "failed") return "destructive";
  return "outline";
}

function pct(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "0.0%";
  return `${(Number(v) * 100).toFixed(1)}%`;
}

function money(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "$0.000000";
  return `$${Number(v).toFixed(6)}`;
}

export default function Inspector() {
  const [windowMinutes, setWindowMinutes] = useState(1440);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<InspectorOverview | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    try {
      const res = await getHrInspectorOverview(windowMinutes, 20, 8, signal);
      setData(res);
    } catch (err: any) {
      setError(err?.response?.data?.detail || err?.message || "Failed to load inspector overview");
    } finally {
      setLoading(false);
    }
  }, [windowMinutes]);

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const topRecommendations = useMemo(() => {
    return data?.model_fit?.recommendations?.opportunities?.slice(0, 5) || [];
  }, [data]);

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <h2 className="text-3xl font-bold tracking-tight flex items-center gap-2">
            <ShieldCheck className="h-7 w-7 text-primary" />
            HR Inspector
          </h2>
          <p className="text-sm text-muted-foreground">
            Unified view of harness stability, traces, model-fit, and production readiness.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant={windowMinutes === 60 ? "default" : "outline"} size="sm" onClick={() => setWindowMinutes(60)}>1h</Button>
          <Button variant={windowMinutes === 1440 ? "default" : "outline"} size="sm" onClick={() => setWindowMinutes(1440)}>24h</Button>
          <Button variant={windowMinutes === 10080 ? "default" : "outline"} size="sm" onClick={() => setWindowMinutes(10080)}>7d</Button>
          <Button variant="outline" size="sm" onClick={() => load()}>
            <RefreshCw className="mr-2 h-4 w-4" />
            Refresh
          </Button>
        </div>
      </div>

      {loading && (
        <Card>
          <CardContent className="pt-6 flex items-center gap-2 text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading inspector data...
          </CardContent>
        </Card>
      )}

      {!loading && error && (
        <Card className="border-destructive/40">
          <CardContent className="pt-6 flex items-start gap-2 text-destructive">
            <AlertTriangle className="mt-0.5 h-4 w-4" />
            <div>{error}</div>
          </CardContent>
        </Card>
      )}

      {!loading && !error && data && (
        <>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <Card>
              <CardHeader className="pb-3">
                <CardDescription>Readiness</CardDescription>
                <CardTitle className="text-lg">Infrastructure Score</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="flex items-center justify-between">
                  <div className="text-3xl font-bold">{data.readiness.infrastructure_score.toFixed(1)}</div>
                  <Badge variant={statusBadgeVariant(data.readiness.verdict)}>{data.readiness.verdict}</Badge>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-3">
                <CardDescription>Harness</CardDescription>
                <CardTitle className="text-lg">Run Success Rate</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-3xl font-bold">{pct(data.harness.metrics.success_rate)}</div>
                <p className="text-xs text-muted-foreground mt-1">
                  completed {data.harness.metrics.completed} • failed {data.harness.metrics.failed}
                </p>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-3">
                <CardDescription>Prompt Quality</CardDescription>
                <CardTitle className="text-lg">Overall Eval Health</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="flex items-center justify-between">
                  <div className="text-3xl font-bold">
                    {Number(data.prompt_quality?.overall_avg_score || 0).toFixed(2)}
                  </div>
                  <Badge variant={statusBadgeVariant(data.prompt_quality?.status || "unknown")}>
                    {data.prompt_quality?.status || "unknown"}
                  </Badge>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-3">
                <CardDescription>OCR Quality</CardDescription>
                <CardTitle className="text-lg">Valid Text Ratio</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="flex items-center justify-between">
                  <div className="text-3xl font-bold">{pct(data.ocr_quality?.valid_text_ratio || 0)}</div>
                  <Badge variant={statusBadgeVariant(data.ocr_quality?.status || "unknown")}>
                    {data.ocr_quality?.status || "unknown"}
                  </Badge>
                </div>
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <CardTitle className="text-xl">Readiness Notes</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {data.readiness.notes.map((note, idx) => (
                <div key={`${idx}-${note}`} className="flex items-start gap-2 text-sm">
                  <CheckCircle2 className="h-4 w-4 mt-0.5 text-primary" />
                  <span>{note}</span>
                </div>
              ))}
            </CardContent>
          </Card>

          <div className="grid gap-4 xl:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle className="text-xl">Recent Harness Runs</CardTitle>
                <CardDescription>
                  {data.harness.status === "ok" ? `${data.harness.run_count} runs found` : `status: ${data.harness.status}`}
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-2">
                {data.harness.recent_runs.slice(0, 12).map((run) => (
                  <div key={run.run_id} className="rounded-lg border p-3">
                    <div className="flex items-center justify-between gap-3">
                      <div className="font-medium text-sm">{run.agent_type}</div>
                      <Badge variant={statusBadgeVariant(run.status)}>{run.status}</Badge>
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      run {run.run_id.slice(0, 10)} • steps {run.steps} • tokens {run.tokens} • cost {money(run.cost_usd)}
                    </div>
                    {run.error_message && (
                      <div className="mt-1 text-xs text-destructive line-clamp-2">{run.error_message}</div>
                    )}
                  </div>
                ))}
                {data.harness.recent_runs.length === 0 && (
                  <p className="text-sm text-muted-foreground">No runs available for this tenant yet.</p>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-xl">Trace Summaries</CardTitle>
                <CardDescription>Token/cost behavior from recent run traces.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-2">
                {data.harness.trace_summaries.map((trace) => (
                  <div key={trace.run_id} className="rounded-lg border p-3 text-sm">
                    <div className="flex items-center justify-between">
                      <div className="font-medium">run {trace.run_id.slice(0, 10)}</div>
                      <Badge variant={statusBadgeVariant(trace.status)}>{trace.status}</Badge>
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      spans {trace.span_count} • in {trace.total_input_tokens} • out {trace.total_output_tokens} • cost {money(trace.total_cost_usd)}
                    </div>
                  </div>
                ))}
                {data.harness.trace_summaries.length === 0 && (
                  <p className="text-sm text-muted-foreground">No trace summaries available yet.</p>
                )}
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <CardTitle className="text-xl">Model-Fit Recommendations</CardTitle>
              <CardDescription>Top opportunities based on token/cost behavior in the selected window.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              {topRecommendations.map((rec, idx) => (
                <div key={`${rec.task_name}-${rec.suggested_model}-${idx}`} className="rounded-lg border p-3">
                  <div className="flex items-center justify-between gap-2">
                    <div className="font-medium text-sm">{rec.task_name}</div>
                    <Badge variant={statusBadgeVariant(rec.confidence === "high" ? "good" : rec.confidence === "medium" ? "watch" : "unknown")}>
                      {rec.confidence}
                    </Badge>
                  </div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    {rec.current_model} → {rec.suggested_model} • est. savings {Number(rec.estimated_savings_pct || 0).toFixed(1)}%
                  </div>
                </div>
              ))}
              {topRecommendations.length === 0 && (
                <p className="text-sm text-muted-foreground">No model-fit recommendations available yet.</p>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}

