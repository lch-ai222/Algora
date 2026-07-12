# Judge Meta-Eval Report v1

「评测评测器本身」——量化 code-review LLM-Judge 与人工 gold 的一致性，决定每个维度是否可作**硬门禁**。方法与叙事拷改自 ft_diag_agent 的 `judge_meta_eval`（参考基线 kappa≈0.62）。

## 方法

- gold 集：`data/judge_gold/code_review_gold.jsonl`，6 个 code-review case、16 个人工标注 item，每个 item 记录一个「正确判定」（`gold_passed`）和所属维度。
- judge：`judge/code_review_judge.py`，结构化输出 + **强制引用**（每条判定必须引用代码原文，引用不在代码中则降 confidence）+ **swap 平均**（正/反序各判一次去位置偏差）+ temperature=0。
- 指标：每维度 agreement rate + Cohen's kappa（`judge/meta_eval.py`，纯函数、可单测）。
- 信任门槛：kappa ≥ 0.6 且 agreement ≥ 0.8 才作硬门禁（Landis & Koch “substantial agreement”）；不达标自动降级为 advisory。
- 复现：`python scripts/run_judge_meta_eval.py`（需 `.env` provider）。

## 结果（DeepSeek v4-flash，本次运行）

| 维度 | n | agreement | kappa | 信任 |
|---|---|---|---|---|
| CORRECTNESS | 6 | 1.00 | 1.00 | gate |
| EDGE_CASES | 5 | 1.00 | 1.00 | gate |
| READABILITY | 5 | 0.80 | **0.62** | gate（贴边） |

## 解读

- **客观维度**（是否正确、是否处理边界）judge 与人工完全一致（kappa=1.0）——这些本就有接近程序 oracle 的判据，judge 可靠。
- **主观维度**（可读性/命名）kappa=0.62，恰在 Landis & Koch “substantial agreement” 下沿、也与 ft_diag 参考基线吻合：judge 在主观维度更易与人工分歧，**风险更高**。当前 0.62 略高于 0.6 阈值故仍作 gate，但若换更主观的 rubric 或更小 gold 集跌破 0.6，`trust_map` 会自动把该维度降级为 advisory（不再当硬门禁）。
- 结论落到评分纪律：**能程序判的绝不用 judge**；judge 只用于无程序 oracle 的质量维度，且必须先用人工 gold 量 kappa、不达标降级。这就是「确定性门禁 + 带引用的 LLM 评审」的混合评分。

## 单条 judge 示例（带引用）

对 `average(nums)`（空列表会 ZeroDivisionError）：
- `Computes the arithmetic mean` → **passed**，引用 `return total / len(nums)`（有效）。
- `Handles an empty input list without crashing` → **failed**，引用 `return total / len(nums)`（有效，正是崩溃点）。
- confidence=1.0，swap 无分歧，无未引用的 pass。

## 局限与下一步

- gold 集小（16 item），kappa 有抖动；扩到 30+ item 更稳。
- 主观维度可加更多对抗样本（好/坏命名、误导性 docstring）压 kappa，演示降级路径。
- 可把 trust_map 接入 runner，让 judge 维度按信任度参与 Strict/质量评分（当前 judge 独立于确定性 grader，未进 Task/Strict 门禁——刻意保守）。
