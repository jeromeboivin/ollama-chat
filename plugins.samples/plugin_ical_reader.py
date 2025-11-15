"""
iCal Calendar Reader Plugin - Smart Timezone-Aware Version

This plugin reads iCalendar (.ics) files from configured URLs and provides
calendar event information to the main application.

Features:
- Automatically detects system timezone
- Handles daylight saving time (DST) transitions automatically
- Smart detection of broken timezone calendars
- Minimal configuration required

Configuration:
- Create a 'calendars_config.json' file in the same directory as this plugin
- Simplest format (auto-detect timezone issues):
  {
    "Calendar Name": "https://example.com/calendar.ics"
  }
- Advanced format (explicit timezone control):
  {
    "Calendar Name": {
      "url": "https://example.com/calendar.ics",
      "treat_utc_as_local": true,
      "local_timezone": "Europe/Paris"
    }
  }

Dependencies:
- httpx: HTTP client for fetching calendar data
- icalendar: For parsing iCalendar files
- python-dateutil: For datetime parsing
- pytz: For timezone handling
- tzlocal: For detecting system timezone

Install with: pip install httpx icalendar python-dateutil pytz tzlocal
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
    from tzlocal import get_localzone
except ImportError as e:
    print(f"ERROR: Missing required library: {e}")
    print("Install dependencies: pip install httpx icalendar python-dateutil pytz tzlocal")
    sys.exit(1)


class iCalPlugin:
    def __init__(self, default_display_tz: Optional[str] = None):
        """
        Initialize the plugin.
        
        :param default_display_tz: Default timezone for displaying times. 
                                   If None, automatically detects system timezone.
        """
        self.calendars = {}
        
        # Auto-detect system timezone if not specified
        if default_display_tz is None:
            try:
                system_tz = get_localzone()
                self.default_display_tz = str(system_tz)
                print(f"Auto-detected system timezone: {self.default_display_tz}")
            except Exception as e:
                print(f"Warning: Could not detect system timezone: {e}")
                self.default_display_tz = 'UTC'
                print("Defaulting to UTC")
        else:
            self.default_display_tz = default_display_tz
        
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
                raw_config = json.load(f)
            
            # Normalize configuration format
            for name, config in raw_config.items():
                if isinstance(config, str):
                    # Simple format: just a URL string
                    self.calendars[name] = {
                        'url': config,
                        'treat_utc_as_local': None,  # Will auto-detect
                        'local_timezone': self.default_display_tz
                    }
                elif isinstance(config, dict):
                    # Advanced format: configuration object
                    self.calendars[name] = {
                        'url': config.get('url', ''),
                        'treat_utc_as_local': config.get('treat_utc_as_local', None),
                        'local_timezone': config.get('local_timezone', self.default_display_tz)
                    }
            
            print(f"Loaded {len(self.calendars)} calendar(s): {', '.join(self.calendars.keys())}")
        except json.JSONDecodeError as e:
            print(f"Error: Failed to parse {config_path}: {e}")
        except Exception as e:
            print(f"Error: Failed to read {config_path}: {e}")

    @staticmethod
    def normalize_to_utc(dt: Union[datetime, date], assume_local_tz: Optional[str] = None) -> datetime:
        """
        Normalizes a datetime or date object to timezone-aware UTC datetime.
        Handles DST transitions automatically.
        
        :param dt: datetime or date object to normalize
        :param assume_local_tz: Timezone to assume for naive datetimes (e.g., 'Europe/Paris')
        """
        if isinstance(dt, datetime):
            if dt.tzinfo:
                # Already timezone-aware, convert to UTC (handles DST automatically)
                return dt.astimezone(pytz.utc)
            else:
                # Naive datetime - apply local timezone if specified
                if assume_local_tz:
                    try:
                        local_tz = pytz.timezone(assume_local_tz)
                        # localize() handles DST ambiguity automatically
                        localized_dt = local_tz.localize(dt, is_dst=None)
                        return localized_dt.astimezone(pytz.utc)
                    except pytz.exceptions.AmbiguousTimeError:
                        # During DST transition, default to DST time
                        local_tz = pytz.timezone(assume_local_tz)
                        localized_dt = local_tz.localize(dt, is_dst=True)
                        return localized_dt.astimezone(pytz.utc)
                    except pytz.exceptions.NonExistentTimeError:
                        # During spring-forward, time doesn't exist, use standard time
                        local_tz = pytz.timezone(assume_local_tz)
                        localized_dt = local_tz.localize(dt, is_dst=False)
                        return localized_dt.astimezone(pytz.utc)
                    except pytz.exceptions.UnknownTimeZoneError:
                        print(f"Warning: Unknown timezone '{assume_local_tz}', defaulting to UTC")
                        return pytz.utc.localize(dt)
                else:
                    # Default to UTC
                    return pytz.utc.localize(dt)
        elif isinstance(dt, date):
            # Convert date to datetime at midnight
            dt_midnight = datetime.combine(dt, time.min)
            if assume_local_tz:
                try:
                    local_tz = pytz.timezone(assume_local_tz)
                    localized_dt = local_tz.localize(dt_midnight, is_dst=None)
                    return localized_dt.astimezone(pytz.utc)
                except pytz.exceptions.UnknownTimeZoneError:
                    print(f"Warning: Unknown timezone '{assume_local_tz}', defaulting to UTC")
                    return pytz.utc.localize(dt_midnight)
                except (pytz.exceptions.AmbiguousTimeError, pytz.exceptions.NonExistentTimeError):
                    local_tz = pytz.timezone(assume_local_tz)
                    localized_dt = local_tz.localize(dt_midnight, is_dst=False)
                    return localized_dt.astimezone(pytz.utc)
            else:
                return pytz.utc.localize(dt_midnight)
        raise TypeError("Input must be a datetime or date object")

    def detect_timezone_issue(self, ical_data: str, calendar_name: str) -> bool:
        """
        Smart detection of calendars that incorrectly mark local times as UTC.
        
        Heuristics:
        1. Check PRODID for known problematic calendar systems
        2. Look for patterns in event times (e.g., all events at round hours in "UTC")
        3. Check if VTIMEZONE is missing when times have Z suffix
        """
        # Known problematic calendar systems
        problematic_prodids = [
            'www.ecoledirecte.com',
            'pronote.net',
            # Add more as discovered
        ]
        
        ical_lower = ical_data.lower()
        
        # Check for known problematic systems
        for prodid in problematic_prodids:
            if prodid in ical_lower:
                print(f"  └─ Detected known calendar system with timezone issues: {prodid}")
                return True
        
        # Check if calendar has Z-suffixed times but no VTIMEZONE definition
        has_z_times = 'dtstart:' in ical_lower and 'z\n' in ical_lower
        has_vtimezone = 'begin:vtimezone' in ical_lower
        
        if has_z_times and not has_vtimezone:
            print(f"  └─ Calendar has UTC times (Z) but no timezone definitions - likely incorrect")
            return True
        
        return False

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

            cal_config = self.calendars[cal]
            ical_url = cal_config['url']
            
            print(f"\nFetching calendar: {cal}")
            
            try:
                # Fetch calendar data synchronously
                with httpx.Client(timeout=60.0, follow_redirects=True) as client:
                    response = client.get(ical_url)
                    response.raise_for_status()
                ical_data = response.text
                print(f"  └─ Successfully fetched {len(ical_data)} bytes")
            except httpx.RequestError as exc:
                print(f"  └─ Error fetching: {exc}")
                continue
            except httpx.HTTPStatusError as exc:
                print(f"  └─ HTTP error {exc.response.status_code}")
                continue

            # Auto-detect or use configured timezone handling
            treat_utc_as_local = cal_config.get('treat_utc_as_local')
            if treat_utc_as_local is None:
                # Auto-detect
                treat_utc_as_local = self.detect_timezone_issue(ical_data, cal)
            
            local_tz = cal_config.get('local_timezone', self.default_display_tz)
            
            if treat_utc_as_local:
                print(f"  └─ Treating UTC times as {local_tz} local times")

            try:
                calendar = Calendar.from_ical(ical_data)
            except ValueError as e:
                print(f"  └─ Failed to parse iCal data: {e}")
                continue

            now_utc = datetime.now(pytz.utc)
            time_limit_utc = now_utc + timedelta(days=days)

            event_count = 0
            for component in calendar.walk():
                if component.name == "VEVENT":
                    try:
                        start_dt = component.get("dtstart").dt
                        end_dt = component.get("dtend").dt
                        
                        # Handle calendars that incorrectly mark local times as UTC
                        if treat_utc_as_local:
                            # Strip timezone info if present, then treat as local
                            if isinstance(start_dt, datetime) and start_dt.tzinfo:
                                start_dt = start_dt.replace(tzinfo=None)
                            if isinstance(end_dt, datetime) and end_dt.tzinfo:
                                end_dt = end_dt.replace(tzinfo=None)
                            
                            # Now normalize with the specified local timezone
                            # This automatically handles DST
                            start_utc = self.normalize_to_utc(start_dt, local_tz)
                            end_utc = self.normalize_to_utc(end_dt, local_tz)
                        else:
                            # Normal handling - DST is handled automatically
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
                            event_count += 1
                    except Exception as e:
                        # Skip malformed events
                        continue
            
            print(f"  └─ Found {event_count} upcoming event(s)")

        all_results.sort(key=lambda e: e["start_time"])
        return all_results

    def format_events(self, events: List[Dict[str, Any]], days: int = 7, display_tz: Optional[str] = None) -> str:
        """
        Format events into a human-readable string.
        DST transitions are handled automatically.
        
        :param events: List of event dictionaries
        :param days: Number of days being displayed
        :param display_tz: Timezone to display times in (default: self.default_display_tz)
        :return: Formatted string
        """
        if not events:
            return f"No upcoming events found in the next {days} day(s)."

        if display_tz is None:
            display_tz = self.default_display_tz

        grouped = {}
        for event in events:
            cal = event.get("calendar", "Unknown")
            grouped.setdefault(cal, []).append(event)

        result = []
        
        try:
            local_tz = pytz.timezone(display_tz)
        except pytz.exceptions.UnknownTimeZoneError:
            print(f"Warning: Unknown display timezone '{display_tz}', using UTC")
            local_tz = pytz.utc
        
        for cal, cal_events in grouped.items():
            result.append(f"\n📚 Upcoming events for {cal} (next {days} day(s)):\n")
            for i, event in enumerate(cal_events, 1):
                # Convert to local timezone for display
                # astimezone() automatically handles DST
                start_local = event['start_time'].astimezone(local_tz)
                end_local = event['end_time'].astimezone(local_tz)
                
                # Format with timezone abbreviation (automatically shows DST/standard time)
                start_str = start_local.strftime("%Y-%m-%d %H:%M %Z")
                end_str = end_local.strftime("%H:%M %Z")
                
                result.append(f"  Event {i}: {event['summary']}")
                result.append(f"    ⏰ {start_str} → {end_str}")
                if event.get('location'):
                    result.append(f"    📍 {event['location']}")
                if event.get('description'):
                    desc = event['description'][:100]
                    result.append(f"    📄 {desc}...")
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
                'description': 'Fetch upcoming events from iCalendar feeds. Can retrieve events from a specific calendar or all configured calendars. Automatically handles timezone conversions and DST.',
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


# Convenience function for quick testing
if __name__ == "__main__":
    plugin = iCalPlugin()
    print("\n" + "="*60)
    result = plugin.get_calendar_events(days=14)
    print(result)