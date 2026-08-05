# AGENTS.md

本文件记录 Algora（CodeAgent Eval Lab）项目**长期不变**的协作规则、工程规范和产品/架构边界。新会话或其他智能体进入本项目后，应**先读本文件**，再读 [`PROJECT_STATE.md`](PROJECT_STATE.md)（当前状态）和 [`TASKS.md`](TASKS.md)（里程碑与任务）；需要深入实现细节时读 [`docs/developer_guide.md`](docs/developer_guide.md)；项目总体设计以 [`coding_agent_eval_plan_v2.md`](coding_agent_eval_plan_v2.md) 为准。

> 注意区分两个 AGENTS.md：**本文件（根目录）** 是给协作智能体看的项目规则；[`datasets/mini_store_src/AGENTS.md`](datasets/mini_store_src/AGENTS.md) 是 **benchmark 目标仓库** 的仓库约定，会被 V2 harness 注入给被评测的 MiniAgent，两者用途完全不同，不要混改。

## 1. 协作规则

- 不要一味同意用户方案。若方案存在工程风险、评测有效性风险（如污染、区分度不足）、或长期不可维护风险，应明确指出并给出更专业的替代方案。
- 每次修改代码、文档、配置、数据前，先用简短语言说明：改哪些文件、用什么方法、解决什么问题、可能的影响；说明后等待用户确认再动手。用户说“确认/继续/按这个做”即视为本轮授权。
- 不覆盖用户或其他智能体的未说明改动。遇到脏工作区先读清楚再增量修改。
- 不执行破坏性命令（`git reset --hard`、`git checkout -- <file>`、批量删除等），除非用户明确要求。
- **绝不**在代码、文档、测试、trace、artifacts 里写入真实 API key。`.env` 只在本地用、已在 `.gitignore` 中，不提交。

## 2. 工程规范

按“系统干净、项目隔离、依赖可追踪、配置可复现、垃圾可清理”工作。

- Python 依赖放在项目 `.venv`（Python 3.11）中，不污染系统 Python；不使用 `sudo pip`、`curl | sudo bash` 等方式。
- 新增依赖必须同步更新：`pyproject.toml`；如涉及环境变量则更新 `.env.example`；如涉及缓存/运行输出目录则更新 `.gitignore`；必要时更新 `README.md`。
- 新增运行输出目录（trace / patch / log / sqlite）必须说明用途和清理方式；大日志走文件不进库/不进 git。
- 提交前跑 `pytest -q` 与 `ruff check`，保持全绿。
- 前端依赖在 `frontend/`（npm）内管理；`node_modules/`、`frontend/dist/` 不提交。

## 3. 产品与架构边界

Algora 是一个**仓库级 Coding Agent + 确定性评测流水线**，目标是走通「执行 → 轨迹采集 → 自动评分 → 失败归因 → 版本回归」的完整闭环。它**不是**要复刻 Claude Code，重点是闭环本身可复现、可验证、可归因。

三个必须分清的层：

1. **Coding Agent（被测对象）** — `src/codeagent_eval/agent/` + `tools/` + `sandbox/`。MiniAgent 的 loop、6 个工具、进程隔离沙箱。V1/V2/V3 是同一 agent 的 harness 演进；V3 增加 planner、context 与有累计预算的会话续接。
2. **Evaluation Pipeline（评测系统）** — `benchmark/` + `graders/` + `runner.py` + `failure_taxonomy.py` + `compare.py`。这是**确定性 pipeline，不是又一个评测 agent**。
3. **Console（React 控制台）** — `backend/` + `frontend/`。只读地可视化已产出的 artifacts。

关键边界（评测有效性的红线）：

- **分级评分优先级不可倒置**：确定性程序验证（测试）> 静态规则（约束/patch）> LLM-Judge > 人工。能程序判的绝不用模型判；LLM-Judge **绝不**用于判「测试是否过 / 文件是否改 / 是否超时」这类有程序 oracle 的维度。
- **hidden 测试对被测 agent 不可见**：hidden 测试存在 suite 的 case 目录里，只在**评分时**注入 worktree（`inject_hidden_tests`），trial 运行期间绝不可读。任何改动都要保证这一点，`scripts/selfcheck.py` 是硬门槛。
- **多轮后续测试分阶段可见**：`FeedbackDriver` 只运行/回灌当前已公开的 visible tests；下一轮测试随用户 follow-up 才注入，并进入 harness diff baseline。hidden/regression 信息仍不得回灌，未来轮测试不得在初始 worktree 出现。
- **无污染**：mini_store 是自建私有集；每个 case 用 `materialize_case` 现构一个**只含该 case 缺陷、且 git 历史里没有正确答案**的仓库，杜绝 agent 用 `git checkout` 取到解。
- **V1/V2 归因纪律**：对比 V1/V2 时**同模型、同 benchmark、同预算、同温度、同步数、同环境**，变化只归因到 harness。违反此纪律的对比结果无效。
- **Task Success vs Strict Success 双指标**：Task=功能正确（target+regression+hidden 全过）；Strict=Task 且工程合规（约束通过 + patch 干净、未改测试）。不要合并成单一指标。
- **诚实标注**：saturation（强模型把简单 case 全过）、judge 不达标降级、SWE-bench 只作 compatibility sample —— 都要如实说，不掩盖。

## 4. 模块边界

```
src/codeagent_eval/
  llm.py            OpenAI 兼容 provider（tool-calling + 结构化 JSON + trace scope）。拷改自 ft_diag。
  settings.py       env 驱动的 frozen dataclass 配置。
  models.py         LlmCallRecord（观测）+ AgentTask / TraceEvent（coding 领域）。
  observability.py  token/cost JSONL 导出。拷贝自 ft_diag。
  agent/            MiniAgent loop + prompts + planner/context + run-scoped ScratchPad。
  tools/            Tool 抽象 + Registry + 6 个 coding 工具 + plan/scratchpad 工具。
  sandbox/          进程隔离沙箱：命令策略（policy.py）+ worktree（worktree.py）。【全新】
  benchmark/        case 模型（case.py）+ 现构/注入/参考修复（materialize.py）。【全新】
  graders/          pytest 执行（pytest_run.py）+ Test/Constraint/Patch grader + 合并（result.py）。【全新】
  failure_taxonomy.py  失败自动归因（§9 taxonomy）。
  compare.py        版本对比（improved/regressed/stable + delta）。
  runner.py         CLI 闭环：执行 → 评分 → 归因 → 聚合 → 落盘。
backend/app/        FastAPI 只读 API（读 artifacts/runs/，按需生成 W3-5 报告事实模型）。
frontend/           Vite + React + TS 控制台（实验/轨迹/版本对比/CrossAgent 报告）。
datasets/           mini_store_src（干净源）+ mini_store_suite（9 个 case + defect/hidden）。
                    mini_store_long（8 个 hard case）+ mini_store_multiturn（3 个 staged case）。
scripts/            selfcheck.py（硬门槛）+ compare_runs.py。
artifacts/runs/     每次实验的 trace/patch/grader/failure-tags/summary。不提交。
```

不可越界：
- grader **不**改被测代码、**不**用 LLM 判确定性维度。
- sandbox 是唯一执行不可信命令的地方；命令默认走 `CommandPolicy`（deny-by-default）。
- runner 捕获 patch/changed_files **必须在注入 hidden 测试之前**，否则 hidden 文件会污染 diff。

## 5. 配置与密钥

- provider 用 `.env`（参照 `.env.example`）。`LLM_PROVIDER=deepseek|openai`，OpenAI 兼容。当前复用 DeepSeek key。
- 无 key 时可跑 `reference`/`none` 两档（无 LLM），跑不了 `v1`/`v2`。
- `.env` 不提交；测试全部可离线跑（真实 LLM 冒烟测试用 `RUN_LLM_SMOKE=1` 门控）。

## 6. 常用命令

```bash
# 环境
python3.11 -m venv .venv && .venv/bin/pip install -e ".[dev,api]"

# 质量门禁
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check src/ tests/ scripts/ backend/

# benchmark 硬门槛（9 个 case 必须全 valid）
.venv/bin/python scripts/selfcheck.py
.venv/bin/python scripts/selfcheck.py datasets/mini_store_long
.venv/bin/python scripts/selfcheck.py datasets/mini_store_multiturn

# 闭环
.venv/bin/python -m codeagent_eval.runner --agent reference     # 上界（无 LLM）
.venv/bin/python -m codeagent_eval.runner --agent none          # 下界（无 LLM）
.venv/bin/python -m codeagent_eval.runner --agent v1 --repeats 5 # 需要 key
.venv/bin/python -m codeagent_eval.runner --agent v2 --repeats 5
.venv/bin/python scripts/compare_runs.py <v1_run_dir> <v2_run_dir>

# 控制台
.venv/bin/uvicorn backend.app.main:app --port 8000
cd frontend && npm install && npm run dev   # http://localhost:5173
```

## 7. 数据目录

- `datasets/mini_store_src/` — 干净（正确）源 + 可见测试；提交。
- `datasets/mini_store_suite/` — `suite.json` + `cases/<id>/{defect,hidden}/`；提交。
- `datasets/mini_store_multiturn/` — 3 条多轮 case；`turns/<round-id>/tests/` 只在对应 follow-up 时公开，hidden 仍只在最终评分注入；提交。
- `artifacts/runs/<experiment_id>/` — 每 trial 的 `config.json / trajectory.jsonl / patch.diff / grader-results.json / failure-tags.json` + 顶层 `summary.json/csv`；**不提交**（`.gitignore`）。清理直接 `rm -rf artifacts/runs/<id>`。
  - `config.json` 记录**运行溯源**：`agent / provider / model / temperature / complexity / max_tokens / max_steps / timeout_seconds`；`summary.json` 顶层 `run_config` 记同一套（整个实验恒定）。V1/V2 对比只有在这些一致时才成立（归因纪律），故必须落盘可审计。

## 8. 设计原则（反复回到这几条）

1. **闭环 > 广度**：可执行 → 可复现 → 可验证 → 可定位失败 → 可驱动优化 → 可回归确认。
2. **确定性优先的分级评分**（见 §3 红线）。
3. **私有集无污染**是卖点，要主动说。
4. **scaffold 决定成败**：换 harness、同模型能差很多分（在够难的 case 上）。强模型会把简单 case 打满 —— 如实报告 saturation，用区分度检查（reference/none/V1/V2/reference 四档）证明 pipeline 有效。
