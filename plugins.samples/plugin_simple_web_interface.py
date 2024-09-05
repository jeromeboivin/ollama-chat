# pip install flask flask-socketio
import flask
import flask_socketio
import threading
import re

class PluginSimpleWebInterface:
    def __init__(self):
        self.app = flask.Flask(__name__)
        self.app.config['SECRET_KEY'] = 'secret!'
        self.socketio = flask_socketio.SocketIO(self.app)
        self.user_input = None
        self.response_ready = threading.Event()
        self.stop_flag = False  # Flag to indicate stop button press

        # Start the web server with WebSockets in a separate thread within the constructor
        web_thread = threading.Thread(target=self.run_web_server)
        web_thread.daemon = True
        web_thread.start()

    def clean_message(self, message):
        """Remove ANSI escape sequences from the message."""
        ansi_escape = re.compile(r'\x1B[@-_][0-?]*[ -/]*[@-~]')
        return ansi_escape.sub('', message)

    def on_user_input_done(self, user_input, verbose_mode=False):
        return None

    def on_user_input(self, input_prompt=None):
        if input_prompt:
            self.socketio.emit('chatbot_response', {'message': self.clean_message(input_prompt)})
        self.response_ready.wait()
        self.response_ready.clear()
        return self.user_input
    
    def on_prompt(self, message):
        # Ignore prompts for now
        return True

    def stop_generation(self):
        return self.stop_flag

    def on_print(self, message):
        if not self.stop_flag:
            self.socketio.emit('chatbot_response', {'message': self.clean_message(message)})
        return True

    def on_llm_token_response(self, message):
        if not self.stop_flag:
            self.socketio.emit('chatbot_token_response', {'message': self.clean_message(message)})
        return True

    def on_llm_response(self, message):
        # Ignore LLM responses for now as it has been streamed to the web interface through on_llm_token_response method
        #if not self.stop_flag:
        #    self.socketio.emit('chatbot_response', {'message': self.clean_message(message)})
        return True

    def on_stdout_flush(self):
        return True

    def run_web_server(self):
        @self.app.route('/')
        def index():
            return flask.render_template_string(self.html_template)

        @self.socketio.on('user_input')
        def handle_user_input(data):
            self.user_input = data['message']
            self.response_ready.set()
            self.stop_flag = False  # Reset stop flag when new input is received
            response = self.on_user_input_done(self.user_input)
            flask_socketio.emit('chatbot_response', {'message': response})

        @self.socketio.on('stop_generation')
        def handle_stop_generation():
            self.stop_flag = True

        self.socketio.run(self.app, debug=True, use_reloader=False)

    @property
    def html_template(self):
        return '''
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Chatbot Interface</title>
            <style>
                body {
                    font-family: 'Helvetica Neue', Arial, sans-serif;
                    background-color: #f0f2f5;
                    margin: 0;
                    padding: 0;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    height: 100vh;
                    color: #333;
                }
                .user_input {
                }
                .chat-container {
                    width: 100%;
                    max-width: 800px;
                    background-color: #ffffff;
                    box-shadow: 0 4px 14px rgba(0, 0, 0, 0.1);
                    border-radius: 12px;
                    display: flex;
                    flex-direction: column;
                    height: 80%;
                    overflow: hidden;
                }
                .chat-box {
                    flex: 1;
                    padding: 20px;
                    overflow-y: auto;
                    background-color: #f0f2f5;
                    display: flex;
                    flex-direction: column;
                }
                .chat-box .chatbot-message {
                    display: flex;
                    align-items: flex-start;
                    margin: 10px 0;
                }
                .chat-box .chatbot-message .icon {
                    margin-right: 10px;
                    font-size: 24px;
                    color: #0a82ff;
                }
                .chat-box .chatbot-message .message-container {
                    background-color: #e5e7eb;
                    color: #333;
                    padding: 12px 18px;
                    border-radius: 18px;
                    max-width: 75%;
                    line-height: 1.4;
                    font-size: 16px;
                    position: relative;
                }
                .chat-box .chatbot-message .copy-button {
                    background-color: #ffffff;
                    color: #0a82ff;
                    border: 1px solid #0a82ff;
                    border-radius: 12px;
                    padding: 5px 10px;
                    font-size: 14px;
                    cursor: pointer;
                    margin-top: 5px;
                    transition: background-color 0.3s ease;
                }
                .chat-box .chatbot-message .copy-button:hover {
                    background-color: #0a82ff;
                    color: #ffffff;
                }
                .chat-box p.user {
                    background-color: #0a82ff;
                    color: white;
                    align-self: flex-end;
                    text-align: right;
                    padding: 12px 18px;
                    border-radius: 18px;
                    max-width: 75%;
                    margin: 10px 0;
                    line-height: 1.4;
                    font-size: 16px;
                }
                .chat-input {
                    display: flex;
                    padding: 15px;
                    background-color: #ffffff;
                    border-top: 1px solid #ddd;
                }
                .chat-input input {
                    flex: 1;
                    padding: 12px 18px;
                    border-radius: 25px;
                    border: 1px solid #ddd;
                    outline: none;
                    font-size: 16px;
                    margin-right: 10px;
                    background-color: #f9f9f9;
                }
                .chat-input button {
                    padding: 12px 18px;
                    border-radius: 25px;
                    background-color: #0a82ff;
                    color: white;
                    border: none;
                    cursor: pointer;
                    font-size: 16px;
                    transition: background-color 0.3s ease;
                }
                .chat-input button:hover {
                    background-color: #006edc;
                }
                .stop-button {
                    background-color: red;
                    color: white;
                    border: none;
                    cursor: pointer;
                    font-size: 16px;
                    padding: 0 15px;
                    border-radius: 25px;
                    margin-left: 10px;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    transition: background-color 0.3s ease;
                }
                .stop-button:hover {
                    background-color: darkred;
                }
            </style>
            <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.3.2/socket.io.js"></script>
            <script>
                document.addEventListener('DOMContentLoaded', (event) => {
                    var socket = io.connect('http://' + document.domain + ':' + location.port);
                    var chatbox = document.getElementById('chatbox');
                    var currentMessageElement = null;

                    socket.on('connect', function() {
                        console.log('WebSocket connected!');
                    });

                    socket.on('chatbot_response', function(data) {
                        if (data && data.message) {
                            data.message = data.message.replace(/\\n/g, "<br />");
                            var botMessageContainer = document.createElement('div');
                            botMessageContainer.className = 'chatbot-message';

                            var botIcon = document.createElement('span');
                            botIcon.className = 'icon';
                            botIcon.innerHTML = '🦙';

                            var botMessage = document.createElement('div');
                            botMessage.className = 'message-container';
                            botMessage.innerHTML = data.message;

                            botMessageContainer.appendChild(botIcon);
                            botMessageContainer.appendChild(botMessage);
                            chatbox.appendChild(botMessageContainer);
                            chatbox.scrollTop = chatbox.scrollHeight;
                            currentMessageElement = botMessage;
                        }
                    });

                    socket.on('chatbot_token_response', function(data) {
                        if (data && data.message) {
                            data.message = data.message.replace(/\\n/g, "<br />");

                            if (!currentMessageElement) {
                                var botMessageContainer = document.createElement('div');
                                botMessageContainer.className = 'chatbot-message';

                                var botIcon = document.createElement('span');
                                botIcon.className = 'icon';
                                botIcon.innerHTML = '🦙';

                                currentMessageElement = document.createElement('div');
                                currentMessageElement.className = 'message-container';

                                botMessageContainer.appendChild(botIcon);
                                botMessageContainer.appendChild(currentMessageElement);
                                chatbox.appendChild(botMessageContainer);
                            }

                            currentMessageElement.innerHTML += data.message;
                            chatbox.scrollTop = chatbox.scrollHeight;
                            /**
                            * Code not working as expected
                            if (data.message.endsWith("</br>") || data.message.endsWith("<br />")) {
                                // Create the copy button and container div
                                var copyButtonContainer = document.createElement('div');
                                copyButtonContainer.className = 'copy-button-container';

                                var copyButton = document.createElement('button');
                                copyButton.className = 'copy-button';
                                copyButton.textContent = '📋';
                                copyButton.onclick = function() {
                                    // Replace <br \/> or <br> with newline character
                                    var textToCopy = currentMessageElement.innerHTML.replace(/<br \/>|<br>/g, "\\n");
                                    // If text to copy ends with a newline, remove it
                                    if (textToCopy.endsWith("\\n")) {
                                        textToCopy = textToCopy.slice(0, -1);
                                    }
                                    navigator.clipboard.writeText(textToCopy);
                                    copyButton.textContent = '📋';
                                    setTimeout(() => copyButton.textContent = '📋', 2000);
                                };

                                copyButtonContainer.appendChild(copyButton);
                                chatbox.lastElementChild.appendChild(copyButtonContainer);
                            }*/
                        }
                    });

                    document.getElementById('inputForm').onsubmit = function(e) {
                        e.preventDefault();
                        var userInput = document.getElementById('user_input').value;
                        var userMessage = document.createElement('p');
                        userMessage.className = 'user';
                        userMessage.textContent = userInput;
                        chatbox.appendChild(userMessage);
                        socket.emit('user_input', {message: userInput});
                        document.getElementById('user_input').value = '';
                        chatbox.scrollTop = chatbox.scrollHeight;

                        currentMessageElement = null;
                    };

                    document.getElementById('stopButton').onclick = function() {
                        socket.emit('stop_generation');
                    };
                });
            </script>
        </head>
        <body>
            <div class="chat-container">
                <div id="chatbox" class="chat-box">
                    <!-- Chatbot responses will be appended here -->
                </div>
                <div class="chat-input">
                    <form id="inputForm">
                        <input type="text" id="user_input" class="user_input" placeholder="Type your message..." required>
                        <button type="submit">Send</button>
                    </form>
                    <button id="stopButton" class="stop-button">■</button>
                </div>
            </div>
        </body>
        </html>
        '''

# Main execution: Replace this with your chatbot's main program logic
if __name__ == "__main__":
    plugin = PluginSimpleWebInterface()

    # Example CLI chatbot loop that waits for web input
    while True:
        user_input = plugin.on_user_input()
        response = plugin.on_user_input_done(user_input)

        if plugin.stop_flag:
            print("Generation stopped by user.")
            plugin.stop_flag = False  # Reset flag after stopping

        if response:
            plugin.on_print(response)
