# SWE-bench 接入 + Docker 沙箱设计（C 层）

C 层是「只讲 + 部分落地」。本文说明 SWE-bench 适配器的真实/兼容路径，以及 Docker 沙箱的设计与落地边界。

## 1. SWE-bench 适配器（已落地）

`src/codeagent_eval/benchmark/swebench.py` 读**官方 instance schema**并跑官方判定流程。

官方字段（`SWEBenchInstance` 全部支持，`FAIL_TO_PASS`/`PASS_TO_PASS` 兼容官方的「JSON 字符串编码 list」）：

| 字段 | 含义 | 我们的用法 |
|---|---|---|
| `instance_id` | 实例 id | 结果标识 |
| `repo` / `base_commit` | 目标仓库 + 基准 commit | 检出点 |
| `problem_statement` | issue 文本 | agent 的 instruction |
| `test_patch` | 带来相关测试的 diff | 判定前先 `git apply`（与候选 patch 分离，防作弊） |
| `patch` | 官方 gold 解 | `--mode gold` 的参考解 |
| `FAIL_TO_PASS` | 修复后应由失败转通过的测试 | target |
| `PASS_TO_PASS` | 必须保持通过的测试 | regression |
| `environment_setup_commit` | 环境构建 commit | 真实实例的 env 复现锚点 |

判定：应用 `test_patch` → 应用候选 patch（gold 或 agent 产出）→ 跑 `FAIL_TO_PASS`（须全过）+ `PASS_TO_PASS`（须保持过）→ `resolved`。这与官方 harness 判 resolved 的逻辑一致。

### 兼容样本（已真跑）

`datasets/swebench_compat/`：一个 SWE-bench 格式实例 `textkit__slug-strip-1`，用一个自包含小仓库（`repo_local`）承载，故可在本机端到端跑：
- `python scripts/run_swebench.py --mode gold` → resolved 1/1（应用 gold patch）。
- `python scripts/run_swebench.py --mode agent --agent-version v2` → **MiniAgent(V2) 真实修复并 resolved 1/1**（FAIL_TO_PASS 转通过、PASS_TO_PASS 保持）。

**诚实标注**：这是 **Compatibility Sample**（SWE-bench 格式，非官方排行榜实例）。前端/输出均标注，绝不当排行榜数字。

### 真实 SWE-bench Lite 实例怎么接

同一 schema，只是 `repo_local=None`，需要：
1. `git clone <repo>` 并 `checkout base_commit`（大仓库，需网络）。
2. 复现该仓库在 `environment_setup_commit` 的**运行环境**（各仓库依赖不同：编译扩展、pinned deps、系统库）——这正是官方 harness 用 **Docker per-instance image** 的原因。
3. `materialize_instance` 里把 `repo_local` 分支换成 clone + env 构建（留了 `NotImplementedError` + 指引）。
4. 其余判定流程（apply test_patch → 候选 patch → FAIL_TO_PASS/PASS_TO_PASS）**完全复用**。

即：适配器与判定已就绪，真实实例的成本几乎全在**环境复现**，而非评测逻辑。

## 2. Docker 沙箱（设计 + Dockerfile，未在本机构建）

MVP 沙箱是「临时 git worktree + 子进程 + 命令白名单 + 超时 + 输出截断」（`src/codeagent_eval/sandbox/`）。Docker 是文档化的升级项，用于：

- **更强隔离**：内核级隔离（namespace/cgroup），而非仅命令层拦截。
- **真断网**：`docker run --network none`，而非 MVP 的「拦网络工具」。
- **环境一致性**：跨平台可复现；SWE-bench 官方即要求 Docker 做 per-instance 环境。
- **资源限制**：`--cpus`/`--memory`。

`docker/sandbox.Dockerfile` 给出 per-trial 镜像：`python:3.11-slim` + git + 本包，非 root 用户、不挂载宿主、默认无网。运行：

```bash
docker build -f docker/sandbox.Dockerfile -t codeagent-eval-sandbox .
docker run --rm --network none --cpus 1 --memory 1g codeagent-eval-sandbox \
  python -m codeagent_eval.runner --agent v2 --suite datasets/mini_store_suite --cases bugfix-pricing-tax
```

**落地边界**：本开发环境无 Docker daemon，故未实际 build/run；Dockerfile + 运行契约作为**设计验证**。落地时 `WorktreeSandbox` 的执行层可替换为「在容器内跑」，Planner/工具/grader 契约不变（沙箱是唯一被替换的执行边界，见 `AGENTS.md` §4）。

## 3. 只讲（不建）

Terminal-Bench/Harbor、PostgreSQL 结构化存储、外部 agent adapter、成本看板全量 —— 架构上可画清取舍，本项目不落地。
