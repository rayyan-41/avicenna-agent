import os
import os.path
import base64
from pathlib import Path
from typing import Optional
from email.message import EmailMessage
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Define the permission scope (Sending emails only)
SCOPES = ['https://www.googleapis.com/auth/gmail.send']

# Secure storage location in user's home directory
AVICENNA_DIR = Path.home() / '.avicenna'
AVICENNA_DIR.mkdir(exist_ok=True)  # Create directory if it doesn't exist

TOKEN_PATH = AVICENNA_DIR / 'gmail_token.json'
CREDENTIALS_PATH = Path('credentials.json')  # Still in project root for now

class GmailTool:
    def __init__(self) -> None:
        self.creds: Optional[Credentials] = None
        self.sender_email: str = 'me'
        
        # token.json is now stored in ~/.avicenna/ for security
        if TOKEN_PATH.exists():
            self.creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
            
        # If there are no (valid) credentials available, let the user log in.
        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                try:
                    self.creds.refresh(Request())
                except Exception as e:
                    print(f"⚠️ Warning: Token refresh failed: {e}")
                    print("⚠️ Re-authentication required...")
                    self.creds = None
            
            if not self.creds:
                if not CREDENTIALS_PATH.exists():
                    raise FileNotFoundError(
                        f"❌ CRITICAL: '{CREDENTIALS_PATH}' not found in project root.\n"
                        "Please download OAuth credentials from Google Cloud Console."
                    )
                
                # Triggers the local browser authentication
                print("⚠️ Initiating Google Login in your browser...")
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(CREDENTIALS_PATH), SCOPES)
                self.creds = flow.run_local_server(port=0)
                
            # Save the credentials for the next run in secure location
            with open(TOKEN_PATH, 'w') as token:
                token.write(self.creds.to_json())
            print(f"✅ Token saved securely to: {TOKEN_PATH}")

        # Build the Gmail service
        self.service = build('gmail', 'v1', credentials=self.creds)
        
        # Get sender email from authenticated user profile
        try:
            profile = self.service.users().getProfile(userId='me').execute()
            self.sender_email = profile['emailAddress']
        except Exception as e:
            # Fallback: will be set to 'me' in email sending
            self.sender_email = 'me'
            print(f"⚠️ Warning: Could not fetch sender email: {e}")

    def draft_email(self, recipient_email: str, subject: str, body: str) -> str:
        """
        Creates an email draft and shows a preview WITHOUT sending.
        
        Args:
            recipient_email: The email address of the receiver.
            subject: The subject line of the email.
            body: The content of the email.
        """
        # Add watermark to the email body
        watermark = f"\n\n---\nThis email was sent by Avicenna AI Agent through an automation process. Sender: {self.sender_email}"
        full_body = body + watermark
        
        # Get sender email from authenticated user
        sender_email = self.sender_email
        
        # Escape body for JSON display
        body_display = body.replace('"', '\\"').replace('\n', '\\n')
        
        # Create email preview in JSON format
        email_preview = f'''📧 EMAIL DRAFT PREVIEW:

```json
{{
  "recipient": "{recipient_email}",
  "sender": "{sender_email}",
  "subject": "{subject}",
  "body": "{body_display}"
}}
```

⚠️ Note: A watermark will be automatically added at the bottom:
"This email was sent by Avicenna through an automation process. For any discrepancy, please contact rayyanahmadsultan@gmail.com"

📌 To send this email, say: "Send the email" or "Confirm and send"
📌 To cancel, say: "Cancel" or "Don't send"
'''
        return email_preview

    def send_email(self, recipient_email: str, subject: str, body: str) -> str:
        """
        Sends an email using the authorized Gmail account.
        
        Args:
            recipient_email: The email address of the receiver.
            subject: The subject line of the email.
            body: The content of the email.
        """
        try:
            # Add watermark to the email body
            watermark = f"\n\n---\nThis email was sent by Avicenna AI Agent through an automation process. Sender: {self.sender_email}"
            full_body = body + watermark
            
            message = EmailMessage()
            message.set_content(full_body)
            message['To'] = recipient_email
            message['From'] = 'me'
            message['Subject'] = subject

            # Encode the message for Gmail API
            encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
            create_message = {'raw': encoded_message}

            # API Call
            send_message = (self.service.users().messages().send
                            (userId="me", body=create_message).execute())
            
            return f"✅ Email sent successfully to {recipient_email}! (ID: {send_message['id']})"
        except Exception as e:
            return f"❌ Failed to send email: {e}"

# --- Direct Execution Block (The Handshake) ---
if __name__ == "__main__":
    print("🔌 Authenticating Gmail Tool...")
    try:
        tool = GmailTool()
        print("\n✅ SUCCESS: Authentication complete.")
        print("   'token.json' has been created in your root folder.")
        print("   Avicenna can now use this tool to send emails.")
    except Exception as e:
        print(f"\n❌ ERROR: {e}")