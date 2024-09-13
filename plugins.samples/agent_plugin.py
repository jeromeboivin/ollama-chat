from flask import Flask, request, jsonify
import requests
import threading

class CommunicationPlugin:
    def __init__(self):
        """
        Initialize the plugin with default values for the other program instance URL and port.
        """
        self.other_instance_url = None
        self.port = None
        self.initial_message = None
        self.last_response = None
        self.is_first_call = True
        self.message_received_event = threading.Event()
        self.received_message = None

        # Initialize Flask app and routes
        self.app = Flask(__name__)
        self.setup_routes()

    def setup_routes(self):
        """
        Set up the Flask routes for communication.
        """
        @self.app.route('/respond', methods=['POST'])
        def respond_to_conversation():
            """
            Endpoint to respond to the conversation.
            """
            self.received_message = request.json.get('message', '')
            self.message_received_event.set()  # Notify that a message has been received
            return jsonify({
                "response": self.received_message  # Echo back the received message
            })

    def run_server(self):
        """
        Start the Flask server.
        """
        if self.port:
            self.app.run(port=self.port)

    def set_other_instance_url(self, url):
        """
        Set the URL of the other program instance.
        """
        self.other_instance_url = url

    def set_listening_port(self, port):
        """
        Set the port for the Flask server.
        """
        self.port = port
        if self.port and not hasattr(self, 'server_thread'):
            # Start the Flask server in a separate thread
            self.server_thread = threading.Thread(target=self.run_server, daemon=True)
            self.server_thread.start()

    def set_initial_message(self, message):
        """
        Set the initial message to be sent to the other instance.
        """
        self.initial_message = message

    def on_user_input(self, input_prompt=None):
        """
        Wait for the other instance's answer and treat it as user input for this instance.
        """
        print("[INFO] Waiting for the other instance to provide user input...")

        # Handle subsequent user input requests
        self.message_received_event.clear()  # Reset event before waiting
        try:
            if self.is_first_call and self.initial_message:
                # Send the initial message to the other instance
                response = requests.post(f"{self.other_instance_url}/respond", json={"message": self.initial_message})
                if response.status_code == 200:
                    print(f"[INFO] Sent initial message to the other instance: {self.initial_message}")
                    self.is_first_call = False
                    # Wait for the message to be received
                    self.message_received_event.wait()  # Blocking call until event is set
                    other_instance_response = self.received_message
                    print(f"[INFO] Received user input from the other instance: {other_instance_response}")
                    return other_instance_response
                else:
                    print(f"[ERROR] Failed to send initial message to the other instance: {response.status_code}")
                    return None
            elif self.last_response:
                # Send the stored response to the other instance
                response = requests.post(f"{self.other_instance_url}/respond", json={"message": self.last_response})
                self.last_response = None  # Reset the stored response

                if response.status_code == 200:
                    # Wait for the message to be received
                    self.message_received_event.wait()  # Blocking call until event is set
                    other_instance_response = self.received_message
                    print(f"[INFO] Received user input from the other instance: {other_instance_response}")
                    return other_instance_response
                else:
                    print(f"[ERROR] Failed to get user input from the other instance: {response.status_code}")
                    return None
            else:
                # Wait for the message to be received
                self.message_received_event.wait()  # Blocking call until event is set
                other_instance_response = self.received_message
                print(f"[INFO] Received user input from the other instance: {other_instance_response}")
                return other_instance_response
        except Exception as e:
            print(f"[ERROR] Exception while getting user input: {str(e)}")
            return None

    def on_llm_response(self, response):
        """
        Store the current instance's response to be sent to the other instance.
        """
        print(f"[INFO] LLM generated response: {response}")
        self.last_response = response

    def on_exit(self):
        """
        Handle cleanup tasks before the program exits.
        """
        print("Goodbye from CommunicationPlugin!")

# Example usage
if __name__ == "__main__":
    # Create an instance of the CommunicationPlugin
    plugin = CommunicationPlugin()
    
    # Set values for the other instance URL, port, and initial message
    plugin.set_other_instance_url("http://localhost:5001")  # URL of the other instance
    plugin.set_listening_port(5000)  # Port for this instance
    plugin.set_initial_message("Hello, this is the start of our conversation!")

    # Keep the main thread alive to keep the server running
    try:
        while True:
            pass
    except KeyboardInterrupt:
        print("Server interrupted and shutting down.")
