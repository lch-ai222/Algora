# CodeAgent Eval Lab (Algora)

A repo-level **coding agent** wired to a **deterministic evaluation pipeline**. The point is
the closed loop, not breadth: a task is *executed* in an isolated sandbox → the *trajectory*
(tool calls, commands, tests, patch) is captured → results are *graded* by deterministic
programs first (tests / constraints / patch) and an LLM-Judge only where no program oracle
exists → failures are *attributed* to a taxonomy → an improved harness (V1→V2) is *regression
tested* under identical conditions.

## Why it's built this way

- **Deterministic-first scoring**: program verification > static rules > LLM-Judge > human. Only
  things a program cannot decide (code-review quality, spec coverage) go to a Judge — and the
  Judge itself is meta-evaluated against a human gold set (Cohen's kappa; below-threshold
  dimensions are downgraded from hard gate to advisory).
- **Private, uncontaminated benchmark**: `datasets/mini_store` is a self-built SWE-style repo and
  private Golden Dataset, not an industry-standard public benchmark. Its value is controlled
  defects, hidden tests, and fast regression without answers in git history.
- **Task Success vs Strict Success**: reveals "functionally done but engineering non-compliant".

## Status

**All 7 original milestones (M0–M5 + C), B1, and V3 foundation W1-1/W1-2 complete.** Verification (current): `94 passed, 1 skipped` (the
skip is an `RUN_LLM_SMOKE`-gated real-model test) · `ruff` clean · `selfcheck` 9/9 · HumanEval
canonical 10/10. Per-milestone test/case counts below are cumulative snapshots — the numbers in
this line and in [PROJECT_STATE.md](PROJECT_STATE.md) are authoritative.

- **V3 W1-1 — long-horizon private suite** ✅ — an independent `mini_store_long` snapshot with
  four hard refactor/spec/cascade/build cases, persistent canaries, hidden tests, and 53 clean-repo
  tests. Both deterministic anchors hold (reference 1.0, none 0.0); `selfcheck` is 4/4. The formal
  DeepSeek V2 calibration (`v2-20260803T191808Z`, one trial per case) reached Task/Strict 1.00,
  median 30 tool actions, 13.5 model rounds, and 3 test runs. This is horizon calibration, not a
  statistically stable capability score.
- **V3 W1-2 — AgentAdapter foundation** ✅ — a typed `AgentAdapter` protocol, normalized
  `AgentRunResult`, enforceable `BudgetContract`, capability probing, `MiniAgentAdapter`, registry,
  and runner support for `--adapter mini_agent --harness v2`. Provider failures are excluded from
  capability denominators, per-turn output limits are explicit, and unavailable pricing is stored
  as `null` with `cost_source=unavailable` rather than a false zero.

- **M0 — scaffold + reused LLM provider** ✅ (`src/codeagent_eval/{settings,models,llm,observability}.py`,
  offline-tested tool-call parsing in `tests/test_llm_provider.py`).
- **M1 — MiniAgent V1 + process-isolation sandbox** ✅ — worktree sandbox with a deny-by-default
  command policy (`sandbox/`), 6 coding tools (`tools/`), and the agentic loop with full
  trajectory capture (`agent/`). Unit-tested offline (sandbox/tools/loop); a real-LLM smoke test
  is gated on `RUN_LLM_SMOKE=1` + an API key.
- **M2 — internal benchmark + deterministic graders + CLI closed loop** ✅ — `mini_store`
  (a cross-module inventory app) with **9 self-checked cases** (6 base built here + 3 adversarial
  regression-traps added in M4) (`datasets/`), per-case materialization with no fix in git history,
  hidden tests injected only at grade time, Test/Constraint/Patch graders with Task vs Strict
  success (`graders/`), and a runner CLI (`runner.py`) with `reference`/`none`/`v1`/`v2` agents,
  artifact persistence (incl. model/provider/temperature/budget provenance), and
  mean+variance / pass@k vs pass^k aggregation. Discrimination verified (reference 1.0, none 0.0).
- **M4 — V1→V2 harness regression (money shot)** ✅ — adds 3 adversarial regression-trap cases
  (bringing `mini_store` to 9), then compares a minimal V1 harness vs a disciplined V2
  (reproduce-first, run the *whole* suite + `git_diff` before finishing, repeated-action guard,
  AGENTS.md injection), same model/benchmark/budget/temperature. Failures are auto-attributed to
  a taxonomy (`failure_taxonomy.py`), and `compare.py` produces the Version Compare
  (improved/regressed/stable + cost deltas). Result on `mini_store` (deepseek, 5 repeats):

  | agent | Task | Strict | note |
  |---|---|---|---|
  | reference | 1.00 | 1.00 | upper bound |
  | **V2** | **1.00** | **1.00** | +~50% tool calls |
  | V1 | 0.98 | 0.98 | `regtrap-loyalty-bonus` 0.80, pass^k=0 |
  | none | 0.00 | 0.00 | lower bound |

  Version Compare: **improved=1, regressed=0, stable=8**. V2's "verify the full suite before
  finishing" flips the one case V1 ships an over-broad fix on (`regtrap-loyalty-bonus`
  0.80→1.00, pass^k 0→1: unreliable→reliable), auto-tagged `PREMATURE_TERMINATION`. On a
  strong model the other 8 cases saturate both harnesses — an honest discrimination finding:
  scaffold decides exactly the case where the naive agent doesn't verify, at a measurable cost.
- **M3 — FastAPI + React console** ✅ — a read-only console over the persisted artifacts
  (`backend/app/`, `frontend/`): Experiments list, Experiment Detail (stat tiles + case table
  with pass@k/pass^k + failure tags), Trial Trace Viewer (step list + event detail + grader
  summary + colorized diff), and Version Compare (improved/regressed/stable + cost deltas).
  Vite + React + TS, typechecks and builds clean.
- **M5 — EvalPlus-schema study / LLM-Judge / kappa** ✅ — a 10-problem curated/self-built
  EvalPlus-schema subset used to validate the function-level evaluation flow (not a full official
  HumanEval+ run or leaderboard result; DeepSeek scores Pass@1 100% on this easy slice), an
  LLM-as-Judge for code review (`judge/code_review_judge.py`,
  structured + **forced citations** + swap-averaging + temperature=0), and judge meta-eval
  (`judge/meta_eval.py`, agreement + Cohen's kappa + trust map). On the human gold set the judge
  agrees perfectly on objective dimensions (CORRECTNESS/EDGE_CASES κ=1.0) but only κ=0.62 on
  subjective READABILITY — near the Landis-Koch boundary, matching the plan's reference. See
  [docs/judge_meta_eval_report_v1.md](docs/judge_meta_eval_report_v1.md).
- **B1 — official HumanEval+/EvalPlus smoke slice** ✅ — pinned EvalPlus 0.3.1, five official
  tasks selected before generation with seed `20260712`, canonical oracle gate (Base/Plus 1.00),
  official sanitizer/evaluator, immutable manifest, and split network-generation/local-execution
  phases. DeepSeek v4-flash: Base pass@1 1.00, Plus pass@1 0.80 (one stricter-test failure); this
  is a protocol-learning slice, not a full benchmark score. See
  [docs/evalplus_smoke_report_v1.md](docs/evalplus_smoke_report_v1.md).
- **C — SWE-bench compatibility adapter + Docker design** ✅ — `benchmark/swebench.py` reads the official
  SWE-bench instance schema (`FAIL_TO_PASS` / `PASS_TO_PASS` / `test_patch` / gold `patch`) and
  runs the official resolve flow. A **compatibility sample** (`datasets/swebench_compat/`, a
  small self-contained repo) runs end-to-end here: gold patch resolves it, and the MiniAgent
  (V2) resolves it for real. Clearly labelled "Compatibility Sample", not a leaderboard number.
  Docker sandbox is a validated design (`docker/sandbox.Dockerfile` + design doc) — not built
  here (no daemon). See [docs/swebench_and_docker.md](docs/swebench_and_docker.md).

The public-benchmark goal is protocol learning rather than an expensive full leaderboard run:
use a small number of official instances while preserving the official data, environment, oracle,
execution, and reporting contracts. See
[docs/benchmark_methodology_and_roadmap.md](docs/benchmark_methodology_and_roadmap.md) for the
HumanEval+/EvalPlus → SWE-bench → Terminal-Bench → OctoBench roadmap, implementation-level labels,
statistical plan, and private Golden Dataset expansion priorities.

### Console

```bash
.venv/bin/uvicorn backend.app.main:app --port 8000    # API over artifacts/runs/
cd frontend && npm install && npm run dev             # http://localhost:5173 (proxies /api)
```

### Run it

```bash
python scripts/selfcheck.py                              # hard gate: all 9 cases valid
python -m codeagent_eval.runner --agent reference        # upper bound (no LLM)
python -m codeagent_eval.runner --agent none             # lower bound (no LLM)
python -m codeagent_eval.runner --agent v1 --repeats 5   # minimal baseline (needs API key in .env)
python -m codeagent_eval.runner --agent v2 --repeats 5   # disciplined harness
python scripts/selfcheck.py datasets/mini_store_long     # hard gate: all 4 long cases valid
python -m codeagent_eval.runner --adapter mini_agent --harness v2 \
  --suite datasets/mini_store_long --max-completion-tokens 4096
python scripts/compare_runs.py <v1_run_dir> <v2_run_dir> # Version Compare (improved/regressed/stable)
```

See [coding_agent_eval_plan_v2.md](coding_agent_eval_plan_v2.md) for the full design.

### Official EvalPlus smoke slice

EvalPlus is intentionally isolated from the main `.venv` because its optional dependency set is
large. Its cache also stays inside the project and is ignored by git.

```bash
python3.11 -m venv .venv-evalplus
.venv-evalplus/bin/python -m pip install -e ".[evalplus]"
.venv-evalplus/bin/python scripts/run_evalplus_smoke.py --selfcheck
.venv-evalplus/bin/python scripts/run_evalplus_smoke.py --generate-only
.venv-evalplus/bin/python scripts/run_evalplus_smoke.py \
  --resume artifacts/runs/<evalplus-smoke-run> --allow-local-model-execution
```

Review generated samples before the resume step. The official local evaluator executes generated
Python without Docker; the split flow ensures the execution phase has no model-API network access.
Cleanup: `rm -rf .venv-evalplus .cache/evalplus artifacts/runs/evalplus-smoke-<timestamp>`.

## Dev setup

```bash
python3.11 -m venv .venv
.venv/bin/pip install -e ".[dev,api]"
cp .env.example .env   # fill in DEEPSEEK_API_KEY (or set LLM_PROVIDER=openai + OPENAI_API_KEY)
.venv/bin/python -m pytest -q
```

The LLM provider is OpenAI-compatible; `LLM_PROVIDER` selects `deepseek` or `openai`. Tests run
offline (no API key) via a fake client.
