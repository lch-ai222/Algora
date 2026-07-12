# TASKS.md

Algora 里程碑与任务追踪。活文档，随进度更新。设计源 [`coding_agent_eval_plan_v2.md`](coding_agent_eval_plan_v2.md)，状态见 [`PROJECT_STATE.md`](PROJECT_STATE.md)。

优先级：**P0** = 最低成功线（守住 M1+M2+M4）；**P1** = 网易差异化 / 可演示；**P2** = 只讲/加分。

## 里程碑总览

| M | 内容 | 优先级 | 状态 |
|---|---|---|---|
| M0 | 脚手架 + provider 复用 | P0(enabling) | ✅ 完成 |
| M1 | MiniAgent V1 + 沙箱 | P0 | ✅ 完成 |
| M2 | 内部 benchmark + 确定性 grader + CLI | P0 | ✅ 完成 |
| M4 | V1→V2 回归对比（money shot） | P0 | ✅ 完成 |
| M3 | FastAPI + React 控制台 | P1 | ✅ 完成 |
| M5 | HumanEval+ + LLM-Judge + kappa | P1 | ✅ 完成 |
| C | SWE-bench 适配器 ×1 + Docker 设计 | P2 | ✅ 完成 |
| DOC | 长期文档（本批） | — | ✅ 完成 |

---

## M0 · 脚手架 + provider 复用 ✅
- [x] `pyproject.toml` / 包骨架 / `.env.example` / 目录。
- [x] 拷改 `llm.py`（去 fault-tree 依赖，保留 tool_completion / json_completion / trace scope）。
- [x] `observability.py` / `settings.py` / `models.py`。
- **验收**：带 tools 的 completion 拿到结构化 tool_calls，trace scope 采集 LlmCallRecord（离线测试通过）。✅

## M1 · MiniAgent + 沙箱 ✅
- [x] `sandbox/policy.py`（CommandPolicy）+ `sandbox/worktree.py`（WorktreeSandbox）。25 单测。
- [x] `tools/`：6 个工具 + Registry，禁止路径 + 唯一匹配守卫。
- [x] `agent/loop.py` + `agent/prompts.py`（V1/V2）。
- **验收**：端到端修好 seed bug 并导出 diff；全部 tool_call 入 trace；超步/超时安全终止；命令失败不崩主进程。✅

## M2 · benchmark + 确定性 grader + CLI ✅
- [x] `datasets/mini_store_src`（跨模块库）+ 可见测试全绿。
- [x] `datasets/mini_store_suite`：6 base case（4 bugfix + 2 spec）。
- [x] `benchmark/`：case 模型 + materialize + inject_hidden + reference_fix。
- [x] `graders/`：pytest_run + Test/Constraint/Patch + Task/Strict。
- [x] `runner.py`：reference/none/v1/v2 + artifacts + 聚合（mean+方差、pass@k/pass^k）。
- [x] `scripts/selfcheck.py` 硬门槛，6→9 case 全 valid。
- **验收**：一条命令跑完套件；hidden 不可见；失败定位到具体测试/约束；分别报 Task 与 Strict。✅

## M4 · V1→V2 回归对比 ✅
- [x] 3 条对抗性 regression-trap case（refund-fee / loyalty-bonus / bundle-tier），暴露 V1 缺“完成前跑全套”纪律。
- [x] V2 harness：reproduce-first + 完成前跑全套 + git_diff + 重复动作守卫 + 注入 AGENTS.md。
- [x] `failure_taxonomy.py`（§9 自动归因）。
- [x] `compare.py` + `scripts/compare_runs.py`（improved/regressed/stable + 成本 delta）。
- [x] 真实 LLM 跑 V1/V2 各 9×5，产出 Version Compare。
- **验收**：一次明确迭代；每项改动对应哪类失败说得清；同环境；展示 improved/regressed/stable 而非单一总分。✅
- **结果**：improved=1（loyalty 0.80→1.00, pass^k 0→1），regressed=0，stable=8；归因 PREMATURE_TERMINATION。

## M3 · FastAPI + React 控制台 ✅
- [x] `backend/app/`：experiments / experiment / trial / compare 只读 API。
- [x] `frontend/`：Experiments 列表 / Experiment Detail / Trace Viewer / Version Compare。
- [x] 浏览器实测四个视图 + Vite 代理 + 生产构建。
- **验收**：前端看每 case 结果、看完整 trace、看最终 patch、筛失败 case、看 Version Compare。✅

## M5 · HumanEval+ + LLM-Judge + kappa ✅
- [x] `benchmark/humaneval_plus.py`：HumanEval+ adapter（10 题子集，EvalPlus schema），Pass@1、Base/Plus、时延/异常/超时；temp 目录 + 超时执行；数据集 canonical 自检 10/10。
- [x] `scripts/run_humaneval.py`（含 `--selfcheck`）。DeepSeek 实测 Pass@1 100%（易题）。
- [x] `judge/code_review_judge.py`：LLM-Judge，结构化 `{score,max_score,passed_items,missed_items,confidence,reason,verdicts}` + **强制引用**（引用须在代码中，否则降 confidence）+ swap 平均 + temperature=0。
- [x] `judge/meta_eval.py`（拷改 ft_diag）：agreement + Cohen's kappa + trust map + 不达标降级；`judge/gold.py` + `data/judge_gold/`（6 case/16 item）。
- [x] `scripts/run_judge_meta_eval.py`；`docs/judge_meta_eval_report_v1.md`。
- **验收**：跑出真公开 benchmark 数字（Pass@1 100%）；judge 每条判定带有效引用；kappa 展示（CORRECTNESS/EDGE_CASES=1.0，READABILITY=0.62 贴阈值）。✅

## C · 只讲 + 部分落地 ✅（P2）
- [x] `benchmark/swebench.py`：读官方 schema（`FAIL_TO_PASS`/`PASS_TO_PASS`/`test_patch`/gold `patch`），跑官方 resolve 流程；`scripts/run_swebench.py`（gold/agent）。
- [x] 兼容样本 `datasets/swebench_compat/`：gold resolved 1/1；**MiniAgent(V2) 真跑 resolved 1/1**；标注 "Compatibility Sample"。
- [x] Docker：`docker/sandbox.Dockerfile` + `docs/swebench_and_docker.md`（设计验证；本机无 daemon 未 build）。
- [x] 真实 SWE-bench Lite 接入路径写清（clone + env 复现；`materialize_instance` 留 NotImplementedError + 指引）。
- 只讲（不建）：Terminal-Bench/Harbor、PostgreSQL、外部 agent adapter、成本看板全量 —— 见 `docs/swebench_and_docker.md` §3。

## DOC · 长期文档 ✅
- [x] 根 `AGENTS.md`
- [x] `PROJECT_STATE.md`
- [x] `TASKS.md`
- [x] `docs/developer_guide.md`

---

## 当前推荐执行顺序

全部 7 个里程碑（M0–M5 + C）已完成。剩余为可选加固与演示准备：

1. 面试演示彩排（8–10 分钟脚本见 `coding_agent_eval_plan_v2.md` §15）。
2. 可选加固：更难 case 提升 V1/V2 区分度；HumanEval 换真 EvalPlus 全量；judge gold 扩到 30+ item 演示降级路径；SSE 实时进度接入控制台；SQLite 结构化存储；真实 SWE-bench Lite 实例 + Docker 落地。
