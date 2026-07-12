import { useEffect, useState } from "react";
import { api, Compare as Cmp, ExperimentRow } from "../api";
import { Delta, pct, Stat } from "../ui";
import { Route } from "../App";

export function Compare({
  baseline,
  candidate,
  setRoute,
}: {
  baseline?: string;
  candidate?: string;
  setRoute: (r: Route) => void;
}) {
  const [rows, setRows] = useState<ExperimentRow[]>([]);
  const [b, setB] = useState<string | undefined>(baseline);
  const [c, setC] = useState<string | undefined>(candidate);
  const [cmp, setCmp] = useState<Cmp>();
  const [err, setErr] = useState<string>();

  useEffect(() => {
    api.experiments().then((r) => {
      setRows(r);
      // Default to the newest v1 (baseline) and v2 (candidate) with matching case counts.
      if (!b) setB(r.find((e) => e.agent === "v1")?.experiment_id);
      if (!c) setC(r.find((e) => e.agent === "v2")?.experiment_id);
    });
  }, []);

  useEffect(() => {
    if (b && c) api.compare(b, c).then(setCmp).catch((e) => setErr(String(e)));
  }, [b, c]);

  const picker = (val: string | undefined, set: (v: string) => void, label: string) => (
    <label className="row" style={{ gap: 6 }}>
      <span className="pill">{label}</span>
      <select value={val ?? ""} onChange={(e) => set(e.target.value)}>
        <option value="" disabled>
          pick…
        </option>
        {rows.map((r) => (
          <option key={r.experiment_id} value={r.experiment_id}>
            {r.agent} · {r.experiment_id}
          </option>
        ))}
      </select>
    </label>
  );

  return (
    <>
      <div className="card">
        <div className="row" style={{ marginBottom: 12 }}>
          <strong>Version Compare</strong>
          <div className="spacer" />
          {picker(b, setB, "baseline")}
          {picker(c, setC, "candidate")}
        </div>
        {err && <div className="muted">Failed: {err}</div>}
        {cmp && (
          <div className="grid">
            <Stat
              label="Task Success"
              value={
                <>
                  {pct(cmp.baseline_task)} → {pct(cmp.candidate_task)} <Delta v={cmp.suite_task_delta} />
                </>
              }
            />
            <Stat
              label="Strict Success"
              value={
                <>
                  {pct(cmp.baseline_strict)} → {pct(cmp.candidate_strict)} <Delta v={cmp.suite_strict_delta} />
                </>
              }
            />
            <Stat
              label="Improved / Regressed / Stable"
              value={
                <>
                  <span className="status-improved">{cmp.improved.length}</span> /{" "}
                  <span className="status-regressed">{cmp.regressed.length}</span> /{" "}
                  <span className="status-stable">{cmp.stable.length}</span>
                </>
              }
            />
          </div>
        )}
      </div>

      {cmp && (
        <div className="card">
          <table>
            <thead>
              <tr>
                <th>Case</th>
                <th>Task (base → cand)</th>
                <th>Strict</th>
                <th>Tools Δ</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {cmp.cases.map((r) => (
                <tr
                  key={r.case_id}
                  className="clickable"
                  onClick={() => c && setRoute({ view: "trace", expId: b!, caseId: r.case_id, rep: 0 })}
                >
                  <td className="mono">{r.case_id}</td>
                  <td>
                    {pct(r.baseline_task)} → {pct(r.candidate_task)}{" "}
                    {r.task_delta !== 0 && <Delta v={r.task_delta} />}
                  </td>
                  <td>
                    {pct(r.baseline_strict)} → {pct(r.candidate_strict)}
                  </td>
                  <td>
                    <Delta v={r.tool_calls_delta} invert />
                  </td>
                  <td className={`status-${r.status}`}>{r.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
