import win32com.client
import datetime

class OutlookCalendarManager:
    """
    Handles the core logic of interacting with the Outlook calendar.
    """
    def __init__(self):
        """
        Initializes the Outlook application interface.
        """
        try:
            self.outlook = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
            # 9 represents the Calendar folder
            self.calendar = self.outlook.GetDefaultFolder(9)
        except Exception as e:
            print("Error: Could not connect to Outlook. Make sure Outlook is running.")
            print(f"Details: {e}")
            self.outlook = None
            self.calendar = None

    def get_appointments(self, start_date=None, end_date=None):
        """
        Retrieves appointments from the Outlook calendar within a given date range.

        Args:
            start_date (datetime.datetime, optional): The start date of the range.
                                                      Defaults to the first day of last month.
            end_date (datetime.datetime, optional): The end date of the range.
                                                    Defaults to today.

        Returns:
            list: A list of dictionaries, where each dictionary represents an appointment.
                  Returns an empty list if Outlook is not accessible or no appointments are found.
        """
        if not self.calendar:
            return []

        # If end date is not provided, default to today
        if end_date is None:
            end_date = datetime.datetime.now()

        # If start date is not provided, default to the first day of the last month
        if start_date is None:
            today = datetime.date.today()
            first_day_current_month = today.replace(day=1)
            last_day_previous_month = first_day_current_month - datetime.timedelta(days=1)
            start_date = last_day_previous_month.replace(day=1)
            # Convert date object to datetime object for consistency
            start_date = datetime.datetime.combine(start_date, datetime.datetime.min.time())

        # Get all appointments from the calendar folder
        appointments = self.calendar.Items
        
        # Sort appointments by their start time. This is crucial for the filter to work correctly.
        appointments.Sort("[Start]")
        
        # Include recurring appointments in the search
        appointments.IncludeRecurrences = True

        # Format dates into the string format that Outlook's filter requires
        start_str = start_date.strftime('%m/%d/%Y %H:%M %p')
        end_str = end_date.strftime('%m/%d/%Y %H:%M %p')

        # Create the filter string to restrict appointments to the date range
        # [Start] and [End] are Outlook properties for appointment times
        restriction = f"[Start] >= '{start_str}' AND [End] <= '{end_str}'"
        
        # Apply the filter to the appointments collection
        restricted_appointments = appointments.Restrict(restriction)

        calendar_entries = []
        # Iterate through the filtered appointments and extract details
        for appointment in restricted_appointments:
            calendar_entries.append({
                'subject': appointment.Subject,
                'start': appointment.Start.Format("%Y-%m-%d %H:%M"),
                'end': appointment.End.Format("%Y-%m-%d %H:%M"),
                'location': appointment.Location,
                'body': appointment.Body,
                'organizer': appointment.Organizer,
            })
            
        return calendar_entries

class OutlookCalendarReaderPlugin:
    """
    A plugin to expose Outlook calendar reading functionality.
    """
    def __init__(self):
        self.plugin = OutlookCalendarManager()

    def get_appointments(self, start_date=None, end_date=None):
        """
        Plugin method to get appointments. Can handle string dates in 'YYYY-MM-DD' format.
        """
        start_dt = None
        end_dt = None
        
        try:
            if start_date:
                start_dt = datetime.datetime.strptime(start_date, '%Y-%m-%d')
            if end_date:
                # Set time to end of the day to include all appointments on that day
                end_dt = datetime.datetime.strptime(end_date, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
        except ValueError as e:
            print(f"Error parsing date string: {e}. Please use 'YYYY-MM-DD' format.")
            return []

        return self.plugin.get_appointments(start_dt, end_dt)

    def get_tool_definition(self):
        """
        Returns the definition of the tool for use in agentic systems.
        """
        return {
            'type': 'function',
            'function': {
                'name': "get_appointments",
                'description': "Get calendar appointments from Outlook within a specified date range.",
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'start_date': {
                            'type': 'string',
                            'description': "The start date of the range in 'YYYY-MM-DD' format. Defaults to the first day of the previous month.",
                        },
                        'end_date': {
                            'type': 'string',
                            'description': "The end date of the range in 'YYYY-MM-DD' format. Defaults to today.",
                        },
                    },
                    'required': []
                }
            }
        }

if __name__ == "__main__":
    # --- Example Usage ---
    
    # The script now uses the plugin structure.
    #
    # To use a specific date range, you can still pass them in as strings:
    # entries = plugin.get_appointments(start_date='2024-01-01', end_date='2024-01-31')

    print(f"Attempting to fetch calendar entries using default dates (from last month to today)...")

    # 1. Create an instance of the calendar reader plugin
    plugin = OutlookCalendarReaderPlugin()

    # 2. Get the appointments within the specified range (using defaults)
    entries = plugin.get_appointments()
    
    # 3. You can also test the tool definition
    # import json
    # print(json.dumps(plugin.get_tool_definition(), indent=2))

    # 4. Print the results
    if entries:
        print(f"\nFound {len(entries)} appointments:\n")
        for i, entry in enumerate(entries):
            print(f"--- Appointment {i+1} ---")
            print(f"  Subject: {entry['subject']}")
            print(f"  Start:   {entry['start']}")
            print(f"  End:     {entry['end']}")
            print(f"  Location: {entry['location'] or 'Not specified'}")
            print("-" * 25 + "\n")
    else:
        print("No calendar entries found in the specified date range.")

