import time
import sys

class PluginSample:
    def __init__(self):
        self.web_crawler = None

    def set_web_crawler(self, web_crawler_class):
        """
        Optional method to set the web crawler class to be used by the plugin.

        :param web_crawler_class: The web crawler class to be used.
        """
        self.web_crawler = web_crawler_class

    def on_user_input(self, input_prompt):
        """
        Optional method to handle user input before it is processed by the main program.

        :param input_prompt: The user input prompt.
        :return: Modified user input prompt or None.
        """
        # Example: Add a prefix to the user input
        return f"[Modified] {input_prompt}"

    def on_print(self, message):
        """
        Optional method to handle print messages before they are printed to the console.

        :param message: The message to be printed.
        :return: True if the message was handled, False otherwise.
        """
        # Example: Print the message in uppercase
        print(message.upper())
        return True

    def on_stdout_write(self, message):
        """
        Optional method to handle stdout write messages before they are written to the console.

        :param message: The message to be written to stdout.
        :return: True if the message was handled, False otherwise.
        """
        # Example: Write the message in lowercase
        sys.stdout.write(message.lower())
        return True

    def on_llm_token_response(self, token):
        """
        Optional method to handle LLM token responses before they are written to the console.

        :param token: The LLM token response.
        :return: True if the token response was handled, False otherwise.
        """
        # Example: Write the token response with a prefix
        sys.stdout.write(f"[Token] {token}")
        return True

    def on_prompt(self, prompt):
        """
        Optional method to handle prompts before they are written to the console.

        :param prompt: The prompt to be written.
        :return: True if the prompt was handled, False otherwise.
        """
        # Example: Write the prompt with a suffix
        sys.stdout.write(f"{prompt} [Suffix]")
        return True

    def on_stdout_flush(self):
        """
        Optional method to handle stdout flush events before they are flushed to the console.

        :return: True if the flush event was handled, False otherwise.
        """
        # Example: Print a message before flushing
        print("Flushing stdout...")
        sys.stdout.flush()
        return True

    def stop_generation(self):
        """
        Optional method to determine whether to stop the response generation.

        :return: True to stop generation, False otherwise.
        """
        # Example: Stop generation after 10 seconds
        if time.time() % 10 < 1:
            print("Stopping generation...")
            return True
        return False

    def on_llm_response(self, response):
        """
        Optional method to handle LLM responses before they are processed by the main program.

        :param response: The LLM response.
        :return: True if the response was handled, False otherwise.
        """
        # Example: Print the response with a prefix
        print(f"[LLM Response] {response}")
        return True

    def on_user_input_done(self, user_input, verbose_mode=False):
        """
        Optional method to handle user input after it is processed by the main program.

        :param user_input: The user input.
        :param verbose_mode: Whether verbose mode is enabled.
        :return: Modified user input or None.
        """
        # Example: Add a suffix to the user input
        return f"{user_input} [Done]"

    def on_exit(self):
        """
        Optional method to handle cleanup tasks before the program exits.

        :return: None
        """
        # Example: Print a goodbye message
        print("Goodbye from SamplePlugin!")

    def get_tool_definition(self):
        """
        Optional method to provide a custom tool definition for the plugin.

        :return: A dictionary representing the tool definition.
        """
        return {
            'type': 'function',
            'function': {
                'name': 'sample_tool',
                'description': 'A sample tool provided by SamplePlugin',
                'parameters': {
                    "type": "object",
                    "properties": {
                        "param1": {
                            "type": "string",
                            "description": "A sample parameter"
                        }
                    },
                    "required": [
                        "param1"
                    ]
                }
            }
        }

    def sample_tool(self, param1):
        """
        A sample tool function provided by the plugin.

        :param param1: A sample parameter.
        :return: A sample response.
        """
        return f"Sample tool executed with param1: {param1}"