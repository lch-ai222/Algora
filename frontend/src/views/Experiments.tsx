import { useEffect, useState } from "react";
import { api, ExperimentRow } from "../api";
import { pct } from "../ui";
import { Route } from "../App";

export function Experiments({ setRoute }: { setRoute: (r: Route) => void }) {
  const [rows, setRows] = useState<ExperimentRow[]>([]);
  const [err, setErr] = useState<string>();

  useEffect(() => {
    api.experiments().then(setRows).catch((e) => setErr(String(e)));
  }, []);

  if (err) return <div className="card">Failed to load: {err}</div>;

  return (
    <div className="card">
      <div className="row" style={{ marginBottom: 10 }}>
        <strong>Experiments</strong>
        <span className="pill">{rows.length} runs</span>
      </div>
      <table>
        <thead>
          <tr>
            <th>Experiment</th>
            <th>Agent</th>
            <th>Suite</th>
            <th>Cases×Reps</th>
            <th>Task</th>
            <th>Strict</th>
            <th>Created</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.experiment_id} className="clickable" onClick={() => setRoute({ view: "detail", expId: r.experiment_id })}>
              <td className="mono">{r.experiment_id}</td>
              <td>
                <span className="badge agent">{r.agent}</span>
              </td>
              <td>{r.suite}</td>
              <td className="muted">
                {r.num_cases}×{r.repeats}
              </td>
              <td>{pct(r.suite_task_success)}</td>
              <td>{pct(r.suite_strict_success)}</td>
              <td className="muted">{r.created_at}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
