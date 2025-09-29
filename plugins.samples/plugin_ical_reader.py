"""
iCal Calendar Reader Plugin

This plugin reads iCalendar (.ics) files from configured URLs and provides
calendar event information to the main application.

Configuration:
- Create a 'calendars_config.json' file in the same directory as this plugin
- Use the provided calendars_config.json.sample as a template

Dependencies:
- httpx: HTTP client for fetching calendar data
- icalendar: For parsing iCalendar files
- python-dateutil: For datetime parsing
- pytz: For timezone handling

Install with: pip install httpx icalendar python-dateutil pytz
"""

import json
import os
import sys
from datetime import datetime, date, timedelta, time
from typing import List, Dict, Any, Optional, Union

try:
    import httpx
    import pytz
    from icalendar import Calendar
except ImportError as e:
    print(f"ERROR: Missing required library: {e}")
    print("Install dependencies: pip install httpx icalendar python-dateutil pytz")
    sys.exit(1)


class iCalPlugin:
    def __init__(self):
        self.calendars = {}
        self.load_calendars_config()

    def load_calendars_config(self):
        """Load calendar configuration from JSON file."""
        config_path = os.path.join(os.path.dirname(__file__), "calendars_config.json")
        
        if not os.path.exists(config_path):
            sample_path = config_path + ".sample"
            if os.path.exists(sample_path):
                print(f"Warning: {config_path} not found.")
                print(f"Please copy {sample_path} to {config_path} and configure your calendar URLs.")
            else:
                print(f"Warning: No calendar configuration found at {config_path}")
            return
        
        try:
            with open(config_path, 'r') as f:
                self.calendars = json.load(f)
            print(f"Loaded {len(self.calendars)} calendar(s): {', '.join(self.calendars.keys())}")
        except json.JSONDecodeError as e:
            print(f"Error: Failed to parse {config_path}: {e}")
        except Exception as e:
            print(f"Error: Failed to read {config_path}: {e}")

    @staticmethod
    def normalize_to_utc(dt: Union[datetime, date]) -> datetime:
        """
        Normalizes a datetime or date object to timezone-aware UTC datetime.
        """
        if isinstance(dt, datetime):
            if dt.tzinfo:
                return dt.astimezone(pytz.utc)
            else:
                return pytz.utc.localize(dt)
        elif isinstance(dt, date):
            return pytz.utc.localize(datetime.combine(dt, time.min))
        raise TypeError("Input must be a datetime or date object")

    def fetch_calendar_events(self, calendar_name: Optional[str] = None, days: int = 7) -> List[Dict[str, Any]]:
        """
        Fetch and parse upcoming events from specified calendar(s).
        
        :param calendar_name: Name of calendar to fetch, or None for all calendars
        :param days: Number of days to look ahead (1-365)
        :return: List of event dictionaries
        """
        if not 1 <= days <= 365:
            raise ValueError("Days must be between 1 and 365")

        if not self.calendars:
            print("No calendars configured.")
            return []

        calendar_names = [calendar_name] if calendar_name else list(self.calendars.keys())
        all_results = []

        for cal in calendar_names:
            if cal not in self.calendars:
                print(f"Warning: Calendar '{cal}' not found in configuration")
                continue

            ical_url = self.calendars[cal]
            
            try:
                # Fetch calendar data synchronously
                with httpx.Client(timeout=60.0, follow_redirects=True) as client:
                    response = client.get(ical_url)
                    response.raise_for_status()
                ical_data = response.text
            except httpx.RequestError as exc:
                print(f"Error fetching calendar '{cal}': {exc}")
                continue
            except httpx.HTTPStatusError as exc:
                print(f"HTTP error {exc.response.status_code} for calendar '{cal}'")
                continue

            try:
                calendar = Calendar.from_ical(ical_data)
            except ValueError as e:
                print(f"Failed to parse iCal data for '{cal}': {e}")
                continue

            now_utc = datetime.now(pytz.utc)
            time_limit_utc = now_utc + timedelta(days=days)

            for component in calendar.walk():
                if component.name == "VEVENT":
                    try:
                        start_dt = component.get("dtstart").dt
                        end_dt = component.get("dtend").dt
                        start_utc = self.normalize_to_utc(start_dt)
                        end_utc = self.normalize_to_utc(end_dt)

                        if now_utc <= start_utc < time_limit_utc:
                            event = {
                                "calendar": cal,
                                "summary": str(component.get("summary", "No Title")),
                                "start_time": start_utc,
                                "end_time": end_utc,
                                "location": str(component.get("location")) if component.get("location") else None,
                                "description": str(component.get("description")) if component.get("description") else None,
                            }
                            all_results.append(event)
                    except Exception as e:
                        # Skip malformed events
                        continue

        all_results.sort(key=lambda e: e["start_time"])
        return all_results

    def format_events(self, events: List[Dict[str, Any]], days: int = 7) -> str:
        """
        Format events into a human-readable string.
        
        :param events: List of event dictionaries
        :param days: Number of days being displayed
        :return: Formatted string
        """
        if not events:
            return f"No upcoming events found in the next {days} day(s)."

        grouped = {}
        for event in events:
            cal = event.get("calendar", "Unknown")
            grouped.setdefault(cal, []).append(event)

        result = []
        for cal, cal_events in grouped.items():
            result.append(f"\n📚 Upcoming events for {cal} (next {days} day(s)):\n")
            for i, event in enumerate(cal_events, 1):
                start_str = event['start_time'].strftime("%Y-%m-%d %H:%M UTC")
                end_str = event['end_time'].strftime("%Y-%m-%d %H:%M UTC")
                
                result.append(f"  Event {i}: {event['summary']}")
                result.append(f"    ⏰ {start_str} → {end_str}")
                if event.get('location'):
                    result.append(f"    📍 {event['location']}")
                if event.get('description'):
                    result.append(f"    📄 {event['description'][:100]}...")
                result.append("")

        return "\n".join(result)

    def get_tool_definition(self):
        """
        Provide tool definitions for calendar operations.
        """
        return {
            'type': 'function',
            'function': {
                'name': 'get_calendar_events',
                'description': 'Fetch upcoming events from iCalendar feeds. Can retrieve events from a specific calendar or all configured calendars.',
                'parameters': {
                    "type": "object",
                    "properties": {
                        "calendar_name": {
                            "type": "string",
                            "description": f"Name of the calendar to fetch. Available: {', '.join(self.calendars.keys())}. Leave empty for all calendars.",
                        },
                        "days": {
                            "type": "integer",
                            "description": "Number of days to look ahead (1-365). Default is 7.",
                            "default": 7
                        },
                        "format": {
                            "type": "string",
                            "description": "Output format: 'raw' for structured data or 'formatted' for readable text",
                            "enum": ["raw", "formatted"],
                            "default": "formatted"
                        }
                    },
                    "required": []
                }
            }
        }

    def get_calendar_events(self, calendar_name: Optional[str] = None, days: int = 7, format: str = "formatted") -> str:
        """
        Tool function to get calendar events.
        
        :param calendar_name: Calendar name or None for all
        :param days: Days to look ahead
        :param format: 'raw' or 'formatted'
        :return: Calendar events as string
        """
        try:
            events = self.fetch_calendar_events(calendar_name, days)
            
            if format == "raw":
                # Return structured data as JSON string
                events_serializable = []
                for event in events:
                    event_copy = event.copy()
                    event_copy['start_time'] = event['start_time'].isoformat()
                    event_copy['end_time'] = event['end_time'].isoformat()
                    events_serializable.append(event_copy)
                return json.dumps(events_serializable, indent=2)
            else:
                # Return formatted text
                return self.format_events(events, days)
        except Exception as e:
            return f"Error fetching calendar events: {str(e)}"