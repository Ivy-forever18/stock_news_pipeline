# stock_news_pipeline

面向量化研究与事件驱动策略的**数据 + Agent 一体化工程**：多源新闻/宏观事件采集、标准化、交易日映射、特征化，并通过内置 LLM Agent 闭环支持自然语言交互、因子生成与模拟交易决策。

## 项目意义

这个项目不只是“抓新闻”，而是在解决量化落地中最容易失真的环节：

- 时间语义统一：跨来源、跨时区的新闻时间戳统一映射到交易日，减少盘后/周末/假期导致的标签错位。
- 数据可追溯：原始层与聚合层双持久化（raw + trading-day bundle），方便回放、审计与故障定位。
- 研究到生产的连接：同一份数据可服务于因子研究、事件特征工程、在线评估 API 和策略验证。

## 项目定位

这个项目解决的是量化落地中"最后一公里"的三层问题：

| 层次 | 痛点 | 本项目方案 |
|------|------|-----------|
| 数据层 | 多源时间戳不一致、交易日边界丢信息 | `TradingCalendar` 统一跨时区映射，raw + bundle 双持久化 |
| 工具层 | 工具散乱、上下游耦合 | 统一 `ToolRegistry`，每个工具 schema 标准化，可独立迭代 |
| 决策层 | 研究与执行割裂 | Agent Orchestrator 将自然语言问题编译为工具调用序列，结果结构化输出 |

## 系统架构

```text
  用户 / 前端
      │
      │  POST /api/agent/ask  (自然语言问题)
      ▼
┌─────────────────────────────────────────────────┐
│              AgentOrchestrator                  │
│  ① 生成规划 system prompt（含工具目录）         │
│  ② LLM 输出 JSON tool_calls                    │
│  ③ 代价模型：score = InfoGain / Cost 排序       │
│  ④ 按 max_tool_calls / max_tool_budget 截断    │
│  ⑤ 执行工具，收集 ToolEnvelope 列表            │
│  ⑥ 结果注入 LLM → reflection（可选多轮）       │
│  ⑦ 最终回答 + 结构化 evidence 返回前端         │
└──────────┬──────────────────────────────────────┘
           │ call_tool(name, params)
           ▼
┌─────────────────────────────────────────────────┐
│                 TOOL_REGISTRY                   │
│  NPP.news.query       新闻检索（本地 SQLite）   │
│  NPP.calendar.earnings / macro  财报/宏观日历   │
│  UPQ.stock.daily / intraday     日线/分钟行情   │
│  UPQ.option.chain.query         期权链          │
│  PMB.order.place / status       模拟下单/查单   │
│  PMB.portfolio.snapshot         账户快照        │
│  QLIB.factor.generate           Alpha 因子生成  │
└──────────┬──────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────┐
│              Data & Persistence                 │
│  data_sources/  → pipelines/ → SQLite / JSONL  │
│  MassiveClient（重试 + 退避）                  │
│  FOMC scraper / Nasdaq earnings / Ecocal        │
└─────────────────────────────────────────────────┘
```

## Agent LLM 设计

### 规划-执行-反思三阶段

```
question
   │
   ▼
[Planning]  system prompt 含 10 工具 JSON schema
            → LLM 输出: { assistant_plan, tool_calls[] }
   │
   ▼
[Cost Model] 每个 tool_call 计算 score = InfoGain / Cost
             - InfoGain：问题关键词与工具族匹配 + 参数丰富度
             - Cost：工具族基础代价 + 宽查询惩罚
             → 按预算 (max_tool_calls, max_tool_budget) 截断排序
   │
   ▼
[Execution]  调用工具，返回 ToolEnvelope（含 status/data/error）
   │
   ▼
[Reflection] （可选，max_reflection_rounds 轮）
             system prompt 含当前工具输出
             → LLM 判断: need_more_tools? → 追加调用
   │
   ▼
[Synthesis]  工具结果 + reflection_history → LLM 生成 final_answer
             + 结构化 evidence { items[], stats{total/ok/error} }
```

### 工具代价模型（TOOL_COSTS）

| 工具族 | 基础代价 | 设计理由 |
|--------|---------|---------|
| PMB    | 1.0     | 状态读取，确定性高 |
| NPP    | 1.2     | 本地 SQLite，略有 I/O |
| UPQ    | 1.3     | 外部行情，网络不确定 |
| QLIB   | 2.5     | LLM 子调用，代价最高 |

宽查询（`limit > 20` 或 `symbols` 数组过大）额外叠加惩罚系数，避免预算被单个大查询耗尽。

### 信息增益估算（QUESTION_TOOL_KEYWORDS）

LLM 规划的 `tool_calls` 经代价模型重排后才执行：问题中出现 `"news/headline/event"` → NPP 族增益 +0.7/命中关键词；`"price/bar/ohlc"` → UPQ 族；`"portfolio/order/cash"` → PMB 族；`"factor/alpha/qlib"` → QLIB 族。参数越具体（指定 `symbol`、`portfolio_id`）增益越高。

### 结构化 Evidence 输出

每次 `/api/agent/ask` 返回：

```json
{
  "success": true,
  "result": {
    "final_answer": "...",
    "tool_calls": [...],
    "tool_results": [...],
    "evidence": {
      "items": [
        { "id": "1", "tool": "NPP.news.query", "status": "ok",
          "summary": "count=5", "signal": {"key": "count", "value": 5} }
      ],
      "stats": { "total": 4, "ok": 4, "error": 0 }
    },
    "reflection_history": [...],
    "tool_budget": { "max": 6.0, "used": 4.5, "remaining": 1.5 }
  }
}
```

前端 Evidence Cards 实时渲染每张工具调用结果，并展示预算消耗与反思历史。

## 工程价值

- **可靠采集**：`MassiveClient` 支持 dry-run、重试、指数退避、`requests/urllib` 双栈回退，应对限流与网络抖动。
- **时间语义统一**：`TradingCalendar` 跨时区映射到 NYSE 交易日，含盘后、假期、周末边界处理，减少标签错位。
- **标准化工具接口**：`ToolDef(name, description, fn, parameters)` + `ToolEnvelope(status, data, error)` 统一输入输出 schema，新增工具只需注册一行。
- **预算感知调度**：Agent 不直接执行 LLM 规划，而是经代价模型过滤后执行，防止 QLIB 因子生成等高代价工具无限制触发。
- **可测试性**：P1（工具单元）/ P2（API 端到端）/ P2-Agent（编排回归）三层测试套件，可独立运行，CI 友好。
- **可运维性**：SQLite 落盘、JSONL 按股票分文件、结构化日志、`check_fix.py` 一键诊断导入链路。

## 目录结构

```text
src/
  agent/
    orchestrator.py         # AgentOrchestrator：规划-代价-执行-反思-汇总
    llm_client.py           # 统一 LLM 调用入口（多 provider / 重试）
    generator_qlib.py       # Qlib 因子 LLM 生成 + schema 校验
    generator_qlib_search.py # 生成-评估-去重搜索流程
  api/
    app.py                  # Flask 入口（端口 5002）
    news_api.py             # /api/agent/ask, /api/tools/*, /api/news/*
    factor_eval_api.py      # 因子校验与评估 REST API
  tools/
    registry.py             # TOOL_REGISTRY + call_tool() + get_openai_tools()
  data_sources/             # Massive / FOMC / Ecocal / Nasdaq earnings 适配
  pipelines/                # NewsDataPipeline（normalize + trading-map）
  utils/                    # TradingCalendar、data_models 等
  schemas/base.py           # ToolEnvelope、RunMode 等共享 dataclass
  config/settings.py        # 全局路径 / DB / 日志配置
scripts/
  fetch_massive_news.py
  fetch_nasdaq_earnings.py
  test_massive_api.py
run.py                      # 数据管道主入口
data/outputs/               # SQLite / JSONL / CSV 产物
```

## 快速开始

### 1. 安装依赖（Python 3.11 推荐）

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 启动 Agent + API 服务

```bash
python -m src.api.app
# → http://127.0.0.1:5002
```

浏览器打开后可在首页 **Agent Chat** 卡片中直接提问，例如：
- "查一下 AAPL 最近的新闻"
- "给我 SPY 最近 5 天的日线数据"
- "帮我生成一个动量因子表达式"

### 3. 运行数据管道

```bash
python run.py          # 默认 simple 管道
python run.py --no-simple --days 7
```

### 4. 测试

```bash
make test-p1          # 工具层单元回归（NPP/UPQ/PMB）
make test-p2          # API 端到端（HTTP 请求/响应）
make test-p2-agent    # Agent 编排回归
make test             # 全量
```

## API 参考

### Agent 问答

```
POST /api/agent/ask
Content-Type: application/json

{
  "question": "最近有哪些重要的宏观事件？",
  "model": "deepseek-chat",
  "max_tool_calls": 6,
  "max_tool_budget": 6.0,
  "max_reflection_rounds": 1
}
```

### 工具管理

```
GET  /api/tools/list          # 列出所有注册工具
POST /api/tools/call          # 直接调用单个工具
```

### 因子评估

```bash
python src/api/factor_eval_api.py   # 端口 8080
GET  /health
POST /check       # 表达式可用性验证
POST /eval        # 单因子评估
POST /batch_eval  # 批量评估
```

## 已注册工具（10 个）

| 工具名 | 功能 | 族 / 代价 |
|--------|------|----------|
| `NPP.news.query` | 按股票/关键词/时间查询新闻 | NPP / 1.2 |
| `NPP.calendar.earnings` | 财报日历 | NPP / 1.2 |
| `NPP.calendar.macro` | 宏观经济事件日历 | NPP / 1.2 |
| `UPQ.stock.daily` | 日线 OHLCV | UPQ / 1.3 |
| `UPQ.stock.intraday` | 分钟级盘中行情 | UPQ / 1.3 |
| `UPQ.option.chain.query` | 期权链（IV / 行权价） | UPQ / 1.3 |
| `PMB.order.place` | 模拟账户下单 | PMB / 1.0 |
| `PMB.order.status` | 查询订单状态 | PMB / 1.0 |
| `PMB.portfolio.snapshot` | 账户持仓 & 资产快照 | PMB / 1.0 |
| `QLIB.factor.generate` | 自然语言 → Qlib Alpha 因子表达式 | QLIB / 2.5 |

## 关键数据产物

| 文件 | 内容 |
|------|------|
| `data/outputs/raw_news.db` | 原始新闻/事件明细（SQLite） |
| `data/outputs/trading_day_collection.db` | 交易日聚合结果 |
| `data/outputs/raw_by_symbol/*.jsonl` | 按股票维度原始落盘 |
| `data/outputs/qlib_event_features.csv` | 可直接用于建模的特征 |

## 后续可增强方向

- 接入真实行情 API（替换 synthetic bar 回退）。
- Agent 多轮对话上下文管理（跨次问答记忆）。
- 工具调用并发执行（当前串行）。
- 增加端到端测试覆盖（交易日边界、分页重试、异常恢复）。
- 将 SQLite 层升级为可横向扩展的数据存储（如 Postgres/ClickHouse）。
