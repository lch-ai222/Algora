// Typed client for the CodeAgent Eval console API.

export interface ExperimentRow {
  experiment_id: string;
  agent: string;
  suite: string;
  repeats: number;
  suite_task_success: number;
  suite_strict_success: number;
  created_at: string;
  num_cases: number;
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

async function get<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${url}`);
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
};
