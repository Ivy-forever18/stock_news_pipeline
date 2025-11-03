from datetime import datetime, timedelta
import logging
from typing import List, Optional, Dict, Any
from dataclasses import asdict

from utils.data_models import EconomicEvent
from config.settings import ECON_EVENT_IMPORTANCE_THRESHOLD

class EconomicEventsCollector:
    """
    经济事件收集器 - 使用ecocal库
    备用方案: 如果ecocal不理想 可以切换到其他数据源
    """
    
    def __init__(self, use_fallback: bool = False):
        self.use_fallback = use_fallback
        self.ecocal = None
        self.logger = logging.getLogger(__name__)
        
        if not use_fallback:
            self._init_ecocal()
    
    def _init_ecocal(self):
        """初始化ecocal库"""
        try:
            from ecocal import Calendar
            self.ecocal_cls = Calendar
            self.logger.info("ecocal库初始化成功")
        except ImportError:
            self.logger.warning("ecocal库未安装，使用备用方案")
            self.use_fallback = True
        except Exception as e:
            self.logger.error(f"ecocal初始化失败: {e}")
            self.use_fallback = True
    
    def fetch_events(self, 
                    start_date: datetime, 
                    end_date: datetime,
                    min_importance: int = 2,
                    countries: Optional[List[str]] = None) -> List[EconomicEvent]:
        """
        获取经济事件
        """
        if self.use_fallback or not hasattr(self, 'ecocal_cls'):
            return self._fetch_events_fallback(start_date, end_date, min_importance)
        return self._fetch_events_ecocal(start_date, end_date, min_importance, countries)
    
    def _fetch_events_ecocal(self, 
                           start_date: datetime, 
                           end_date: datetime,
                           min_importance: int,
                           countries: Optional[List[str]] = None) -> List[EconomicEvent]:
        """使用ecocal库获取经济事件"""
        try:
            # 创建日历对象并获取 DataFrame
            cal = self.ecocal_cls(start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'))
            df = cal.calendar
            if df is None or df.empty:
                self.logger.warning("ecocal返回空日历")
                return []
            economic_events = []
            for _, row in df.iterrows():
                # ecocal字段: Id, Start, Name, Impact, Currency
                event_id = row.get('Id', '')
                event_name = row.get('Name', 'Unknown Event')
                event_date = row.get('Start')
                country = row.get('Currency', 'Unknown')
                importance = row.get('Impact', 'NONE')
                description = ''  # ecocal无详细描述字段
                # Impact字符串转分数
                impact_map = {'HIGH': 3, 'MEDIUM': 2, 'LOW': 1, 'NONE': 0}
                imp = impact_map.get(str(importance).upper(), 0)
                if imp < min_importance:
                    continue
                # 国家过滤（用货币字段近似）
                if countries and country not in countries:
                    continue
                # 日期解析
                try:
                    if isinstance(event_date, str):
                        # 支持 ecocal 返回的 MM/DD/YYYY 格式
                        try:
                            event_date = datetime.strptime(event_date[:10], '%m/%d/%Y')
                        except Exception:
                            event_date = datetime.strptime(event_date[:10], '%Y-%m-%d')
                    elif hasattr(event_date, 'to_pydatetime'):
                        event_date = event_date.to_pydatetime()
                except Exception:
                    continue
                event = EconomicEvent(
                    event_id=event_id or f"econ_{country}_{event_date.strftime('%Y%m%d')}_{abs(hash(event_name)) % 10000:04d}",
                    date=event_date,
                    event_name=event_name,
                    country=country,
                    importance=imp,
                    source="ecocal",
                    description=description
                )
                economic_events.append(event)
            self.logger.info(f"从ecocal获取 {len(economic_events)} 个经济事件")
            return economic_events
        except Exception as e:
            self.logger.error(f"ecocal获取事件失败: {e}")
            return self._fetch_events_fallback(start_date, end_date, min_importance)
    
    def _parse_ecocal_event(self, 
                          event_data: Dict[str, Any],
                          min_importance: int,
                          countries: Optional[List[str]] = None) -> Optional[EconomicEvent]:
        """解析ecocal事件数据"""
        try:
            # 根据ecocal的实际数据结构调整这些字段
            # 这里是一个示例映射，需要根据实际情况调整
            
            # 提取事件信息
            event_name = event_data.get('event', 'Unknown Event')
            event_date_str = event_data.get('date', '')
            country = event_data.get('country', 'Unknown')
            importance = event_data.get('importance', 1)
            
            # 重要性过滤
            if importance < min_importance:
                return None
            
            # 国家过滤
            if countries and country not in countries:
                return None
            
            # 解析日期
            try:
                event_date = datetime.strptime(event_date_str, '%Y-%m-%d')
            except (ValueError, TypeError):
                self.logger.warning(f"无法解析事件日期: {event_date_str}")
                return None
            
            # 创建经济事件对象
            event = EconomicEvent(
                event_id=f"econ_{country}_{event_date.strftime('%Y%m%d')}_{hash(event_name) % 10000:04d}",
                date=event_date,
                event_name=event_name,
                country=country,
                importance=importance,
                source="ecocal",
                description=event_data.get('description', '')
            )
            
            return event
            
        except Exception as e:
            self.logger.debug(f"解析ecocal事件失败: {e}")
            return None
    
    def _fetch_events_fallback(self, 
                             start_date: datetime, 
                             end_date: datetime,
                             min_importance: int) -> List[EconomicEvent]:
        """
        备用方案获取经济事件
        可以集成其他经济日历API或网页抓取
        """
        self.logger.info("使用备用方案获取经济事件")
        
        # TODO: 实现备用数据源
        # 可能的备选:
        # 1. Investing.com经济日历
        # 2. Forex Factory经济日历  
        # 3. 其他经济数据API
        
        # 暂时返回空列表
        return []

# 测试函数
def test_ecocal_integration():
    """测试ecocal集成"""
    import logging
    logging.basicConfig(level=logging.INFO)
    
    collector = EconomicEventsCollector()
    
    # 测试最近30天的事件
    end_date = datetime.now()
    start_date = end_date - timedelta(days=30)
    
    events = collector.fetch_events(start_date, end_date, min_importance=2)
    
    print(f"获取到 {len(events)} 个经济事件:")
    for event in events[:5]:  # 只显示前5个
        print(f"  {event.date.strftime('%Y-%m-%d')}: {event.event_name} ({event.country}, 重要性:{event.importance})")

if __name__ == "__main__":
    test_ecocal_integration()