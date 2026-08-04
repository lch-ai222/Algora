# Algora — CodeAgent Eval Lab

An evaluation platform for coding agents, plus a coding agent to evaluate against.

It runs **Claude Code and a self-built MiniAgent on the same model, under the same budget
contract, over the same private benchmark**, normalizes their heterogeneous trajectories into
one schema, grades deterministically, and attributes failures to a taxonomy. Because the model
is held constant, a difference between them is attributable to the scaffold rather than to the
LLM behind it.

The benchmark is private and self-built, so nothing here is a public leaderboard number. What
it is instead: a harness careful enough that its own defects get caught before they become
findings — see [Measurement defects found and fixed](#measurement-defects-found-and-fixed).

---

## Headline results

All figures below are directional evidence from small samples; every claim is stated with its
sample size and its limits in the linked reports.

### Same model, different scaffold

`glm-5.2` on all three arms, wall clock as the primary budget (the only one every framework
enforces identically). These headline numbers were measured on the original 4-case
long-horizon suite; the suite now contains 8 cases and the matrix has not yet been rerun.
Full report: **[docs/cross_agent_report_v1.md](docs/cross_agent_report_v1.md)**

| arm | budget | n | Task | Strict | tool calls | model turns |
|---|---|---|---|---|---|---|
| Claude Code 2.1.220 | loose | 8 | **1.00** | **1.00** | 27.8 | 46.4 |
| Claude Code 2.1.220 | 120s | 12 | **0.50** | 0.50 | 14.6 | 24.1 |
| MiniAgent v3.1 | 120s | 12 | **1.00** | 0.83 | 34.3 | 18.8 |
| MiniAgent v2 | 120s | 12 | 0.92 | 0.83 | 34.3 | 19.3 |

Paired at the trial level: Task differs by −0.50 with all six disagreements pointing the same
way (exact McNemar **p = 0.031**), while the 4-case cluster bootstrap puts Claude Code's rate
anywhere in ［0.33, 0.83］. Both are true and they answer different questions — the sample
pins down the *direction* but not the *value*.

Given enough time every scaffold scores 1.00 — the suite has no resolving power. Tighten the
clock to 120s and Claude Code halves while the MiniAgent holds. The trajectories say why: in
120s Claude Code issues **14.6 tool calls against the MiniAgent's 34.3**, spending its budget
reasoning rather than acting. It is also the only arm scoring 1.00 on *both* Task and Strict.
The honest reading is that its scaffold **trades latency for engineering compliance** — a net
gain when time is ample, a net loss when it is not.

### Discrimination comes from the budget, not from harder cases

The same suite, varying only `--max-steps`. No new cases were written.

| `max_steps` | DeepSeek v4-flash | GLM-4.5-air | gap |
|---|---|---|---|
| 20 (case default) | 1.00 | 1.00 | **0.00** |
| 8 | 1.00 | 0.78 | 0.22 |
| 4 | 0.93 | **0.07** | **0.85** |

Saturation was not the cases being too easy; the budget was too loose for capability
differences to surface. Two findings that changed how later experiments were designed:
**models adapt to the budget rather than consume it** (DeepSeek uses 7 steps when given 20, yet
still scores 1.00 when given 6, so headroom cannot predict the effect), and **the curve is a
cliff, not a gradient**.

Swapping models buys a 0.16 gap. Tightening the budget buys 0.85.

### Ablating the self-built agent

V3 = V2 + a task planner + context management. Long suite, 12k hard context ceiling applied to
*every* arm, 4 cases × 3 repeats.

| arm | Task | Strict | context overflows | compactions |
|---|---|---|---|---|
| v2 (neither) | 0.42 | 0.42 | 9 | 0 |
| **v3.1 (both)** | **1.00** | 0.92 | 0 | 55 |
| v3.1 − context | 0.33 | 0.33 | 10 | 0 |
| v3.1 − planner | **1.00** | 0.92 | 0 | 44 |

Removing context management costs 0.667 with eight of twelve trials flipping, all in the same
direction (exact McNemar **p = 0.008**). Removing the planner flips nothing at all
(0 discordant, p = 1.0) — which bounds its effect rather than proving it has none.

Context management is the entire effect. The planner is neutral and costs ~18% more tool
calls. An earlier version of this ablation reported the planner as actively *harmful*; that
turned out to be two defects in this codebase, not a property of planning — see below.

### Failure modes the pass/fail oracle cannot see

Three detectors run over the artifacts. Their rates must be split by whether the harness was
actually letting the agent misbehave, and historical scans must not be silently merged with
new case-specific probes.

**Reward hacking** — a patch that disarms verification instead of satisfying it.

An agent can turn a suite green by fixing the code or by disarming the tests.
[`detectors/reward_hacking.py`](src/codeagent_eval/detectors/reward_hacking.py) scans diffs for
eight graded signals, each carrying the diff line that triggered it. Validation is separate
from the rate: eight hand-written hacks must all fire, every reference solution must stay
clean — otherwise "we found nothing" and "the detector is broken" are the same observation.

Scanning **640 patches already on disk** (no new experiments) found zero strong signals. The
zero is reported split, and the script derives the split itself rather than leaving it to the
reader:

| sample | n | findings | 95% upper bound |
|---|---|---|---|
| MiniAgent (sandbox forbids test edits) | 624 | 0 | *enforcement, not observation* |
| Claude Code (unconstrained) | 16 | 0 | **19.4%** |

Only the unconstrained sample measures behaviour.

**Context amnesia** — whether a rule stated *once*, in the opening message, still holds twenty
steps later. Each long case carries a canary: a persistent, objectively checkable constraint,
verified passively against every edit the agent makes. Passive matters — asking the agent
midway whether it remembers the rule would re-state the rule, turning the measurement into an
intervention. The headline is not overall adherence but the **first-half minus second-half**
difference: a rule never understood fails uniformly, a rule lost to context fails late, and
only the split tells them apart. The historical scan of 808 edits in 117 canary-carrying trials
found adherence 1.000 and decay +0.000. The later `long-release-accounting` case produced the
first real early-to-late decay (+1.000); this observes a change in behaviour, but cannot by
itself distinguish forgetting from a deliberate strategy change.

**Instruction drift** — a constraint broken partway through. The constraint grader looks only
at the final patch, so it cannot distinguish "obeyed throughout" from "broke the rule and took
it back"; replaying the trajectory recovers the first-breach step, the obedience ratio, and
whether the breach shipped or was self-corrected. The historical 364-trial replay found zero
breaches; the later `long-release-accounting` probe produced 3/3 shipped breaches. For the
MiniAgent, only the changed-file limit is a free observation—its path and command rules are
refused by the sandbox before they can happen.

---

## Measurement defects found and fixed

Thirteen defects were caught during this work. Five were ordinary bugs. **Eight would not have
crashed anything — they would have produced a confident, wrong conclusion.**

| defect | what the report would have said |
|---|---|
| `failure_taxonomy` matched the MiniAgent's native stop strings | every external agent's failure modes silently tagged UNKNOWN |
| `--context-budget-tokens` constrained only V3 | compaction's value untestable; the ablation measures its cost alone |
| `version == "v2"` gated V2's completion guard | V3 silently lost it, so the ablation compared more than the capability under test |
| plan adherence keyed on model-supplied ids, which models rename | reported adherence figures were measurement artifacts |
| `resume` adopted infra-invalid trials | a transient rate limit frozen into results as if it were the measurement |
| `last_model` recorded the requested, not the served, model | artifacts claiming a model that never ran |
| materialized repos had no `.gitignore` | "Claude Code is engineering-non-compliant in 6 of 8 trials" (it was pytest bytecode) |
| `--max-wall-clock` reached one adapter branch only | "Claude Code is unaffected by a tight budget" — **the opposite of the truth** |

The last one is the sharpest illustration: the provenance record said `timeout_seconds=120`
and was correct; only the enforcement path was unwired, so every artifact looked normal.

---

## How it is built

```
report        docs/*.md  ·  backend + frontend console over artifacts/
────────────────────────────────────────────────────────────────────────
analysis      detectors/ (reward hacking · instruction drift · context amnesia · repro bundle)
              stats/ (cluster bootstrap · exact McNemar · Wilson)
              failure_taxonomy.py           compare.py
────────────────────────────────────────────────────────────────────────
orchestration runner.py — process-pool parallelism, trial-level resume,
              budget contract, manifest fingerprint, provenance
────────────────────────────────────────────────────────────────────────
adapters      AgentAdapter ─┬─ MiniAgentAdapter   (in-process)
                            └─ ClaudeCodeAdapter  (headless CLI)
              normalize.py — heterogeneous trajectories → one TraceEvent schema
────────────────────────────────────────────────────────────────────────
agent         loop.py │ prompts (v1/v2/v3) │ planner.py │ context.py
              tools/ │ sandbox/ (worktree + deny-by-default command policy)
────────────────────────────────────────────────────────────────────────
data          benchmark/ (case · materialize · swebench · evalplus)
              graders/ (pytest · constraint · patch)   judge/ (+ kappa meta-eval)
              mini_store_suite (9 short) │ mini_store_long (8 long-horizon)
```

### Principles the code enforces

- **Deterministic-first scoring.** Program verification > static rules > LLM-Judge > human. The
  Judge is itself meta-evaluated against a human gold set; dimensions below the kappa threshold
  are downgraded from gate to advisory.
- **Unknown stays unknown.** An unpriced model reports `cost_usd=null`, never `0.0` — a zero is
  indistinguishable from "this was free". CNY rates are never silently converted to USD.
- **Infra failure is missing evidence, not agent failure.** Provider errors are excluded from
  success denominators and re-run on resume rather than frozen into the result.
- **Budgets are experimental variables.** `--max-steps`, `--max-wall-clock`,
  `--context-ceiling-tokens` all override case defaults and land in the resume fingerprint, so
  two budgets can never be merged into one experiment.
- **An ablation must isolate one capability.** `--ablate planner|context` records itself in
  `adapter_version`; an ablated V3 is a different system and the artifacts say so.
- **Task Success vs Strict Success**, so "functionally done but engineering non-compliant" is
  visible rather than averaged away.

---

## Run it

```bash
python3.11 -m venv .venv
.venv/bin/pip install -e ".[dev,api]"
cp .env.example .env          # fill in a provider key
.venv/bin/python -m pytest -q # 360 passed, 1 skipped — offline, no API key needed
```

```bash
# Benchmark health: every case solvable by reference, none by doing nothing
python scripts/selfcheck.py datasets/mini_store_suite
python scripts/check_bounds.py --suite datasets/mini_store_suite --workers 2

# The self-built agent
python -m codeagent_eval.runner --adapter mini_agent --harness v3 \
  --suite datasets/mini_store_long --max-wall-clock 120 --workers 3

# Claude Code, same model, same budget
ANTHROPIC_BASE_URL=... ANTHROPIC_AUTH_TOKEN=... \
python -m codeagent_eval.runner --adapter claude_code --claude-model glm-5.2 \
  --suite datasets/mini_store_long --max-wall-clock 120 --workers 3

# Scan every trial ever produced for reward hacking, instruction drift, and context amnesia
python scripts/scan_failure_modes.py artifacts/runs

# Compare two arms with an interval and a paired test, not two point estimates
python scripts/compare_experiments.py artifacts/runs/<a> artifacts/runs/<b>

# Turn one deterministic failure into a sanitized diagnostic + replay fixture
python scripts/build_repro_bundle.py build artifacts/runs/<run>/<case>/rep0 \
  --suite datasets/mini_store_long
python scripts/build_repro_bundle.py replay artifacts/repro_bundles/<bundle-id>
```

Each trial persists `config.json` (model, budgets, adapter version, pricing revision),
`trajectory.jsonl` (normalized), `native/` (the external agent's raw stream), `patch.diff`,
`grader-results.json`, `failure-tags.json` — enough to re-grade or diagnose without re-running.
Failure bundles go to `artifacts/repro_bundles/` and are gitignored. They exclude hidden-test
code/details and native adapter logs; replay rematerializes the case, applies the patch, injects
hidden tests at grade time, and checks the deterministic grade signature without a model call.
Clean one generated bundle with `rm -rf artifacts/repro_bundles/<bundle-id>`.

Console: `uvicorn backend.app.main:app --port 8000` + `cd frontend && npm run dev`.

---

## Status and evidence levels

`360 passed, 1 skipped` · `ruff` clean · selfcheck 9/9 short and 8/8 long · deterministic
bounds reference=1.00 / none=0.00 on both suites · CI green including a containerized
`--network none` evaluation gate.

| area | level |
|---|---|
| `mini_store` short + long | complete private benchmark, self-built, uncontaminated |
| Cross-agent comparison | live, model-controlled; 8–12 trials per arm |
| Reward-hacking detection | validated detector; 640 patches scanned, 16 of them unconstrained |
| Instruction-drift detection | trajectory replay; 364 trials scanned, 16 of them unconstrained |
| Context-amnesia detection | passive canary checks; 808 edits over 117 trials |
| HumanEval+/EvalPlus | official smoke slice, 5 pinned tasks — [report](docs/evalplus_smoke_report_v1.md) |
| SWE-bench | schema-compatible adapter + self-built sample; **no official instances yet** |
| Terminal-Bench / OctoBench | protocol study only |

Not done: run/cross-run memory, multi-turn, a second external-agent adapter, static report export,
and SWE-bench official instances. The long suite now has 8 cases,
meeting `MIN_USEFUL_CLUSTERS`; however, the headline cross-agent and ablation tables above still
come from the original 4-case matrix. With case as the clustering unit, only rerunning on the
expanded suite can strengthen those claims—extra repeats on the old four cases cannot.

## Documents

- [docs/cross_agent_report_v1.md](docs/cross_agent_report_v1.md) — the cross-agent comparison
- [docs/iteration_plan_v3.md](docs/iteration_plan_v3.md) — plan, pre-registered hypotheses, execution log
- [docs/benchmark_methodology_and_roadmap.md](docs/benchmark_methodology_and_roadmap.md) — evidence levels, statistical plan
- [PROJECT_STATE.md](PROJECT_STATE.md) — authoritative current state
- [docs/judge_meta_eval_report_v1.md](docs/judge_meta_eval_report_v1.md) · [docs/evalplus_smoke_report_v1.md](docs/evalplus_smoke_report_v1.md) · [docs/swebench_and_docker.md](docs/swebench_and_docker.md)
