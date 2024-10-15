"""
# Steps to Set Up:

## Install Required Libraries:
You will need to install the google-api-python-client, google-auth-httplib2, and google-auth-oauthlib libraries.
You can install them using pip:

pip install --upgrade google-api-python-client google-auth-httplib2 google-auth-oauthlib

## Create OAuth Credentials:

- Go to the Google Cloud Console.
- Create a new project and enable the Google Calendar API for it.
- In the "APIs & Services" > "Credentials" section, create OAuth 2.0 credentials.
- Download the credentials.json file and store it in the current script location, name it google-credentials.json.
"""

import os
import datetime
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build


class GoogleCalendarBase:
    def __init__(self, credentials_file='google-credentials.json', token_file='google-token.json', scopes=None):
        """Common functionality for Google Calendar Reader and Writer"""
        # Get the current directory where the script is located
        script_dir = os.path.dirname(os.path.abspath(__file__))

        # Set the credentials and token file paths to be in the same folder as the script
        self.credentials_file = os.path.join(script_dir, credentials_file)
        self.token_file = os.path.join(script_dir, token_file)
        
        # Default scope for both reading and writing
        self.scopes = scopes if scopes else ['https://www.googleapis.com/auth/calendar']
        self.creds = None
        self.service = None

        try:
            self.authenticate()
        except Exception as e:
            print(f"An error occurred during authentication: {e}")
            # Remove the token file to force re-authentication
            if os.path.exists(self.token_file):
                os.remove(self.token_file)
                self.creds = None

                self.authenticate()

    def authenticate(self):
        """Authenticate the user and set up Google Calendar API service"""
        if os.path.exists(self.token_file):
            self.creds = Credentials.from_authorized_user_file(self.token_file, self.scopes)
        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                self.creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(self.credentials_file, self.scopes)
                self.creds = flow.run_local_server(port=0)
            # Save the credentials for the next run
            with open(self.token_file, 'w') as token:
                token.write(self.creds.to_json())

        # Build the Google Calendar API service
        self.service = build('calendar', 'v3', credentials=self.creds)


class GoogleCalendarReaderPlugin(GoogleCalendarBase):
    def get_upcoming_events(self, max_results=10, calendarId='primary'):
        """Fetches the upcoming events from the user's primary calendar"""
        # Use timezone-aware datetime object to represent UTC time
        now = datetime.datetime.now(datetime.UTC).isoformat()
        try:
            events_result = self.service.events().list(
                calendarId=calendarId, timeMin=now, maxResults=max_results, singleEvents=True,
                orderBy='startTime').execute()
        except Exception as e:
            print(f"An error occurred while fetching events: {e}")
            return []

        events = events_result.get('items', [])

        if not events:
            print('No upcoming events found.')
            return []

        upcoming_events = []
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            upcoming_events.append({
                'summary': event['summary'],
                'start': start,
                'location': event.get('location', 'N/A')
            })
        return upcoming_events

    def print_upcoming_events(self, max_results=10):
        """Prints upcoming events in a user-friendly way"""
        events = self.get_upcoming_events(max_results=max_results)
        if events:
            for event in events:
                print(f"Event: {event['summary']}")
                print(f"Start Time: {event['start']}")
                print(f"Location: {event['location']}")
                print('-' * 30)
    
    def get_tool_definition(self):
        """
        Provide a custom tool definition for the plugin.

        :return: A dictionary representing the tool definition.
        """
        return {
            'type': 'function',
            'function': {
                'name': 'get_upcoming_events',
                'description': 'Get upcoming events from the user\'s Google Calendar',
                'parameters': {
                    "type": "object",
                    "properties": {
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum number of upcoming events to retrieve"
                        },
                        "calendarId": {
                            "type": "string",
                            "description": "ID of the calendar to retrieve events from (default: primary)"
                        }
                    }
                }
            }
        }

class GoogleCalendarWriterPlugin(GoogleCalendarBase):
    def add_event(self, summary, start_time, end_time, description=None, location=None):
        """Add a new event to the user's calendar"""
        event = {
            'summary': summary,
            'location': location,
            'description': description,
            'start': {
                'dateTime': start_time,
                'timeZone': 'UTC',  # Adjust timezone accordingly
            },
            'end': {
                'dateTime': end_time,
                'timeZone': 'UTC',  # Adjust timezone accordingly
            },
        }
        
        created_event = self.service.events().insert(calendarId='primary', body=event).execute()
        return f"Event created: {created_event.get('htmlLink')}"
    
    def get_tool_definition(self):
        """
        Provide a custom tool definition for the plugin.

        :return: A dictionary representing the tool definition.
        """
        return {
            'type': 'function',
            'function': {
                'name': 'add_event',
                'description': 'Add an event to the user\'s Google Calendar',
                'parameters': {
                    "type": "object",
                    "properties": {
                        "summary": {
                            "type": "string",
                            "description": "Title of the event"
                        },
                        "start_time": {
                            "type": "string",
                            "description": "Start time of the event in ISO format (e.g., 2024-10-09T10:00:00Z)"
                        },
                        "end_time": {
                            "type": "string",
                            "description": "End time of the event in ISO format (e.g., 2024-10-09T11:00:00Z)"
                        },
                        "description": {
                            "type": "string",
                            "description": "Description of the event (optional)"
                        },
                        "location": {
                            "type": "string",
                            "description": "Location of the event (optional)"
                        }
                    },
                    "required": [
                        "summary",
                        "start_time",
                        "end_time"
                    ]
                }
            }
        }


# Usage Example:

# Create a reader to get events
# calendar_reader = GoogleCalendarReaderPlugin()
# calendar_reader.print_upcoming_events(max_results=5)

# Create a writer to add events
# calendar_writer = GoogleCalendarWriterPlugin()
# calendar_writer.add_event(
#     summary="Meeting with John",
#     start_time="2024-10-09T10:00:00Z",  # ISO format in UTC
#     end_time="2024-10-09T11:00:00Z",
#     description="Discuss project milestones",
#     location="Conference Room"
# )
