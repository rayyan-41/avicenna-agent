# OAuth 2.0 Architecture for Google Workspace Integration

## Table of Contents
1. [Overview](#overview)
2. [The OAuth 2.0 Flow](#the-oauth-20-flow)
3. [Why Redirect URI Matters](#why-redirect-uri-matters)
4. [OAuth Client Types](#oauth-client-types)
5. [Why Desktop App Fails](#why-desktop-app-fails)
6. [Why workspace-mcp Needs Web App Type](#why-workspace-mcp-needs-web-app-type)
7. [Alternative Solutions](#alternative-solutions)
8. [Security Considerations](#security-considerations)
9. [Implementation Details](#implementation-details)
10. [Troubleshooting](#troubleshooting)

---

## Overview

Google Workspace integration in Avicenna uses the **workspace-mcp** MCP server, which requires OAuth 2.0 authentication. Understanding the OAuth flow and client types is crucial for proper configuration.

**Key Requirement:** workspace-mcp requires a **Web Application** OAuth client, not a Desktop app client.

---

## The OAuth 2.0 Flow

### Step-by-Step Flow Diagram

```
┌─────────────┐         ┌──────────────┐         ┌─────────────┐
│  Avicenna   │         │   Browser    │         │   Google    │
│   (Client)  │         │              │         │   (Server)  │
└─────────────┘         └──────────────┘         └─────────────┘
       │                        │                        │
       │ 1. Generate Auth URL   │                        │
       │────────────────────────>│                        │
       │    with redirect_uri    │                        │
       │                         │                        │
       │                         │ 2. User clicks link    │
       │                         │───────────────────────>│
       │                         │   (User signs in)      │
       │                         │                        │
       │                         │ 3. Google redirects    │
       │                         │    to redirect_uri     │
       │                         │<───────────────────────│
       │                         │    with auth code      │
       │                         │                        │
       │                         │ http://localhost:8000/ │
       │ 4. Avicenna receives    │    oauth2callback?     │
       │<────────────────────────│    code=ABC123         │
       │    the auth code        │                        │
       │                         │                        │
       │ 5. Exchange code for    │                        │
       │    access token         │                        │
       │────────────────────────────────────────────────>│
       │                         │                        │
       │ 6. Google returns       │                        │
       │    access token         │                        │
       │<────────────────────────────────────────────────│
       │                         │                        │
       │ 7. Use token to         │                        │
       │    access Calendar API  │                        │
       │────────────────────────────────────────────────>│
```

### Detailed Steps

**Step 1: Generate Authorization URL**
```python
# workspace-mcp generates a URL like:
auth_url = f"https://accounts.google.com/o/oauth2/auth?"
auth_url += f"response_type=code"
auth_url += f"&client_id={CLIENT_ID}"
auth_url += f"&redirect_uri=http://localhost:8000/oauth2callback"
auth_url += f"&scope=https://www.googleapis.com/auth/calendar"
auth_url += f"&access_type=offline"
```

**Step 2: User Authorization**
- User clicks the link
- Browser opens Google's sign-in page
- User enters credentials
- User reviews requested permissions
- User clicks "Allow"

**Step 3: Authorization Code Redirect**
- Google validates the request
- Generates a temporary authorization code
- Redirects browser to: `http://localhost:8000/oauth2callback?code=ABC123`

**Step 4: Code Reception**
- workspace-mcp has started a temporary web server on port 8000
- The server receives the HTTP request with the code
- Extracts the authorization code from URL parameters

**Step 5: Token Exchange**
```python
# workspace-mcp exchanges code for tokens:
POST https://oauth2.googleapis.com/token
{
  "code": "ABC123",
  "client_id": "YOUR_CLIENT_ID",
  "client_secret": "YOUR_CLIENT_SECRET",
  "redirect_uri": "http://localhost:8000/oauth2callback",
  "grant_type": "authorization_code"
}
```

**Step 6: Access Token**
- Google validates the code
- Returns access token and refresh token
- workspace-mcp saves tokens locally (usually in `~/.config` or similar)

**Step 7: API Access**
```python
# workspace-mcp uses token for API calls:
GET https://www.googleapis.com/calendar/v3/calendars/primary/events
Authorization: Bearer ya29.a0AfH6SMB...
```

---

## Why Redirect URI Matters

### The Redirect URI Problem

The **redirect URI** is a critical security component of OAuth 2.0. Here's why:

**Without Redirect URI Whitelisting:**
```
Attacker creates malicious OAuth client
  → User clicks auth link
  → User signs in to Google
  → Google redirects to attacker.com with auth code
  → Attacker now has access to user's account!
```

**With Redirect URI Whitelisting:**
```
1. Developer registers redirect URI in Google Console
2. Google validates redirect_uri in auth request
3. If redirect_uri not in whitelist → ERROR
4. Only whitelisted URIs receive auth codes
```

### How workspace-mcp Uses It

```python
# workspace-mcp implementation (simplified):

import http.server
import urllib.parse
from threading import Thread

class OAuthCallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        # Parse the callback URL
        query = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(query)
        
        # Extract authorization code
        auth_code = params.get('code', [None])[0]
        
        # Send success page to browser
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Authorization successful! You can close this window.")
        
        # Store code for token exchange
        global received_code
        received_code = auth_code

# Start temporary server
server = http.server.HTTPServer(('localhost', 8000), OAuthCallbackHandler)
Thread(target=server.serve_forever).start()

# Generate auth URL and wait for callback
print(f"Visit: {auth_url}")
while received_code is None:
    time.sleep(0.1)

# Shutdown server
server.shutdown()

# Exchange code for token
tokens = exchange_code_for_token(received_code)
```

---

## OAuth Client Types

Google Cloud Platform offers different OAuth 2.0 client types, each designed for specific use cases:

### Comparison Table

| Feature | Desktop App | Web Application | Service Account |
|---------|-------------|-----------------|-----------------|
| **Redirect URI** | ❌ No custom URIs | ✅ Custom URIs allowed | N/A (no user flow) |
| **Local Web Server** | ❌ Not supported | ✅ Supported | N/A |
| **User Interaction** | ✅ Manual code entry | ✅ Automatic redirect | ❌ None |
| **Use Case** | CLI tools (old style) | Web apps, modern CLI | Server-to-server |
| **Allowed Redirects** | `urn:ietf:wg:oauth:2.0:oob` | `http://localhost:*` | N/A |
| **Token Storage** | User manages | App manages | Key file |
| **workspace-mcp Compatible** | ❌ NO | ✅ YES | ⚠️ Different flow |

### Desktop App Details

**Intended Flow:**
```
1. App generates auth URL with redirect_uri=urn:ietf:wg:oauth:2.0:oob
2. User opens URL in browser
3. User signs in to Google
4. Google displays authorization code on screen:
   
   ┌─────────────────────────────────┐
   │  Your code is:                  │
   │                                 │
   │  4/0AY0e-g7xYz...              │
   │                                 │
   │  Copy this code and paste it    │
   │  into your application          │
   └─────────────────────────────────┘

5. User manually copies code
6. User pastes code into terminal
7. App exchanges code for token
```

**Limitations:**
- No custom redirect URIs
- Cannot use `http://localhost:8000/oauth2callback`
- Requires manual user intervention
- Poor user experience

### Web Application Details

**Intended Flow:**
```
1. App starts local web server on localhost:8000
2. App generates auth URL with redirect_uri=http://localhost:8000/oauth2callback
3. User opens URL in browser
4. User signs in to Google
5. Google redirects to http://localhost:8000/oauth2callback?code=ABC123
6. Local web server catches request automatically
7. App extracts code and exchanges for token
8. App shuts down web server
```

**Advantages:**
- Fully automated
- Better user experience
- No manual copy/paste
- Standard OAuth 2.0 flow

**Configuration:**
- Must whitelist redirect URIs in Google Console
- Common ports: 8000, 8080, 3000
- Must use exact URI (including path)

---

## Why Desktop App Fails

### The Technical Issue

When workspace-mcp tries to use a Desktop app client:

```
1. workspace-mcp generates:
   redirect_uri = "http://localhost:8000/oauth2callback"

2. Google checks OAuth client configuration:
   client_type = "Desktop App"
   allowed_redirect_uris = ["urn:ietf:wg:oauth:2.0:oob"]

3. Google validates:
   if redirect_uri not in allowed_redirect_uris:
       raise Error("redirect_uri_mismatch")

4. Result: ❌ ERROR
```

### The Error You See

**Browser Error:**
```
Error 400: redirect_uri_mismatch

The redirect URI in the request: http://localhost:8000/oauth2callback 
does not match the ones authorized for the OAuth client.
```

**Root Cause:**
- Desktop apps don't support custom redirect URIs
- workspace-mcp is hardcoded to use `http://localhost:8000/oauth2callback`
- These are incompatible

---

## Why workspace-mcp Needs Web App Type

### Architecture Analysis

**workspace-mcp's OAuth Implementation:**

```python
# From workspace-mcp source (conceptual):

class GoogleWorkspaceAuth:
    def __init__(self):
        self.redirect_uri = "http://localhost:8000/oauth2callback"
        self.server_port = 8000
    
    def get_credentials(self):
        # Check for existing token
        if os.path.exists(self.token_file):
            return self.load_token()
        
        # Start OAuth flow
        return self.do_oauth_flow()
    
    def do_oauth_flow(self):
        # Start local web server
        server = self.start_callback_server()
        
        # Generate auth URL
        auth_url = self.build_auth_url(
            redirect_uri=self.redirect_uri
        )
        
        # Display to user
        print(f"Visit: {auth_url}")
        
        # Wait for callback
        auth_code = server.wait_for_callback()
        
        # Exchange for token
        token = self.exchange_code(auth_code)
        
        # Save token
        self.save_token(token)
        
        return token
```

**Key Points:**
1. `redirect_uri` is **hardcoded** to use localhost with specific port
2. Starts a **web server** automatically
3. Expects browser to **redirect** to that server
4. Cannot work with Desktop app's manual flow

### Why Not Just Modify workspace-mcp?

**Challenges:**

1. **It's a package dependency:**
   ```bash
   uvx workspace-mcp  # Downloads from PyPI
   ```
   - You'd need to fork and maintain your own version
   - Updates would break your fork

2. **The manual flow breaks MCP architecture:**
   ```
   MCP Server <--> Avicenna <--> User
   
   With manual flow:
   - MCP server asks for code
   - Avicenna receives request
   - How does Avicenna ask user for code?
   - User is interacting with Avicenna, not workspace-mcp
   - Creates complex communication chain
   ```

3. **Automatic flow is better:**
   - User just clicks link
   - Everything else is automatic
   - Better UX
   - Industry standard

---

## Alternative Solutions

### Option 1: Web Application OAuth Client ✅ (Recommended)

**Steps:**
1. Go to [Google Cloud Console - Credentials](https://console.cloud.google.com/apis/credentials)
2. Click **+ CREATE CREDENTIALS** → **OAuth client ID**
3. Application type: **Web application**
4. Name: `Avicenna Web Client`
5. Authorized redirect URIs:
   - `http://localhost:8000/oauth2callback`
   - `http://localhost:8080/oauth2callback`
6. Click **CREATE**
7. Update `.env` with new Client ID and Secret

**Pros:**
- ✅ Works with workspace-mcp
- ✅ Standard OAuth flow
- ✅ Best user experience
- ✅ No code changes needed

**Cons:**
- None

---

### Option 2: Use Different MCP Server ⚠️

**Find alternative Google Workspace MCP servers that support Desktop flow:**

```python
# Example of Desktop-compatible implementation:
def desktop_oauth_flow():
    # Generate OOB auth URL
    auth_url = build_auth_url(redirect_uri="urn:ietf:wg:oauth:2.0:oob")
    
    print(f"Visit: {auth_url}")
    
    # User manually copies code
    code = input("Enter the authorization code: ")
    
    # Exchange for token
    token = exchange_code(code)
    return token
```

**Pros:**
- ✅ Would work with Desktop OAuth client

**Cons:**
- ❌ May not exist for Google Workspace
- ❌ Worse user experience (manual code entry)
- ❌ More steps for user

---

### Option 3: Modify workspace-mcp Source ⚠️

**Fork and modify workspace-mcp:**

```bash
# Clone workspace-mcp
git clone https://github.com/[original-repo]/workspace-mcp.git
cd workspace-mcp

# Modify OAuth flow
# Edit auth.py to use OOB flow
# Build and install locally
pip install -e .

# Update mcp_config_schema.py to use local version
```

**Pros:**
- ✅ Could work with Desktop client

**Cons:**
- ❌ Requires Python development skills
- ❌ Must maintain your fork
- ❌ Miss upstream updates
- ❌ Complex to deploy
- ❌ Still worse UX

---

### Option 4: Service Account 🏢

**For G Suite/Workspace domain admins only:**

```python
# Service account flow (no user interaction):
from google.oauth2 import service_account

credentials = service_account.Credentials.from_service_account_file(
    'service-account-key.json',
    scopes=['https://www.googleapis.com/auth/calendar']
)

# Impersonate user
delegated_credentials = credentials.with_subject('user@domain.com')
```

**Requirements:**
- Must be G Suite/Workspace domain admin
- Domain-wide delegation enabled
- Service account created
- Different permission model

**Pros:**
- ✅ No user interaction needed
- ✅ Good for automation

**Cons:**
- ❌ Requires domain admin access
- ❌ Only works for Workspace domains (not personal Gmail)
- ❌ Different setup process
- ❌ workspace-mcp doesn't support this (would need custom MCP server)

---

## Security Considerations

### Why Google Requires Redirect URI Whitelisting

**Attack Scenario Without Whitelisting:**

```
1. Attacker creates malicious OAuth client
2. Attacker generates auth URL:
   https://accounts.google.com/o/oauth2/auth?
     client_id=ATTACKER_CLIENT_ID&
     redirect_uri=https://evil.com/steal

3. Attacker sends link to victim (phishing email, etc.)

4. Victim clicks link and signs in

5. Google redirects to:
   https://evil.com/steal?code=ABC123

6. Attacker's server receives auth code

7. Attacker exchanges code for access token

8. ❌ Attacker now has access to victim's account!
```

**Protection With Whitelisting:**

```
1. Developer registers redirect URIs in Google Console:
   - http://localhost:8000/oauth2callback
   - https://myapp.com/oauth/callback

2. Attacker tries to use different URI:
   redirect_uri=https://evil.com/steal

3. Google validates:
   if redirect_uri not in registered_uris:
       return Error("redirect_uri_mismatch")

4. ✅ Attack prevented!
```

### Localhost Security

**Is localhost safe for OAuth?**

**YES, because:**

1. **Localhost is not accessible from internet:**
   ```
   127.0.0.1 → Loopback interface
   Only accessible from your computer
   Cannot be reached by attackers
   ```

2. **Temporary server:**
   ```python
   # workspace-mcp pattern:
   server.start()      # Before OAuth
   wait_for_callback() # Receive code
   server.shutdown()   # After receiving code
   
   # Server only runs for ~30 seconds
   # Minimal attack surface
   ```

3. **Google validates client_id:**
   ```
   Even if attacker runs server on localhost:8000
   They need YOUR client_id and client_secret
   Google checks these before issuing tokens
   ```

**Best Practices:**

1. **Never commit credentials to git:**
   ```bash
   # .gitignore
   .env
   credentials.json
   token.json
   ```

2. **Use environment variables:**
   ```python
   # ✅ Good
   client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
   
   # ❌ Bad
   client_id = "547357431166-..."  # Hardcoded
   ```

3. **Restrict OAuth scopes:**
   ```python
   # ✅ Request only what you need
   scopes = [
       'https://www.googleapis.com/auth/calendar.readonly'
   ]
   
   # ❌ Don't request everything
   scopes = [
       'https://www.googleapis.com/auth/calendar',
       'https://www.googleapis.com/auth/drive',
       # ... etc
   ]
   ```

---

## Implementation Details

### Current Avicenna Configuration

**File: `.env`**
```bash
GOOGLE_OAUTH_CLIENT_ID=547357431166-xxx.apps.googleusercontent.com
GOOGLE_OAUTH_CLIENT_SECRET=GOCSPX-xxx
```

**File: `source/avicenna/config.py`**
```python
from dotenv import load_dotenv

# Load .env file
load_dotenv(env_path)

# Load credentials
GOOGLE_OAUTH_CLIENT_ID: Optional[str] = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
GOOGLE_OAUTH_CLIENT_SECRET: Optional[str] = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
```

**File: `mcp_servers/mcp_client.py`**
```python
# Environment variable propagation (FIXED)
env = os.environ.copy()

# Only add non-empty values from server config
for key, value in server_config.env.items():
    if value:  # Skip empty strings
        env[key] = value

# Now .env credentials pass through to MCP servers
```

**File: `mcp_servers/mcp_config_schema.py`**
```python
ServerConfig(
    name="google-workspace",
    type=ServerType.UVX,
    module="workspace-mcp",
    enabled=True,
    env={
        "GOOGLE_OAUTH_CLIENT_ID": "",      # Placeholder (empty)
        "GOOGLE_OAUTH_CLIENT_SECRET": ""   # Placeholder (empty)
    }
)
```

### How It All Works Together

```
1. Avicenna starts
   └─> config.py loads .env
       └─> GOOGLE_OAUTH_CLIENT_ID = "547..."
       └─> GOOGLE_OAUTH_CLIENT_SECRET = "GOCSPX..."

2. MCP Manager initializes servers
   └─> For each server config:
       └─> env = os.environ.copy()  # Includes .env values
       └─> Add non-empty config values
       └─> Spawn server process with merged env

3. workspace-mcp starts
   └─> Reads GOOGLE_OAUTH_CLIENT_ID from env
   └─> Reads GOOGLE_OAUTH_CLIENT_SECRET from env
   └─> Starts OAuth flow

4. User requests calendar access
   └─> workspace-mcp checks for token
   └─> No token found → initiate OAuth
   └─> Start local server on :8000
   └─> Generate auth URL
   └─> Display to user

5. User clicks auth URL
   └─> Browser → Google sign-in
   └─> Google → redirect to localhost:8000
   └─> workspace-mcp receives code
   └─> Exchange code for token
   └─> Save token
   └─> Complete API request
```

---

## Troubleshooting

### Error: "redirect_uri_mismatch"

**Symptom:**
```
Error 400: redirect_uri_mismatch
The redirect URI in the request does not match
```

**Causes:**
1. Using Desktop app instead of Web app
2. Redirect URI not added to OAuth client
3. Typo in redirect URI

**Solution:**
1. Create Web Application OAuth client
2. Add exact redirect URI: `http://localhost:8000/oauth2callback`
3. Wait 30-60 seconds for propagation

---

### Error: "Invalid prompt: consent"

**Symptom:**
```
Access blocked: Authorization Error
Invalid parameter value for prompt: Invalid prompt: consent (ctrl click)
```

**Cause:**
Desktop app doesn't support `prompt=consent` parameter

**Solution:**
Switch to Web Application OAuth client

---

### Error: "Connection refused" to localhost:8000

**Symptom:**
```
Failed to connect to localhost:8000
Connection refused
```

**Causes:**
1. workspace-mcp didn't start server
2. Port 8000 already in use
3. Firewall blocking localhost

**Solutions:**
1. Check workspace-mcp logs
2. Find what's using port 8000:
   ```powershell
   netstat -ano | findstr :8000
   ```
3. Try different port (requires workspace-mcp config)

---

### Credentials Not Propagating

**Symptom:**
```
workspace-mcp: Error: GOOGLE_OAUTH_CLIENT_ID not found
```

**Cause:**
Empty strings in server config overwriting .env values

**Solution:**
Already fixed in `mcp_client.py`:
```python
for key, value in server_config.env.items():
    if value:  # Only add non-empty values
        env[key] = value
```

---

### Token Expired

**Symptom:**
```
Error: Token has been expired or revoked
```

**Solutions:**
1. Delete token file (workspace-mcp will re-authenticate):
   ```powershell
   # Find token location (usually):
   del $env:USERPROFILE\.config\workspace-mcp\token.json
   # or
   del $env:APPDATA\workspace-mcp\token.json
   ```

2. Restart Avicenna
3. Re-authorize when prompted

---

### Multiple Redirect URIs Needed

**When to add multiple:**
- Different ports: 8000, 8080, 3000
- HTTP and HTTPS
- Different paths

**Example:**
```
http://localhost:8000/oauth2callback
http://localhost:8080/oauth2callback
http://127.0.0.1:8000/oauth2callback
https://localhost:8000/oauth2callback
```

**Note:** workspace-mcp typically only needs port 8000

---

## Quick Reference

### OAuth Client Type Decision Tree

```
Do you need custom redirect URIs?
│
├─ YES → Use Web Application
│   └─ Example: workspace-mcp, local web apps
│
└─ NO → Consider Desktop App
    └─ Example: CLI tools with manual code entry

Is your app running a local web server?
│
├─ YES → Must use Web Application
│   └─ Example: workspace-mcp
│
└─ NO → Can use Desktop App
    └─ Example: simple CLI scripts

Do you want automatic OAuth flow?
│
├─ YES → Use Web Application
│   └─ Better UX, no manual steps
│
└─ NO → Desktop App acceptable
    └─ User must copy/paste code
```

### Required Google APIs

Enable these in [Google Cloud Console - APIs](https://console.cloud.google.com/apis/library):

- ✅ Google Calendar API
- ✅ Gmail API
- ✅ Google Drive API
- ✅ Google Docs API
- ✅ Google Sheets API
- ✅ Google Slides API

### Environment Variables

**Required in `.env`:**
```bash
GOOGLE_OAUTH_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_OAUTH_CLIENT_SECRET=GOCSPX-your-secret
```

**Not needed (automatically handled):**
```bash
# ❌ Don't set these manually
GOOGLE_ACCESS_TOKEN=...
GOOGLE_REFRESH_TOKEN=...
```

workspace-mcp manages tokens automatically.

---

## Summary

**For Avicenna + workspace-mcp:**

1. ✅ Create **Web Application** OAuth client in Google Cloud Console
2. ✅ Add redirect URI: `http://localhost:8000/oauth2callback`
3. ✅ Update `.env` with Client ID and Secret
4. ✅ Enable required Google APIs
5. ✅ Restart Avicenna
6. ✅ Click authorization link when prompted
7. ✅ Grant permissions
8. ✅ Enjoy automatic Google Workspace integration!

**Key Takeaway:**
> workspace-mcp uses a modern OAuth flow with automatic redirect handling, which requires a Web Application OAuth client. Desktop apps don't support custom redirect URIs and are incompatible with this architecture.

---

**Last Updated:** January 28, 2026  
**Avicenna Version:** 2.0 - MCP Ecosystem
