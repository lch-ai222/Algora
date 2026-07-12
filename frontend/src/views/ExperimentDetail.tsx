import { useEffect, useState } from "react";
import { api, ExperimentDetail as Detail } from "../api";
import { pct, Stat } from "../ui";
import { Route } from "../App";

export function ExperimentDetail({ expId, setRoute }: { expId: string; setRoute: (r: Route) => void }) {
  const [d, setD] = useState<Detail>();
  const [onlyFailed, setOnlyFailed] = useState(false);
  const [err, setErr] = useState<string>();

  useEffect(() => {
    api.experiment(expId).then(setD).catch((e) => setErr(String(e)));
  }, [expId]);

  if (err) return <div className="card">Failed: {err}</div>;
  if (!d) return <div className="card">Loading…</div>;

  const cases = onlyFailed ? d.cases.filter((c) => c.task_success_rate < 1) : d.cases;

  return (
    <>
      <div className="card">
        <div className="row" style={{ marginBottom: 12 }}>
          <span className="badge agent">{d.agent}</span>
          <strong className="mono">{d.experiment_id}</strong>
          <span className="pill">
            {d.suite} · {d.repeats} repeats
          </span>
          <div className="spacer" />
          {d.run_config?.model ? (
            <span className="pill mono" title="run provenance — a V1/V2 comparison is only valid when these match">
              {d.run_config.provider}/{d.run_config.model} · temp {d.run_config.temperature} · max_tokens{" "}
              {d.run_config.max_tokens}
            </span>
          ) : (
            <span className="pill">deterministic (no model)</span>
          )}
        </div>
        <div className="grid">
          <Stat label="Suite Task Success" value={pct(d.suite_task_success)} />
          <Stat label="Suite Strict Success" value={pct(d.suite_strict_success)} />
          <Stat label="Cases" value={d.cases.length} />
        </div>
      </div>

      <div className="card">
        <div className="row" style={{ marginBottom: 10 }}>
          <strong>Cases</strong>
          <div className="spacer" />
          <label className="pill">
            <input type="checkbox" checked={onlyFailed} onChange={(e) => setOnlyFailed(e.target.checked)} /> only
            task&lt;100%
          </label>
        </div>
        <table>
          <thead>
            <tr>
              <th>Case</th>
              <th>Task</th>
              <th>Strict</th>
              <th title="at least one repeat passed">pass@k</th>
              <th title="every repeat passed">pass^k</th>
              <th>Tools</th>
              <th>Failure</th>
            </tr>
          </thead>
          <tbody>
            {cases.map((c) => {
              const tag = c.failure_tags && Object.keys(c.failure_tags)[0];
              return (
                <tr
                  key={c.case_id}
                  className="clickable"
                  onClick={() => setRoute({ view: "trace", expId, caseId: c.case_id, rep: 0 })}
                >
                  <td className="mono">{c.case_id}</td>
                  <td>{pct(c.task_success_rate)}</td>
                  <td>{pct(c.strict_success_rate)}</td>
                  <td>{c.pass_at_k ? "✓" : "—"}</td>
                  <td>{c.pass_pow_k ? "✓" : <span className="status-regressed">✗</span>}</td>
                  <td className="muted">{c.tool_calls_mean}</td>
                  <td>{tag ? <span className="badge tag">{tag}</span> : <span className="muted">—</span>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}
