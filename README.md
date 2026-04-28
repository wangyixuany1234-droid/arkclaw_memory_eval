# Arkclaw 记忆功能自动化评估流水线

本项目提供了一套完整的自动化评估方案，用于测试与分析 Arkclaw 记忆功能的效果。它实现了从用例解析、记忆注入（ingest）、问答（qa）、结果评判（judge）到生成可视化报表的全流程。

## 核心特性

- **端到端自动化**：从 CSV 用例输入到静态网页报表输出，全程自动化。
- **可配置与可筛选**：支持通过 YAML 文件和命令行参数配置 API 端点、筛选用例、控制执行步骤。
- **多维度评估**：结合 LLM Judge 与硬规则（Rule-based）进行双重打分，提供全面的失败归因。
- **丰富的可观测性**：详细记录每轮对话的耗时、Token 用量（若可用）以及 Arkclaw 网关返回的原始事件流，便于问题回溯与性能分析。
- **交互式报表**：生成包含多维筛选、指标卡、趋势图与可展开明细的静态 HTML 报表，直观展示评估结果。
- **降级容错**：在未配置 API 密钥或网关不可达的情况下，框架仍可空跑并生成结构完整但无实际结果的报告，便于前端验证与框架调试。

## 项目结构

```
arkclaw_memory_eval/
├── eval/                   # Python 包核心代码
│   ├── __init__.py
│   ├── arkclaw_client.py   # Arkclaw 网关客户端
│   ├── config.py           # 配置加载模块
│   ├── csv_loader.py       # CSV 用例解析与编排
│   ├── judge.py            # LLM Judge 与结果合成
│   ├── noise_generator.py  # D04 场景噪声对话生成
│   ├── pipeline.py         # 评估流水线主逻辑
│   ├── rules.py            # Rule-based 打分
│   ├── run.py              # 命令行入口
│   └── types.py            # 数据结构定义
├── report/                 # 静态报表目录（用于部署）
│   ├── index.html
│   ├── app.js
│   ├── summary.csv         # 报表数据源
│   └── results.jsonl       # 报表数据源
├── result/                 # 原始输出数据目录
│   ├── cases/              # 每个 case 的详细 JSON 产物
│   ├── results.jsonl       # 所有 case 的详细结果
│   └── summary.csv         # 所有 case 的摘要统计
├── config.example.yaml     # 配置文件模板
├── requirements.txt        # Python 依赖
└── README.md               # 本文档
```

## 快速开始

### 1. 环境准备

- Python 3.8+
- 安装依赖：
  ```bash
  pip install -r requirements.txt
  ```

### 2. 配置

评估框架依赖 Arkclaw 网关和豆包 LLM Judge 两个外部服务。请通过环境变量或配置文件提供认证信息。

#### 环境变量（推荐）

这是最安全和灵活的方式，不会将密钥硬编码在文件中。

```bash
# Arkclaw 网关配置
export ARKCLAW_BASE_URL="https://your-arkclaw-gateway-url/v1"
export ARKCLAW_API_KEY="sk-arkclaw-xxxxxxxx"

# 豆包 LLM Judge 配置
# 若豆包有独立 endpoint，使用 DOUBAO_*
export DOUBAO_BASE_URL="https://your-doubao-gateway-url/v1"
export DOUBAO_API_KEY="sk-doubao-xxxxxxxx"
# 若使用与通用模型相同的 endpoint，可配置 OPENAI_*
# export OPENAI_BASE_URL="https://your-openai-compatible-url/v1"
# export OPENAI_API_KEY="your-api-key"
```

#### 配置文件（可选）

你也可以创建一个 `config.yaml` 文件来管理配置。可以将 `config.example.yaml` 复制一份并修改。

```yaml
# config.yaml
arkclaw:
  base_url: "https://your-arkclaw-gateway-url/v1"
  api_key: "sk-arkclaw-xxxxxxxx"

doubao:
  base_url: "https://your-doubao-gateway-url/v1"
  api_key: "sk-doubao-xxxxxxxx"
```

**配置优先级**：环境变量 > `config.yaml` > 代码内默认值。

### 3. 执行评估

使用 `eval.run` 模块启动评估（需在 `arkclaw_memory_eval/` 目录下执行）。

**基础示例**：

运行所有用例，执行 ingest、qa、judge 全流程，并为本次运行打上标签。

```bash
python -m eval.run \
    --cases "../Lance Memory测试用例集_partial_single_table.csv" \
    --iteration-tag "2026-04-18-full-run"
```

**带筛选的示例**：

仅运行 P0 和 P1 优先级的“对话记忆”和“任务执行记忆”用例，且只执行 qa 和 judge 步骤。

```bash
python -m eval.run \
    --cases "../Lance Memory测试用例集_partial_single_table.csv" \
    --iteration-tag "2026-04-18-p0-p1-qa-only" \
    --filter-priority "P0,P1" \
    --filter-type "对话记忆,任务执行记忆" \
    --steps "qa,judge"
```

### 4. 查看结果

运行结束后，产物会生成在 `result/` 目录。同时，用于部署的静态文件会准备在 `report/` 目录。

直接在浏览器中打开 `report/index.html` 即可查看交互式报表。

## 命令行参数详解

- `--cases` (必需): 指向用例集的 CSV 文件路径。
- `--iteration-tag` (必需): 为本次评估运行指定一个唯一的、可读的标签，例如 `2026-04-18-feature-x-test`。该标签会记录在所有产物中，用于报表筛选和多轮结果对比。
- `--filter-priority`: 按优先级筛选用例，多个值用逗号分隔 (e.g., `P0,P1`)。
- `--filter-type`: 按记忆类型筛选，多个值用逗号分隔 (e.g., `对话记忆,工具结果记忆`)。
- `--filter-time`: 按时间维度筛选，多个值用逗号分隔。
- `--steps`: 控制执行的步骤，默认为 `ingest,qa,judge`。可按需选择 `ingest`、`qa`、`judge` 的任意组合。
- `--new-session`: 控制何时启用新会话。
  - `ingest` (默认): 仅在 `ingest` 的第一轮强制开启新会话。
  - `qa`: 在 `qa` 步骤前强制开启新会话（用于测试无注入直接问答的场景）。
  - `none`: 不主动控制新会话，依赖 Arkclaw 的默认行为。
- `--output-dir`: 指定结果输出目录，默认为 `result`。
- `--config`: 指定 YAML 配置文件路径。

## 降级与常见问题

- **未配置 API 密钥或网关不可达会怎样？**
  - 流水线依然可以运行，但 `arkclaw_client` 和 `llm_judge_client` 会处于禁用状态。
  - **Arkclaw 调用**：不会发生真实的网络请求。返回的 `assistant_content` 为 `null`。
  - **LLM Judge**：不会调用豆包模型。`llm` 部分的分数和结论为 `null`。
  - **最终结果**：
    - `results.jsonl` 中 `arkclawEnabled` 和 `llmJudgeEnabled` 字段会是 `false`。
    - `summary.csv` 中的分数将仅依赖规则分（Rule-based Judge），且失败率可能较高（因为没有真实回答）。
    - 报表会正常渲染，并在“数据状态”卡片中明确提示“Arkclaw 网关：未配置”和“LLM Judge：未启用”。

- **如何生成 D04 场景的噪声对话？**
  - `csv_loader.py` 在解析用例时，会特别识别 `case_id` 为 `D04` 且描述中包含“15 轮”等关键词的用例。
  - `noise_generator.py` 会使用 `config.py` 中 `NoiseConfig` 定义的主题库，生成包含一句核心记忆（“我下周要参加会计考试”）和 14 句无关话题的对话列表。
  - 你可以在 `config.yaml` 中自定义 `noise.topics` 列表来改变噪声对话的内容。

## 结果文件说明

### `result/results.jsonl`

每行一个 JSON 对象，对应一个用例的完整可观测性数据。

- `case_meta`: 用例的元信息（ID, 类型, 场景等）。
- `sessionKey`: 本次运行为该用例生成的唯一会话标识。
- `dialogue`: 包含所有 `ingest` 和 `qa` 轮次的 user/assistant 对话记录。
- `rawEvents`: Arkclaw 客户端记录的原始事件数组，包括请求、最终响应、错误等。
  - `eventsSummary`: 对 `rawEvents` 的归纳，提取了 `runId`、`sessionKey`、是否出错等关键信息。
- `judge`: 评判结果。
  - `final_label`: `pass` / `fail` / `partial`。
  - `llm`: LLM Judge 的详细输出（分数、理由、命中/漏掉事实等）。
  - `rule`: 规则 Judge 的详细输出（是否空回复、超时、包含拒答/幻觉等）。
  - `failure_reasons`: 结合两者归因出的失败原因列表。
- `timing`: 各阶段耗时（ms）。
- `tokens`: 各阶段 Token 消耗。

### `result/summary.csv`

适合用表格工具直接查看的摘要数据。

- `caseId`, `title`, `memoryType`, ...: 用例元信息。
- `success`: 最终评判结论。
- `avgScore`, `llmScore`, `ruleScore`: 平均分、LLM 分、规则分。
- `passCount`, `failCount`, `turnCount`: 统计信息。
- `iterationTag`: 本次运行的迭代标签。
- `ingestMs`, `qaMs`, `judgeMs`, `totalMs`: 耗时统计。
- `...Tokens`: 各阶段 Token 统计。
- `llmJudgeEnabled`: LLM Judge 在本次运行中是否启用。

### `result/cases/*.json`

每个用例的详细 JSON 产物，内容与 `results.jsonl` 中的单行记录相同，便于按用例 ID 单独排查问题。

## 报表说明

`report/index.html` 提供了一个无需后端服务的纯静态交互式报表。

- **数据源**: 报表通过 JavaScript 直接读取同目录下的 `summary.csv` 和 `results.jsonl` 文件。
- **筛选**: 支持按优先级、记忆类型、时间维度、迭代标签、LLM Judge 启用状态进行多维交叉筛选，所有图表和表格都会实时响应。
- **指标卡**: 动态展示筛选后用例的总体通过率、平均分等核心指标。
- **图表分析**:
  - **通过率图**: 按记忆类型和优先级两个维度展示通过率，快速定位薄弱环节。
  - **耗时分布**: 展示 ingest / qa / judge 各阶段的平均耗时。
  - **失败归因**: 统计所有失败用例的原因分布，如 `empty_response`, `missed_mustMention`, `llm_low_score` 等。
- **明细表**:
  - 展示筛选后所有用例的摘要信息。
  - 点击每行末尾的“展开”按钮，可以查看该用例的**详细对话记录**、**Judge 评判 JSON** 和 **Arkclaw 原始事件摘要**，为深度分析提供便利。

---
