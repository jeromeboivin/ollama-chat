import requests
import json

class WeatherPluginSample():
    def get_tool_definition(self):
        return {
            'type': 'function',
            'function': {
                'name': 'get_current_weather',
                'description': 'Get the current weather for a city',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'city': {
                            'type': 'string',
                            'description': 'The name of the city',
                        }
                    },
                    'required': ['city']
                },
            },
        }

    def on_user_input_done(self, user_input, verbose_mode=False):
        return None

    def get_current_weather(self, city):
        # URL to fetch weather data from wttr.in in JSON format
        url = f"https://wttr.in/{city}?format=j2"
        
        # Make the API request
        response = requests.get(url)
        
        # Check if the response status code is OK
        if response.status_code == 200:
            data = response.json()
            return json.dumps(data['current_condition'][0])
        else:
            # If the city is not found or an error occurs
            return None
