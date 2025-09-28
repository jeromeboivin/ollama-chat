import json
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path
import sys
import markdown


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
            print(f"Checking for config at: {path}")
            if os.path.exists(path):
                try:
                    with open(path, 'r') as f:
                        self.config = json.load(f)
                        abs_path = os.path.abspath(path)
                        print(f"Email configuration successfully loaded from: {abs_path}")
                        print(f"SMTP Server: {self.config.get('smtp_server')}")
                        print(f"SMTP Port: {self.config.get('smtp_port')}")
                        print(f"Using TLS: {self.config.get('use_tls', True)}")
                        print(f"Sender Email: {self.config.get('sender_email')}")
                        return
                except json.JSONDecodeError as e:
                    print(f"Error: Invalid JSON in config file {path}: {e}")
                except Exception as e:
                    print(f"Error loading config from {path}: {str(e)}")
        
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
            # Create message with mixed type to support attachments
            msg = MIMEMultipart('mixed')
            msg['From'] = f"{self.config.get('sender_name', 'Sender')} <{self.config['sender_email']}>"
            msg['To'] = to
            msg['Subject'] = subject
            
            if cc:
                msg['Cc'] = cc
            
            # Create multipart/alternative for both HTML and plain text versions
            alt_part = MIMEMultipart('alternative')
            
            # Always attach plain text version first (fallback)
            plain_part = MIMEText(body, 'plain', 'utf-8')
            alt_part.attach(plain_part)
            
            # Add HTML version
            if html:
                html_content = body  # HTML content provided directly
            else:
                # Convert markdown to HTML with the 'nl2br' extension
                html_content = markdown.markdown(body, extensions=['nl2br'], output_format='html5')
            
            html_part = MIMEText(html_content, 'html', 'utf-8')
            alt_part.attach(html_part)
            
            # Add the alternative part to the main message
            msg.attach(alt_part)
            
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
            print(f"\nAttempting to connect to {self.config['smtp_server']}:{self.config['smtp_port']}...")
            with smtplib.SMTP(self.config['smtp_server'], self.config['smtp_port']) as server:
                if self.config.get('use_tls', True):
                    print("Starting TLS connection...")
                    server.starttls()
                
                print(f"Authenticating as {self.config['sender_email']}...")
                server.login(self.config['sender_email'], self.config['sender_password'])
                print("Authentication successful!")
                
                print(f"Sending email to {len(recipients)} recipient(s)...")
                server.send_message(msg, to_addrs=recipients)
                print("Email sent successfully!")
            
            return f"Email sent successfully to {to}"
            
        except smtplib.SMTPAuthenticationError as e:
            error_msg = f"Authentication failed: {str(e)}\nPlease check:\n1. Email address is correct\n2. App password is valid\n3. 2FA is enabled for your account"
            print(error_msg)
            return error_msg
        except smtplib.SMTPServerDisconnected as e:
            error_msg = f"Server connection error: {str(e)}\nPlease check:\n1. Internet connection\n2. SMTP server address\n3. SMTP port\n4. Firewall settings"
            print(error_msg)
            return error_msg
        except smtplib.SMTPException as e:
            error_msg = f"SMTP Error: {str(e)}\nPlease check SMTP server configuration and credentials"
            print(error_msg)
            return error_msg
        except Exception as e:
            error_msg = f"Error sending email: {str(e)}\nPlease check the full error message above for details"
            print(error_msg)
            return error_msg
    
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
    import argparse
    plugin = EmailPlugin()

    parser = argparse.ArgumentParser(description="Send an email using the EmailPlugin.")
    parser.add_argument('--to', required=True, help='Recipient email address (comma-separated for multiple)')
    parser.add_argument('--subject', required=True, help='Email subject')
    parser.add_argument('--body', required=True, help='Email body content')
    parser.add_argument('--html', action='store_true', help='Set if the body is HTML')
    parser.add_argument('--cc', help='CC recipients (comma-separated, optional)')
    parser.add_argument('--bcc', help='BCC recipients (comma-separated, optional)')
    parser.add_argument('--attachments', nargs='*', help='List of file paths to attach (optional)')

    args = parser.parse_args()

    if plugin.config and plugin.config.get('sender_email') != 'your_email@gmail.com':
        result = plugin.send_email(
            to=args.to,
            subject=args.subject,
            body=args.body,
            html=args.html,
            cc=args.cc,
            bcc=args.bcc,
            attachments=args.attachments
        )
        print(result)
    else:
        print("Please configure email_config.json with your Gmail credentials first.")