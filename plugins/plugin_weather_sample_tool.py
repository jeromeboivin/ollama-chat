import requests

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

    def on_user_input(self, user_input, verbose_mode=False):
        return None

    def get_current_weather(self, city):
        # URL to fetch weather data from wttr.in in JSON format
        url = f"https://wttr.in/{city}?format=j2"
        
        # Make the API request
        response = requests.get(url)
        
        # Check if the response status code is OK
        if response.status_code == 200:
            data = response.json()

            # Extract relevant weather information
            current_weather = data['current_condition'][0]
            city_name = data['nearest_area'][0]['areaName'][0]['value']
            temperature = current_weather['temp_C']
            feels_like = current_weather['FeelsLikeC']
            description = current_weather['weatherDesc'][0]['value']
            humidity = current_weather['humidity']
            wind_speed = current_weather['windspeedKmph']
            wind_direction = current_weather['winddir16Point']
            
            # Create a natural language response
            weather_report = (
                f"The current weather in {city_name} is {description.lower()} with a temperature of "
                f"{temperature}°C, feeling like {feels_like}°C. The humidity is around {humidity}%, and "
                f"the wind is blowing at {wind_speed} km/h from the {wind_direction}."
            )
            
            return weather_report
        else:
            # If the city is not found or an error occurs
            return "I couldn't find the city you're looking for, or an error occurred while fetching the weather data."
