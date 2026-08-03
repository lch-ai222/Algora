# HumanEval+/EvalPlus 官方 Smoke Slice 报告 v1

本报告记录 Algora 第一次使用**官方 HumanEval+ 数据与官方 EvalPlus evaluator**完成的资源受限 Smoke Slice。目标是验证标准协议和实操链路，不估计完整 HumanEval+ 能力，不作为排行榜成绩。

## 1. 实施等级与目标

- 实施等级：`smoke_slice`
- Benchmark：HumanEval+
- EvalPlus：固定 `0.3.1`
- 目标：官方数据加载 → 运行前固定抽样 → oracle gate → 模型生成 → 官方 sanitizer → 官方 base/plus evaluator → 原始结果与溯源落盘。
- 非目标：全量 164 题、正式 pass@k 排名、商业 Coding Agent 能力结论。

## 2. 配置

| 项目 | 值 |
|---|---|
| Provider / Model | DeepSeek / `deepseek-v4-flash` |
| Temperature | 0.0 |
| Samples per task | 1 |
| 官方任务数 | 5 |
| 选择方式 | 模型调用前按固定 seed `20260712` 抽样 |
| Task IDs | 16、39、128、139、159 |
| Plus 模式 | 官方 HumanEvalPlus-Mini |
| EvalPlus | 0.3.1 |
| 执行模式 | official local evaluator；无 Docker |
| 并发 | 1 |
| 数据切片 SHA-256 | `8bde728516a3b4ec5966a8edc39a7acb71be10fbab04a2612c86d0ec4efa629e` |

联网生成与代码执行被拆成两个阶段：联网阶段只生成并使用 EvalPlus 的官方 sanitizer 净化样本，不执行生成代码；随后回到受限环境运行官方 evaluator。这样避免为了模型 API 网络权限而扩大生成代码的执行权限。

## 3. Oracle Gate

先把 5 个官方任务的 `prompt + canonical_solution` 写成官方 `samples.jsonl`，再用同一 selected dataset、同一 `--mini` 和同一 evaluator 评分：

| Oracle | Base pass@1 | Plus pass@1 |
|---|---:|---:|
| Canonical solution | 1.00 | 1.00 |

只有 oracle 全过，模型结果才允许进入评分。该 gate 同时发现并促成修复了两个环境兼容问题：

1. 不能对 virtualenv Python 路径调用 `Path.resolve()`，否则符号链接会落到系统解释器并丢失专用环境依赖。
2. EvalPlus 0.3.1 在当前 macOS 的默认 memory rlimit 会报 `current limit exceeds maximum limit`；本次显式设置 `EVALPLUS_MAX_MEMORY_BYTES=-1`。因此本次没有进程内存硬限制，报告必须保留该安全边界。

## 4. 模型结果

| 指标 | 结果 |
|---|---:|
| Base pass@1 | **1.00** |
| Plus pass@1 | **0.80** |
| Base → Plus drop | **0.20** |
| 生成成功 | 5/5 |
| 总 token | 2,872 |
| 生成总时延 | 27,966 ms |
| 估算成本 | 0（当前费率配置为 unknown） |

| Task | Base | Plus | 说明 |
|---|---|---|---|
| HumanEval/16 | pass | pass | distinct characters |
| HumanEval/39 | pass | **fail** | `prime_fib` 在 plus 输入 `n=12` 失败 |
| HumanEval/128 | pass | pass | product of signs |
| HumanEval/139 | pass | pass | special factorial |
| HumanEval/159 | pass | pass | eat |

`HumanEval/39` 的生成实现使用试除到 `sqrt(n)` 的素数判定；原始输入 1–10 全过，而 Plus 增加的 11/12 暴露了大 Fibonacci 数上的计算脆弱性。这里的结论是对本次代码与失败输入的解释，不外推到模型总体性能。

## 5. 方法论结论

1. HumanEval 与 HumanEval+ 不能只报一个“代码生成正确率”；应同时展示 Base、Plus 和 drop。
2. 官方 Plus 输入确实能发现原始测试未覆盖的脆弱实现，本次 5 题中出现 1 个明确案例。
3. Smoke Slice 的首要成果是协议、oracle、环境失败分类和证据链，不是 80% 或 100% 这个点估计。
4. 5 题样本没有总体代表性，也不适合计算置信区间、显著性或与排行榜横向比较。
5. 官方 evaluator 返回码不总能代表子进程健康：oracle 必须同时要求 return code、可解析指标和 Base/Plus=100%。

## 6. 安全、资源与复现边界

- 官方推荐 Docker；本次是本地 evaluator，不是内核级隔离。
- 当前 macOS 兼容设置关闭 EvalPlus memory rlimit；不能把进程隔离描述成安全沙箱。
- 专用 `.venv-evalplus` 约 662 MB；官方数据缓存约 9.1 MB。
- 环境和缓存均不提交，可清理后复现。

复现：

```bash
python3.11 -m venv .venv-evalplus
.venv-evalplus/bin/python -m pip install -e ".[evalplus]"

# 只验证官方 canonical oracle
.venv-evalplus/bin/python scripts/run_evalplus_smoke.py --selfcheck

# 联网阶段：生成和净化，不执行模型代码
.venv-evalplus/bin/python scripts/run_evalplus_smoke.py --generate-only

# 受限环境阶段：人工检查 samples 后再执行
.venv-evalplus/bin/python scripts/run_evalplus_smoke.py \
  --resume artifacts/runs/<evalplus-smoke-run> \
  --allow-local-model-execution
```

清理：

```bash
rm -rf .venv-evalplus .cache/evalplus artifacts/runs/evalplus-smoke-<timestamp>
```

代表性产物：`artifacts/runs/evalplus-smoke-20260712T142204Z/`（不提交）。
