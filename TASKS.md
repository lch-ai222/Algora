# TASKS.md

Algora 里程碑与任务追踪。活文档，随进度更新。设计源 [`coding_agent_eval_plan_v2.md`](coding_agent_eval_plan_v2.md)，状态见 [`PROJECT_STATE.md`](PROJECT_STATE.md)。

优先级：**P0** = 当前核心闭环/标准协议的最高优先级；**P1** = 重要差异化与能力扩展；**P2** = 依赖更多数据或架构改造的后续研究。原里程碑中的最低成功线仍为 M1+M2+M4。

## 里程碑总览

| M | 内容 | 优先级 | 状态 |
|---|---|---|---|
| M0 | 脚手架 + provider 复用 | P0(enabling) | ✅ 完成 |
| M1 | MiniAgent V1 + 沙箱 | P0 | ✅ 完成 |
| M2 | 内部 benchmark + 确定性 grader + CLI | P0 | ✅ 完成 |
| M4 | V1→V2 回归对比（money shot） | P0 | ✅ 完成 |
| M3 | FastAPI + React 控制台 | P1 | ✅ 完成 |
| M5 | EvalPlus-schema 子集 + LLM-Judge + kappa | P1 | ✅ 完成（子集验证） |
| C | SWE-bench 兼容样例 + Docker 设计 | P2 | ✅ 完成（兼容验证） |
| DOC | 长期文档（本批） | — | ✅ 完成 |
| B1 | HumanEval+/EvalPlus 官方 Smoke Slice | P0 | ✅ 完成 |
| B2 | SWE-bench 官方实例 Smoke Slice | P0 | ⬜ 待开发 |
| B3 | 统计增强与分层报告 | P0/P1 | 🟨 统计核心完成，分层/成本待补 |
| B4 | Terminal-Bench/Harbor Protocol Study → Smoke Slice | P1 | 📝 文档阶段 |
| B5 | OctoBench Protocol Study → Smoke Slice | P1 | 📝 文档阶段 |
| G1 | 私有 Golden Dataset 类型扩充 | P0/P1/P2 | 🟨 长程 8-case 完成，其他类型待补 |
| V3 W1-1 | `mini_store_long` 长程 suite | P0 | ✅ 完成 |
| V3 W1-2 | AgentAdapter + MiniAgentAdapter + runner 接入 | P0 | ✅ 完成 |
| V3 W1-3 | ClaudeCodeAdapter | P0 | ✅ 代码；✅ protocol + repo live |
| V3 W1-4 | planner + V3 harness | P0 | ✅ 完成 |
| V3 W1-5 | CI + 容器内断网评测 | P0 | ✅ 完成 |
| V3 W1-6 | 并行执行 + trial 级续跑 | P0 | ✅ 完成 |
| V3 W1-7 | GLM provider + 模型阶梯 + 成本溯源 | P0 | ✅ 完成 |
| V3 W2-1 | 分级截断 + 确定性 compaction | P0 | ✅ 完成 |
| V3 W2-2 | run 内 ScratchPad | P1 | ⬜ 未开始 |
| V3 W2-3 | 上下文遗忘检测器 | P0 | ✅ 核心完成 |
| V3 W2-4 | 测试投机检测器 | P0 | ✅ 完成 |
| V3 W2-5 | hackbait 专用 suite | P1 | ⬜ 未开始 |
| V3 W2-6 | 指令偏移检测器 | P0 | ✅ 完成 |
| V3 W2-7 | SWE-bench 官方 Smoke Slice | P0 | ⬜ 未开始 |
| V3 W2-8 | 第二外部 Agent adapter | P0 | ⬜ 未开始 |
| V3 W3-1 | 确定性 multi-turn + 3 case | P0 | ⬜ 未开始 |
| V3 W3-2 | 跨 run RepoMemory | P1 | ⬜ 未开始 |
| V3 W3-3 | 统计增强 | P0/P1 | 🟨 bootstrap/McNemar/Wilson 完成 |
| V3 W3-4 | repro bundle + 回归 fixture | P0 | ⬜ 未开始 |
| V3 W3-5 | 静态报告 + 跨 Agent UI | P0 | ⬜ 未开始 |
| V3 W3-6 | 全量实验与假设回填 | P0 | 🟨 4-case 矩阵完成，8-case 待重跑 |
| V3 W3-7 | 开源清理 + 洞察报告 | P1 | 🟨 README/横向报告部分完成 |

---

## V3 Week 1 · 地基

### W1-1 · `mini_store_long` ✅

- [x] 独立 `repo_src` 快照，避免修改历史短程基线；当前干净仓库 83 tests。
- [x] 4 个地基 hard case，后续扩到 8 个：API 迁移、跨模块退货、级联库存、build/CLI、折扣取整、税率真源、释放记账、订单快照。
- [x] `Horizon`、`CanarySpec`、`expected_steps`、`expected_tool_calls`、build/multi-turn task type 等 schema。
- [x] short 9/9、long 8/8 selfcheck；reference=1.0、none=0.0。
- [x] 正式校准 `v2-20260803T191808Z`：Task/Strict 1.00，动作中位数 30，模型轮次 13.5，测试循环 3，infra 0/4。
- **边界**：每 case 仅 1 次，数字只证明轨迹长度和闭环可执行，不代表稳定能力估计。

### W1-2 · Adapter 地基 ✅

- [x] `AgentAdapter` Protocol、`AgentRunResult`、`BudgetContract`、`Capability`、probe 与 registry。
- [x] `MiniAgentAdapter` 归一化 patch/trace/token/cost/stop reason/environment manifest；不支持的硬预算明确报错。
- [x] runner 保留 legacy `--agent`，新增 `--adapter mini_agent --harness v2`、`agent-result.json` 和显式 `--max-completion-tokens`。
- [x] provider/网络错误作为 infra-invalid 排除出能力分母；compare 拒绝基础设施无效 run。
- [x] V2 拒绝截断、空回复、无改动、未测试和末次测试失败的假完成；V1 行为不变。
- [x] 成本费率缺失时记录 `cost_usd=null`、`cost_source=unavailable`，不伪造零成本。
- **阶段验收快照**：W1-2 完成时 94 passed/1 skipped；当前总门禁见 `PROJECT_STATE.md`（349 passed/1 skipped）。

### W1-3 · ClaudeCodeAdapter ✅（代码 + live）

- [x] headless stream-json 边流边落盘，保留 native trajectory 并归一化为 `AgentRunResult`。
- [x] 独立 `CLAUDE_CONFIG_DIR`、环境白名单、进程组超时终止、CLI 脚手架剥离和成本语义降级。
- [x] 39 条离线测试以可执行 CLI stand-in 覆盖真实 subprocess、流式解析和预算终止路径。
- [x] 外部 stop reason 先映射 `canonical_stop_reason`，修复跨框架静默误归因。
- [x] Homebrew stable 安装 Claude Code 2.1.220；真实 `probe()` 通过。
- [x] 无认证流与智谱 GLM-5.2 协议流均返回有效 stream-json；`--max-turns` 虽未显示在 help 中但真实可用。
- [x] 获得明确数据披露授权后完成 `bugfix-pricing-tax` repo smoke：Task/Strict 1.00，6 tools / 8 model turns，hidden 仅评分时可见。
- [x] 修复 live 暴露的两项溯源丢失：CLI 版本进入实验 manifest/resume 指纹；外部 adapter 总 token 进入统一 trial 与 summary。
- [ ] 正式横向结果前先做 endpoint 稳定性/限流校准；后续两次 `ENOTFOUND` 均须保持 infra-invalid，不得计入能力分母。

### W1-4 · Planner + V3 harness ✅

- [x] `update_plan` 工具、状态机、计划修订轨迹和 V3 prompt。
- [x] 遵守率以文件写入/测试等仓库动作验证，不接受 Agent 自我声明作为证据。
- [x] `AgentConfig.for_harness()` 集中定义 V1/V2/V3 身份，防止新 harness 静默丢失旧守卫。
- [x] 修复 item id 改名造成的遵守率假象，新增 `plan_done_unverified` 与改名计数。
- **实验结论**：修正后 planner 对 Task/Strict 中性，但工具调用约增加 18%。

### W1-5 · CI + 容器化评测 ✅

- [x] quality / sandbox-image / console 三门禁与 bounds / EvalPlus oracle / LLM smoke 三个 nightly job。
- [x] CI 首跑全绿；镜像内以 `--network none` 跑短程、长程 selfcheck 和确定性边界。
- [x] `check_bounds.py` 对 reference=1.00 / none=0.00 逐 case 校验。

### W1-6 · 并行 + trial 级续跑 ✅

- [x] `--workers N` 进程池并行；短程 9×2 实测 17.0s → 4.26s（4.0×）。
- [x] trial 完成标记、manifest 指纹和聚合顺序稳定性；配置不符拒绝 resume。
- [x] infra-invalid trial 必须重试，不能被冻结成“已完成”证据。
- [x] 自动 experiment ID 加 UUID 后缀，防止两个独立进程同秒启动时覆盖 manifest/summary/清理目录。
- [x] 每个 repeat 使用独立 build 目录，修复并行 materialize 覆盖。

### W1-7 · Provider/模型阶梯/成本 ✅

- [x] 单一 `ProviderSpec` 表接入 DeepSeek、OpenAI 兼容和智谱 GLM；`--model` 写入 provenance。
- [x] 每模型费率含 source/as_of、aliases、tiered/cache 口径；未知价格为 `None`。
- [x] 记录 requested/served model，修复 `deepseek-reasoner` 解析到 flash 导致的静默错误归因。
- [x] GLM-4.5-air 与 glm-4.7-flash 已实跑；免费档限流作为 infra-invalid 单独报告。
- **边界**：`usd_per_cny=null`，GLM USD 成本按设计为 unavailable。

### W2-1 · Context management ✅

- [x] 工具输出分级截断、基于真实 prompt token 的触发条件和确定性 compaction。
- [x] 保证 assistant tool_calls 与 tool replies 不被切断；每次压缩发 `COMPACTION` 事件。
- [x] `--context-budget-tokens`、`--context-ceiling-tokens` 与 `--ablate` 写入 provenance/resume 指纹。
- [x] 上下文硬上限对所有 harness 生效，保证消融组承受相同约束。
- **修正后 H3**：V3.1=1.00，V3.1−context=0.33；compaction 是全部成功效应，planner 中性。

### Week 2 其余任务

- [ ] **W2-2 ScratchPad**：run 内显式工作记忆尚未实现；跨 run memory 不得先于 trial 隔离设计。
- [x] **W2-3 Context amnesia**：被动 canary 检测、early/late split、短轨迹拒绝给 decay、跨 adapter 路径归一化均已完成；正式曲线报告仍归 W3-5。
- [x] **W2-4 Reward hacking**：8 类信号、evidence span、人工 hack 样本全命中、reference 零误报与历史回扫均已完成。
- [ ] **W2-5 Hackbait suite**：未实现；当前只有 16 个未被沙箱强制拦截的 Claude Code trial，零检出上界仍宽。
- [x] **W2-6 Instruction drift**：轨迹重放、首次违规步、obedience ratio、self-corrected/persisted 已完成。
- [ ] **W2-7 官方 SWE-bench Smoke Slice**：仍只有 schema-compatible 自建样例。
- [ ] **W2-8 第二外部 adapter**：aider / mini-swe-agent 尚未接入。

### Week 3 · 统计、产品化与收口

- [ ] **W3-1 Multi-turn**：确定性反馈驱动与 3 条多轮 case 未实现。
- [ ] **W3-2 RepoMemory**：跨任务记忆与 trial 间清空验证未实现。
- 🟨 **W3-3（部分）**：cluster bootstrap、exact McNemar、Wilson 区间已实现并应用；分层宏平均、成本配对统计仍未实现。
- [ ] **W3-4 Repro bundle**：诊断包与自动回归 fixture 未实现。
- [ ] **W3-5 Report/UI**：静态 HTML/MD 报告和专用 CrossAgent 视图未实现；现有通用控制台可读 artifacts。
- 🟨 **W3-6（部分）**：4-case 模型受控横向矩阵、H2/H3 和检测器历史回扫已有数据；8-case 矩阵、第二模型/第二外部 Agent 和全部预注册假设未完成。
- 🟨 **W3-7（部分）**：README 与 `cross_agent_report_v1.md` 已完成；开源状态核验、命名统一和完整 capability-gap/failure-atlas 文档未完成。

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

## M5 · EvalPlus-schema 子集 + LLM-Judge + kappa ✅
- [x] `benchmark/humaneval_plus.py`：10 题自建/精选 EvalPlus-schema 子集，Pass@1、Base/Plus、时延/异常/超时；temp 目录 + 超时执行；数据集 canonical 自检 10/10。
- [x] `scripts/run_humaneval.py`（含 `--selfcheck`）。DeepSeek 实测 Pass@1 100%（易题）。
- [x] `judge/code_review_judge.py`：LLM-Judge，结构化 `{score,max_score,passed_items,missed_items,confidence,reason,verdicts}` + **强制引用**（引用须在代码中，否则降 confidence）+ swap 平均 + temperature=0。
- [x] `judge/meta_eval.py`（拷改 ft_diag）：agreement + Cohen's kappa + trust map + 不达标降级；`judge/gold.py` + `data/judge_gold/`（6 case/16 item）。
- [x] `scripts/run_judge_meta_eval.py`；`docs/judge_meta_eval_report_v1.md`。
- **验收**：函数级 base/plus 评测流程跑通（Pass@1 100%，仅代表该 10 题易子集，不是正式 HumanEval+ 成绩）；judge 每条判定带有效引用；kappa 展示（CORRECTNESS/EDGE_CASES=1.0，READABILITY=0.62 贴阈值）。✅

## C · 只讲 + 部分落地 ✅（P2）
- [x] `benchmark/swebench.py`：读官方 schema（`FAIL_TO_PASS`/`PASS_TO_PASS`/`test_patch`/gold `patch`），跑官方 resolve 流程；`scripts/run_swebench.py`（gold/agent）。
- [x] 兼容样本 `datasets/swebench_compat/`：gold resolved 1/1；**MiniAgent(V2) 真跑 resolved 1/1**；标注 "Compatibility Sample"。
- [x] Docker：`docker/sandbox.Dockerfile` + `docs/swebench_and_docker.md`；CI 已 build，并在 `--network none` 下执行评测门禁。
- [x] 真实 SWE-bench Lite 接入路径写清（clone + env 复现；`materialize_instance` 留 NotImplementedError + 指引）。
- 仍只讲（不建）：Terminal-Bench/Harbor、PostgreSQL、成本看板全量；通用 adapter 契约与 MiniAgentAdapter 已在 V3 W1-2 落地，外部实现从 W1-3 开始。

## DOC · 长期文档 ✅
- [x] 根 `AGENTS.md`
- [x] `PROJECT_STATE.md`
- [x] `TASKS.md`
- [x] `docs/developer_guide.md`
- [x] `docs/benchmark_methodology_and_roadmap.md`

---

## B1 · HumanEval+/EvalPlus 官方 Smoke Slice ✅（P0）

- [x] 固定 EvalPlus 0.3.1；模型调用前以 seed `20260712` 选择 5 个官方任务并记录 SHA-256。
- [x] canonical oracle 使用同一官方 evaluator，Base/Plus=1.00/1.00。
- [x] 联网 generation 与受限环境 execution 拆分；官方 sanitizer + evaluator。
- [x] DeepSeek v4-flash：Base=1.00、Plus=0.80；逐题结果、trace、manifest 和限制落盘。
- [x] 产物标记 `smoke_slice`；报告明确不是完整排行榜成绩。
- **验收**：官方实例端到端可复现，`HumanEval/39` 展示 base→plus 的严格测试区分作用。✅

## B2 · SWE-bench 官方实例 Smoke Slice ⬜（P0）

- [ ] 选择少量可复现的官方 Verified/Lite 实例并记录筛选偏差。
- [ ] 按官方容器/环境契约先验证 oracle/gold。
- [ ] 保证 Agent 阶段不可见 test patch/gold；评分时运行 FAIL_TO_PASS/PASS_TO_PASS。
- [ ] 区分环境、oracle、Agent、patch apply、超时和 grader 失败。
- **验收**：至少一个真实官方实例完成 oracle + candidate 全流程；结果明确标注 official-instance smoke slice。

## B3 · 统计增强与分层报告 🟨（P0/P1）

- [x] P0：case-level/cluster bootstrap 置信区间 + Wilson 区间。
- [x] P0：Task/Strict exact McNemar。
- [ ] P0：成本配对 bootstrap/置换检验。
- [ ] P0：按 difficulty/task_type/repo/language 分层，报告宏平均与样本数。
- [ ] P0：token/cost/tool/time per successful trial 与预算约束成功率。
- [ ] P1：first target/full-suite pass time、测试失败恢复率、case 区分度。
- [ ] P2：多个模型/Agent、30+ case 后再研究项目—总分相关性。
- **纪律**：同一 case 的 repeats 不当独立 case；同时报告 effect size、区间、样本数和预算；“不显著”不等于“相同”。

## B4/B5 · Terminal-Bench 与 OctoBench 📝（P1）

- [x] 在 benchmark 方法论路线图中记录评测构念、协议、资源、风险与实施顺序。
- [ ] HumanEval+、SWE-bench 增量完成后，细化 Terminal-Bench/Harbor adapter 与 oracle 方案。
- [ ] 选择少量官方 Terminal-Bench 任务：先 oracle，后 Agent，保留容器末态与终端轨迹。
- [ ] 细化 OctoBench 官方环境、scaffold 指令与 objective checklist 映射。
- [ ] 选择少量官方 OctoBench 环境，验证 Task/Strict 分离和持续约束。
- **验收**：分别完成 protocol-conformant smoke slice；不作为全量 leaderboard 结果。

## G1 · 私有 Golden Dataset 扩充 🟨（长程地基已完成）

- [x] P0（部分）：长程跨模块 spec、行为保持/API 迁移 refactor、级联 bugfix、build/CLI case 已落地；短程 instruction-following 仍待补。
- [ ] P1：带证据的 code review；以缺陷检出率/mutation score 评分的 test generation；performance；security；并发/资源泄漏/事务一致性。
- [ ] P2：multi-turn 需求澄清、需求变化与跨轮状态；先设计用户模拟器、多轮 oracle、稳定性与泄漏防护。
- [ ] 所有 case 补齐来源、标签、难度、语言、reference/oracle、污染/flaky/捷径检查、版本和修订记录。

---

## 当前推荐执行顺序

V3 W1 全部完成，W2-1/3/4/6 完成，W3-3/6/7 部分完成。当前顺序：

1. 在当前 8-case 长程 suite 上重跑 Claude Code / MiniAgent 模型受控矩阵，替换旧 4-case 的统计瓶颈。
2. 接入 aider 或 mini-swe-agent 作为第二外部 Agent；同时保留默认模型真实产品组与统一模型 scaffold 受控组。
3. 完成 W3-1 multi-turn、W3-4 repro bundle、W3-5 静态报告/跨 Agent UI，直接补齐 JD 尚缺的交付物。
4. 完成 B2 官方 SWE-bench Smoke Slice；至少一个官方实例走通 gold oracle + candidate，全程明确非排行榜。
5. 先实现 run 内 ScratchPad，再评估跨 run memory；任何持久记忆都必须有 trial 隔离和泄漏单测。
6. B3 补分层宏平均、成本配对统计与成本/成功前沿；正式 Golden Dataset/hidden/reference 不随开源框架公开。
