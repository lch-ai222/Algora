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
   - `v1`/`v2`：`MiniAgent(provider, AgentConfig(version)).run(task, sandbox)`，loop 用工具改仓库。
   - `reference`：`apply_reference_fix`（拷回干净版），上界。
   - `none`：不动，下界。
4. **在注入 hidden 前**捕获 `patch` 与 `changed_files`（否则 hidden 文件污染 diff）。
5. `inject_hidden_tests` → 把 case 的 hidden 测试拷进 worktree `tests/`。
6. 评分：`grade_tests`（target/regression/hidden）→ `grade_constraints` → `grade_patch` → `combine`（Task/Strict）。
7. `attribute_failure`（失败归因）→ `_persist_trial`（config/trajectory/patch/grader/failure-tags）。`config.json` 记录运行溯源：`agent/provider/model/temperature/complexity/max_tokens/max_steps/timeout_seconds`（`summary.json` 顶层 `run_config` 同）——用于审计 V1/V2 同配置归因纪律。
8. 清理 worktree 与现构仓库。

`run_experiment` 在其上做 cases×repeats、聚合（mean+方差、pass@k/pass^k、failure_tags）、写 `summary.json/csv`。

## 3. LLM Provider（`llm.py`）

拷改自 ft_diag。要点：
- OpenAI 兼容，`LLM_PROVIDER` 选 deepseek/openai；client 带 timeout + retries。
- `tool_completion(system, messages, tools, ...) -> LlmToolTurn`：单轮 tool-use；解析 `tool_calls` 成 `LlmToolCall`（含 `arguments_error`）。**多轮 loop 在 agent 层**。
- `json_completion(..., response_model)`：结构化 JSON，供 M5 的 Judge。
- `llm_trace_scope(case_id, node_name)`：contextvar 收集本 trial 的 `LlmCallRecord`（token/cost/latency）。
- 失败返回 `None` + `last_error`，**不抛进 trial**。

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
- 组初始 user message → 循环：`tool_completion` → 记 MODEL_REQUEST/RESPONSE → 无 tool_calls 则 FINAL 停 → 执行每个 tool_call、回灌 role=tool 消息 → 记专有事件（TEST_RESULT/COMMAND_FINISH/FILE_WRITE/FILE_READ）。
- 停因：`final / max_steps / timeout / provider_error / repeated_action`。
- `completion_checks`：has_changes / ran_tests / last_test_passed / over_steps / over_timeout / triggered_forbidden / blocked_commands。
- `AgentConfig`：V1/V2 差异 = prompt + `detect_repeated_actions`（V2 开）。runner 里 V2 还注入 `AGENTS.md`（benchmark 仓库那份）。

`prompts.py`：**V1 是刻意最小的基线**（“做最小改动、确认命名的那个失败测试过就结束、不必跑全套”）；**V2 是纪律化**（reproduce-first、完成前跑 target+全套+git_diff、失败重规划、不改测试、避免重复动作、结构化完成报告）。V1/V2 只差 harness，同模型同预算。

## 7. Benchmark（`benchmark/`）

`case.py` · `EvalCase`：case_id / task_type / instruction / visible_tests / regression_tests / hidden_tests / constraints(forbidden_paths,max_changed_files…) / max_steps / timeout / tags。`load_suite` 读 `suite.json`。

`materialize.py`：
- `materialize_case`：干净源 + `cases/<id>/defect/` 覆盖 → 单 commit 仓库（**fix 不在历史**，防 `git checkout` 取解）。
- `inject_hidden_tests`：评分时把 `cases/<id>/hidden/*.py` 拷进 worktree `tests/`。
- `apply_reference_fix`：拷回干净版（=已知正确解），供 selfcheck 与 reference 档。

隔离设计要点：每 case 只引入自己的缺陷，其余模块正确 → regression 在 base 通过；对抗 case 把“正确修复所需的不变量”放在**分离的可见测试文件**里（V2 跑全套能发现，V1 只跑命名测试发现不了）。

## 8. Graders（`graders/`）

分级优先级：**程序验证 > 静态规则 > LLM-Judge > 人工**。

- `pytest_run.run_pytest`：`python -m pytest -v` 跑指定 node ids，逐行解析 PASSED/FAILED/ERROR/SKIPPED → `PytestOutcome`（`all_passed` 要求真跑过且无失败）。
- `test_grader.grade_tests`：target/regression/hidden 三组 → `functional_success = 三者全过`。
- `constraint_grader.grade_constraints`：禁止路径 / 改动文件数超限 / 新依赖 / 完成前是否跑测 / 禁止命令 → violations。
- `patch_grader.grade_patch`：有无 patch / `git apply --check` 能否应用 / 增删行 / **是否改测试绕过验证** → passed。
- `result.combine`：**Task Success** = functional；**Strict Success** = Task ∧ 约束通过 ∧ patch 干净。

## 9. 失败归因（`failure_taxonomy.py`）

只对失败 trial 打标，确定性规则、可解释：timeout/repeated_action/provider_error/max_steps(PLANNING)、改测试/禁止路径(INSTRUCTION_VIOLATION)、无改动(EDIT)、**target 过但 regression/hidden 挂且已结束(PREMATURE_TERMINATION，或跑过失败测试仍停=RECOVERY)**、没读源就改(CODE_RETRIEVAL)、否则 UNKNOWN。返回有序 tags，首个为 primary。

## 10. 版本对比（`compare.py`）

按 **Task Success 率** 分 improved/regressed/stable；同时报 Strict、tool/token delta 与套件级 delta。`scripts/compare_runs.py` 命令行打印，控制台 Version Compare 视图同源。

## 11. Runner（`runner.py`）

CLI：`--agent v1|v2|reference|none --suite <dir> --repeats k --cases <ids> --out <dir>`。v1/v2 需 provider 可用（`.env`）。产物落 `artifacts/runs/<experiment_id>/<case_id>/rep<k>/`。

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

## 14. 启动与测试

见 [`../AGENTS.md`](../AGENTS.md) §6。质量门禁：`pytest -q`（全绿，当前计数见 [`../PROJECT_STATE.md`](../PROJECT_STATE.md)）+ `ruff check` + `scripts/selfcheck.py`（9/9）。真实 LLM 冒烟：`RUN_LLM_SMOKE=1` + key。

## 15. 测试覆盖现状

- `test_llm_provider`（provider 解析/trace）、`test_sandbox`（策略/生命周期/超时/截断/逃逸/patch，25）、`test_tools`（6 工具 + 守卫）、`test_agent_loop`（scripted 端到端 + 停因 + V2 守卫）、`test_pipeline`（reference 上界/none 下界/区分度/grader 守卫）、`test_compare`、`test_failure_taxonomy`、`test_api`（后端）。

## 16. 维护规则

- 改沙箱/grader/materialize 后必跑 `selfcheck.py` 与全套测试。
- 任何影响“hidden 不可见 / 历史无解 / V1V2 同配置”的改动都要在 PROJECT_STATE 的“已知风险”里说明。
- 新增依赖/目录/命令同步 `pyproject.toml`/`.gitignore`/`.env.example`/`README.md`。
- 完成里程碑后更新 `PROJECT_STATE.md` 与 `TASKS.md`。
