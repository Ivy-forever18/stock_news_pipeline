"""
StockBench 新闻数据加载器
从 storage/cache/news_by_day 目录加载每日新闻数据
支持日期范围过滤、去重、入库
"""
import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Set
import hashlib

from utils.data_models import NewsItem
from config.settings import STOCKBENCH_DATA_PATH, DATABASE_CONFIG

class StockBenchNewsLoader:
    """StockBench 新闻加载器
    - 按日期读取新闻 JSON 文件
    - 解析为 NewsItem 实例
    - 支持去重和数据库存储
    """
    
    def __init__(self, data_path: Optional[str] = None):
        """
        Args:
            data_path: StockBench新闻数据目录，默认使用配置中的STOCKBENCH_DATA_PATH
        """
        self.data_path = Path(data_path or STOCKBENCH_DATA_PATH)
        if not self.data_path.exists():
            raise ValueError(f"StockBench数据目录不存在: {self.data_path}")
        
        self.db_path = Path(DATABASE_CONFIG['raw_news_db'])
        self.logger = logging.getLogger(__name__)
        self._init_db()
    
    def _init_db(self):
        """初始化新闻数据库表"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        with sqlite3.connect(self.db_path) as conn:
            c = conn.cursor()
            # 原始新闻表
            c.execute("""
            CREATE TABLE IF NOT EXISTS raw_news (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp DATETIME NOT NULL,
                company_symbol TEXT,
                url TEXT,
                content_hash TEXT NOT NULL,
                raw_data TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """)
            # 索引
            c.execute("CREATE INDEX IF NOT EXISTS idx_news_timestamp ON raw_news(timestamp)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_news_company ON raw_news(company_symbol)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_news_content_hash ON raw_news(content_hash)")
            conn.commit()
    
    def fetch_news(self, 
                  start_date: datetime, 
                  end_date: datetime,
                  force_reload: bool = False) -> List[NewsItem]:
        """获取指定日期范围的新闻
        
        Args:
            start_date: 开始日期
            end_date: 结束日期
            force_reload: 是否强制重新加载（忽略已入库数据）
        
        Returns:
            新闻列表 (已去重)
        """
        if not force_reload:
            # 先尝试从数据库加载
            stored = self._load_from_db(start_date, end_date)
            if stored:
                self.logger.info(f"从数据库加载 {len(stored)} 条新闻")
                return stored
        
        # 从文件加载并解析
        news_items: List[NewsItem] = []
        content_hashes: Set[str] = set()
        
        current = start_date
        while current <= end_date:
            date_str = current.strftime('%Y-%m-%d')
            
            # 遍历所有公司目录
            for company_dir in self.data_path.iterdir():
                if not company_dir.is_dir():
                    continue
                    
                company_symbol = company_dir.name
                news_file = company_dir / f"{date_str}.json"
                
                if news_file.exists():
                    try:
                        with open(news_file, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                            
                        # 解析每条新闻
                        items = data.get('items', []) if isinstance(data, dict) else data
                        for item in items:
                            try:
                                # 添加公司代码
                                if isinstance(item, dict):
                                    item['symbol'] = company_symbol
                                
                                news = self._parse_news_item(item)
                                if not news:
                                    continue
                                    
                                # 去重 (基于内容哈希)
                                content_hash = self._compute_content_hash(news)
                                if content_hash in content_hashes:
                                    continue
                                content_hashes.add(content_hash)
                                
                                news_items.append(news)
                            except Exception as e:
                                self.logger.warning(f"解析新闻失败 [{company_symbol}]: {e}")
                                continue
                                
                    except Exception as e:
                        self.logger.error(f"读取新闻文件失败 {news_file}: {e}")
            
            current = current + timedelta(days=1)
        
        # 入库
        if news_items:
            self._save_to_db(news_items)
            self.logger.info(f"解析并入库 {len(news_items)} 条新闻")
        
        return news_items
    
    def _parse_news_item(self, data: Dict) -> Optional[NewsItem]:
        """解析单条新闻数据为NewsItem对象"""
        try:
            # 必需字段
            news_id = str(data.get('id', ''))
            title = data.get('title', '').strip()
            content = data.get('description', data.get('content', '')).strip()
            timestamp_str = data.get('published_utc', data.get('timestamp', ''))
            
            if not (news_id and title and content and timestamp_str):
                return None
            
            # 时间解析
            try:
                if isinstance(timestamp_str, (int, float)):
                    timestamp = datetime.fromtimestamp(timestamp_str)
                else:
                    # 尝试多种格式解析
                    try:
                        timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                    except Exception:
                        try:
                            timestamp = datetime.strptime(timestamp_str, '%Y-%m-%dT%H:%M:%S')
                        except Exception:
                            return None
            except Exception:
                return None
            
            return NewsItem(
                id=news_id,
                source="stockbench",
                title=title,
                content=content,
                timestamp=timestamp,
                company_symbol=data.get('symbol'),
                url=data.get('url'),
                raw_data=data
            )
        except Exception as e:
            self.logger.debug(f"新闻解析失败: {e}")
            return None
    
    def _compute_content_hash(self, news: NewsItem) -> str:
        """计算新闻内容哈希，用于去重"""
        text = f"{news.title}\n{news.content}".strip().lower()
        return hashlib.md5(text.encode('utf-8')).hexdigest()
    
    def _save_to_db(self, news_items: List[NewsItem]):
        """保存新闻到数据库"""
        with sqlite3.connect(self.db_path) as conn:
            c = conn.cursor()
            for news in news_items:
                content_hash = self._compute_content_hash(news)
                try:
                    c.execute("""
                    INSERT OR REPLACE INTO raw_news (
                        id, source, title, content, timestamp, 
                        company_symbol, url, content_hash, raw_data
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        news.id,
                        news.source,
                        news.title,
                        news.content,
                        news.timestamp.isoformat(),
                        news.company_symbol,
                        news.url,
                        content_hash,
                        json.dumps(news.raw_data)
                    ))
                except Exception as e:
                    self.logger.warning(f"保存新闻失败 {news.id}: {e}")
            conn.commit()
    
    def _load_from_db(self, start_date: datetime, end_date: datetime) -> List[NewsItem]:
        """从数据库加载指定日期范围的新闻"""
        with sqlite3.connect(self.db_path) as conn:
            c = conn.cursor()
            c.execute("""
            SELECT id, source, title, content, timestamp,
                   company_symbol, url, raw_data
            FROM raw_news
            WHERE timestamp >= ? AND timestamp <= ?
            ORDER BY timestamp
            """, (start_date.isoformat(), end_date.isoformat()))
            
            news_items = []
            for row in c.fetchall():
                try:
                    raw_data = json.loads(row[7]) if row[7] else {}
                    news = NewsItem(
                        id=row[0],
                        source=row[1],
                        title=row[2],
                        content=row[3],
                        timestamp=datetime.fromisoformat(row[4].replace('Z', '+00:00')),
                        company_symbol=row[5],
                        url=row[6],
                        raw_data=raw_data
                    )
                    news_items.append(news)
                except Exception as e:
                    self.logger.warning(f"加载新闻失败 {row[0]}: {e}")
            
            return news_items

# 测试函数
def test_stockbench_news():
    """测试StockBench新闻加载"""
    import logging
    logging.basicConfig(level=logging.INFO)
    
    # 初始化加载器
    loader = StockBenchNewsLoader()
    
    # 测试特定日期的新闻
    start_date = datetime(2025, 1, 1)
    end_date = datetime(2025, 1, 2)
    
    news = loader.fetch_news(start_date, end_date)
    
    print(f"\n获取到 {len(news)} 条新闻:")
    for n in news[:5]:  # 只显示前5条
        print(f"  [{n.timestamp.strftime('%Y-%m-%d %H:%M')}] {n.title} ({n.company_symbol})")

if __name__ == "__main__":
    test_stockbench_news()