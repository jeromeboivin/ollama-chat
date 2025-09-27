import json
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path
import sys


class EmailPlugin:
    """
    Plugin for sending emails through SMTP protocol with Gmail support.
    Configuration is loaded from an external JSON file.
    """
    
    def __init__(self):
        self.config = None
        self.config_file = "email_config.json"
        self.load_config()
    
    def load_config(self):
        """
        Load configuration from external JSON file.
        """
        config_paths = [
            self.config_file,
            os.path.join(os.path.dirname(__file__), self.config_file),
            os.path.join(os.getcwd(), self.config_file)
        ]
        
        for path in config_paths:
            if os.path.exists(path):
                try:
                    with open(path, 'r') as f:
                        self.config = json.load(f)
                        # print(f"Email configuration loaded from {path}")
                        return
                except Exception as e:
                    print(f"Error loading config from {path}: {e}")
        
        print(f"Warning: Email configuration file not found. Creating template at {self.config_file}")
        self.create_config_template()
    
    def create_config_template(self):
        """
        Create a template configuration file if none exists.
        """
        template = {
            "smtp_server": "smtp.gmail.com",
            "smtp_port": 587,
            "use_tls": True,
            "sender_email": "your_email@gmail.com",
            "sender_password": "your_app_password",
            "sender_name": "Your Name",
            "default_recipients": []
        }
        
        try:
            with open(self.config_file, 'w') as f:
                json.dump(template, f, indent=4)
            print(f"Template configuration created at {self.config_file}")
            print("Please update it with your Gmail credentials.")
            print("Note: For Gmail, use an App Password instead of your regular password.")
            print("Enable 2-factor authentication and generate an app password at:")
            print("https://myaccount.google.com/apppasswords")
        except Exception as e:
            print(f"Error creating config template: {e}")
    
    def get_tool_definition(self):
        """
        Provide tool definition for sending emails.
        """
        return {
            'type': 'function',
            'function': {
                'name': 'send_email',
                'description': 'Send an email through SMTP (configured for Gmail)',
                'parameters': {
                    "type": "object",
                    "properties": {
                        "to": {
                            "type": "string",
                            "description": "Recipient email address (comma-separated for multiple)"
                        },
                        "subject": {
                            "type": "string",
                            "description": "Email subject"
                        },
                        "body": {
                            "type": "string",
                            "description": "Email body content"
                        },
                        "html": {
                            "type": "boolean",
                            "description": "Whether the body is HTML content (default: False)"
                        },
                        "cc": {
                            "type": "string",
                            "description": "CC recipients (comma-separated, optional)"
                        },
                        "bcc": {
                            "type": "string",
                            "description": "BCC recipients (comma-separated, optional)"
                        },
                        "attachments": {
                            "type": "array",
                            "items": {
                                "type": "string"
                            },
                            "description": "List of file paths to attach (optional)"
                        }
                    },
                    "required": ["to", "subject", "body"]
                }
            }
        }
    
    def send_email(self, to, subject, body, html=False, cc=None, bcc=None, attachments=None):
        """
        Send an email through SMTP.
        
        :param to: Recipient email address(es)
        :param subject: Email subject
        :param body: Email body content
        :param html: Whether the body is HTML content
        :param cc: CC recipients (optional)
        :param bcc: BCC recipients (optional)
        :param attachments: List of file paths to attach (optional)
        :return: Success message or error description
        """
        if not self.config:
            return "Error: Email configuration not loaded. Please check email_config.json"
        
        try:
            # Create message
            msg = MIMEMultipart('alternative' if html else 'mixed')
            msg['From'] = f"{self.config.get('sender_name', 'Sender')} <{self.config['sender_email']}>"
            msg['To'] = to
            msg['Subject'] = subject
            
            if cc:
                msg['Cc'] = cc
            
            # Add body
            if html:
                msg.attach(MIMEText(body, 'html'))
            else:
                msg.attach(MIMEText(body, 'plain'))
            
            # Add attachments if provided
            if attachments:
                for file_path in attachments:
                    if os.path.isfile(file_path):
                        self.attach_file(msg, file_path)
                    else:
                        print(f"Warning: Attachment not found: {file_path}")
            
            # Prepare recipient list
            recipients = [addr.strip() for addr in to.split(',')]
            if cc:
                recipients.extend([addr.strip() for addr in cc.split(',')])
            if bcc:
                recipients.extend([addr.strip() for addr in bcc.split(',')])
            
            # Connect to server and send
            with smtplib.SMTP(self.config['smtp_server'], self.config['smtp_port']) as server:
                if self.config.get('use_tls', True):
                    server.starttls()
                
                server.login(self.config['sender_email'], self.config['sender_password'])
                server.send_message(msg, to_addrs=recipients)
            
            return f"Email sent successfully to {to}"
            
        except smtplib.SMTPAuthenticationError:
            return "Error: Authentication failed. Please check your email and password in config."
        except smtplib.SMTPException as e:
            return f"SMTP Error: {str(e)}"
        except Exception as e:
            return f"Error sending email: {str(e)}"
    
    def attach_file(self, msg, file_path):
        """
        Attach a file to the email message.
        
        :param msg: Email message object
        :param file_path: Path to the file to attach
        """
        with open(file_path, 'rb') as f:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header(
                'Content-Disposition',
                f'attachment; filename= {os.path.basename(file_path)}'
            )
            msg.attach(part)
    
    def on_exit(self):
        """
        Cleanup when the plugin exits.
        """
        # print("Email plugin shutting down.")


# Example usage and testing
if __name__ == "__main__":
    # Test the plugin
    plugin = EmailPlugin()
    
    # Example of sending an email (will only work with proper configuration)
    if plugin.config and plugin.config.get('sender_email') != 'your_email@gmail.com':
        result = plugin.send_email(
            to="recipient@example.com",
            subject="Test Email from Plugin",
            body="This is a test email sent from the EmailPlugin.",
            html=False
        )
        print(result)
    else:
        print("Please configure email_config.json with your Gmail credentials first.")