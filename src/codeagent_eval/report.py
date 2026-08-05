"""Build deterministic, offline Markdown/HTML reports from Algora experiment artifacts."""

from __future__ import annotations

import html
import json
import shutil
import statistics
import tempfile
from dataclasses import asdict, dataclass
from itertools import combinations
from pathlib import Path
from typing import Any

from codeagent_eval.benchmark import EvalCase, load_suite
from codeagent_eval.models import utc_now_iso
from codeagent_eval.stats import (
    Cluster,
    CostObservation,
    UnpairedSamples,
    cluster_bootstrap_ci,
    paired_comparison,
    paired_cost_comparison,
    stratified_macro_average,
    summarize_costs,
)

REPORT_SCHEMA = "algora.static_report.v1"
_EXPLICIT_ZERO_COST_SOURCES = {"provider_reported_free", "free_tier"}


class ReportError(ValueError):
    """Artifacts cannot support the requested report without inventing evidence."""


@dataclass(frozen=True)
class TrialRecord:
    key: str
    case_id: str
    repeat: str
    task_success: bool
    strict_success: bool
    valid: bool
    cost_usd: float | None
    cost_source: str
    tokens: int | None
    duration_ms: int | None


@dataclass(frozen=True)
class ExperimentData:
    path: Path
    experiment_id: str
    label: str
    summary: dict[str, Any]
    records: tuple[TrialRecord, ...]

    @property
    def valid_records(self) -> list[TrialRecord]:
        return [record for record in self.records if record.valid]


def _read_json(path: Path, *, required: bool = True) -> dict[str, Any] | None:
    if not path.is_file():
        if required:
            raise ReportError(f"missing required artifact: {path}")
        return None
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise ReportError(f"unreadable JSON artifact: {path}") from exc
    if not isinstance(value, dict):
        raise ReportError(f"expected JSON object: {path}")
    return value


def _numeric(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _cost_from_payloads(payloads: list[dict[str, Any]], config: dict[str, Any]) -> tuple[float | None, str]:
    """Accept positive priced costs; reject ambiguous historical zeroes as unavailable."""
    seen_sources: list[str] = []
    for payload in payloads:
        source = str(payload.get("cost_source") or "unavailable")
        seen_sources.append(source)
        amount = _numeric(payload.get("cost_usd"))
        if amount is None or amount < 0 or source == "unavailable":
            continue
        if amount > 0 or source in _EXPLICIT_ZERO_COST_SOURCES:
            return amount, source

    # Historical MiniAgent artifacts used 0.0/derived before the pricing table existed. Treating
    # those as free would be a stronger and false claim than saying the cost is unavailable.
    provider = config.get("provider")
    reason = "unavailable"
    if any(source == "derived" for source in seen_sources) and provider:
        reason = "legacy_zero_unpriced"
    return None, reason


def _usage_from_payloads(payloads: list[dict[str, Any]]) -> tuple[int | None, int | None]:
    candidates: list[tuple[int, int | None]] = []
    for payload in payloads:
        prompt = payload.get("prompt_tokens")
        completion = payload.get("completion_tokens")
        if isinstance(prompt, int) and isinstance(completion, int):
            tokens = prompt + completion
            duration = payload.get("duration_ms")
            candidates.append((tokens, duration if isinstance(duration, int) else None))
    return max(candidates, key=lambda item: item[0]) if candidates else (None, None)


def _trial_record(trial_dir: Path, known_cases: set[str]) -> TrialRecord:
    grade = _read_json(trial_dir / "grader-results.json")
    config = _read_json(trial_dir / "config.json")
    failure = _read_json(trial_dir / "failure-tags.json", required=False) or {}
    trial = _read_json(trial_dir / "trial.json", required=False)
    agent_result = _read_json(trial_dir / "agent-result.json", required=False)
    case_id = str(config.get("case_id") or grade.get("case_id") or trial_dir.parent.name)
    if case_id not in known_cases:
        raise ReportError(f"artifact case {case_id!r} is absent from the selected suite")
    ids = {value for value in (config.get("case_id"), grade.get("case_id"), failure.get("case_id"))
           if value is not None}
    if ids != {case_id}:
        raise ReportError(f"artifact case_id mismatch in {trial_dir}: {sorted(ids)}")

    payloads = [value for value in (trial, agent_result) if value is not None]
    # Older MiniAgent artifacts persisted only agent-result.json. Read validity from whichever
    # normalized trial payload is present so a legacy provider failure cannot enter the ability
    # denominator merely because trial.json did not exist yet.
    checks = (trial or agent_result or {}).get("completion_checks", {})
    valid = not (
        checks.get("provider_error")
        or failure.get("primary") == "ENVIRONMENT"
        or config.get("harness_error")
    )
    cost, source = _cost_from_payloads(payloads, config)
    tokens, duration = _usage_from_payloads(payloads)
    return TrialRecord(
        key=f"{case_id}/{trial_dir.name}", case_id=case_id, repeat=trial_dir.name,
        task_success=bool(grade.get("task_success")),
        strict_success=bool(grade.get("strict_success")), valid=valid,
        cost_usd=cost, cost_source=source, tokens=tokens, duration_ms=duration,
    )


def _default_label(summary: dict[str, Any], experiment_id: str) -> str:
    config = summary.get("run_config", {})
    agent = summary.get("agent") or summary.get("adapter") or experiment_id
    bits = [str(agent)]
    if config.get("model"):
        bits.append(str(config["model"]))
    if config.get("max_wall_clock_override"):
        bits.append(f"{config['max_wall_clock_override']}s")
    if config.get("max_steps_override"):
        bits.append(f"{config['max_steps_override']} steps")
    if config.get("ablate"):
        bits.append("−" + ",".join(config["ablate"]))
    return " · ".join(bits)


def load_experiment(experiment: str | Path, suite_dir: str | Path,
                    label: str | None = None) -> ExperimentData:
    path = Path(experiment).resolve()
    summary = _read_json(path / "summary.json")
    suite = load_suite(suite_dir)
    if summary.get("suite") != suite.name:
        raise ReportError(
            f"experiment {path.name!r} reports suite {summary.get('suite')!r}, expected {suite.name!r}"
        )
    known_cases = {case.case_id for case in suite.cases}
    grade_files = sorted(path.glob("*/rep*/grader-results.json"))
    if not grade_files:
        raise ReportError(f"experiment {path.name!r} has no trial grader artifacts")
    records = tuple(_trial_record(file.parent, known_cases) for file in grade_files)
    experiment_id = str(summary.get("experiment_id") or path.name)
    return ExperimentData(
        path=path, experiment_id=experiment_id,
        label=label or _default_label(summary, experiment_id), summary=summary, records=records,
    )


def _clusters(records: list[TrialRecord], metric: str) -> list[Cluster]:
    grouped: dict[str, list[bool]] = {}
    for record in records:
        grouped.setdefault(record.case_id, []).append(bool(getattr(record, metric)))
    return [Cluster(key=case_id, outcomes=tuple(values)) for case_id, values in sorted(grouped.items())]


def _outcomes(records: list[TrialRecord], metric: str) -> dict[str, bool]:
    return {record.key: bool(getattr(record, metric)) for record in records}


def _cost_observations(records: list[TrialRecord]) -> list[CostObservation]:
    return [
        CostObservation(
            key=record.key, case_id=record.case_id,
            task_success=record.task_success, cost_usd=record.cost_usd,
        )
        for record in records
    ]


def _metric_summary(records: list[TrialRecord], metric: str, resamples: int) -> dict[str, Any]:
    ci = cluster_bootstrap_ci(_clusters(records, metric), n_resamples=resamples)
    return asdict(ci)


def _case_rates(records: list[TrialRecord]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[TrialRecord]] = {}
    for record in records:
        grouped.setdefault(record.case_id, []).append(record)
    return {
        case_id: {
            "trials": len(values),
            "task_success": statistics.mean(item.task_success for item in values),
            "strict_success": statistics.mean(item.strict_success for item in values),
        }
        for case_id, values in grouped.items()
    }


def _strata(records: list[TrialRecord], cases: dict[str, EvalCase]) -> dict[str, list[dict[str, Any]]]:
    task = {case_id: [item.task_success for item in records if item.case_id == case_id]
            for case_id in {item.case_id for item in records}}
    strict = {case_id: [item.strict_success for item in records if item.case_id == case_id]
              for case_id in task}
    result: dict[str, list[dict[str, Any]]] = {}
    for dimension in ("task_type", "difficulty", "horizon"):
        mapping = {case_id: str(getattr(cases[case_id], dimension)) for case_id in task}
        task_rows = {row.stratum: row for row in stratified_macro_average(task, mapping)}
        strict_rows = {row.stratum: row for row in stratified_macro_average(strict, mapping)}
        result[dimension] = [
            {
                "stratum": name,
                "case_count": row.case_count,
                "trial_count": row.trial_count,
                "task_success": row.macro_average,
                "strict_success": strict_rows[name].macro_average,
            }
            for name, row in task_rows.items()
        ]
    return result


def _paired_metric(a: ExperimentData, b: ExperimentData, metric: str) -> dict[str, Any]:
    try:
        result = paired_comparison(
            _outcomes(a.valid_records, metric), _outcomes(b.valid_records, metric),
            label_a=a.label, label_b=b.label,
        )
    except UnpairedSamples as exc:
        return {"available": False, "reason": str(exc)}
    return {"available": True, **asdict(result), "discordant": result.discordant,
            "difference": result.difference}


def _paired_cost(a: ExperimentData, b: ExperimentData, resamples: int) -> dict[str, Any]:
    costs_a = {item.key: item for item in _cost_observations(a.valid_records)}
    costs_b = {item.key: item for item in _cost_observations(b.valid_records)}
    try:
        result = paired_cost_comparison(
            costs_a, costs_b, label_a=a.label, label_b=b.label, n_resamples=resamples
        )
    except UnpairedSamples as exc:
        return {"available": False, "reason": str(exc)}
    return asdict(result)


def build_report_data(
    experiments: list[str | Path], suite_dir: str | Path, *, labels: list[str] | None = None,
    resamples: int = 10_000,
) -> dict[str, Any]:
    """Load experiments and produce the JSON fact source used by both renderers."""
    if not experiments:
        raise ReportError("at least one experiment is required")
    if labels is not None and len(labels) != len(experiments):
        raise ReportError("--labels must contain exactly one label per experiment")
    if resamples < 1:
        raise ReportError("resamples must be positive")
    suite = load_suite(suite_dir)
    cases = {case.case_id: case for case in suite.cases}
    loaded = [
        load_experiment(path, suite_dir, labels[index] if labels else None)
        for index, path in enumerate(experiments)
    ]
    if len({item.label for item in loaded}) != len(loaded):
        raise ReportError("experiment labels must be unique")

    arms = []
    observed_cases: set[str] = set()
    for experiment in loaded:
        valid = experiment.valid_records
        if not valid:
            raise ReportError(f"experiment {experiment.experiment_id!r} has no valid trials")
        observed_cases.update(record.case_id for record in experiment.records)
        config = experiment.summary.get("run_config", {})
        cost_summary = summarize_costs(_cost_observations(valid))
        arms.append({
            "experiment_id": experiment.experiment_id,
            "label": experiment.label,
            "provenance": {
                "agent": experiment.summary.get("agent"),
                "adapter": experiment.summary.get("adapter"),
                "harness": experiment.summary.get("harness"),
                "model": config.get("model"),
                "provider": config.get("provider"),
                "adapter_version": config.get("adapter_version"),
                "max_wall_clock": config.get("max_wall_clock_override"),
                "max_steps": config.get("max_steps_override"),
                "ablate": config.get("ablate") or [],
            },
            "trials": {
                "total": len(experiment.records), "valid": len(valid),
                "infra_invalid": len(experiment.records) - len(valid),
            },
            "task_success": _metric_summary(valid, "task_success", resamples),
            "strict_success": _metric_summary(valid, "strict_success", resamples),
            "cost": asdict(cost_summary),
            "case_rates": _case_rates(valid),
            "strata": _strata(valid, cases),
        })

    comparisons_data = []
    for a, b in combinations(loaded, 2):
        comparisons_data.append({
            "a": a.label, "b": b.label,
            "task_success": _paired_metric(a, b, "task_success"),
            "strict_success": _paired_metric(a, b, "strict_success"),
            "cost": _paired_cost(a, b, resamples),
        })

    suite_order = [case.case_id for case in suite.cases if case.case_id in observed_cases]
    return {
        "schema": REPORT_SCHEMA,
        "created_at": utc_now_iso(),
        "suite": {"name": suite.name, "case_count": len(suite_order), "cases": suite_order},
        "arms": arms,
        "comparisons": comparisons_data,
        "limitations": [
            "Confidence intervals resample cases, not repeats; more repeats do not add task diversity.",
            "Infrastructure-invalid trials are excluded from capability and cost denominators.",
            "Missing or ambiguous historical cost is unavailable, never zero; cost per success requires full coverage.",
            "This report describes only the selected artifacts and is not a public leaderboard result.",
        ],
    }


def _fmt_rate(value: float | None) -> str:
    return "—" if value is None else f"{value:.3f}"


def _fmt_usd(value: float | None) -> str:
    return "unavailable" if value is None else f"${value:.6f}"


def _fmt_cost_delta(cost: dict[str, Any]) -> str:
    if not cost["available"]:
        return f"unavailable: {cost['reason']}"
    return (
        f"{_fmt_usd(cost['case_macro_delta_usd'])} "
        f"[{_fmt_usd(cost['case_macro_delta_low_usd'])}, "
        f"{_fmt_usd(cost['case_macro_delta_high_usd'])}]"
    )


def _md_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _md_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines.extend("| " + " | ".join(_md_cell(value) for value in row) + " |" for row in rows)
    return "\n".join(lines)


def _evidence_warnings(report: dict[str, Any]) -> list[str]:
    warnings = []
    for arm in report["arms"]:
        for metric_name in ("task_success", "strict_success"):
            warning = arm[metric_name].get("warning")
            if warning:
                warnings.append(f"{arm['label']} · {metric_name}: {warning}")
    for comparison in report["comparisons"]:
        warning = comparison["cost"].get("warning")
        if warning:
            warnings.append(f"{comparison['a']} − {comparison['b']} · cost: {warning}")
    return warnings


def render_markdown(report: dict[str, Any], title: str) -> str:
    lines = [f"# {title}", "", f"Suite: `{report['suite']['name']}` · "
             f"{report['suite']['case_count']} observed cases · generated {report['created_at']}", ""]
    headline = []
    for arm in report["arms"]:
        task, strict, cost = arm["task_success"], arm["strict_success"], arm["cost"]
        headline.append([
            arm["label"], f"{task['point']:.3f} [{task['low']:.3f}, {task['high']:.3f}]",
            f"{strict['point']:.3f} [{strict['low']:.3f}, {strict['high']:.3f}]",
            f"{arm['trials']['valid']}/{arm['trials']['total']}", arm["trials"]["infra_invalid"],
            f"{cost['n_priced']}/{cost['n_trials']}", _fmt_usd(cost["total_cost_usd"]),
            _fmt_usd(cost["cost_per_success_usd"]),
        ])
    lines += ["## Headline", "", _md_table(
        ["Arm", "Task 95% CI", "Strict 95% CI", "Valid", "Infra", "Priced", "Total cost", "Cost/success"],
        headline,
    ), ""]

    warnings = _evidence_warnings(report)
    if warnings:
        lines += ["## Evidence warnings", ""]
        lines.extend(f"- {warning}" for warning in warnings)
        lines.append("")

    provenance = []
    for arm in report["arms"]:
        item = arm["provenance"]
        provenance.append([
            arm["label"], item.get("adapter") or item.get("agent") or "—", item.get("model") or "—",
            item.get("max_wall_clock") or "case default", item.get("max_steps") or "case default",
            ",".join(item.get("ablate") or []) or "—",
        ])
    lines += ["## Provenance", "", _md_table(
        ["Arm", "System", "Model", "Wall clock", "Max steps", "Ablation"], provenance,
    ), ""]

    case_rows = []
    for case_id in report["suite"]["cases"]:
        row: list[Any] = [case_id]
        for arm in report["arms"]:
            rate = arm["case_rates"].get(case_id)
            row.append("—" if rate is None else f"{rate['task_success']:.3f}/{rate['strict_success']:.3f}")
        case_rows.append(row)
    lines += ["## Case matrix", "", "Cells are Task/Strict.", "",
              _md_table(["Case", *[arm["label"] for arm in report["arms"]]], case_rows), ""]

    lines += ["## Stratified macro averages", ""]
    for dimension in ("task_type", "difficulty", "horizon"):
        rows = []
        for arm in report["arms"]:
            for item in arm["strata"][dimension]:
                rows.append([
                    arm["label"], item["stratum"], item["case_count"], item["trial_count"],
                    _fmt_rate(item["task_success"]), _fmt_rate(item["strict_success"]),
                ])
        lines += [f"### {dimension}", "", _md_table(
            ["Arm", "Stratum", "Cases", "Trials", "Task", "Strict"], rows,
        ), ""]

    lines += ["## Paired comparisons", ""]
    if not report["comparisons"]:
        lines += ["Only one arm was selected; no paired comparison is available.", ""]
    else:
        rows = []
        for item in report["comparisons"]:
            task, strict, cost = item["task_success"], item["strict_success"], item["cost"]
            rows.append([
                f"{item['a']} − {item['b']}",
                (f"{task['difference']:+.3f}; p={task['p_value']:.4f}" if task["available"]
                 else f"unavailable: {task['reason']}"),
                (f"{strict['difference']:+.3f}; p={strict['p_value']:.4f}" if strict["available"]
                 else f"unavailable: {strict['reason']}"),
                _fmt_cost_delta(cost),
            ])
        lines += [_md_table(["Pair", "Task delta", "Strict delta", "Case-macro cost delta"], rows), ""]

    lines += ["## Evidence boundaries", ""]
    lines.extend(f"- {item}" for item in report["limitations"])
    return "\n".join(lines) + "\n"


def _html_table(headers: list[str], rows: list[list[Any]]) -> str:
    head = "".join(f"<th>{html.escape(str(item))}</th>" for item in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(item))}</td>" for item in row) + "</tr>"
        for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def render_html(report: dict[str, Any], title: str) -> str:
    headline = []
    for arm in report["arms"]:
        task, strict, cost = arm["task_success"], arm["strict_success"], arm["cost"]
        headline.append([
            arm["label"], f"{task['point']:.3f} [{task['low']:.3f}, {task['high']:.3f}]",
            f"{strict['point']:.3f} [{strict['low']:.3f}, {strict['high']:.3f}]",
            f"{arm['trials']['valid']}/{arm['trials']['total']}", arm["trials"]["infra_invalid"],
            f"{cost['n_priced']}/{cost['n_trials']}", _fmt_usd(cost["total_cost_usd"]),
            _fmt_usd(cost["cost_per_success_usd"]),
        ])
    sections = ["<h2>Headline</h2>", _html_table(
        ["Arm", "Task 95% CI", "Strict 95% CI", "Valid", "Infra", "Priced", "Total cost", "Cost/success"],
        headline,
    )]

    warnings = _evidence_warnings(report)
    if warnings:
        items = "".join(f"<li>{html.escape(warning)}</li>" for warning in warnings)
        sections += ["<h2>Evidence warnings</h2>", f"<ul>{items}</ul>"]

    provenance = []
    for arm in report["arms"]:
        item = arm["provenance"]
        provenance.append([
            arm["label"], item.get("adapter") or item.get("agent") or "—", item.get("model") or "—",
            item.get("max_wall_clock") or "case default", item.get("max_steps") or "case default",
            ",".join(item.get("ablate") or []) or "—",
        ])
    sections += ["<h2>Provenance</h2>", _html_table(
        ["Arm", "System", "Model", "Wall clock", "Max steps", "Ablation"], provenance,
    )]

    case_rows = []
    for case_id in report["suite"]["cases"]:
        row: list[Any] = [case_id]
        for arm in report["arms"]:
            rate = arm["case_rates"].get(case_id)
            row.append("—" if rate is None else f"{rate['task_success']:.3f}/{rate['strict_success']:.3f}")
        case_rows.append(row)
    sections += ["<h2>Case matrix</h2><p>Cells are Task/Strict.</p>",
                 _html_table(["Case", *[arm["label"] for arm in report["arms"]]], case_rows)]

    sections.append("<h2>Stratified macro averages</h2>")
    for dimension in ("task_type", "difficulty", "horizon"):
        rows = []
        for arm in report["arms"]:
            for item in arm["strata"][dimension]:
                rows.append([
                    arm["label"], item["stratum"], item["case_count"], item["trial_count"],
                    _fmt_rate(item["task_success"]), _fmt_rate(item["strict_success"]),
                ])
        sections += [f"<h3>{html.escape(dimension)}</h3>", _html_table(
            ["Arm", "Stratum", "Cases", "Trials", "Task", "Strict"], rows,
        )]

    pair_rows = []
    for item in report["comparisons"]:
        task, strict, cost = item["task_success"], item["strict_success"], item["cost"]
        pair_rows.append([
            f"{item['a']} − {item['b']}",
            (f"{task['difference']:+.3f}; p={task['p_value']:.4f}" if task["available"]
             else f"unavailable: {task['reason']}"),
            (f"{strict['difference']:+.3f}; p={strict['p_value']:.4f}" if strict["available"]
             else f"unavailable: {strict['reason']}"),
            _fmt_cost_delta(cost),
        ])
    sections += ["<h2>Paired comparisons</h2>", (
        _html_table(["Pair", "Task delta", "Strict delta", "Case-macro cost delta"], pair_rows)
        if pair_rows else "<p>Only one arm was selected.</p>"
    )]
    limitations = "".join(f"<li>{html.escape(item)}</li>" for item in report["limitations"])
    sections += ["<h2>Evidence boundaries</h2>", f"<ul>{limitations}</ul>"]

    css = """
body{font:15px/1.5 system-ui,sans-serif;max-width:1180px;margin:2rem auto;padding:0 1rem;color:#172033}
h1,h2,h3{line-height:1.2}table{border-collapse:collapse;width:100%;margin:1rem 0 2rem;font-size:14px}
th,td{border:1px solid #d7dce5;padding:.5rem .65rem;text-align:left;vertical-align:top}
th{background:#f2f5f9}tbody tr:nth-child(even){background:#fafbfd}.meta{color:#5d6678}
.note{padding:.8rem 1rem;background:#fff7df;border-left:4px solid #e6a700}
""".strip()
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\"><meta name=\"viewport\" "
        f"content=\"width=device-width,initial-scale=1\"><title>{html.escape(title)}</title>"
        f"<style>{css}</style></head><body><h1>{html.escape(title)}</h1>"
        f"<p class=\"meta\">Suite: {html.escape(report['suite']['name'])} · "
        f"{report['suite']['case_count']} observed cases · {html.escape(report['created_at'])}</p>"
        "<p class=\"note\">Missing cost is reported as unavailable, never zero. "
        "Infrastructure-invalid trials are excluded.</p>"
        + "".join(sections) + "</body></html>\n"
    )


def write_static_report(report: dict[str, Any], out_dir: str | Path,
                        *, title: str = "Algora Cross-Agent Evaluation Report") -> Path:
    """Write report.json/md/html atomically without overwriting an existing report."""
    out_dir = Path(out_dir)
    if out_dir.exists():
        raise ReportError(f"report output already exists; refusing to overwrite: {out_dir}")
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".report-", dir=out_dir.parent))
    try:
        (staging / "report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        )
        (staging / "report.md").write_text(render_markdown(report, title))
        (staging / "report.html").write_text(render_html(report, title))
        staging.replace(out_dir)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return out_dir
