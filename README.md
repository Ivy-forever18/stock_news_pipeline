# Stock News Pipeline

新闻数据管道项目，用于收集和整理股票相关新闻与经济事件。

## 环境设置

1. 创建 conda 环境（项目需要 Python 3.11）：
```bash
conda create -n ecocal_py311 python=3.11
conda activate ecocal_py311
```

2. 安装依赖：
```bash
pip install -r requirements.txt
```

## 使用说明

运行数据管道：
```bash
python run.py --no-simple  # 使用完整管道
```

可选参数：
- `--days N`: 处理最近 N 天的数据（默认：1）
- `--use-simple`: 使用简化版管道（用于测试）

## 输出

处理后的数据保存在：
- `data/outputs/raw_news.db`: 原始新闻数据
- `data/outputs/trading_day_collection.db`: 按交易日整理的数据集合