from datetime import datetime, date, timedelta, time
import logging
from typing import List, Optional, Set
import holidays
import pytz

class TradingCalendar:
    """
    Trading Calendar Management
    Handles holidays and weekends, and provides a timestamp-based mapping to trading days 
    (supports time zones and after-hours strategies).
    """

    def __init__(self, market: str = 'US', market_tz: str = 'America/New_York'):
        self.market = market
        self.logger = logging.getLogger(__name__)
        self.holidays = self._load_holidays()
        self.market_tz = pytz.timezone(market_tz)
        #Default trading hours (local time zone): 09:30 - 16:00
        self.market_open = time(9, 30)
        self.market_close = time(16, 0)

    def _load_holidays(self) -> Set[date]:
        """Holday loading based on market"""
        try:
            us_holidays = holidays.UnitedStates(years=range(2020, 2031))
            return set(us_holidays.keys())
        except Exception as e:
            self.logger.error(f"Failed to load holidays: {e}")
            return self._get_fallback_holidays()

    def _get_fallback_holidays(self) -> Set[date]:
        """alternative holiday list"""
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
        """Check if the date is a trading day"""
        if check_date.weekday() >= 5:  # 5=Sat, 6=Sun
            return False
        
        
        if check_date in self.holidays:
            return False
        
        return True

    def get_next_trading_day(self, from_date: date) -> date:
        """
        Get the next trading day after the given date.
        
        Args:
            from_date: Start Date
            
        Returns:
            Next trading day date
        """
        current_date = from_date
        
        while True:
            current_date += timedelta(days=1)
            if self.is_trading_day(current_date):
                return current_date

    def get_previous_trading_day(self, from_date: date) -> date:
        """
        Get the previous trading day before the given date.
        
        Args:
            from_date: Start Date
            
        Returns:
            Previous trading day date
        """
        current_date = from_date
        
        while True:
            current_date -= timedelta(days=1)
            if self.is_trading_day(current_date):
                return current_date

    def adjust_to_trading_day(self, input_date: date) -> date:
        """Adjust the date to the nearest trading day (non-trading day -> next trading day)"""
        if self.is_trading_day(input_date):
            return input_date
        
        return self.get_next_trading_day(input_date)

    def map_timestamp_to_trading_day(self, ts: datetime, policy: str = 'after_close_to_next_day') -> str:
        """
        Maps timestamps with timestamps to trading days (returns the string 'YYYY-MM-DD').
        
        Policy:
        'after_close_to_next_day' (default): Post-market events are assigned to the next trading day.
        'assign_to_same_day': Force assignment to the same day (if it's a trading day).
        'before_open_to_same_day': Pre-market events are assigned to the current day (if it's a trading day).
        """
        
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except Exception:
                try:
                    ts = datetime.strptime(ts.split("Z")[0], "%Y-%m-%dT%H:%M:%S")
                except Exception:
                    ts = datetime.utcnow()

        # Unified to market time zone
        if ts.tzinfo is None:
            ts_local = self.market_tz.localize(ts)
        else:
            ts_local = ts.astimezone(self.market_tz)

        local_date = ts_local.date()

        # Non-trading day -> Next trading day
        if not self.is_trading_day(local_date):
            next_td = self.get_next_trading_day(local_date)
            return next_td.isoformat()
        
        # Trading day -> Check time against market hours
        open_dt = self.market_tz.localize(datetime.combine(local_date, self.market_open))
        close_dt = self.market_tz.localize(datetime.combine(local_date, self.market_close))

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
                return local_date.isoformat()

    def get_trading_days_range(self, start_date: date, end_date: date) -> List[date]:
        trading_days = []
        current_date = start_date
        
        while current_date <= end_date:
            if self.is_trading_day(current_date):
                trading_days.append(current_date)
            current_date += timedelta(days=1)
        
        return trading_days


if __name__ == "__main__":
    calendar = TradingCalendar()
    
    test_date = date(2024, 1, 1)  
    print(f"{test_date} Is it a trading day? {calendar.is_trading_day(test_date)}")
    
    next_trading = calendar.get_next_trading_day(test_date)
    print(f"Next trading day is: {next_trading}")