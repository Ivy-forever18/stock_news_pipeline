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

## 核心类与方法（快速参考）
- src/pipelines/news_pipeline.py
  - class NewsDataPipeline:
    - init_db(), fetch_global_events(start_date, end_date), fetch_company_news(...), run_pipeline(days_back)
  - class SimpleNewsDataPipeline:
    - 轻量版本，提供 fetch_global_events、group_by_trading_days、run_pipeline 等（用于快速测试）
- src/data_sources/fomc_scraper.py
  - FOMCScraper.fetch_fomc_schedule()
- src/data_sources/economic_events.py
  - EconomicEventsCollector.fetch_events(start_date, end_date, min_importance=...)
  - 可选依赖：ecocal（若未安装会回退到备用方案）
- src/config/settings.py
  - OUTPUTS_DIR, RAW_DATA_DIR, PROCESSED_DATA_DIR 等路径由该文件定义，运行时会自动创建目录

## 输出与位置
- OUTPUTS_DIR（由 src/config/settings.py 定义，默认位于 data/outputs）：
  - trading_bundles_YYYYMMDD.json（Simple 管道会生成）
  - raw/processed DB 文件（完整管道视实现而定）

## 常见问题快速提示
- 导入错误：先运行 python check_fix.py，确认 src 在 PYTHONPATH 中且 data_sources 目录命名正确。
- ecocal 未安装：economic_events 会警告并使用备用方案；如需依赖功能，请 pip install ecocal（或在 requirements 中加入）。