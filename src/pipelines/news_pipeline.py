# src/pipelines/news_pipeline.py
import sqlite3
import json
import os
import logging
import hashlib
import traceback
from datetime import datetime, timedelta
from typing import List, Dict, Any

from data_sources.fomc_scraper import FOMCScraper
from data_sources.economic_events import EconomicEventsCollector
from data_sources.stockbench_news import StockBenchNewsLoader
from utils.trading_calendar import TradingCalendar
from utils.data_models import EconomicEvent, NewsItem, TradingDayBundle
from config.settings import DATABASE_CONFIG, OUTPUTS_DIR

# 确保输出目录存在
os.makedirs(OUTPUTS_DIR, exist_ok=True)

class NewsDataPipeline:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.fomc_scraper = FOMCScraper()
        self.economic_collector = EconomicEventsCollector()
        self.stockbench_loader = StockBenchNewsLoader()
        self.trading_calendar = TradingCalendar()
        self.init_db()

    def init_db(self):
        """初始化数据库表结构"""
        try:
            # Initialize raw news database
            conn = sqlite3.connect(DATABASE_CONFIG['raw_news_db'])
            conn.execute('''CREATE TABLE IF NOT EXISTS raw_news
                            (id TEXT PRIMARY KEY,
                             source TEXT,
                             title TEXT,
                             content TEXT,
                             timestamp DATETIME,
                             company_symbol TEXT,
                             url TEXT,
                             content_hash TEXT,
                             raw_data TEXT,
                             created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
            conn.close()
            
            # Initialize trading days database
            conn = sqlite3.connect(DATABASE_CONFIG['trading_day_db'])
            conn.execute('''CREATE TABLE IF NOT EXISTS trading_days
                            (trading_date TEXT PRIMARY KEY, 
                             global_events TEXT, 
                             company_news TEXT,
                             has_major_events BOOLEAN DEFAULT FALSE,
                             created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
            conn.close()
            
            self.logger.info("Database initialization completed")
            
        except Exception as e:
            self.logger.error(f"Database initialization failed: {e}")
            raise

    def insert_to_raw_db(self, news_items: List[Dict], source: str):
        """插入数据到原始新闻数据库"""
        try:
            conn = sqlite3.connect(DATABASE_CONFIG['raw_news_db'])
            cursor = conn.cursor()
            
            for item in news_items:
                if isinstance(item, dict):
                    # 全局事件
                    event_content = item.get('description', '')
                    content_hash = hashlib.md5(event_content.encode('utf-8')).hexdigest()
                    
                    cursor.execute(
                        "INSERT OR REPLACE INTO raw_news (id, source, title, content, timestamp, company_symbol, url, content_hash, raw_data) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            item.get('event_id', str(hash(str(item)))),
                            source,
                            item.get('event_name', ''),
                            event_content,
                            item.get('date', ''),
                            item.get('company', ''),
                            '',
                            content_hash,
                            json.dumps(item, ensure_ascii=False)
                        )
                    )
                else:
                    # NewsItem对象
                    cursor.execute(
                        "INSERT OR REPLACE INTO raw_news (id, source, title, content, timestamp, company_symbol, url, raw_data) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            item.id,
                            item.source,
                            item.title,
                            item.content,
                            item.timestamp.isoformat(),
                            item.company_symbol,
                            item.url,
                            json.dumps(item.raw_data, ensure_ascii=False) if item.raw_data else '{}'
                        )
                    )
            
            conn.commit()
            conn.close()
            self.logger.debug(f"Inserted {len(news_items)} records into raw_news database, source: {source}")
            
        except Exception as e:
            self.logger.error(f"Failed to insert into raw database: {e}")
            if 'conn' in locals():
                conn.close()

    def fetch_company_news(self, start_date: datetime, end_date: datetime) -> List[NewsItem]:
        """Fetch company news"""
        try:
            self.logger.info("Fetching company news...")
            return self.stockbench_loader.fetch_news(start_date, end_date)
        except Exception as e:
            self.logger.error(f"Failed to fetch company news: {e}")
            return []

    def fetch_global_events(self, start_date: datetime, end_date: datetime) -> List[Dict]:
        """获取全球事件（FOMC + 经济事件）"""
        global_events = []
        
        try:
            # 1. 获取 FOMC 事件
            self.logger.info("Fetching FOMC meeting schedule...")
            fomc_events = self.fomc_scraper.fetch_fomc_schedule()
            
            # Filter FOMC events within date range
            for event in fomc_events:
                if start_date.date() <= event.date.date() <= end_date.date():
                    global_events.append({
                        'date': event.date.strftime('%Y-%m-%d'),
                        'event_type': 'FOMC Meeting',
                        'event_name': event.event_name,
                        'source': 'Federal Reserve',
                        'importance': event.importance,
                        'description': event.description
                    })
            
            # 2. Get economic events
            self.logger.info("Fetching economic events...")
            economic_events = self.economic_collector.fetch_events(start_date, end_date)
            
            for event in economic_events:
                global_events.append({
                    'date': event.date.strftime('%Y-%m-%d'),
                    'event_type': 'Economic Event',
                    'event_name': event.event_name,
                    'source': event.source,
                    'importance': event.importance,
                    'country': event.country,
                    'description': event.description
                })
            
            self.logger.info(f"Retrieved {len(global_events)} global events")
            
        except Exception as e:
            self.logger.error(f"Failed to fetch global events: {e}")
        
        return global_events

    def process_company_news(self, start_date: datetime, end_date: datetime) -> Dict[str, List[Dict]]:
        """获取并处理公司新闻"""
        company_news = {}
        
        try:
            # 获取新闻
            news_items = self.fetch_company_news(start_date, end_date)
            
            # 按公司和日期分组
            for news in news_items:
                company = news.company_symbol
                if not company:
                    continue
                    
                date_str = news.timestamp.strftime('%Y-%m-%d')
                if company not in company_news:
                    company_news[company] = []
                
                company_news[company].append({
                    'date': date_str,
                    'event_type': 'Company News',
                    'company': company,
                    'headline': news.title,
                    'summary': news.content,
                    'source': news.source,
                    'url': news.url,
                    'raw_data': news.raw_data
                })
            
            # 记录统计信息
            total_news = sum(len(news) for news in company_news.values())
            companies_with_news = len(company_news)
            self.logger.info(f"获取到 {total_news} 条公司新闻，涉及 {companies_with_news} 家公司")
            
        except Exception as e:
            self.logger.error(f"Failed to process company news: {e}")
        
        return company_news

    def group_by_trading_days(self, global_events: List[Dict], news_items: List[NewsItem], 
                            start_date: datetime, end_date: datetime) -> Dict[str, Dict]:
        """Group data by trading days"""
        trading_day_bundles = {}
        
        try:
            # 1. First group news by company
            company_news = {}
            for news in news_items:
                if news.company_symbol:
                    if news.company_symbol not in company_news:
                        company_news[news.company_symbol] = []
                    company_news[news.company_symbol].append(news)
            
            current_date = start_date
            while current_date <= end_date:
                date_str = current_date.strftime('%Y-%m-%d')
                
                # Adjust to trading day
                trading_day = self.trading_calendar.adjust_to_trading_day(current_date)
                trading_day_str = trading_day.strftime('%Y-%m-%d')
                
                # Initialize trading day bundle
                if trading_day_str not in trading_day_bundles:
                    trading_day_bundles[trading_day_str] = {
                        'global_events': [],
                        'company_news': {},
                        'has_major_events': False
                    }
                
                # Add global events
                day_global_events = [e for e in global_events if e['date'] == date_str]
                trading_day_bundles[trading_day_str]['global_events'].extend(day_global_events)
                
                # Check for major events
                for event in day_global_events:
                    if event.get('importance', 0) >= 3:  # Events with importance >= 3 are major events
                        trading_day_bundles[trading_day_str]['has_major_events'] = True
                
                # Add company news
                for company, news_list in company_news.items():
                    day_company_news = [n for n in news_list if n['date'] == date_str]
                    if company not in trading_day_bundles[trading_day_str]['company_news']:
                        trading_day_bundles[trading_day_str]['company_news'][company] = []
                    trading_day_bundles[trading_day_str]['company_news'][company].extend(day_company_news)
                
                current_date += timedelta(days=1)
            
            self.logger.info(f"Created {len(trading_day_bundles)} trading day bundles")
            
        except Exception as e:
            self.logger.error(f"Failed to group by trading days: {e}")
        
        return trading_day_bundles

    def save_trading_day_bundles(self, trading_day_bundles: Dict[str, Dict]):
        """Save trading day bundles to database"""
        try:
            conn = sqlite3.connect(DATABASE_CONFIG['trading_day_db'])
            cursor = conn.cursor()
            
            for trading_day, bundle in trading_day_bundles.items():
                # 只有当有数据时才保存
                if bundle['global_events'] or any(bundle['company_news'].values()):
                    cursor.execute(
                        """INSERT OR REPLACE INTO trading_days 
                           (trading_date, global_events, company_news, has_major_events) 
                           VALUES (?, ?, ?, ?)""",
                        (trading_day, 
                         json.dumps(bundle['global_events'], ensure_ascii=False),
                         json.dumps(bundle['company_news'], ensure_ascii=False),
                         bundle['has_major_events'])
                    )
            
            conn.commit()
            conn.close()
            
            self.logger.info(f"Saved {len(trading_day_bundles)} trading day bundles")
            
        except Exception as e:
            self.logger.error(f"Failed to save trading day bundles: {e}")
            if 'conn' in locals():
                conn.close()

    def run_pipeline(self, days_back: int = 7):
        """Run the complete data processing pipeline"""
        self.logger.info(f"🚀 Starting news data pipeline, processing last {days_back} days")
        
        try:
            # Calculate date range
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days_back)
            
            self.logger.info(f"Processing date range: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
            
            # 1. Fetch global events
            global_events = self.fetch_global_events(start_date, end_date)
            self.insert_to_raw_db(global_events, 'global')
            
            # 2. Fetch company news
            news_items = self.fetch_company_news(start_date, end_date)
            if news_items:
                self.insert_to_raw_db(news_items, 'company')
            
            # 3. Group by trading days
            trading_day_bundles = self.group_by_trading_days(global_events, news_items, start_date, end_date)
            
            # 4. Save trading day bundles
            self.save_trading_day_bundles(trading_day_bundles)
            
            # 5. Output statistics
            total_global_events = len(global_events)
            total_company_news = len(news_items) if news_items else 0
            
            self.logger.info("📊 Processing complete statistics:")
            self.logger.info(f"  - Global events: {total_global_events}")
            self.logger.info(f"  - Company news: {total_company_news}")
            self.logger.info(f"  - Trading day bundles: {len(trading_day_bundles)}")
            self.logger.info(f"  - Output directory: {OUTPUTS_DIR}")
            
        except Exception as e:
            self.logger.error(f"Pipeline execution failed: {e}")
            raise

# Simple version for testing
class SimpleNewsDataPipeline:
    """Simplified version of the pipeline for quick testing"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.fomc_scraper = FOMCScraper()
        self.economic_collector = EconomicEventsCollector()
        self.trading_calendar = TradingCalendar()
    
    def fetch_global_events(self, start_date: datetime, end_date: datetime) -> List[Dict]:
        """获取全球事件（FOMC + 经济事件）"""
        global_events = []
        
        try:
            # 1. 获取 FOMC 事件
            self.logger.info("Fetching FOMC meeting schedule...")
            fomc_events = self.fomc_scraper.fetch_fomc_schedule()
            
            # Filter FOMC events within date range
            for event in fomc_events:
                if start_date.date() <= event.date.date() <= end_date.date():
                    global_events.append({
                        'date': event.date.strftime('%Y-%m-%d'),
                        'event_type': 'FOMC Meeting',
                        'event_name': event.event_name,
                        'source': 'Federal Reserve',
                        'importance': event.importance,
                        'description': event.description
                    })
            
            # 2. Get economic events
            self.logger.info("Fetching economic events...")
            economic_events = self.economic_collector.fetch_events(start_date, end_date)
            
            for event in economic_events:
                global_events.append({
                    'date': event.date.strftime('%Y-%m-%d'),
                    'event_type': 'Economic Event',
                    'event_name': event.event_name,
                    'source': event.source,
                    'importance': event.importance,
                    'country': event.country,
                    'description': event.description
                })
            
            self.logger.info(f"Retrieved {len(global_events)} global events")
            
        except Exception as e:
            self.logger.error(f"Failed to fetch global events: {e}")
        
        return global_events
    
    def fetch_company_news(self, start_date: datetime, end_date: datetime) -> List[NewsItem]:
        """Fetch company news - returns empty list in simplified version"""
        self.logger.info("Simplified version: skipping company news fetching")
        return []
    
    def group_by_trading_days(self, global_events: List[Dict], news_items: List[NewsItem], 
                            start_date: datetime, end_date: datetime) -> Dict[str, Dict]:
        """Group data by trading days"""
        trading_day_bundles = {}
        
        try:
            current_date = start_date
            while current_date <= end_date:
                date_str = current_date.strftime('%Y-%m-%d')
                
                # Adjust to trading day
                trading_day = self.trading_calendar.adjust_to_trading_day(current_date)
                trading_day_str = trading_day.strftime('%Y-%m-%d')
                
                # Initialize trading day bundle
                if trading_day_str not in trading_day_bundles:
                    trading_day_bundles[trading_day_str] = {
                        'global_events': [],
                        'has_major_events': False
                    }
                
                # Add global events
                day_global_events = [e for e in global_events if e['date'] == date_str]
                trading_day_bundles[trading_day_str]['global_events'].extend(day_global_events)
                
                # Check for major events
                for event in day_global_events:
                    if event.get('importance', 0) >= 3:
                        trading_day_bundles[trading_day_str]['has_major_events'] = True
                
                current_date += timedelta(days=1)
            
            self.logger.info(f"Created {len(trading_day_bundles)} trading day bundles")
            
        except Exception as e:
            self.logger.error(f"Failed to group by trading days: {e}")
        
        return trading_day_bundles
    
    def insert_to_raw_db(self, events: List[Dict], source: str):
        """Simplified version: skip database insertion"""
        self.logger.info(f"Simplified version: skipping database insertion for {len(events)} {source} events")
    
    def run_pipeline(self, days_back: int = 1):
        """Run the news data pipeline"""
        self.logger.info(f"Running simplified pipeline, processing {days_back} days of data")
        
        try:
            self.logger.info(f"🚀 Starting news data pipeline, processing last {days_back} days")
            
            # Calculate date range
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days_back)
            self.logger.info(f"Processing date range: {start_date.date()} to {end_date.date()}")
            
            # 1. Fetch global events
            global_events = self.fetch_global_events(start_date, end_date)
            self.logger.info(f"Retrieved {len(global_events)} global events")
            
            # Insert into database (simplified - just logs)
            self.insert_to_raw_db(global_events, "global_events")
            
            # 2. Fetch company news (simplified - returns empty list)
            news_items = self.fetch_company_news(start_date, end_date)
            self.logger.info(f"Retrieved {len(news_items)} company news items")
            
            # 3. Group data by trading days
            trading_day_bundles = self.group_by_trading_days(global_events, news_items, start_date, end_date)
            self.logger.info(f"Generated {len(trading_day_bundles)} trading day bundles")
            
            # 4. Save data bundle
            output_file = os.path.join(OUTPUTS_DIR, f"trading_bundles_{end_date.strftime('%Y%m%d')}.json")
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump({
                    'metadata': {
                        'start_date': start_date.isoformat(),
                        'end_date': end_date.isoformat(),
                        'generated_at': datetime.now().isoformat()
                    },
                    'trading_days': trading_day_bundles,
                    'global_events_summary': {
                        'total': len(global_events),
                        'by_type': {
                            'FOMC Meeting': len([e for e in global_events if e['event_type'] == 'FOMC Meeting']),
                            'Economic Event': len([e for e in global_events if e['event_type'] == 'Economic Event'])
                        }
                    }
                }, f, ensure_ascii=False, indent=2)
            self.logger.info(f"Saved data bundles to: {output_file}")
            
            return {
                "status": "success",
                "processed_days": days_back,
                "global_events": len(global_events),
                "company_news": len(news_items),
                "trading_days": len(trading_day_bundles),
                "output_file": output_file
            }
            
        except Exception as e:
            self.logger.error(f"Pipeline execution failed: {e}")
            traceback.print_exc()
            return {
                "status": "error",
                "error": str(e)
            }
