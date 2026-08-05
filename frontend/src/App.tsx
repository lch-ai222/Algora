import { useState } from "react";
import { Experiments } from "./views/Experiments";
import { ExperimentDetail } from "./views/ExperimentDetail";
import { TraceViewer } from "./views/TraceViewer";
import { Compare } from "./views/Compare";
import { CrossAgent } from "./views/CrossAgent";

export type Route =
  | { view: "experiments" }
  | { view: "detail"; expId: string }
  | { view: "trace"; expId: string; caseId: string; rep: number }
  | { view: "compare"; baseline?: string; candidate?: string }
  | { view: "cross-agent" };

export function App() {
  const [route, setRoute] = useState<Route>({ view: "experiments" });

  return (
    <div className="app">
      <div className="topbar">
        <h1>CodeAgent Eval Console</h1>
        <div className="crumbs">
          <a onClick={() => setRoute({ view: "experiments" })}>experiments</a>
          {route.view === "detail" && <span>{route.expId}</span>}
          {route.view === "trace" && (
            <>
              <a onClick={() => setRoute({ view: "detail", expId: route.expId })}>{route.expId}</a>
              <span>
                {route.caseId} · rep{route.rep}
              </span>
            </>
          )}
          {route.view === "compare" && <span>version compare</span>}
          {route.view === "cross-agent" && <span>cross-agent report</span>}
        </div>
        <div className="spacer" />
        <div className="row topnav">
          <a onClick={() => setRoute({ view: "cross-agent" })}>Cross-Agent Report</a>
          <a onClick={() => setRoute({ view: "compare" })}>Version Compare</a>
        </div>
      </div>

      {route.view === "experiments" && <Experiments setRoute={setRoute} />}
      {route.view === "detail" && <ExperimentDetail expId={route.expId} setRoute={setRoute} />}
      {route.view === "trace" && (
        <TraceViewer expId={route.expId} caseId={route.caseId} rep={route.rep} setRoute={setRoute} />
      )}
      {route.view === "compare" && (
        <Compare baseline={route.baseline} candidate={route.candidate} setRoute={setRoute} />
      )}
      {route.view === "cross-agent" && <CrossAgent />}
    </div>
  );
}
