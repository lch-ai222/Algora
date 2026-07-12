// Small shared presentational helpers.
import type { ReactNode } from "react";

export function pct(x: number | undefined): string {
  return x === undefined ? "—" : `${(x * 100).toFixed(0)}%`;
}

export function Stat({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="stat">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
    </div>
  );
}

export function PassBadge({ ok }: { ok: boolean }) {
  return <span className={`badge ${ok ? "pass" : "fail"}`}>{ok ? "pass" : "fail"}</span>;
}

export function Delta({ v, invert = false }: { v: number; invert?: boolean }) {
  const good = invert ? v < 0 : v > 0;
  const cls = v === 0 ? "zero" : good ? "pos" : "neg";
  const s = v > 0 ? `+${v}` : `${v}`;
  return <span className={`delta ${cls}`}>{s}</span>;
}

// Minimal unified-diff colorizer.
export function DiffView({ patch }: { patch: string }) {
  if (!patch.trim()) return <div className="muted">(no changes)</div>;
  return (
    <pre className="diff">
      {patch.split("\n").map((line, i) => {
        let cls = "";
        if (line.startsWith("+++") || line.startsWith("---")) cls = "meta";
        else if (line.startsWith("@@")) cls = "hunk";
        else if (line.startsWith("+")) cls = "add";
        else if (line.startsWith("-")) cls = "del";
        else if (line.startsWith("diff ") || line.startsWith("index ")) cls = "meta";
        return (
          <div key={i} className={cls}>
            {line || " "}
          </div>
        );
      })}
    </pre>
  );
}
