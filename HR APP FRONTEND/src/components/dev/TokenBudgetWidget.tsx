import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, RefreshCw, Timer, Wallet, Zap } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  getModelEfficiency,
  getModelRecommendations,
  getTokenBudgets,
  getTokenHotspots,
  getTokenSummary,
  type ModelEfficiencyRow,
  type ModelRecommendation,
  type TokenBudgets,
  type TokenHotspot,
  type TokenSummary,
} from '@/services/tokenMonitor';

function fmtNumber(value: number): string {
  return new Intl.NumberFormat('en-US').format(value || 0);
}

function fmtUsd(value: number): string {
  return `$${(value || 0).toFixed(4)}`;
}

export function TokenBudgetWidget() {
  const [summary, setSummary] = useState<TokenSummary | null>(null);
  const [hotspots, setHotspots] = useState<TokenHotspot[]>([]);
  const [budgets, setBudgets] = useState<TokenBudgets | null>(null);
  const [models, setModels] = useState<ModelEfficiencyRow[]>([]);
  const [recommendations, setRecommendations] = useState<ModelRecommendation[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);

  const fetchData = useCallback(async (isRefresh = false) => {
    try {
      if (isRefresh) {
        setRefreshing(true);
      } else {
        setLoading(true);
      }
      setError(null);

      const [summaryData, hotspotsData, budgetsData, modelRows, recommendationData] = await Promise.all([
        getTokenSummary(30),
        getTokenHotspots(5, 30),
        getTokenBudgets(),
        getModelEfficiency(30),
        getModelRecommendations(30, 8),
      ]);

      setSummary(summaryData);
      setHotspots(hotspotsData);
      setBudgets(budgetsData);
      setModels(modelRows);
      setRecommendations(recommendationData.opportunities || []);
      setUpdatedAt(new Date());
    } catch (err: any) {
      if (err?.name !== 'CanceledError' && err?.name !== 'AbortError') {
        setError(err?.response?.data?.detail || err?.message || 'Failed to load token monitor');
      }
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    fetchData(false);
    const id = window.setInterval(() => {
      fetchData(true);
    }, 15000);
    return () => window.clearInterval(id);
  }, [fetchData]);

  const overBudgetRate = useMemo(() => {
    if (!summary || summary.calls === 0) return 0;
    return (summary.over_budget_calls / summary.calls) * 100;
  }, [summary]);

  return (
    <Card className="border-dashed">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between gap-3">
          <div>
            <CardTitle className="text-base">Developer Token Monitor</CardTitle>
            <CardDescription>
              Internal-only live budget status for recruiter-side AI pipelines (last 30 min).
            </CardDescription>
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="gap-1.5"
            onClick={() => fetchData(true)}
            disabled={refreshing}
          >
            <RefreshCw className={`h-3.5 w-3.5 ${refreshing ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
        </div>
      </CardHeader>

      <CardContent className="space-y-3">
        {loading ? (
          <div className="text-sm text-muted-foreground">Loading monitor data...</div>
        ) : error ? (
          <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
            {error}
          </div>
        ) : (
          <>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
              <div className="rounded-lg border p-2">
                <div className="text-xs text-muted-foreground flex items-center gap-1"><Zap className="h-3 w-3" />Tokens</div>
                <div className="text-lg font-semibold">{fmtNumber(summary?.total_tokens || 0)}</div>
              </div>
              <div className="rounded-lg border p-2">
                <div className="text-xs text-muted-foreground">Calls</div>
                <div className="text-lg font-semibold">{fmtNumber(summary?.calls || 0)}</div>
              </div>
              <div className="rounded-lg border p-2">
                <div className="text-xs text-muted-foreground flex items-center gap-1"><Wallet className="h-3 w-3" />Estimated Cost</div>
                <div className="text-lg font-semibold">{fmtUsd(summary?.total_cost_usd || 0)}</div>
              </div>
              <div className="rounded-lg border p-2">
                <div className="text-xs text-muted-foreground flex items-center gap-1"><Timer className="h-3 w-3" />Avg Latency</div>
                <div className="text-lg font-semibold">{(summary?.avg_latency_ms || 0).toFixed(0)} ms</div>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2 text-xs">
              <Badge variant={overBudgetRate > 20 ? 'destructive' : 'secondary'}>
                Over-budget rate: {overBudgetRate.toFixed(1)}%
              </Badge>
              <Badge variant={(summary?.cost_alert_calls || 0) > 0 ? 'destructive' : 'secondary'}>
                Cost alerts: {summary?.cost_alert_calls || 0}
              </Badge>
              {budgets && (
                <Badge variant="outline">
                  Default budget/call: {fmtNumber(budgets.default_token_budget)} tokens
                </Badge>
              )}
              {updatedAt && <span className="text-muted-foreground">Updated {updatedAt.toLocaleTimeString()}</span>}
            </div>

            <div className="space-y-1">
              <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Top Pipeline Hotspots</div>
              {hotspots.length === 0 ? (
                <div className="text-sm text-muted-foreground">No pipeline calls captured yet.</div>
              ) : (
                hotspots.map((row) => (
                  <div key={row.task_name} className="rounded-md border p-2 flex flex-wrap items-center justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-sm font-medium truncate">{row.task_name}</p>
                      <p className="text-xs text-muted-foreground">
                        {fmtNumber(row.calls)} calls • {fmtNumber(row.total_tokens)} tokens • budget {fmtNumber(row.budget_tokens)}
                      </p>
                    </div>
                    <div className="flex items-center gap-2 text-xs">
                      {row.over_budget_calls > 0 && (
                        <Badge variant="destructive" className="gap-1">
                          <AlertTriangle className="h-3 w-3" />
                          {row.over_budget_calls} over
                        </Badge>
                      )}
                      <Badge variant="outline">{fmtUsd(row.total_cost_usd)}</Badge>
                    </div>
                  </div>
                ))
              )}
            </div>

            <div className="space-y-1">
              <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Model Efficiency</div>
              {models.length === 0 ? (
                <div className="text-sm text-muted-foreground">No model usage data yet.</div>
              ) : (
                models
                  .slice()
                  .sort((a, b) => a.cost_per_1k_tokens_usd - b.cost_per_1k_tokens_usd)
                  .slice(0, 5)
                  .map((row) => (
                    <div key={row.model} className="rounded-md border p-2 flex flex-wrap items-center justify-between gap-2">
                      <div className="min-w-0">
                        <p className="text-sm font-medium truncate">{row.model}</p>
                        <p className="text-xs text-muted-foreground">
                          {fmtNumber(row.calls)} calls • {fmtUsd(row.avg_cost_per_call_usd)} / call • {row.avg_latency_ms.toFixed(0)} ms
                        </p>
                      </div>
                      <Badge variant="outline">{fmtUsd(row.cost_per_1k_tokens_usd)} / 1K tokens</Badge>
                    </div>
                  ))
              )}
            </div>

            <div className="space-y-1">
              <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Optimizer Suggestions</div>
              {recommendations.length === 0 ? (
                <div className="text-sm text-muted-foreground">
                  No reliable model-switch opportunity yet (need mixed-model history per task).
                </div>
              ) : (
                recommendations.slice(0, 5).map((rec) => (
                  <div key={`${rec.task_name}:${rec.current_model}:${rec.suggested_model}`} className="rounded-md border p-2">
                    <p className="text-sm font-medium">
                      {rec.task_name}: {rec.current_model} → {rec.suggested_model}
                    </p>
                    <p className="text-xs text-muted-foreground mt-1">
                      Save {fmtUsd(rec.estimated_savings_per_call_usd)} / call ({rec.estimated_savings_pct.toFixed(1)}%).
                      Token ratio {rec.token_ratio_vs_current.toFixed(2)} • latency ratio {rec.latency_ratio_vs_current.toFixed(2)}.
                    </p>
                    <div className="mt-1 flex flex-wrap items-center gap-2 text-xs">
                      <Badge variant="outline">Confidence: {rec.confidence}</Badge>
                      <span className="text-muted-foreground">
                        Calls (current/suggested): {fmtNumber(rec.current_calls)} / {fmtNumber(rec.suggested_calls)}
                      </span>
                    </div>
                  </div>
                ))
              )}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
