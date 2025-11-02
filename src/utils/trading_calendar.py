from datetime import datetime, date, timedelta
import logging
from typing import List, Optional, Set
import holidays

class TradingCalendar:
    """
    交易日历管理
    处理节假日和周末，确保新闻正确分组到交易日
    """
    
    def __init__(self, market: str = 'US'):
        self.market = market
        self.logger = logging.getLogger(__name__)
        self.holidays = self._load_holidays()
    
    def _load_holidays(self) -> Set[date]:
        """加载节假日"""
        try:
            # 使用holidays库获取美国市场假期
            us_holidays = holidays.UnitedStates(years=range(2020, 2026))
            return set(us_holidays.keys())
        except Exception as e:
            self.logger.error(f"加载节假日失败: {e}")
            # 返回一些已知的主要假期作为备选
            return self._get_fallback_holidays()
    
    def _get_fallback_holidays(self) -> Set[date]:
        """备选节假日列表"""
        # 这里列出一些主要的美国市场假期
        major_holidays = set()
        for year in range(2020, 2026):
            major_holidays.update([
                date(year, 1, 1),   # New Year
                date(year, 1, 15),  # MLK Day (third Monday)
                date(year, 2, 19),  # Presidents Day (third Monday)  
                date(year, 5, 27),  # Memorial Day (last Monday)
                date(year, 6, 19),  # Juneteenth
                date(year, 7, 4),   # Independence Day
                date(year, 9, 2),   # Labor Day (first Monday)
                date(year, 11, 28), # Thanksgiving (fourth Thursday)
                date(year, 12, 25)  # Christmas
            ])
        return major_holidays
    
    def is_trading_day(self, check_date: date) -> bool:
        """
        检查是否为交易日
        
        Args:
            check_date: 要检查的日期
            
        Returns:
            如果是交易日返回True
        """
        # 周末不是交易日
        if check_date.weekday() >= 5:  # 5=Saturday, 6=Sunday
            return False
        
        # 节假日不是交易日
        if check_date in self.holidays:
            return False
        
        return True
    
    def get_next_trading_day(self, from_date: date) -> date:
        """
        获取下一个交易日
        
        Args:
            from_date: 起始日期
            
        Returns:
            下一个交易日
        """
        current_date = from_date
        
        while True:
            current_date += timedelta(days=1)
            if self.is_trading_day(current_date):
                return current_date
    
    def get_previous_trading_day(self, from_date: date) -> date:
        """
        获取前一个交易日
        
        Args:
            from_date: 起始日期
            
        Returns:
            前一个交易日
        """
        current_date = from_date
        
        while True:
            current_date -= timedelta(days=1)
            if self.is_trading_day(current_date):
                return current_date
    
    def adjust_to_trading_day(self, input_date: date) -> date:
        """
        将日期调整到最近的交易日
        如果是非交易日，调整到下一个交易日
        
        Args:
            input_date: 输入日期
            
        Returns:
            调整后的交易日
        """
        if self.is_trading_day(input_date):
            return input_date
        
        return self.get_next_trading_day(input_date)
    
    def get_trading_days_range(self, start_date: date, end_date: date) -> List[date]:
        """
        获取日期范围内的所有交易日
        
        Args:
            start_date: 开始日期
            end_date: 结束日期
            
        Returns:
            交易日列表
        """
        trading_days = []
        current_date = start_date
        
        while current_date <= end_date:
            if self.is_trading_day(current_date):
                trading_days.append(current_date)
            current_date += timedelta(days=1)
        
        return trading_days

# 使用示例
if __name__ == "__main__":
    calendar = TradingCalendar()
    
    test_date = date(2024, 1, 1)  # 元旦，应该是假期
    print(f"{test_date} 是交易日吗? {calendar.is_trading_day(test_date)}")
    
    next_trading = calendar.get_next_trading_day(test_date)
    print(f"下一个交易日是: {next_trading}")