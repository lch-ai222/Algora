import { useEffect, useState } from "react";
import { api, Trial, TraceEvent } from "../api";
import { DiffView, PassBadge } from "../ui";
import { Route } from "../App";

export function TraceViewer({
  expId,
  caseId,
  rep,
  setRoute,
}: {
  expId: string;
  caseId: string;
  rep: number;
  setRoute: (r: Route) => void;
}) {
  const [reps, setReps] = useState<number[]>([]);
  const [trial, setTrial] = useState<Trial>();
  const [sel, setSel] = useState<number>(0);
  const [err, setErr] = useState<string>();

  useEffect(() => {
    api.reps(expId, caseId).then(setReps).catch(() => {});
  }, [expId, caseId]);
  useEffect(() => {
    setTrial(undefined);
    api.trial(expId, caseId, rep).then((t) => { setTrial(t); setSel(0); }).catch((e) => setErr(String(e)));
  }, [expId, caseId, rep]);

  if (err) return <div className="card">Failed: {err}</div>;
  if (!trial) return <div className="card">Loading…</div>;

  const g = trial.grade;
  const ev: TraceEvent | undefined = trial.events[sel];

  return (
    <>
      <div className="card">
        <div className="row">
          <strong className="mono">{caseId}</strong>
          {g && <PassBadge ok={g.task_success} />}
          <span className="pill">stop: {String(trial.config?.stop_reason)}</span>
          <div className="spacer" />
          <span className="pill">rep</span>
          <select value={rep} onChange={(e) => setRoute({ view: "trace", expId, caseId, rep: Number(e.target.value) })}>
            {reps.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Grader + failure summary */}
      <div className="card">
        <div className="row" style={{ gap: 20 }}>
          {g && (
            <>
              <span>
                Task <PassBadge ok={g.task_success} />
              </span>
              <span>
                Strict <PassBadge ok={g.strict_success} />
              </span>
              <span className="pill">target {g.test.target_passed ? "✓" : "✗"}</span>
              <span className="pill">regression {g.test.regression_passed ? "✓" : "✗"}</span>
              <span className="pill">hidden {g.test.hidden_passed ? "✓" : "✗"}</span>
              <span className="pill">files {g.patch.changed_file_count}</span>
              {g.patch.modified_tests && <span className="badge fail">modified tests</span>}
            </>
          )}
        </div>
        {trial.failure?.failed && (
          <div className="row" style={{ marginTop: 10 }}>
            {trial.failure.tags.map((t) => (
              <span key={t.tag} className="badge tag" title={t.reason}>
                {t.tag}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Trajectory */}
      <div className="card">
        <div className="trace">
          <div className="steplist">
            {trial.events.map((e, i) => (
              <div key={e.event_id} className={`step ${i === sel ? "active" : ""}`} onClick={() => setSel(i)}>
                <div className="etype">
                  s{e.step} · {e.type}
                </div>
                <div className="mono" style={{ fontSize: 12 }}>
                  {e.name || <span className="muted">—</span>}
                </div>
              </div>
            ))}
          </div>
          <div className="eventdetail">
            {ev ? (
              <>
                <div className="row" style={{ marginBottom: 8 }}>
                  <span className="badge agent">{ev.type}</span>
                  {ev.name && <span className="mono">{ev.name}</span>}
                </div>
                <pre>{JSON.stringify(ev.payload, null, 2)}</pre>
              </>
            ) : (
              <div className="muted">no events</div>
            )}
          </div>
        </div>
      </div>

      {/* Final patch */}
      <div className="card">
        <div className="row" style={{ marginBottom: 8 }}>
          <strong>Patch</strong>
          <span className="pill">
            +{g?.patch.insertions ?? 0} / -{g?.patch.deletions ?? 0} · hidden{" "}
            {g?.test?.hidden?.passed?.length ?? 0} passed
          </span>
        </div>
        <DiffView patch={trial.patch} />
      </div>
    </>
  );
}
