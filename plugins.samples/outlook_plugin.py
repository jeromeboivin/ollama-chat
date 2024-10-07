import win32com.client
import json
import os

class OutlookEmailManager:
    def __init__(self, folders=None):
        # If the folders parameter is not provided, read folders from a local JSON file
        folders_config_file = os.path.join(os.path.dirname(__file__), "outlook_folders.json")
        if not folders and os.path.exists(folders_config_file):
            with open(folders_config_file, "r") as f:
                folders = json.load(f)

        self.outlook = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
        self.folders = folders or ["Inbox"]
        self.outlook_folders = self._get_outlook_folders()

    def _get_outlook_folders(self):
        outlook_folders = {}
        for folder_name in self.folders:
            if folder_name.lower() == "inbox":
                outlook_folders[folder_name] = self.outlook.GetDefaultFolder(6)  # 6 represents the inbox folder
            else:
                root_folder = self.outlook.GetDefaultFolder(6)
                try:
                    outlook_folders[folder_name] = root_folder.Folders[folder_name]
                except Exception as e:
                    print(f"Folder '{folder_name}' not found: {e}")
        return outlook_folders

    def get_unread_emails(self):
        unread = []
        for folder_name, folder in self.outlook_folders.items():
            messages = folder.Items
            for message in messages:
                if message.UnRead:
                    unread.append({
                        'folder': folder_name,
                        'subject': message.Subject,
                        'sender': message.SenderName,
                        'date': message.ReceivedTime.Format("%Y-%m-%d %H:%M:%S"),
                        'body': message.Body
                    })
        return unread

    def send_email(self, to, subject, body):
        outlook = win32com.client.Dispatch("Outlook.Application")
        mail = outlook.CreateItem(0)  # 0 represents an email item
        mail.To = to
        mail.Subject = subject
        mail.Body = body
        mail.Send()

class OutlookEmailReaderPlugin:
    def __init__(self):
        self.plugin = OutlookEmailManager()

    def get_unread_emails(self):
        return self.plugin.get_unread_emails()
    
    def get_tool_definition(self):
        return {
            'type': 'function',
            'function': {
                'name': "get_unread_emails",
                'description': "Get unread emails",
                'parameters': {}
            }
        }
    
class OutlookEmailSenderPlugin:
    def __init__(self):
        self.plugin = OutlookEmailManager()

    def send_email(self, to, subject, body):
        self.plugin.send_email(to, subject, body)
    
    def get_tool_definition(self):
        return {
            'type': 'function',
            'function': {
                'name': "send_email",
                'description': "Send an email",
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'to': {
                            'type': 'string',
                            'description': 'The recipient email address',
                        },
                        'subject': {
                            'type': 'string',
                            'description': 'The email subject',
                        },
                        'body': {
                            'type': 'string',
                            'description': 'The email body',
                        }
                    }
                },
                'required': ['to', 'body']
            }
        }