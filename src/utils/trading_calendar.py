from datetime import datetime, date, timedelta, time
import logging
from typing import List, Optional, Set
import holidays
import pytz

class TradingCalendar:
    """
    交易日历管理
    处理节假日和周末，确保新闻正确分组到交易日

    扩展: 增加 map_timestamp_to_trading_day 接口，支持 datetime 输入并根据交易时段策略
    """

    def __init__(self, market: str = 'US', market_tz: str = 'America/New_York'):
        self.market = market
        self.logger = logging.getLogger(__name__)
        self.holidays = self._load_holidays()
        self.market_tz = pytz.timezone(market_tz)
        # 默认交易时段（本地时区）：09:30 - 16:00
        self.market_open = time(9, 30)
        self.market_close = time(16, 0)

    def _load_holidays(self) -> Set[date]:
        """加载节假日"""
        try:
            # 使用holidays库获取美国市场假期
            us_holidays = holidays.UnitedStates(years=range(2020, 2031))
            return set(us_holidays.keys())
        except Exception as e:
            self.logger.error(f"加载节假日失败: {e}")
            # 返回一些已知的主要假期作为备选
            return self._get_fallback_holidays()

    def _get_fallback_holidays(self) -> Set[date]:
        """备选节假日列表"""
        major_holidays = set()
        for year in range(2020, 2031):
            major_holidays.update([
                date(year, 1, 1),   # New Year
                date(year, 1, 15),  # MLK Day (approx)
                date(year, 2, 19),  # Presidents Day (approx)
                date(year, 5, 27),  # Memorial Day (approx)
                date(year, 6, 19),  # Juneteenth
                date(year, 7, 4),   # Independence Day
                date(year, 9, 2),   # Labor Day (approx)
                date(year, 11, 28), # Thanksgiving (approx)
                date(year, 12, 25)  # Christmas
            ])
        return major_holidays

    def is_trading_day(self, check_date: date) -> bool:
        """
        检查是否为交易日
        """
        if check_date.weekday() >= 5:  # 5=Saturday, 6=Sunday
            return False
        if check_date in self.holidays:
            return False
        return True

    def get_next_trading_day(self, from_date: date) -> date:
        current_date = from_date
        while True:
            current_date += timedelta(days=1)
            if self.is_trading_day(current_date):
                return current_date

    def get_previous_trading_day(self, from_date: date) -> date:
        current_date = from_date
        while True:
            current_date -= timedelta(days=1)
            if self.is_trading_day(current_date):
                return current_date

    def adjust_to_trading_day(self, input_date: date) -> date:
        """
        将日期调整到最近的交易日
        如果是非交易日，调整到下一个交易日
        """
        if self.is_trading_day(input_date):
            return input_date
        return self.get_next_trading_day(input_date)

    def map_timestamp_to_trading_day(self, ts: datetime, policy: str = 'after_close_to_next_day') -> str:
        """
        Map a timezone-aware (or naive assumed market tz) timestamp to a trading date string YYYY-MM-DD.

        Policies:
        - 'after_close_to_next_day': timestamps after market close are assigned to next trading day (默认)
        - 'assign_to_same_day': assign to same calendar day if it's a trading day
        - 'before_open_to_same_day': timestamps before market open are assigned to same day (useful for pre-market)
        """
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts)
            except Exception:
                ts = datetime.strptime(ts.split('Z')[0], '%Y-%m-%dT%H:%M:%S')

        # make timezone-aware in market tz
        if ts.tzinfo is None:
            ts_local = self.market_tz.localize(ts)
        else:
            ts_local = ts.astimezone(self.market_tz)

        local_date = ts_local.date()

        # If the date is not a trading day, return next trading day
        if not self.is_trading_day(local_date):
            next_td = self.get_next_trading_day(local_date)
            return next_td.isoformat()

        open_dt = datetime.combine(local_date, self.market_open)
        open_dt = self.market_tz.localize(open_dt)
        close_dt = datetime.combine(local_date, self.market_close)
        close_dt = self.market_tz.localize(close_dt)

        if open_dt <= ts_local <= close_dt:
            return local_date.isoformat()
        else:
            if ts_local > close_dt:
                if policy == 'after_close_to_next_day':
                    next_td = self.get_next_trading_day(local_date)
                    return next_td.isoformat()
                else:
                    return local_date.isoformat()
            if ts_local < open_dt:
                if policy == 'before_open_to_same_day':
                    return local_date.isoformat()
                # default: assign to same calendar day if trading, else next
                return local_date.isoformat()

    def get_trading_days_range(self, start_date: date, end_date: date) -> List[date]:
        trading_days = []
        current_date = start_date
        while current_date <= end_date:
            if self.is_trading_day(current_date):
                trading_days.append(current_date)
            current_date += timedelta(days=1)
        return trading_days

