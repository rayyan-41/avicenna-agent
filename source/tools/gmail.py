import os.path
import base64
from email.message import EmailMessage
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Define the permission scope (Sending emails only)
SCOPES = ['https://www.googleapis.com/auth/gmail.send']

class GmailTool:
    def __init__(self):
        self.creds = None
        # token.json stores the user's access and refresh tokens.
        # It is created automatically when the authorization flow completes for the first time.
        if os.path.exists('token.json'):
            self.creds = Credentials.from_authorized_user_file('token.json', SCOPES)
            
        # If there are no (valid) credentials available, let the user log in.
        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                self.creds.refresh(Request())
            else:
                if not os.path.exists('credentials.json'):
                     raise FileNotFoundError("❌ CRITICAL: 'credentials.json' not found in project root.")
                
                # Triggers the local browser authentication
                print("⚠️ Initiating Google Login in your browser...")
                flow = InstalledAppFlow.from_client_secrets_file(
                    'credentials.json', SCOPES)
                self.creds = flow.run_local_server(port=0)
                
            # Save the credentials for the next run
            with open('token.json', 'w') as token:
                token.write(self.creds.to_json())

        # Build the Gmail service
        self.service = build('gmail', 'v1', credentials=self.creds)

    def send_email(self, recipient_email: str, subject: str, body: str) -> str:
        """
        Sends an email using the authorized Gmail account.
        
        Args:
            recipient_email: The email address of the receiver.
            subject: The subject line of the email.
            body: The content of the email.
        """
        try:
            message = EmailMessage()
            message.set_content(body)
            message['To'] = recipient_email
            message['From'] = 'me'
            message['Subject'] = subject

            # Encode the message for Gmail API
            encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
            create_message = {'raw': encoded_message}

            # API Call
            send_message = (self.service.users().messages().send
                            (userId="me", body=create_message).execute())
            
            return f"✅ Email sent successfully! (ID: {send_message['id']})"
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