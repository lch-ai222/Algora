import { useEffect, useMemo, useState } from "react";
import { api, CrossAgentReport, ExperimentRow, PairedMetric, ReportArm } from "../api";
import { pct } from "../ui";

type Stratum = "task_type" | "difficulty" | "horizon";

const money = (value: number | null | undefined) =>
  value == null ? "unavailable" : `$${value.toFixed(6)}`;

const interval = (arm: ReportArm, metric: "task_success" | "strict_success") => {
  const value = arm[metric];
  return `${pct(value.point)} [${pct(value.low)}, ${pct(value.high)}]`;
};

const metricResult = (value: PairedMetric) => {
  if (!value.available) return value.reason ?? "unavailable";
  return `${(value.difference! * 100).toFixed(1)} pp · p=${value.p_value!.toFixed(4)} · ${value.discordant} discordant`;
};

const heatClass = (value: number) =>
  value >= 1 ? "heat-full" : value >= 0.5 ? "heat-mid" : value > 0 ? "heat-low" : "heat-zero";

export function CrossAgent() {
  const [rows, setRows] = useState<ExperimentRow[]>([]);
  const [suite, setSuite] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [report, setReport] = useState<CrossAgentReport>();
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string>();
  const [stratum, setStratum] = useState<Stratum>("difficulty");

  const ready = useMemo(() => rows.filter((row) => row.report_ready), [rows]);
  const suites = useMemo(() => Array.from(new Set(ready.map((row) => row.suite))), [ready]);
  const candidates = useMemo(() => ready.filter((row) => row.suite === suite), [ready, suite]);
  const selectedRows = useMemo(
    () => candidates.filter((row) => selected.includes(row.experiment_id)),
    [candidates, selected],
  );
  const selectionWarnings = useMemo(() => {
    if (selectedRows.length < 2) return [];
    const messages: string[] = [];
    const models = new Set(selectedRows.map((row) => row.model).filter(Boolean));
    if (selectedRows.some((row) => !row.model)) {
      messages.push("At least one arm has no recorded model, so model control cannot be verified from provenance.");
    } else if (models.size > 1) {
      messages.push("The selected arms use different models. Results may be described, but differences cannot be attributed to the agent or harness alone.");
    }
    const schedules = new Set(selectedRows.map((row) => `${row.num_cases}×${row.repeats}`));
    if (schedules.size > 1) {
      messages.push("The selected experiments have different case×repeat sizes; exact paired tests will be unavailable unless their valid trial grids match.");
    }
    return messages;
  }, [selectedRows]);

  useEffect(() => {
    api.experiments()
      .then((items) => {
        setRows(items);
        const usable = items.filter((item) => item.report_ready);
        const initialSuite = usable.find((item) => usable.filter((other) => other.suite === item.suite).length >= 2)?.suite
          ?? usable[0]?.suite
          ?? "";
        setSuite(initialSuite);
        setSelected(usable.filter((item) => item.suite === initialSuite).slice(0, 2).map((item) => item.experiment_id));
      })
      .catch((error) => setErr(String(error)));
  }, []);

  const changeSuite = (nextSuite: string) => {
    setSuite(nextSuite);
    setSelected(ready.filter((item) => item.suite === nextSuite).slice(0, 2).map((item) => item.experiment_id));
    setReport(undefined);
    setErr(undefined);
  };

  const toggle = (experimentId: string) => {
    setSelected((current) => current.includes(experimentId)
      ? current.filter((item) => item !== experimentId)
      : current.length < 6 ? [...current, experimentId] : current);
    setReport(undefined);
    setErr(undefined);
  };

  const generate = async () => {
    if (!selected.length) return;
    setLoading(true);
    setErr(undefined);
    try {
      setReport(await api.crossAgent(selected));
    } catch (error) {
      setReport(undefined);
      setErr(String(error));
    } finally {
      setLoading(false);
    }
  };

  const warnings = report
    ? [
        ...report.arms.flatMap((arm) => [arm.task_success.warning, arm.strict_success.warning]),
        ...report.comparisons.map((comparison) => comparison.cost.warning),
      ].filter((warning): warning is string => Boolean(warning))
    : [];

  return (
    <>
      <div className="card">
        <div className="row report-heading">
          <div>
            <strong>Cross-Agent Evaluation Report</strong>
            <div className="muted report-subtitle">One W3-5 fact model; no statistics are recomputed in the browser.</div>
          </div>
          <div className="spacer" />
          <label className="row compact-control">
            <span className="pill">suite</span>
            <select value={suite} onChange={(event) => changeSuite(event.target.value)}>
              {suites.map((name) => <option key={name}>{name}</option>)}
            </select>
          </label>
          <button disabled={!selected.length || loading} onClick={generate}>
            {loading ? "Analyzing…" : "Build report"}
          </button>
        </div>

        {!ready.length && <div className="empty-state">No report-ready experiments were found.</div>}
        {candidates.length > 0 && (
          <div className="experiment-picker">
            {candidates.map((row) => (
              <label className={`experiment-option ${selected.includes(row.experiment_id) ? "selected" : ""}`} key={row.experiment_id}>
                <input
                  type="checkbox"
                  checked={selected.includes(row.experiment_id)}
                  onChange={() => toggle(row.experiment_id)}
                  disabled={!selected.includes(row.experiment_id) && selected.length >= 6}
                />
                <span>
                  <span className="mono">{row.experiment_id}</span>
                  <small>{row.adapter ?? row.agent}{row.harness ? ` / ${row.harness}` : ""} · {row.model ?? "model unavailable"}</small>
                </span>
              </label>
            ))}
          </div>
        )}
        <div className="muted selection-note">Select 1–6 experiments from one suite. Two or more arms enable paired comparisons.</div>
        {selectionWarnings.length > 0 && (
          <div className="callout warning selection-warning">
            <strong>Comparison audit</strong>
            <ul>{selectionWarnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
          </div>
        )}
        {err && <div className="callout danger">Failed to build report: {err}</div>}
      </div>

      {report && (
        <>
          <div className="report-meta row">
            <span className="badge agent">{report.suite.name}</span>
            <span>{report.suite.case_count} observed cases</span>
            <span>{report.arms.length} arms</span>
            <span className="spacer" />
            <span className="mono muted">{report.schema}</span>
          </div>

          {warnings.length > 0 && (
            <div className="card callout warning">
              <strong>Evidence warnings</strong>
              <ul>{Array.from(new Set(warnings)).map((warning) => <li key={warning}>{warning}</li>)}</ul>
            </div>
          )}

          <div className="arm-grid">
            {report.arms.map((arm) => (
              <div className="card arm-card" key={arm.label}>
                <div className="arm-title">
                  <span className="badge agent">{arm.provenance.adapter ?? arm.provenance.agent ?? "agent"}</span>
                  <strong>{arm.label}</strong>
                </div>
                <div className="headline-metric">
                  <span>Task Success · case-cluster 95% CI</span>
                  <b>{interval(arm, "task_success")}</b>
                </div>
                <div className="headline-metric">
                  <span>Strict Success · case-cluster 95% CI</span>
                  <b>{interval(arm, "strict_success")}</b>
                </div>
                <dl className="mini-stats">
                  <div><dt>Valid / total</dt><dd>{arm.trials.valid} / {arm.trials.total}</dd></div>
                  <div><dt>Infra-invalid</dt><dd className={arm.trials.infra_invalid ? "status-regressed" : ""}>{arm.trials.infra_invalid}</dd></div>
                  <div><dt>Cost coverage</dt><dd>{arm.cost.n_priced} / {arm.cost.n_trials}</dd></div>
                  <div><dt>Cost / success</dt><dd>{money(arm.cost.cost_per_success_usd)}</dd></div>
                </dl>
                {arm.cost.reason && <div className="muted evidence-note">{arm.cost.reason}</div>}
              </div>
            ))}
          </div>

          <div className="card table-scroll">
            <strong>Provenance & budget contract</strong>
            <p className="muted">Use this table to verify that a claimed controlled comparison actually holds its model and budgets fixed.</p>
            <table>
              <thead><tr><th>Arm</th><th>System</th><th>Provider / model</th><th>Adapter version</th><th>Wall clock</th><th>Max steps</th><th>Ablation</th></tr></thead>
              <tbody>{report.arms.map((arm) => (
                <tr key={arm.label}>
                  <td>{arm.label}</td>
                  <td>{arm.provenance.adapter ?? arm.provenance.agent ?? "—"}{arm.provenance.harness ? ` / ${arm.provenance.harness}` : ""}</td>
                  <td>{arm.provenance.provider ?? "—"} / {arm.provenance.model ?? "—"}</td>
                  <td className="mono">{arm.provenance.adapter_version ?? "—"}</td>
                  <td>{arm.provenance.max_wall_clock ?? "case default"}</td>
                  <td>{arm.provenance.max_steps ?? "case default"}</td>
                  <td>{arm.provenance.ablate.length ? arm.provenance.ablate.join(", ") : "—"}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>

          <div className="card table-scroll">
            <strong>Case matrix</strong>
            <p className="muted">Each cell is Task / Strict. Infra-invalid-only scheduled cases remain visible as unavailable.</p>
            <table className="matrix">
              <thead><tr><th>Case</th>{report.arms.map((arm) => <th key={arm.label}>{arm.label}</th>)}</tr></thead>
              <tbody>{report.suite.cases.map((caseId) => (
                <tr key={caseId}>
                  <td className="mono">{caseId}</td>
                  {report.arms.map((arm) => {
                    const value = arm.case_rates[caseId];
                    return <td key={arm.label}>{value
                      ? <span className={`matrix-cell ${heatClass(value.task_success)}`}>{pct(value.task_success)} / {pct(value.strict_success)} <small>n={value.trials}</small></span>
                      : <span className="muted">unavailable</span>}</td>;
                  })}
                </tr>
              ))}</tbody>
            </table>
          </div>

          <div className="card table-scroll">
            <div className="row">
              <strong>Stratified case-macro averages</strong>
              <div className="spacer" />
              <select value={stratum} onChange={(event) => setStratum(event.target.value as Stratum)}>
                <option value="difficulty">difficulty</option>
                <option value="task_type">task type</option>
                <option value="horizon">horizon</option>
              </select>
            </div>
            <table>
              <thead><tr><th>Arm</th><th>Stratum</th><th>Cases</th><th>Trials</th><th>Task</th><th>Strict</th></tr></thead>
              <tbody>{report.arms.flatMap((arm) => arm.strata[stratum].map((item) => (
                <tr key={`${arm.label}-${item.stratum}`}><td>{arm.label}</td><td>{item.stratum}</td><td>{item.case_count}</td><td>{item.trial_count}</td><td>{pct(item.task_success)}</td><td>{pct(item.strict_success)}</td></tr>
              )))}</tbody>
            </table>
          </div>

          <div className="card table-scroll">
            <strong>Paired comparisons</strong>
            <p className="muted">Deltas are A − B. Exact McNemar requires the same case×repeat grid; unavailable is preferable to a fictional pairing.</p>
            {report.comparisons.length ? (
              <table>
                <thead><tr><th>Pair</th><th>Task delta</th><th>Strict delta</th><th>Case-macro cost delta</th></tr></thead>
                <tbody>{report.comparisons.map((comparison) => (
                  <tr key={`${comparison.a}-${comparison.b}`}>
                    <td>{comparison.a} − {comparison.b}</td>
                    <td>{metricResult(comparison.task_success)}</td>
                    <td>{metricResult(comparison.strict_success)}</td>
                    <td>{comparison.cost.available
                      ? `${money(comparison.cost.case_macro_delta_usd)} [${money(comparison.cost.case_macro_delta_low_usd)}, ${money(comparison.cost.case_macro_delta_high_usd)}]`
                      : comparison.cost.reason ?? "unavailable"}</td>
                  </tr>
                ))}</tbody>
              </table>
            ) : <div className="empty-state">Select at least two arms to produce a paired comparison.</div>}
          </div>

          <div className="card boundaries">
            <strong>Evidence boundaries</strong>
            <ul>{report.limitations.map((item) => <li key={item}>{item}</li>)}</ul>
          </div>
        </>
      )}
    </>
  );
}
