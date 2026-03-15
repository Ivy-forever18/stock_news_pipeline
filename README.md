# stock_news_pipeline

轻量说明与快速上手，基于仓库当前代码自动生成 —— 包含模块路径、常用脚本与示例命令。

## 主要目录（关键模块）
- src/
  - data_sources/         # 数据源（fomc_scraper.py, economic_events.py, stockbench_news.py 等）
  - pipelines/            # 管道实现（news_pipeline.py 包含 NewsDataPipeline 与 SimpleNewsDataPipeline）
  - utils/                # 工具（trading_calendar、data_models 等）
  - config/               # 配置（settings.py）
- scripts/ 或 根目录脚本:
  - run.py                # 启动入口：选择简化或完整管道并运行
  - check_fix.py          # 导入/目录检查脚本（帮助定位命名/导入问题）
- data/                   # 运行时生成的数据目录（由 settings.py 中的 PATH 创建）
- requirements.txt

## 快速开始（3 步）
1. 克隆并进入项目
   git clone https://github.com/Ivy-forever18/stock_news_pipeline.git
   cd stock_news_pipeline

2. 建议使用虚拟环境（Python3.11 与仓库代码兼容）
   python -m venv .venv
   source .venv/bin/activate   # macOS/Linux
   .venv\Scripts\activate      # Windows
   pip install -r requirements.txt

3. 运行示例
   - 使用默认（简化）管道（生成 outputs 下 JSON/DB）
     python run.py
   - 使用完整管道（解析 --no-simple）
     python run.py --no-simple
   - 指定回溯天数（处理历史 N 天）
     python run.py --days 7

## 常用脚本说明
- run.py
  - 参数：
    --use-simple / --no-simple：选择 SimpleNewsDataPipeline（默认）或完整 NewsDataPipeline
    --days N：向后处理 N 天（默认 1）
  - 运行逻辑：初始化 pipeline，调用 pipeline.run_pipeline(days_back)

- check_fix.py
  - 用于检查 src 路径与核心导入是否正常（fomc_scraper、economic_events、pipelines.news_pipeline、config.settings）
  - 运行：python check_fix.py

## Massive API 测试

- **测试脚本**: 项目包含一个小脚本用于快速验证 Massive API 连通性：`scripts/test_massive_api.py`。
  - 用法（dry-run / 无 key）:
    ***
    # stock_news_pipeline

    项目简介与使用说明

    本仓库实现了一个面向股票新闻与宏观事件的数据采集与处理管道（ETL）。系统目标是可靠地从外部新闻 API 与自建爬虫收集数据，进行统一规范化、基于交易日进行聚合，并输出可供量化研究或下游模型直接使用的结构化数据包。

   Highlight
    - 可靠的数据摄取：容错 HTTP 客户端 `MassiveClient`，支持 `requests`/`urllib` 回退、重试与指数退避；内置 dry-run 模式便于本地开发与 CI。
    - 时区与交易日智能映射：`TradingCalendar` 支持时区感知的时间戳映射、盘前盘后策略以及自动跳过周末/假期（适合美股/全球市场扩展）。
    - 标准化与聚合：统一多源新闻字段（`normalize_article`），并在 `news_pipeline` 中将全局事件与公司新闻按交易日聚合为 bundle（JSON/SQLite 输出）。
    - 可演示与工程化：提供快速测试脚本 `scripts/test_massive_api.py`、模块化代码结构、易于扩展的分页与数据源接口。
    - 关键技能：Python、API 设计与容错（重试/回退/速率限制处理）、时区/交易日逻辑、ETL 管道设计、SQLite 数据持久化。

    快速开始（建议在 macOS/Linux 下执行）
    1. 克隆仓库并创建虚拟环境
    ```bash
    git clone https://github.com/Ivy-forever18/stock_news_pipeline.git
    cd stock_news_pipeline
    python -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    ```

    2. 运行基本管道（简化模式）
    ```bash
    python run.py
    ```

    3. 测试 Massive API 连通性（dry-run 或使用真实 key）
    ```bash
    # dry-run（不需要密钥）
    python3 scripts/test_massive_api.py

    # 使用临时密钥进行真实请求（只在该命令中注入）
    MASSIVE_API_KEY=your_key_here python3 scripts/test_massive_api.py
    ```

    项目结构（简要）
    - `src/data_sources/`：外部数据源客户端与爬虫适配器（`massive_client.py`, `fomc_scraper.py`, `massive_news.py` 等）。
    - `src/pipelines/`：数据管道实现（`news_pipeline.py` 包含聚合、持久化逻辑）。
    - `src/utils/`：公共工具（`trading_calendar.py`, `data_models.py` 等）。
    - `scripts/`：辅助脚本（`test_massive_api.py`）。

    开发与测试建议
    - 本地开发先使用 dry-run 验证逻辑，无需真实 API key。将 `MASSIVE_API_KEY` 暂时注入命令行以验证线上行为。
    - 建议为关键模块（`MassiveClient`, `TradingCalendar`, `news_pipeline.group_by_trading_days`）添加单元测试，覆盖时区边界、盘后映射与分页逻辑。

    许可证与贡献
    - 本项目采用 MIT 许可证（如需更改，请在根目录添加 LICENSE 文件）。
    - 欢迎通过 Pull Request 提交改进或 issue 报告 bug。

    ***
