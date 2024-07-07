class PluginSample():
    def on_user_input(self, user_input, verbose_mode=False):
        if "/whoami" in user_input:
            return "I'm John Doe."
        
        return None