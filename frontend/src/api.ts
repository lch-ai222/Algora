// Typed client for the CodeAgent Eval console API.

export interface ExperimentRow {
  experiment_id: string;
  agent: string;
  adapter?: string | null;
  harness?: string | null;
  provider?: string | null;
  model?: string | null;
  suite: string;
  repeats: number;
  suite_task_success: number;
  suite_strict_success: number;
  created_at: string;
  num_cases: number;
  report_ready: boolean;
}

export interface CaseAgg {
  case_id: string;
  repeats: number;
  task_success_rate: number;
  strict_success_rate: number;
  pass_at_k: number;
  pass_pow_k: number;
  tool_calls_mean: number;
  tool_calls_std: number;
  duration_ms_mean: number;
  tokens_mean: number;
  failure_tags?: Record<string, number>;
}

export interface RunConfig {
  provider: string | null;
  model: string | null;
  temperature: number | null;
  complexity: string | null;
  max_tokens: number | null;
}

export interface ExperimentDetail {
  experiment_id: string;
  agent: string;
  suite: string;
  repeats: number;
  run_config?: RunConfig;
  suite_task_success: number;
  suite_strict_success: number;
  created_at: string;
  cases: CaseAgg[];
}

export interface TraceEvent {
  event_id: string;
  step: number;
  type: string;
  name?: string | null;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface Trial {
  experiment_id: string;
  case_id: string;
  rep: number;
  config: Record<string, unknown> | null;
  grade: any;
  failure: { failed: boolean; primary: string | null; tags: { tag: string; reason: string }[] } | null;
  patch: string;
  events: TraceEvent[];
}

export interface CompareRow {
  case_id: string;
  baseline_task: number;
  candidate_task: number;
  task_delta: number;
  baseline_strict: number;
  candidate_strict: number;
  strict_delta: number;
  tool_calls_delta: number;
  tokens_delta: number;
  status: "improved" | "regressed" | "stable";
}

export interface Compare {
  baseline_id: string;
  candidate_id: string;
  suite: string;
  suite_task_delta: number;
  suite_strict_delta: number;
  baseline_task: number;
  candidate_task: number;
  baseline_strict: number;
  candidate_strict: number;
  improved: string[];
  regressed: string[];
  stable: string[];
  cases: CompareRow[];
}

export interface Interval {
  point: number;
  low: number;
  high: number;
  n_clusters: number;
  n_observations: number;
  resamples: number;
  confidence: number;
  warning: string | null;
}

export interface ReportCost {
  n_trials: number;
  n_priced: number;
  n_successes: number;
  coverage: number;
  observed_cost_usd: number;
  total_cost_usd: number | null;
  cost_per_success_usd: number | null;
  available: boolean;
  reason: string | null;
}

export interface ReportArm {
  experiment_id: string;
  label: string;
  provenance: {
    agent: string | null;
    adapter: string | null;
    harness: string | null;
    model: string | null;
    provider: string | null;
    adapter_version: string | null;
    max_wall_clock: number | null;
    max_steps: number | null;
    ablate: string[];
  };
  trials: { total: number; valid: number; infra_invalid: number };
  task_success: Interval;
  strict_success: Interval;
  cost: ReportCost;
  case_rates: Record<string, { trials: number; task_success: number; strict_success: number }>;
  strata: Record<
    "task_type" | "difficulty" | "horizon",
    { stratum: string; case_count: number; trial_count: number; task_success: number; strict_success: number }[]
  >;
}

export interface PairedMetric {
  available: boolean;
  reason?: string;
  n_pairs?: number;
  both?: number;
  neither?: number;
  a_only?: number;
  b_only?: number;
  p_value?: number;
  rate_a?: number;
  rate_b?: number;
  discordant?: number;
  difference?: number;
}

export interface PairedCost {
  available: boolean;
  reason: string | null;
  n_pairs?: number;
  n_both_priced?: number;
  case_macro_delta_usd?: number | null;
  case_macro_delta_low_usd?: number | null;
  case_macro_delta_high_usd?: number | null;
  warning?: string | null;
}

export interface CrossAgentReport {
  schema: "algora.static_report.v1";
  created_at: string;
  suite: { name: string; case_count: number; cases: string[] };
  arms: ReportArm[];
  comparisons: {
    a: string;
    b: string;
    task_success: PairedMetric;
    strict_success: PairedMetric;
    cost: PairedCost;
  }[];
  limitations: string[];
}

async function get<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) {
    let detail = url;
    try {
      const payload = await r.json() as { detail?: unknown };
      if (typeof payload.detail === "string") detail = payload.detail;
    } catch {
      // Preserve the requested URL when a non-JSON proxy/server error has no structured detail.
    }
    throw new Error(`${r.status} ${detail}`);
  }
  return r.json() as Promise<T>;
}

export const api = {
  experiments: () => get<ExperimentRow[]>("/api/experiments"),
  experiment: (id: string) => get<ExperimentDetail>(`/api/experiments/${id}`),
  reps: (id: string, caseId: string) => get<number[]>(`/api/experiments/${id}/cases/${caseId}/reps`),
  trial: (id: string, caseId: string, rep: number) =>
    get<Trial>(`/api/experiments/${id}/cases/${caseId}/reps/${rep}`),
  compare: (baseline: string, candidate: string) =>
    get<Compare>(`/api/compare?baseline=${encodeURIComponent(baseline)}&candidate=${encodeURIComponent(candidate)}`),
  crossAgent: (experiments: string[]) => {
    const query = new URLSearchParams();
    experiments.forEach((experiment) => query.append("experiments", experiment));
    return get<CrossAgentReport>(`/api/cross-agent?${query.toString()}`);
  },
};
