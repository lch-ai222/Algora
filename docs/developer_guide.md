# Algora 开发者说明书（CodeAgent Eval Lab）

面向要读代码、改代码、加 case 的开发者/智能体。协作规则见 [`../AGENTS.md`](../AGENTS.md)，状态见 [`../PROJECT_STATE.md`](../PROJECT_STATE.md)。

## 1. 产品定位

一个**仓库级 Coding Agent + 确定性评测流水线**。核心不是 agent 有多强，而是走通闭环：

```
执行(在隔离沙箱改仓库) → 轨迹采集(trace) → 自动评分(确定性优先)
   → 失败归因(taxonomy) → 版本回归(V1→V2 同配置) → 可视化(控制台)
```

三层严格分离（见 AGENTS.md §3）：Coding Agent（被测）≠ Evaluation Pipeline（确定性系统）≠ Console（只读可视化）。

## 2. 端到端数据流

以 `runner.run_trial` 为主线：

1. `materialize_case(suite_dir, clean_repo, case)` → 现构一个 git 仓库：拷贝干净源 → 覆盖该 case 的 `defect/` 文件 → `git init && commit`。**单缺陷、历史无解**。
2. `WorktreeSandbox(repo)` → 从该 commit 拉一个临时 worktree。
3. agent 分支：
   - `v1`/`v2`/`v3`：runner 通过 registry 构造 `MiniAgentAdapter`，执行 `prepare → run → cleanup`；adapter 内部调用 MiniAgent，并归一化为 `AgentRunResult`。V3 可通过 `--ablate planner|context` 做单能力消融。
   - `claude_code`：调用 headless CLI，原始 stream-json 边流边落盘，结束后归一化为同一结果契约；Claude Code 2.1.220 + 智谱 GLM-5.2 的协议与 repo smoke 已 live 验证。
   - `reference`：`apply_reference_fix`（拷回干净版），上界。
   - `none`：不动，下界。
4. **在注入 hidden 前**捕获 `patch` 与 `changed_files`（否则 hidden 文件污染 diff）。
5. `inject_hidden_tests` → 把 case 的 hidden 测试拷进 worktree `tests/`。
6. 评分：`grade_tests`（target/regression/hidden）→ `grade_constraints` → `grade_patch` → `combine`（Task/Strict）。
7. `attribute_failure`（失败归因）→ `_persist_trial`（config/trajectory/patch/grader/failure-tags；adapter 路径另写 `agent-result.json`）。`config.json` 记录运行溯源：`adapter/adapter_version/harness/provider/model/temperature/complexity/max_tokens/max_steps/timeout_seconds`（`summary.json` 顶层 `run_config` 同）。
8. 清理 worktree 与现构仓库。

`run_experiment` 在其上做 cases×repeats、聚合（mean+方差、pass@k/pass^k、failure_tags、动作/模型轮次/测试次数中位数）、写 `summary.json/csv`。`--workers N` 只改变调度，不改变聚合顺序；每个 trial 最后写完成标记，`--resume` 只采纳 manifest 指纹一致且非 infra-invalid 的完整 trial。provider/网络错误是 infra-invalid，不进入成功率分母；进程退出码 3 表示实验含基础设施失败。

## 3. LLM Provider（`llm.py`）

拷改自 ft_diag。要点：
- OpenAI 兼容，`LLM_PROVIDER` 选 deepseek/openai/zhipu；`ProviderSpec` 是 client、默认模型、可用性和实际服务模型解析的单一事实来源，client 带 timeout + retries。
- `tool_completion(system, messages, tools, ...) -> LlmToolTurn`：单轮 tool-use；解析 `tool_calls` 成 `LlmToolCall`（含 `arguments_error`），并保留 `finish_reason` 供 loop 区分正常结束和 token 截断。**多轮 loop 在 agent 层**。
- `json_completion(..., response_model)`：结构化 JSON，供 M5 的 Judge。
- `llm_trace_scope(case_id, node_name)`：contextvar 收集本 trial 的 `LlmCallRecord`（token/cost/latency）。
- 失败返回 `None` + `last_error`，**不抛进 trial**。

`pricing.py` + `config/pricing.json` 负责派生成本：费率必须带 source/as_of；alias 先解析到实际模型；缓存 token 按独立费率计；分档模型使用最贵档并标 `upper_bound`；任何一轮无法定价则整个 trial 成本为 `null/unavailable`。CNY 只有显式配置带出处的 `usd_per_cny` 后才换算，禁止隐式汇率。

## 4. 沙箱（`sandbox/`）—— 最高风险模块，先读单测

`policy.py` · `CommandPolicy`（deny-by-default）：
- 先扫危险子串（`rm -rf /`、`sudo`、`docker`、`curl/wget`、`pip install` 等）→ 拦。
- `shlex.split` 后：出现 shell 算子 token（`|`、`&&`、`>`…）→ 拦（不开 shell，一次一条命令）；引号内的算子是字面量，不误拦。
- 基命令必须在 allow-list（python/pytest/git/ls/rg…）；`git push/pull/clone/fetch/remote` 在无网策略下拦。

`worktree.py` · `WorktreeSandbox`：
- `setup`：`git rev-parse` 定 base sha → `git worktree add --detach`；`run(cmd, timeout)`：过策略 → `subprocess.run`（无 shell、scrubbed env、cwd=worktree、超时、输出截断）；`resolve(path)`：拒绝逃出 worktree 的路径；`export_patch`/`changed_files`：对 base 的 diff；`cleanup`：`worktree remove --force` + prune + 删临时目录。
- scrubbed env：只留 PATH（并把解释器目录前插，保证 `python` 可解析）、清代理、`HOME` 指向沙箱。
- **网络隔离是命令层**（拦网络工具），非内核级；真隔离要 Docker（C 层）。

## 5. 工具（`tools/`）

`base.py`：`Tool`(ABC，含 `openai_schema()`) + `ToolContext`(sandbox/forbidden_paths/timeout/page_size) + `ToolRegistry`(dispatch 捕获参数错/异常，不崩 trial)。

`coding_tools.py`：6 个工具。只读工具（list/search/read）直接走 `sandbox.resolve`（路径守卫）；`apply_patch` 是 str-replace 编辑器（`old_str` 唯一匹配才改；空 `old_str` 创建/覆盖；命中 `forbidden_paths` 拒绝）；`run_command` 走 `sandbox.run`；`git_diff` 走 `export_patch`。

## 6. Agent Loop（`agent/`）

`loop.py` · `MiniAgent.run(task, sandbox)`：
- 组初始 user message → 循环：`tool_completion` → 记 MODEL_REQUEST/RESPONSE → 执行 tool_calls、回灌 role=tool 消息 → 记专有事件（TEST_RESULT/COMMAND_FINISH/FILE_WRITE/FILE_READ）。
- V2/V3 对无 tool_calls 的响应做完成门禁：`finish_reason=length`、空 summary，以及 case 要求完成前测试时的无改动/未测试/末次测试失败，都会发 `premature_final` 事件和客观反馈并继续；V1 仍接受首个 final，保持刻意薄基线。
- 停因：`final / max_steps / timeout / provider_error / repeated_action`。
- `completion_checks`：has_changes / ran_tests / last_test_passed / over_steps / over_timeout / triggered_forbidden / blocked_commands / provider_error / premature_final_attempts。
- `AgentConfig.for_harness()` 是 V1/V2/V3 身份的单一入口：V2 在 V1 上增加纪律化 prompt、完成门禁、重复动作守卫与 benchmark `AGENTS.md` 注入；V3 继承全部 V2 守卫，再增加 planner 与 context manager。禁止用 `version == "v2"` 这类字符串相等判断新增守卫，否则新版本会静默丢能力。

`prompts.py`：**V1 是刻意最小的基线**；**V2 是纪律化**（reproduce-first、完成前跑 target+全套+git_diff、失败重规划、不改测试、避免重复动作、结构化完成报告）；**V3 = V2 + planner/context**，支持逐项消融。同一实验中的模型、suite、温度、预算和未被消融能力必须完全一致。

`planner.py`：loop 持有 PlanTracker 状态，工具只校验/回显。`done` 必须由其间真实文件写入或测试动作支撑；同文本的 item 即使被模型改 id 仍视为同一项。另报 `plan_done_unverified`、`plan_done_retroactively`、`plan_done_without_action` 和 id rename，避免把计划自述当完成证据。

`context.py`：先按工具类型做确定性分级截断，再按 provider 实报 prompt tokens 触发 compaction；摘要由轨迹中的读/写/命令/测试/计划确定性构建，不调用另一个 LLM。切口必须保持 tool-call/reply 配对。`context_budget_tokens` 是压缩阈值，`BudgetContract.max_tokens`/`--context-ceiling-tokens` 是对所有 harness 生效的硬上限，两者不可混为一谈。

### 6.1 Agent Adapter（`adapters/`）

- `base.py`：runtime-checkable `AgentAdapter` Protocol；不可变 `BudgetContract`；`AgentRunResult` 是跨 Agent 的 patch/轨迹/token/cost/停止原因/环境清单契约；`UnsupportedCapability` 禁止静默降级。归一化 prompt/completion 总量必须进入 `TrialResult`，不能假设外部框架会提供逐调用 `LlmCallRecord`，否则 summary 会静默报 0 token。
- `mini_agent.py`：包装 in-process MiniAgent，硬执行 wall-clock/step/context ceiling；对总成本/总 token 等无法保证的预算明确拒绝。每回合输出上限与全程上下文上限是两个不同契约。
- `claude_code.py`：调用 `claude -p --output-format stream-json --verbose`；独立 `CLAUDE_CONFIG_DIR` 隔离操作者 hooks/MCP/settings；wall-clock 通过进程组 SIGTERM→SIGKILL；未知/畸形记录只降级轨迹，不丢已花预算的 trial。第三方 `ANTHROPIC_BASE_URL` 下 native USD 成本语义不可信，必须降为 unavailable。Claude Code 2.1.220 + GLM-5.2 已通过协议流和一个 repo smoke；该版本的 help 不列 `--max-turns`，但实跑接受，说明 capability 不能只靠 help 文本猜测。正式矩阵前仍须校准 endpoint 稳定性，`ENOTFOUND`/限流均按 infra-invalid 处理。
- `normalize.py`：跨框架工具语义表；例如 Read→FILE_READ、Bash+pytest→TEST_RESULT、TodoWrite→PLAN_UPDATE。推断字段必须标 provenance，不能伪装成原生真值。
- `registry.py`：显式名称→构造器，当前为 `mini_agent` 和 `claude_code`。
- 成本：MiniAgent 由固定费率表派生，Claude Code 仅在 native Anthropic 语义成立时接受 native 成本；不可用必须是 `cost_usd=null`、`cost_source=unavailable`。

## 7. Benchmark（`benchmark/`）

对外口径先分清：`mini_store` 是自建私有 Golden Dataset，不是业内公共 benchmark；
`humaneval_plus.py` 当前是 10 题 EvalPlus-schema 子集验证；`swebench.py` 当前完成官方字段兼容和
自建 Compatibility Sample，尚无正式公开排行榜结果。完整方法、能力矩阵和实施等级见
[`benchmark_methodology_and_roadmap.md`](benchmark_methodology_and_roadmap.md)。

`case.py` · `EvalCase`：除基本测试/约束/预算外，V3 增加 `horizon`、`expected_steps`（模型轮次）、`expected_tool_calls`（动作数）、`CanarySpec`、`build_checks`、`allow_test_edits`、`known_shortcuts`，并支持 build/multi_turn task type。`load_suite` 读 `suite.json`。

`materialize.py`：
- `materialize_case`：干净源 + `cases/<id>/defect/` 覆盖 → 单 commit 仓库（**fix 不在历史**，防 `git checkout` 取解）。
- `inject_hidden_tests`：评分时把 `cases/<id>/hidden/*.py` 拷进 worktree `tests/`。
- `apply_reference_fix`：拷回干净版（=已知正确解），供 selfcheck 与 reference 档。

隔离设计要点：每 case 只引入自己的缺陷，其余模块正确 → regression 在 base 通过；对抗 case 把“正确修复所需的不变量”放在**分离的可见测试文件**里（V2 跑全套能发现，V1 只跑命名测试发现不了）。

`datasets/mini_store_long/` 使用独立 `repo_src` 快照，避免为了长任务改坏短程历史基线。4 个 hard case 覆盖 12 文件 API 迁移、5 模块退货功能、单根因级联 bug 与 7 文件 build/CLI/offline-wheel 链路；每条带 canary。质量门禁是干净仓库 53 tests + long selfcheck 4/4 + reference/none 1.0/0.0。

## 8. Graders（`graders/`）

分级优先级：**程序验证 > 静态规则 > LLM-Judge > 人工**。

- `pytest_run.run_pytest`：`python -m pytest -v` 跑指定 node ids，逐行解析 PASSED/FAILED/ERROR/SKIPPED → `PytestOutcome`（`all_passed` 要求真跑过且无失败）。
- `test_grader.grade_tests`：target/regression/hidden 三组 → `functional_success = 三者全过`。
- `constraint_grader.grade_constraints`：禁止路径 / 改动文件数超限 / 新依赖 / 完成前是否跑测 / 禁止命令 → violations。
- `patch_grader.grade_patch`：有无 patch / `git apply --check` 能否应用 / 增删行 / **是否改测试绕过验证** → passed。
- `result.combine`：**Task Success** = functional；**Strict Success** = Task ∧ 约束通过 ∧ patch 干净。

## 9. 失败归因（`failure_taxonomy.py`）

只对失败 trial 打标，确定性规则、可解释：timeout/repeated_action/provider_error/max_steps(PLANNING)、改测试/禁止路径(INSTRUCTION_VIOLATION)、无改动(EDIT)、target 过但 regression/hidden 挂且已结束。只有**最后一个可见测试仍失败**才是 RECOVERY；可见 target/regression 已过但 hidden 漏项归 TASK_UNDERSTANDING；未充分验证则 PREMATURE_TERMINATION。没读源就改为 CODE_RETRIEVAL，否则 UNKNOWN。

## 10. 版本对比（`compare.py`）

按 **Task Success 率** 分 improved/regressed/stable；同时报 Strict、tool/token delta 与套件级 delta。`scripts/compare_runs.py` 命令行打印，控制台 Version Compare 视图同源。

## 11. Runner（`runner.py`）

CLI 保留 legacy `--agent v1|v2|v3|reference|none`，新接入路径为 `--adapter mini_agent|claude_code --harness v1|v2|v3`。通用实验变量含 `--suite/--repeats/--cases/--out/--workers/--resume/--model/--max-steps`；MiniAgent 另有 `--max-completion-tokens`、`--context-budget-tokens`、`--context-ceiling-tokens`、`--ablate`。所有会改变被测系统或约束的参数都进入 provenance 与 resume 指纹。产物落 `artifacts/runs/<experiment_id>/<case_id>/rep<k>/`；自动 ID 为 `agent-UTC-<uuid8>`，避免独立进程同秒启动时共享目录，resume 则始终复用用户给定的完整 ID。

长程复现命令：

```bash
.venv/bin/python -m codeagent_eval.runner --adapter mini_agent --harness v3 \
  --suite datasets/mini_store_long --max-completion-tokens 4096 \
  --context-budget-tokens 10000 --context-ceiling-tokens 12000 --workers 2
```

正式校准 `v2-20260803T191808Z` 的动作/模型轮次/测试运行中位数为 30/13.5/3，Task/Strict=1.0，infra=0。它是 n=1/case 的 horizon gate，不是带统计置信度的能力结论。修正后的 H3（长程 4 case×3 repeats、12k ceiling）为 V3.1=1.00、V3.1−context=0.33、V3.1−planner=1.00：compaction 是全部成功效应，planner 成功率中性但工具调用约 +18%；样本仍小，只作方向性证据。

## 12. 控制台（`backend/` + `frontend/`）

- 后端 `store.py` 直接读 `artifacts/runs/`（无 DB，SQLite 为后置升级）；`routers/experiments.py` 暴露 experiments/experiment/trial/compare；`main.py` 加 CORS + `/api/health`。
- 前端 Vite+React+TS，`api.ts` 带类型；四个视图见 `frontend/src/views/`。`vite.config.ts` 把 `/api` 代理到 :8000。
- 注意：pydantic `@property`（如 `pass_rate`）不进 JSON，前端别依赖，用底层数组字段。

## 13. 怎么加一个 case

1. 在 `mini_store_src/` 写/改**正确**实现 + 可见 target 测试（干净源必须全绿）。
2. 需要“对抗”时，把正确修复所需的不变量放到**分离的可见测试文件**（如 `tests/test_*_invariants.py`），并在 case 的 `regression_tests` 里引用。
3. 在 `cases/<id>/defect/` 放缺陷变体（只改要考的文件）。
4. 在 `cases/<id>/hidden/` 放隐藏测试（更强的边界）。
5. 在 `suite.json` 加 case 条目（instruction 可适度欠定义以诱导 naive 修复）。
6. `python scripts/selfcheck.py` 必须该 case valid（target 在 base 挂、缺陷隔离、参考修复后全过、hidden 不可读）。

## 14. 公开 Benchmark Adapter 统一职责

公开 benchmark 的实现分为 Protocol Study、Compatibility/Smoke Slice、Benchmark Evaluation
三个等级；每次运行必须在产物和报告里标明等级。近期目标是用少量官方实例完成协议一致的
Smoke Slice，而不是全量排行榜。

Adapter 至少负责：

1. 固定 benchmark 名称、官方版本、数据来源和实例筛选规则。
2. 映射官方 task schema，不把自建题伪装成官方实例。
3. 复现官方环境、oracle、候选执行和评分契约；oracle 先于 Agent 自检。
4. 区分环境失败、oracle 失败、Agent 失败、超时和评分失败。
5. 持久化原始输入、候选输出、patch、日志、grader、版本与复现命令。
6. 报告样本规模、预算和不可外推边界；小样例不得写成排行榜成绩。

后续统一结果模型需支持：difficulty/task_type/repo/language 分层字段、case-level 置信区间、
V1/V2 配对比较、每成功任务 token/cost/tool/time、首次 target/full-suite 通过时间和测试失败恢复率。
同一 case 的 repeats 是簇内重复，不得简单当作相互独立的新 case。

### 14.1 EvalPlus 官方 Smoke Slice（B1）

`benchmark/evalplus_official.py` 保持 EvalPlus optional import：主 `.venv` 的离线测试不依赖重型
benchmark 包，正式运行使用 `.venv-evalplus`（固定 EvalPlus 0.3.1）。配置在
`config/benchmarks/evalplus_smoke.json`，入口为 `scripts/run_evalplus_smoke.py`。

执行纪律：固定 seed/显式 task IDs 在模型调用前选择官方实例 → 写 deterministic override dataset
和 SHA-256 → canonical oracle 必须 Base/Plus=100% → 联网阶段 `--generate-only` 只生成与调用官方
sanitizer → 人工检查样本 → 回到受限环境 `--resume ... --allow-local-model-execution` 调官方 evaluator。

Evaluator 成功不能只看 return code：还必须解析出 Base/Plus 指标；oracle 进一步要求二者都为 1.0。
同一 samples 路径不使用 `--i-just-wanna-run`，避免 EvalPlus 0.3.1 已有缓存时进入交互覆盖提示。
macOS 当前配置 `EVALPLUS_MAX_MEMORY_BYTES=-1` 规避 rlimit 兼容错误，因此没有内存硬限制，不能称作
安全沙箱。完整结果与限制见 [`evalplus_smoke_report_v1.md`](evalplus_smoke_report_v1.md)。

## 15. 启动与测试

见 [`../AGENTS.md`](../AGENTS.md) §6。质量门禁：`pytest -q`（当前 255 passed/1 skipped）+ `ruff check` + `scripts/selfcheck.py`（短程 9/9）+ `scripts/selfcheck.py datasets/mini_store_long`（长程 4/4）+ `PYTHONPATH=src scripts/check_bounds.py --suite ...`（当前未 editable-install 的环境需要该前缀；两套 reference=1.00/none=0.00）。真实 LLM 冒烟：`RUN_LLM_SMOKE=1` + key。

## 16. 测试覆盖现状

- `test_llm_provider`（provider spec、served model、finish_reason/trace）、`test_pricing`（alias/cache/tier/币种/不完整定价）、`test_sandbox`（策略/生命周期/超时/截断/逃逸/patch）、`test_tools`（coding + planning 工具）、`test_agent_loop`（V1/V2/V3、完成门禁、context ceiling/compaction、planner 指标）、`test_adapters` 与 `test_claude_code_adapter`（协议/预算/真实 subprocess stand-in/归一化/成本/配置隔离）、`test_parallel_runner`（并行/checkpoint/resume/infra 重试）、`test_long_suite`（schema/isolation/reference/none）、`test_pipeline`、`test_compare`、`test_failure_taxonomy`、`test_pytest_run`、`test_api`。

## 17. 新任务类型与 Oracle 要求

任务扩充优先级见 `benchmark_methodology_and_roadmap.md`：P0 为 bugfix、spec、instruction
following、refactor；P1 为 review、test generation、performance、security 和并发/资源类缺陷；
P2 为 multi-turn。

- Instruction Following 必须把功能成功与约束成功分开，产出真实 Task/Strict 差异。
- Refactor 必须用完整回归/API contract 证明行为保持，不能用 Judge 代替程序 oracle。
- Code Review 的每项判断必须引用代码证据，并用人工 gold 量 Judge 可信度。
- Test Generation 不能只看新测试能否通过，至少使用已知缺陷检出率或 mutation testing。
- Performance/Security 先过功能门禁，再用稳定性能输入或 exploit/negative tests 评分。
- Multi-turn 需要用户模拟器、信息释放策略、多轮 oracle 和泄漏防护，不能简单拼接消息冒充。

每个新 case 还必须记录能力标签、难度、语言、来源、reference、oracle、可能捷径、污染检查、
flaky 检查、数据版本和修订/废弃原因。

## 18. 维护规则

- 改沙箱/grader/materialize 后必跑 `selfcheck.py` 与全套测试。
- 任何影响“hidden 不可见 / 历史无解 / V1V2 同配置”的改动都要在 PROJECT_STATE 的“已知风险”里说明。
- 新增依赖/目录/命令同步 `pyproject.toml`/`.gitignore`/`.env.example`/`README.md`。
- 完成里程碑后更新 `PROJECT_STATE.md` 与 `TASKS.md`。
