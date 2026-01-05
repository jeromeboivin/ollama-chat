import json
from datetime import datetime
import os
import requests
import base64
import re
import uuid
import tempfile
from pathlib import Path
from bs4 import BeautifulSoup
from markdownify import markdownify as md
import mimetypes

'''
For the EcoleDirecteHomeworkPlugin to work correctly, create a JSON file located in the same directory.
Name it 'ecoledirecte_2fa_data.json', the JSON file should follow a specific structure.
Here's how it should be formatted, including scenario where different accounts are linked together:

[
    {
        "students": {
            "ID of kid 1": "Name of kid 1",
            "ID of kid 2": "Name of kid 2"
        },
        "student_ids": [
            "ID of kid 1"
        ],
        "linked_accounts": [
            {
                "student_ids": [
                    "ID of kid 2"
                ],
                "identifiant": "parent_linked_account_identifier"
            }
        ],
        "identifiant": "parent_account_identifier",
        "motdepasse": "parent_account_password",
        "isReLogin": false,
        "uuid": "",
        "fa": [
            {
                "cn": "second_factor_code_name",
                "cv": "second_factor_code_value"
            }
        ]
    }
]

You need to manually retrieve the second-factor authentication (`fa`) data from your browser's local storage, as 2FA is not implemented in the plugin.
Here’s how you can obtain the necessary `fa` information using Chrome Developer Tools:

### Steps to Access `fa` Data in Chrome:

1. **Open Chrome Developer Tools**:
   - Open Chrome and navigate to [https://www.ecoledirecte.com](https://www.ecoledirecte.com).
   - Press `F12` or right-click anywhere on the page and choose **Inspect** to open Developer Tools.

2. **Log in to EcoleDirecte**:
   - Log in to your EcoleDirecte account on the website with your usual credentials (email and password).
   - Complete the two-factor authentication (2FA) if required. This is necessary because the `fa` data is generated and stored after a successful login.

3. **Navigate to Local Storage**:
   - In the Developer Tools, go to the **Application** tab.
   - On the left-hand side, expand the **Storage** section and click on **Local Storage**.
   - Find and select the entry for **https://www.ecoledirecte.com**.

4. **Locate the `fa` Key**:
   - In the list of keys and values under Local Storage, look for the key named **`fa`**. 
   - The value stored under this key contains the necessary 2FA information that you will need to copy into the `ecoledirecte_2fa_data.json` file for the plugin.

5. **Copy the `fa` Data**:
   - Right-click on the **`fa`** key and select **Copy value**.
   - This value is typically a JSON string that looks something like this:
     ```json
     [{"cn": "your_code_name", "cv": "your_code_value"}]
     ```

6. **Paste the `fa` Data into `ecoledirecte_2fa_data.json`**:
   - Open your `ecoledirecte_2fa_data.json` file in a text editor.
   - Locate the `"fa"` section, which should look like this:
     ```json
     "fa": [
       {
         "cn": "...",
         "cv": "..."
       }
     ]
     ```
   - Replace the `"cn"` and `"cv"` fields with the values you copied from Chrome’s local storage.

### Why You Need to Do This:
- The plugin doesn’t implement 2FA directly, so you need to authenticate manually in the browser first.
- Once authenticated, the `fa` data is stored in your browser’s local storage under the `fa` key. This data is essential for the plugin to perform further authenticated API calls without needing you to re-login every time.

By following these steps, you’ll ensure that the plugin has the necessary 2FA credentials to work seamlessly with the EcoleDirecte API.
'''

class Homework:
    def __init__(self, subject, id_devoir, due_date, assigned_on, completed, is_test, submit_online, requires_documents, content=None, documents=None):
        # Check if the due_date is overdue before initializing
        self.due_date = datetime.strptime(due_date, "%Y-%m-%d").date() if due_date else None
        today = datetime.now().date()
        if self.due_date and self.due_date <= today:
            raise ValueError(f"Overdue homework on {self.due_date}.")

        self.subject = subject
        self.id_devoir = id_devoir
        self.assigned_on = assigned_on
        self.completed = completed
        self.is_test = is_test
        self.submit_online = submit_online
        self.requires_documents = requires_documents
        self.content = content
        self.documents = documents or []

    @staticmethod
    def decode_base64_content(encoded_content):
        if encoded_content:
            decoded_bytes = base64.b64decode(encoded_content)
            return decoded_bytes.decode('utf-8')
        return None

    @staticmethod
    def convert_html_to_markdown(html_content, temp_path=None, strip_images=True):
        """
        Converts HTML content to Markdown format, optionally extracting images.
        
        :param html_content: The HTML content to convert
        :param temp_path: Path to save extracted images (default: system temp directory)
        :param strip_images: If True, remove images; if False, extract and reference them
        :return: Markdown content with base64 images removed or replaced with references
        """
        if not html_content:
            return None
        try:
            # Parse HTML to extract and replace base64 images
            soup = BeautifulSoup(html_content, 'html.parser')
            image_counter = 0
            
            # Find all img tags with base64 data
            for img_tag in soup.find_all('img'):
                src = img_tag.get('src', '')
                
                # Check if it's a base64 data URL
                if src.startswith('data:'):
                    if strip_images:
                        # Remove the image entirely
                        img_tag.decompose()
                    else:
                        # Extract and save the image
                        image_data = Homework._extract_and_save_image(
                            src, temp_path, image_counter
                        )
                        if image_data:
                            image_path, image_name = image_data
                            # Replace src with local path reference
                            img_tag['src'] = image_path
                            image_counter += 1
            
            # Convert the modified HTML to Markdown
            markdown_content = md(str(soup))
            # Clean up excessive whitespace
            markdown_content = '\n'.join(line.rstrip() for line in markdown_content.split('\n'))
            return markdown_content.strip()
        except Exception as e:
            print(f"Error converting HTML to Markdown: {e}")
            return html_content

    @staticmethod
    def _extract_and_save_image(data_url, temp_path=None, counter=0):
        """
        Extracts a base64 encoded image from a data URL and saves it to disk.
        
        :param data_url: The data URL containing base64 image data
        :param temp_path: Path to save the image (default: system temp directory)
        :param counter: Counter for unique naming
        :return: Tuple of (relative_path, image_name) or None if extraction fails
        """
        try:
            # Parse the data URL
            match = re.match(r'data:([^;]+);base64,(.+)', data_url)
            if not match:
                return None
            
            mime_type = match.group(1)
            base64_data = match.group(2)
            
            # Determine file extension from MIME type
            extension_map = {
                'image/jpeg': 'jpg',
                'image/png': 'png',
                'image/gif': 'gif',
                'image/webp': 'webp',
                'image/svg+xml': 'svg',
            }
            extension = extension_map.get(mime_type, 'png')
            
            # Create temp directory if not provided
            if temp_path is None:
                temp_path = tempfile.gettempdir()
            
            # Ensure the temp path exists
            Path(temp_path).mkdir(parents=True, exist_ok=True)
            
            # Generate unique filename
            image_name = f"image_{uuid.uuid4().hex[:8]}.{extension}"
            image_full_path = os.path.join(temp_path, image_name)
            
            # Decode and save the image
            image_data = base64.b64decode(base64_data)
            with open(image_full_path, 'wb') as f:
                f.write(image_data)
            
            # Return relative path for Markdown
            return (image_name, image_name)
        except Exception as e:
            print(f"Error extracting and saving image: {e}")
            return None

    @staticmethod
    def _extract_and_save_document(data_url, temp_path=None, doc_counter=0):
        """
        Extracts a base64 encoded document from a data URL and saves it to disk.
        
        Supports: PDF, DOCX, XLSX, PPTX, DOC, XLS, PPT
        
        :param data_url: The data URL containing base64 document data
        :param temp_path: Path to save the document (default: system temp directory)
        :param doc_counter: Counter for unique naming
        :return: Tuple of (relative_path, document_name) or None if extraction fails
        """
        try:
            # Parse the data URL
            match = re.match(r'data:([^;]+);base64,(.+)', data_url)
            if not match:
                return None
            
            mime_type = match.group(1)
            base64_data = match.group(2)
            
            # Determine file extension from MIME type
            extension_map = {
                'application/pdf': 'pdf',
                'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'docx',
                'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'xlsx',
                'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'pptx',
                'application/msword': 'doc',
                'application/vnd.ms-excel': 'xls',
                'application/vnd.ms-powerpoint': 'ppt',
                'application/x-msexcel': 'xls',
                'application/x-mspowerpoint': 'ppt',
            }
            extension = extension_map.get(mime_type, 'bin')
            
            # Create temp directory if not provided
            if temp_path is None:
                temp_path = tempfile.gettempdir()
            
            # Ensure the temp path exists
            Path(temp_path).mkdir(parents=True, exist_ok=True)
            
            # Generate unique filename
            doc_name = f"document_{uuid.uuid4().hex[:8]}.{extension}"
            doc_full_path = os.path.join(temp_path, doc_name)
            
            # Decode and save the document
            doc_data = base64.b64decode(base64_data)
            with open(doc_full_path, 'wb') as f:
                f.write(doc_data)
            
            # Return relative path for Markdown
            return (doc_name, doc_name)
        except Exception as e:
            print(f"Error extracting and saving document: {e}")
            return None

    @staticmethod
    def _extract_documents_from_html(html_content, temp_path=None, strip_documents=True):
        """
        Extracts and handles base64 documents embedded in HTML.
        
        :param html_content: HTML content to process
        :param temp_path: Path to save documents
        :param strip_documents: If True, remove documents; if False, extract them
        :return: Modified HTML with base64 documents handled
        """
        if not html_content:
            return html_content
        
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            doc_counter = 0
            
            # Find all links and embedded objects with base64 data
            for link_tag in soup.find_all('a'):
                href = link_tag.get('href', '')
                
                if href.startswith('data:'):
                    # Check if it looks like a document MIME type
                    mime_type = href.split(';')[0].replace('data:', '')
                    if any(doc_mime in mime_type for doc_mime in [
                        'pdf', 'word', 'document', 'spreadsheet', 'excel', 
                        'presentation', 'powerpoint', 'msexcel', 'mspowerpoint'
                    ]):
                        if strip_documents:
                            # Remove the link
                            link_tag.decompose()
                        else:
                            # Extract and save the document
                            doc_data = Homework._extract_and_save_document(
                                href, temp_path, doc_counter
                            )
                            if doc_data:
                                doc_path, doc_name = doc_data
                                # Replace with a markdown reference
                                link_tag['href'] = doc_path
                                if not link_tag.get_text():
                                    link_tag.string = f"[Document: {doc_name}]"
                                doc_counter += 1
            
            # Also handle script tags that might contain embedded documents
            for script_tag in soup.find_all('script', {'type': 'application/json'}):
                # Skip for now - would need more complex parsing
                pass
            
            return str(soup)
        except Exception as e:
            print(f"Error processing documents in HTML: {e}")
            return html_content

    @classmethod
    def from_api_response(cls, assignment_data, due_date, detailed_data=None, temp_path=None, strip_images=True, strip_documents=True):
        content = None
        documents = None

        if detailed_data and detailed_data.get('code') == 200:
            # Create a dictionary mapping matiere code to details for fast lookup
            matiere_details = {matiere['codeMatiere']: matiere for matiere in detailed_data['data'].get('matieres', [])}

            # Find the matching detailed data for the assignment
            detailed_matiere = matiere_details.get(assignment_data['codeMatiere'])

            if detailed_matiere and detailed_matiere.get('aFaire'):
                contenu = detailed_matiere['aFaire'].get('contenu')
                if contenu:
                    # Decode base64 content
                    decoded_content = cls.decode_base64_content(contenu)
                    # Extract documents first (before converting to Markdown)
                    if decoded_content:
                        decoded_content = cls._extract_documents_from_html(
                            decoded_content,
                            temp_path=temp_path,
                            strip_documents=strip_documents
                        )
                    # Convert HTML to Markdown
                    if decoded_content:
                        content = cls.convert_html_to_markdown(
                            decoded_content, 
                            temp_path=temp_path, 
                            strip_images=strip_images
                        )
                documents = detailed_matiere.get('aFaire', {}).get('documents', [])

        try:
            return cls(
                subject=assignment_data['matiere'],
                id_devoir=assignment_data['idDevoir'],
                due_date=due_date,
                assigned_on=assignment_data['donneLe'],
                completed=assignment_data['effectue'],
                is_test=assignment_data['interrogation'],
                submit_online=assignment_data['rendreEnLigne'],
                requires_documents=assignment_data['documentsAFaire'],
                content=content,
                documents=documents
            )
        except ValueError:
            # If the homework is overdue, skip instantiation
            return None


    def to_dict(self):
        """Convert Homework object to dictionary for easy display or export."""
        return {
            'subject': self.subject,
            'id_devoir': self.id_devoir,
            'due_date': self.due_date.strftime("%Y-%m-%d"),
            'assigned_on': self.assigned_on,
            'completed': self.completed,
            'is_test': self.is_test,
            'submit_online': self.submit_online,
            'requires_documents': self.requires_documents,
            'content': self.content,
            'documents': self.documents
        }

class EcoleDirecteAPI:
    def __init__(self, student_id: int):
        self.student_id = student_id
        self.linked_accounts = []
        self.token = None
        self.renew_token = False
        self.base_url = None
        
        self.credentials = None
        self.token = None
        self.headers = None
        self.payload = 'data={}'
        self.verbose = False

    @staticmethod
    def convert_html_to_markdown(html_content, temp_path=None, strip_images=True):
        """
        Converts HTML content to Markdown format, optionally extracting images.
        
        :param html_content: The HTML content to convert
        :param temp_path: Path to save extracted images (default: system temp directory)
        :param strip_images: If True, remove images; if False, extract and reference them
        :return: Markdown content with base64 images removed or replaced with references
        """
        if not html_content:
            return None
        try:
            # Parse HTML to extract and replace base64 images
            soup = BeautifulSoup(html_content, 'html.parser')
            image_counter = 0
            
            # Find all img tags with base64 data
            for img_tag in soup.find_all('img'):
                src = img_tag.get('src', '')
                
                # Check if it's a base64 data URL
                if src.startswith('data:'):
                    if strip_images:
                        # Remove the image entirely
                        img_tag.decompose()
                    else:
                        # Extract and save the image
                        image_data = EcoleDirecteAPI._extract_and_save_image(
                            src, temp_path, image_counter
                        )
                        if image_data:
                            image_path, image_name = image_data
                            # Replace src with local path reference
                            img_tag['src'] = image_path
                            image_counter += 1
            
            # Convert the modified HTML to Markdown
            markdown_content = md(str(soup))
            # Clean up excessive whitespace
            markdown_content = '\n'.join(line.rstrip() for line in markdown_content.split('\n'))
            return markdown_content.strip()
        except Exception as e:
            print(f"Error converting HTML to Markdown: {e}")
            return html_content

    @staticmethod
    def _extract_and_save_image(data_url, temp_path=None, counter=0):
        """
        Extracts a base64 encoded image from a data URL and saves it to disk.
        
        :param data_url: The data URL containing base64 image data
        :param temp_path: Path to save the image (default: system temp directory)
        :param counter: Counter for unique naming
        :return: Tuple of (relative_path, image_name) or None if extraction fails
        """
        try:
            # Parse the data URL
            match = re.match(r'data:([^;]+);base64,(.+)', data_url)
            if not match:
                return None
            
            mime_type = match.group(1)
            base64_data = match.group(2)
            
            # Determine file extension from MIME type
            extension_map = {
                'image/jpeg': 'jpg',
                'image/png': 'png',
                'image/gif': 'gif',
                'image/webp': 'webp',
                'image/svg+xml': 'svg',
            }
            extension = extension_map.get(mime_type, 'png')
            
            # Create temp directory if not provided
            if temp_path is None:
                temp_path = tempfile.gettempdir()
            
            # Ensure the temp path exists
            Path(temp_path).mkdir(parents=True, exist_ok=True)
            
            # Generate unique filename
            image_name = f"image_{uuid.uuid4().hex[:8]}.{extension}"
            image_full_path = os.path.join(temp_path, image_name)
            
            # Decode and save the image
            image_data = base64.b64decode(base64_data)
            with open(image_full_path, 'wb') as f:
                f.write(image_data)
            
            # Return relative path for Markdown
            return (image_name, image_name)
        except Exception as e:
            print(f"Error extracting and saving image: {e}")
            return None

    @staticmethod
    def _extract_and_save_document(data_url, temp_path=None, doc_counter=0):
        """
        Extracts a base64 encoded document from a data URL and saves it to disk.
        
        Supports: PDF, DOCX, XLSX, PPTX, DOC, XLS, PPT
        
        :param data_url: The data URL containing base64 document data
        :param temp_path: Path to save the document (default: system temp directory)
        :param doc_counter: Counter for unique naming
        :return: Tuple of (relative_path, document_name) or None if extraction fails
        """
        try:
            # Parse the data URL
            match = re.match(r'data:([^;]+);base64,(.+)', data_url)
            if not match:
                return None
            
            mime_type = match.group(1)
            base64_data = match.group(2)
            
            # Determine file extension from MIME type
            extension_map = {
                'application/pdf': 'pdf',
                'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'docx',
                'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'xlsx',
                'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'pptx',
                'application/msword': 'doc',
                'application/vnd.ms-excel': 'xls',
                'application/vnd.ms-powerpoint': 'ppt',
                'application/x-msexcel': 'xls',
                'application/x-mspowerpoint': 'ppt',
            }
            extension = extension_map.get(mime_type, 'bin')
            
            # Create temp directory if not provided
            if temp_path is None:
                temp_path = tempfile.gettempdir()
            
            # Ensure the temp path exists
            Path(temp_path).mkdir(parents=True, exist_ok=True)
            
            # Generate unique filename
            doc_name = f"document_{uuid.uuid4().hex[:8]}.{extension}"
            doc_full_path = os.path.join(temp_path, doc_name)
            
            # Decode and save the document
            doc_data = base64.b64decode(base64_data)
            with open(doc_full_path, 'wb') as f:
                f.write(doc_data)
            
            # Return relative path for Markdown
            return (doc_name, doc_name)
        except Exception as e:
            print(f"Error extracting and saving document: {e}")
            return None

    @staticmethod
    def _extract_documents_from_html(html_content, temp_path=None, strip_documents=True):
        """
        Extracts and handles base64 documents embedded in HTML.
        
        :param html_content: HTML content to process
        :param temp_path: Path to save documents
        :param strip_documents: If True, remove documents; if False, extract them
        :return: Modified HTML with base64 documents handled
        """
        if not html_content:
            return html_content
        
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            doc_counter = 0
            
            # Find all links and embedded objects with base64 data
            for link_tag in soup.find_all('a'):
                href = link_tag.get('href', '')
                
                if href.startswith('data:'):
                    # Check if it looks like a document MIME type
                    mime_type = href.split(';')[0].replace('data:', '')
                    if any(doc_mime in mime_type for doc_mime in [
                        'pdf', 'word', 'document', 'spreadsheet', 'excel', 
                        'presentation', 'powerpoint', 'msexcel', 'mspowerpoint'
                    ]):
                        if strip_documents:
                            # Remove the link
                            link_tag.decompose()
                        else:
                            # Extract and save the document
                            doc_data = EcoleDirecteAPI._extract_and_save_document(
                                href, temp_path, doc_counter
                            )
                            if doc_data:
                                doc_path, doc_name = doc_data
                                # Replace with a markdown reference
                                link_tag['href'] = doc_path
                                if not link_tag.get_text():
                                    link_tag.string = f"[Document: {doc_name}]"
                                doc_counter += 1
            
            return str(soup)
        except Exception as e:
            print(f"Error processing documents in HTML: {e}")
            return html_content

    def get_base_url(self):
        if not self.base_url:
            self.base_url = 'https://api.ecoledirecte.com/v3'
            self.credentials = self.load_credentials()
            self.token = self.login()
            self.headers = self.build_headers()

        return self.base_url

    def load_credentials(self):
        """Loads credentials from the ecoledirecte_2fa_data.json file or from input."""
        try:
            auth_file = 'ecoledirecte_2fa_data.json'
            if not os.path.exists(auth_file):
                auth_file = os.path.join(os.path.dirname(__file__), auth_file)
            with open(auth_file, 'r') as file:
                data = json.load(file)
                # Search for credentials associated with the current student_id
                for entry in data:
                    if str(self.student_id) in entry['student_ids']:
                        return entry
                    for linked_account in entry.get('linked_accounts', []):
                        if str(self.student_id) in linked_account['student_ids']:
                            self.renew_token = True
                            return entry
        except FileNotFoundError:
            raise FileNotFoundError("ecoledirecte_2fa_data.json not found.")
        raise ValueError(f"Credentials for student ID {self.student_id} not found.")

    def login(self):
        """Logs in to the API and retrieves the initial token."""
        login_data = {
            "identifiant": self.credentials['identifiant'],
            "motdepasse": self.credentials['motdepasse'],
            "isReLogin": self.credentials['isReLogin'],
            "uuid": self.credentials['uuid'],
            "fa": self.credentials['fa']
        }
    
        payload = f'data={json.dumps(login_data)}'
    
        if self.verbose:
            print(f"Logging in with credentials: {login_data}")
    
        login_url_initial = f'{self.base_url}/login.awp?gtk=1&v=4.76.0'
        login_url = f'{self.base_url}/login.awp?v=4.76.0'
    
        try:
            # Use a session to persist cookies
            with requests.Session() as session:
                # Initial call to set the cookie
                initial_response = session.get(login_url_initial, headers=self.build_headers())
                initial_response.raise_for_status()
    
                # Extract the GTK cookie value
                gtk_cookie = initial_response.cookies.get('GTK')
                if not gtk_cookie:
                    raise Exception("GTK cookie not found in the initial response.")
    
                if self.verbose:
                    print(f"Initial login response (cookie set): {initial_response.cookies}")
                    print(f"Extracted GTK cookie: {gtk_cookie}")
    
                # Add the X-Gtk header for the second call
                headers = self.build_headers()
                headers['X-Gtk'] = gtk_cookie
    
                # Second call to log in
                response = session.post(login_url, headers=headers, data=payload)
                response.raise_for_status()
    
                login_response = response.json()
    
                if self.verbose:
                    print(f"Login response: {login_response}")
    
                if login_response.get('code') == 200:
                    token = login_response.get('token')
                    self.store_linked_accounts(login_response.get('data', {}).get('accounts', []))
                    return token
                else:
                    raise Exception(f"Login failed: {login_response.get('message', 'Unknown error')}")
        except requests.exceptions.RequestException as e:
            print(f"An error occurred during login: {e}")
            return None

    def store_linked_accounts(self, accounts):
        """Store linked accounts from the login response."""
        if accounts:
            for account in accounts:
                # Append linked account info
                self.linked_accounts.append(account)

    def renew_token_for_linked_account(self, id_login):
        """Renew the token for a linked account using idLogin."""
        renew_url = f'{self.get_base_url()}/renewtoken.awp?verbe=post&v=4.76.0'
        payload = {
            "idUser": id_login,
            "uuid": ""
        }

        try:
            response = requests.post(renew_url, headers=self.headers, data=f'data={json.dumps(payload)}')
            response.raise_for_status()
            renew_response = response.json()

            if renew_response.get('code') == 200:
                new_token = renew_response.get('token')
                self.update_token_in_headers(new_token)
                return new_token
            else:
                raise Exception(f"Token renewal failed: {renew_response.get('message', 'Unknown error')}")
        except requests.exceptions.RequestException as e:
            print(f"An error occurred during token renewal: {e}")
            return None

    def build_headers(self):
        """Build the headers using the current token, if available."""
        headers = {
            'accept': 'application/json, text/plain, */*',
            'accept-language': 'en-US,en;q=0.9,fr-FR;q=0.8,fr;q=0.7',
            'content-type': 'application/x-www-form-urlencoded',
            'origin': 'https://www.ecoledirecte.com',
            'priority': 'u=1, i',
            'referer': 'https://www.ecoledirecte.com/',
            'sec-ch-ua': '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-site',
            'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
        }
        if self.token:
            headers['x-token'] = self.token

        return headers

    def update_token_in_headers(self, new_token):
        """Update the token in the headers after renewal."""
        self.headers['x-token'] = new_token

    def update_token_from_response(self, response_headers):
        """Update the token from the server response's 'x-token' HTTP header and use it."""
        new_token = response_headers.get('x-token')
        if new_token:
            self.token = new_token
            self.update_token_in_headers(new_token)

    def get_homework(self):
        """Fetches the homework for the student."""
        url = f'{self.get_base_url()}/Eleves/{self.student_id}/cahierdetexte.awp'
        self.check_linked_account()
        params = {'verbe': 'get', 'v': '4.76.0'}
        try:
            response = requests.post(url, headers=self.headers, data=self.payload, params=params)
            response.raise_for_status()
            # Update token from the response headers
            self.update_token_from_response(response.headers)
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"An error occurred: {e}")
            return None

    def get_family_id(self):
        for account in self.linked_accounts:
            # Check if the student_id exists in the 'eleves' array inside the 'profile' property
            for eleve in account.get('profile', {}).get('eleves', []):
                if str(self.student_id) == str(eleve.get('id')):  # Compare with 'id' in 'eleves'
                    return account['id']

        return None

    def compute_annee_messages(self):
        current_date = datetime.now()
        current_year = current_date.year
        current_month = current_date.month

        if current_month >= 9:  # From September to December
            return f"{current_year}-{current_year + 1}"
        else:  # From January to August
            return f"{current_year - 1}-{current_year}"

    def get_received_messages(self, latest_n=5, temp_path=None, strip_images=True, strip_documents=True):
        """
        Fetches the latest received messages and their details.
        
        :param latest_n: Number of latest messages to retrieve.
        :param temp_path: Path to save extracted files (default: system temp directory)
        :param strip_images: If True, remove images; if False, extract and reference them
        :param strip_documents: If True, remove documents; if False, extract and reference them
        :return: List of detailed message objects with decoded content.
        """
        base_url = self.get_base_url()
        self.check_linked_account()

        # Fetch the list of received messages
        url = f"{base_url}/familles/{self.get_family_id()}/messages.awp"
        headers = {
            'accept': 'application/json, text/plain, */*',
            'content-type': 'application/x-www-form-urlencoded',
            'x-token': self.token,
        }
        data = {
            "anneeMessages": self.compute_annee_messages()
        }
        params = {
            'force': 'false',
            'typeRecuperation': 'received',
            'idClasseur': '0',
            'orderBy': 'date',
            'order': 'desc',
            'query': '',
            'onlyRead': '',
            'page': '0',
            'itemsPerPage': '100',
            'getAll': '0',
            'verbe': 'get',
            'v': '4.76.0'
        }

        response = requests.post(url, headers=self.headers, data={"data": json.dumps(data)}, params=params)
        response.raise_for_status()
        # Update token from the response headers
        self.update_token_from_response(response.headers)

        if response.status_code == 200:
            # Retrieve the latest received messages (limited by latest_n)
            messages = response.json().get('data', {}).get('messages', {}).get('received', [])
            message_ids = [msg['id'] for msg in messages[:latest_n]]
            
            # Fetch detailed information for each message
            return self.get_message_details(
                message_ids, 
                temp_path=temp_path, 
                strip_images=strip_images,
                strip_documents=strip_documents
            )
        else:
            raise Exception("Failed to retrieve messages.")

    def get_message_details(self, message_ids, temp_path=None, strip_images=True, strip_documents=True):
        """
        Retrieves details for each message based on the provided message_ids.
        Decodes the content field from base64.
        
        :param message_ids: List of message IDs to retrieve.
        :param temp_path: Path to save extracted files (default: system temp directory)
        :param strip_images: If True, remove images; if False, extract and reference them
        :param strip_documents: If True, remove documents; if False, extract and reference them
        :return: List of detailed message objects with decoded content.
        """
        base_url = self.get_base_url()
        self.check_linked_account()

        message_details = []
        base_url = f"{base_url}/familles/{self.get_family_id()}/messages"
        
        headers = {
            'accept': 'application/json, text/plain, */*',
            'content-type': 'application/x-www-form-urlencoded',
            'x-token': self.token,
        }

        for message_id in message_ids:
            try:
                url = f"{base_url}/{message_id}.awp?verbe=get&mode=destinataire&v=4.61.0"
                data = {
                    "anneeMessages": self.compute_annee_messages()
                }

                response = requests.post(url, headers=self.headers, data={"data": json.dumps(data)})
                response.raise_for_status()
                # Update token from the response headers
                self.update_token_from_response(response.headers)

                # Parse the JSON response
                message_data = response.json()

                if message_data.get('code') == 200:
                    detailed_message = message_data.get('data', {})
                    # Decode base64 content if present
                    content_encoded = detailed_message.get('content', '')
                    if content_encoded:
                        content_decoded = base64.b64decode(content_encoded).decode('utf-8')
                        # Extract documents first (before converting to Markdown)
                        content_decoded = self._extract_documents_from_html(
                            content_decoded,
                            temp_path=temp_path,
                            strip_documents=strip_documents
                        )
                        # Convert the decoded content from HTML to Markdown
                        content_markdown = self.convert_html_to_markdown(
                            content_decoded,
                            temp_path=temp_path,
                            strip_images=strip_images
                        )
                        detailed_message['content'] = content_markdown
                    
                    message_details.append(detailed_message)
                else:
                    print(f"Failed to retrieve message {message_id}: {message_data.get('message', 'Unknown error')}")

            except requests.exceptions.RequestException as e:
                print(f"An error occurred while retrieving message {message_id}: {e}")
        
        return message_details

    def check_linked_account(self):
        if self.renew_token:
            for account in self.linked_accounts:
                # Check if the student_id exists in the 'eleves' array inside the 'profile' property
                for eleve in account.get('profile', {}).get('eleves', []):
                    if str(self.student_id) == str(eleve.get('id')):  # Compare with 'id' in 'eleves'
                        # Pass the correct 'idLogin' to renew_token_for_linked_account
                        new_token = self.renew_token_for_linked_account(account['idLogin'])
                        if new_token:
                            if self.verbose:
                                print(f"Token successfully renewed: {new_token}")
                            self.token = new_token
                            self.renew_token = False
                        return  # Exit after finding the correct linked account


    def get_homework_details_for_date(self, due_date: str):
        """Fetches detailed homework for a specific due date."""
        url = f'{self.get_base_url()}/Eleves/{self.student_id}/cahierdetexte/{due_date}.awp'
        self.check_linked_account()
        params = {'verbe': 'get', 'v': '4.76.0'}
        try:
            response = requests.post(url, headers=self.headers, data=self.payload, params=params)
            response.raise_for_status()
            # Update token from the response headers
            self.update_token_from_response(response.headers)
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"An error occurred while fetching details for {due_date}: {e}")
            return None

    def parse_homework(self, response, temp_path=None, strip_images=True, strip_documents=True, include_past=False):
        """
        Parses the main homework list and creates Homework objects.
        
        :param response: API response data
        :param temp_path: Path to save extracted files (default: system temp directory)
        :param strip_images: If True, remove images; if False, extract and reference them
        :param strip_documents: If True, remove documents; if False, extract and reference them
        :param include_past: If True, include past homework; if False, only upcoming homework
        """
        if response and response.get('code') == 200:
            homework_data = response.get('data', {})
            parsed_homework = []
            today = datetime.now().date()

            for date, assignments in homework_data.items():
                # Filter by date based on include_past flag
                due_date = datetime.strptime(date, "%Y-%m-%d").date()
                if not include_past and due_date <= today:
                    continue  # Skip overdue homework if include_past is False

                for assignment in assignments:
                    # Fetch detailed information for the due_date
                    detailed_info = self.get_homework_details_for_date(date)

                    # Create Homework object from API response
                    homework = Homework.from_api_response(
                        assignment, 
                        date, 
                        detailed_info,
                        temp_path=temp_path,
                        strip_images=strip_images,
                        strip_documents=strip_documents
                    )
                    if homework:
                        parsed_homework.append(homework)

            return parsed_homework
        else:
            print("Failed to parse the response.")
            return None

class EcoleDirecteHomeworkPlugin:
    def __init__(self):
        # Load data from ecoledirecte_2fa_data.json
        self.load_student_data()

        # Create instances of EcoleDirecteAPI for each student
        self.api_instances = {student_id: EcoleDirecteAPI(int(student_id)) for student_id in self.students}
        
        # Configuration options for resource handling
        self.temp_path = None
        self.strip_images = True
        self.strip_documents = True

    def load_student_data(self):
        """
        Loads student data from the ecoledirecte_2fa_data.json file.
        """
        file_path = os.path.join(os.path.dirname(__file__), 'ecoledirecte_2fa_data.json')
        with open(file_path, 'r') as f:
            data = json.load(f)
            self.students = data[0]['students']  # Load the "students" section

    def get_tool_definition(self):
        """
        Defines the plugin's available functions for retrieving homework.
        """
        return {
            'type': 'function',
            'function': {
                'name': 'get_homework_from_ecoledirecte',
                'description': 'Retrieve homework for a specified child or for all children if no name is provided, from French web site www.ecoledirecte.com.',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'kid_name': {
                            'type': 'string',
                            'description': 'The name of the kid',
                            'enum': list(self.students.values()),  # restrict to the names loaded from JSON
                            'optional': True  # This allows it to be omitted
                        },
                        'include_past': {
                            'type': 'boolean',
                            'description': 'If True, include homework from the past. If False, only retrieve upcoming homework (default).',
                            'default': False,
                            'optional': True
                        }
                    },
                },
            }
        }

    def on_user_input_done(self, user_input, verbose_mode=False):
        return None

    def get_homework_from_ecoledirecte(self, kid_name=None, include_past=False):
        """
        Retrieves homework for the specified child or for all students if no name is provided.
        
        :param kid_name: Name of the specific child (optional)
        :param include_past: If True, include past homework; if False, only upcoming homework
        """
        if kid_name is None:
            # Fetch homework for all students
            homework_results = {name: self.get_homework_by_kid(name, include_past) for name in self.students.values()}
            return homework_results
        else:
            # Fetch homework for the specified student
            return self.get_homework_by_kid(kid_name, include_past)

    def get_homework_by_kid(self, kid_name=None, include_past=False):
        """
        Retrieves homework for a specified student by name.
        
        :param kid_name: Name of the student
        :param include_past: If True, include past homework
        """
        for student_id, name in self.students.items():
            if name.lower() == kid_name.lower():
                # Fetch homework for the matched student
                api_instance = self.api_instances[student_id]
                response = api_instance.get_homework()
                if response:
                    return self.parse_and_return_homework(api_instance, response, include_past)
                else:
                    return json.dumps(f"No homework data found for {name}.")
        return json.dumps("Invalid kid name provided.")

    def parse_and_return_homework(self, api, response, include_past=False):
        """
        Parses the response data and returns a list of formatted homework.
        
        :param api: EcoleDirecteAPI instance
        :param response: API response data
        :param include_past: If True, include past homework
        """
        parsed_homework = api.parse_homework(
            response, 
            temp_path=self.temp_path, 
            strip_images=self.strip_images,
            strip_documents=self.strip_documents,
            include_past=include_past
        )
        homework_list = []

        for homework in parsed_homework:
            if homework:
                homework_dict = homework.to_dict()
                homework_list.append(homework_dict)

        if homework_list:
            # Return homework as JSON string
            message = "All homework" if include_past else "Upcoming homework"
            return json.dumps({"type": message, "data": homework_list}, indent=4)
        else:
            message = "No homework found." if include_past else "No upcoming homework found."
            return json.dumps(message)

    def is_homework_overdue(self, homework):
        """
        Checks if the homework is overdue.
        """
        due_date = homework.get("due_date")
        if due_date:
            due_date_obj = datetime.strptime(due_date, "%Y-%m-%d")
            return due_date_obj <= datetime.now()  # Homework is overdue if the due date is in the past
        return False

class EcoleDirecteMessagesPlugin:
    def __init__(self):
        # Load data from ecoledirecte_2fa_data.json
        self.load_student_data()

        # Create instances of EcoleDirecteAPI for each student
        self.api_instances = {student_id: EcoleDirecteAPI(int(student_id)) for student_id in self.students}
        
        # Configuration options for resource handling
        self.temp_path = None
        self.strip_images = True
        self.strip_documents = True

    def load_student_data(self):
        """
        Loads student data from the ecoledirecte_2fa_data.json file.
        """
        file_path = os.path.join(os.path.dirname(__file__), 'ecoledirecte_2fa_data.json')
        with open(file_path, 'r') as f:
            data = json.load(f)
            self.students = data[0]['students']  # Load the "students" section

    def get_tool_definition(self):
        """
        Defines the plugin's available functions for retrieving messages.
        """
        return {
            'type': 'function',
            'function': {
                'name': 'get_messages_from_ecoledirecte',
                'description': 'Retrieve the latest messages for a specified child or for all children if no name is provided, from www.ecoledirecte.com.',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'kid_name': {
                            'type': 'string',
                            'description': 'The name of the kid',
                            'enum': list(self.students.values()),  # restrict to the names loaded from JSON
                            'optional': True  # This allows it to be omitted
                        },
                        'latest_n': {
                            'type': 'integer',
                            'description': 'The number of latest messages to retrieve (default is 5).',
                            'default': 5,
                            'optional': True
                        }
                    },
                },
            }
        }

    def on_user_input_done(self, user_input, verbose_mode=False):
        return None

    def get_messages_from_ecoledirecte(self, kid_name=None, latest_n=5):
        """
        Retrieves the latest messages for the specified child or for all students if no name is provided.
        """
        if kid_name is None:
            # Fetch messages for all students
            message_results = {name: self.get_messages_by_kid(name, latest_n) for name in self.students.values()}
            return message_results
        else:
            # Fetch messages for the specified student
            return self.get_messages_by_kid(kid_name, latest_n)

    def get_messages_by_kid(self, kid_name=None, latest_n=5):
        """
        Retrieves the latest messages for a specified student by name.
        """
        for student_id, name in self.students.items():
            if name.lower() == kid_name.lower():
                # Fetch messages for the matched student
                api_instance = self.api_instances[student_id]
                response = api_instance.get_received_messages(
                    latest_n, 
                    temp_path=self.temp_path, 
                    strip_images=self.strip_images,
                    strip_documents=self.strip_documents
                )
                if response:
                    return self.parse_and_return_messages(response)
                else:
                    return json.dumps(f"No message data found for {name}.")
        return json.dumps("Invalid kid name provided.")

    def parse_and_return_messages(self, message_details):
        """
        Parses the response data and returns a list of formatted messages.
        """
        message_list = []

        for message in message_details:
            if message:
                message_dict = {
                    "subject": message.get("subject"),
                    "content": message.get("content"),
                    "date": message.get("date"),
                    "sender": message.get("from", {}).get("name"),
                    "read": message.get("read"),
                    "answered": message.get("answered")
                }
                message_list.append(message_dict)

        if message_list:
            # Return messages as JSON string
            return json.dumps(message_list, indent=4)
        else:
            return json.dumps("No recent messages found.")
