# New file: financial_calendar.py
class FinancialCalendar:
    def __init__(self, data_path=None):
        self.events = {}
        if data_path:
            self.load_calendar(data_path)
    
    def load_calendar(self, data_path):
        """Load financial events from CSV."""
        df = pd.read_csv(data_path)
        for _, row in df.iterrows():
            date = pd.to_datetime(row['date']).date()
            event = {
                'type': row['event_type'],
                'importance': row['importance'],
                'affected_assets': row['affected_assets'].split(',')
            }
            if date not in self.events:
                self.events[date] = []
            self.events[date].append(event)
    
    def get_upcoming_events(self, current_date, lookahead=7):
        """Get important events in the next N days."""
        current_date = pd.to_datetime(current_date).date()
        upcoming = []
        
        for i in range(lookahead):
            check_date = current_date + pd.Timedelta(days=i)
            if check_date in self.events:
                for event in self.events[check_date]:
                    upcoming.append({
                        'days_ahead': i,
                        'type': event['type'],
                        'importance': event['importance'],
                        'affected_assets': event['affected_assets']
                    })
        
        return upcoming