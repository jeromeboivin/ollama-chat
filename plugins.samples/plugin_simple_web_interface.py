# pip install flask flask-socketio
from flask import Flask, render_template_string
from flask_socketio import SocketIO, emit
import threading
import re

class PluginSimpleWebInterface:
    def __init__(self):
        self.app = Flask(__name__)
        self.app.config['SECRET_KEY'] = 'secret!'
        self.socketio = SocketIO(self.app)
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

    def stop_generation(self):
        return self.stop_flag

    def on_print(self, message):
        if not self.stop_flag:
            self.socketio.emit('chatbot_response', {'message': self.clean_message(message)})
        return True

    def on_stdout_write(self, message):
        if not self.stop_flag:
            self.socketio.emit('chatbot_token_response', {'message': self.clean_message(message)})
        return True

    def on_llm_response(self, message):
        if not self.stop_flag:
            self.socketio.emit('chatbot_response', {'message': self.clean_message(message)})
        return True

    def on_stdout_flush(self):
        return True

    def run_web_server(self):
        @self.app.route('/')
        def index():
            return render_template_string(self.html_template)

        @self.socketio.on('user_input')
        def handle_user_input(data):
            self.user_input = data['message']
            self.response_ready.set()
            self.stop_flag = False  # Reset stop flag when new input is received
            response = self.on_user_input_done(self.user_input)
            emit('chatbot_response', {'message': response})

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
            <title>Ollama Chatbot Interface</title>
            <style>
                body {
                    font-family: Arial, sans-serif;
                    background-color: #f5f5f5;
                    margin: 0;
                    padding: 0;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    height: 100vh;
                }
                .chat-container {
                    width: 100%;
                    max-width: 800px;
                    background-color: #ffffff;
                    box-shadow: 0 0 10px rgba(0, 0, 0, 0.1);
                    border-radius: 10px;
                    overflow: hidden;
                    display: flex;
                    flex-direction: column;
                    height: 80%;
                }
                .chat-header {
                    background-color: #007bff;
                    color: white;
                    padding: 15px;
                    font-size: 18px;
                    text-align: center;
                }
                .chat-box {
                    flex: 1;
                    padding: 20px;
                    overflow-y: auto;
                    background-color: #f9f9f9;
                }
                .chat-box p {
                    margin: 10px 0;
                    padding: 10px;
                    border-radius: 5px;
                    background-color: #e1e1e1;
                }
                .chat-box p.user {
                    background-color: #007bff;
                    color: white;
                    align-self: flex-end;
                    text-align: right;
                }
                .chat-box p.bot {
                    background-color: #e1e1e1;
                    color: black;
                    align-self: flex-start;
                    text-align: left;
                }
                .chat-input {
                    display: flex;
                    border-top: 1px solid #ddd;
                }
                .chat-input input {
                    flex: 1;
                    padding: 15px;
                    border: none;
                    outline: none;
                    font-size: 16px;
                }
                .chat-input button {
                    padding: 15px;
                    background-color: #007bff;
                    color: white;
                    border: none;
                    cursor: pointer;
                    font-size: 16px;
                }
                .chat-input button:hover {
                    background-color: #0056b3;
                }
                .stop-button {
                    background-color: red;
                    color: white;
                    border: none;
                    cursor: pointer;
                    font-size: 16px;
                    padding: 0 15px;
                    margin-left: 5px;
                    display: flex;
                    justify-content: center;
                    align-items: center;
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
                            var botMessage = document.createElement('p');
                            botMessage.className = 'bot';
                            botMessage.innerHTML = data.message;
                            chatbox.appendChild(botMessage);
                            chatbox.scrollTop = chatbox.scrollHeight;
                            currentMessageElement = botMessage;
                        }
                    });

                    // New handler for chatbot_token_response
                    socket.on('chatbot_token_response', function(data) {
                        if (data && data.message) {
                            data.message = data.message.replace(/\\n/g, "<br />");

                            // If there's no currentMessageElement, create one
                            if (!currentMessageElement) {
                                currentMessageElement = document.createElement('p');
                                currentMessageElement.className = 'bot';
                                chatbox.appendChild(currentMessageElement);
                            }

                            // Append the token to the current message element
                            currentMessageElement.innerHTML += data.message;
                            chatbox.scrollTop = chatbox.scrollHeight;
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

                        // Reset the currentMessageElement to null when new user input is received
                        currentMessageElement = null;
                    };

                    // Handle Stop button click
                    document.getElementById('stopButton').onclick = function() {
                        socket.emit('stop_generation');
                    };
                });
            </script>
        </head>
        <body>
            <div class="chat-container">
                <div class="chat-header">
                    Ollama Chatbot Interface
                </div>
                <div id="chatbox" class="chat-box">
                    <!-- Chatbot responses will be appended here -->
                </div>
                <div class="chat-input">
                    <form id="inputForm">
                        <input type="text" id="user_input" placeholder="Type your message..." required>
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
