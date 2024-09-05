class PluginSample():
    def on_user_input_done(self, user_input, verbose_mode=False):
        if user_input and "/whoami" in user_input:
            return "I'm John Doe."
        
        return None

    def on_user_input(self, input_prompt=None):
        return None

    def on_print(self, message):
        return False

    def on_stdout_write(self, message):
        return False
    
    def on_llm_token_response(self, message):
        return False

    def on_stdout_flush(self):
        return False

    def on_llm_response(self, message):
        return False