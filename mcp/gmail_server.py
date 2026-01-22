"""MCP Server for Gmail Tools"""
import sys
from pathlib import Path

# Add parent directory to path for imports when run as main
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from source.tools.gmail import GmailTool
else:
    from source.tools.gmail import GmailTool

from fastmcp import FastMCP

# Initialize FastMCP server
mcp = FastMCP("Gmail")

# Initialize Gmail tool (authentication happens here)
try:
    gmail_service = GmailTool()
    print("✅ Gmail authentication successful")
except Exception as e:
    print(f"⚠️ Gmail authentication failed: {e}")
    gmail_service = None

@mcp.tool()
def draft_email(recipient_email: str, subject: str, body: str) -> str:
    """
    Creates an email draft and shows a preview WITHOUT sending.
    
    This is the REQUIRED first step before sending any email.
    Shows the user exactly what will be sent and asks for confirmation.
    
    Args:
        recipient_email: The email address of the receiver
        subject: The subject line of the email
        body: The content/body of the email
        
    Returns:
        A formatted preview of the email with confirmation prompt
    """
    if gmail_service is None:
        return "❌ Gmail service not authenticated. Run gmail_server.py directly first."
    
    return gmail_service.draft_email(recipient_email, subject, body)

@mcp.tool()
def send_email(recipient_email: str, subject: str, body: str) -> str:
    """
    Sends an email using the authorized Gmail account.
    
    IMPORTANT: Should ONLY be called after draft_email and explicit user confirmation.
    
    Args:
        recipient_email: The email address of the receiver
        subject: The subject line of the email
        body: The content/body of the email
        
    Returns:
        Confirmation message with email ID or error message
    """
    if gmail_service is None:
        return "❌ Gmail service not authenticated. Run gmail_server.py directly first."
    
    return gmail_service.send_email(recipient_email, subject, body)

if __name__ == "__main__":
    # Run the MCP server
    mcp.run()
