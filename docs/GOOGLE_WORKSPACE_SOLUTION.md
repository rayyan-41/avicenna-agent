# Google Workspace Authorization - SOLUTION IMPLEMENTED

## The Real Issue (SOLVED)

The authorization failures were NOT caused by OAuth client misconfiguration. The actual problem was:

**workspace-mcp requires `user_google_email` parameter for every Google Workspace tool call**, but:
- Gemini doesn't know your email address
- When it sees a required parameter it doesn't have, it asks the user instead of calling the function
- This created a poor UX where users had to manually provide their email every time

## The Solution Implemented

A **smart, configurable email management system** with zero hardcoding:

### How It Works

1. **First-time setup**: When you first use a Google Workspace tool (calendar, gmail, drive), you'll be prompted once for your Google email
2. **Automatic saving**: Your email is saved to `~/.avicenna/user_config.json`
3. **Future sessions**: Email is auto-injected into all workspace tool calls
4. **Easy to change**: Multiple ways to update your email (see below)

### Email Resolution Priority

The system checks in this order:
1. ✅ `.env` file (`GOOGLE_USER_EMAIL=your@email.com`) - **explicit override**
2. ✅ User config (`~/.avicenna/user_config.json`) - **saved from previous session**
3. ✅ Interactive prompt - **one-time setup if neither exists**

### Configuration Options

**Option 1: Add to .env (recommended for single-user setup)**
```bash
# Add this line to your .env file
GOOGLE_USER_EMAIL=your.email@gmail.com
```

**Option 2: Let it prompt you once (easiest)**
- Just use any Google tool
- You'll be asked for your email once
- It's automatically saved for future sessions

**Option 3: Manually edit user config**
```bash
# Edit ~/.avicenna/user_config.json
{
  "google_user_email": "your.email@gmail.com"
}
```

### Changing Your Email

**Method 1: Update .env**
```bash
GOOGLE_USER_EMAIL=newemail@gmail.com
```

**Method 2: Delete config and be prompted again**
```bash
# Windows
del %USERPROFILE%\.avicenna\user_config.json

# Mac/Linux
rm ~/.avicenna/user_config.json
```

**Method 3: Edit config file directly**
Edit `~/.avicenna/user_config.json`

## OAuth Setup (Still Required)

You still need a **Web Application** OAuth client in Google Cloud Console:

1. Go to [Google Cloud Console - Credentials](https://console.cloud.google.com/apis/credentials)
2. Create **OAuth client ID** → **Web application**
3. Add authorized redirect URI: `http://localhost:8000/oauth2callback`
4. Add credentials to `.env`:
   ```
   GOOGLE_OAUTH_CLIENT_ID=your-id.apps.googleusercontent.com
   GOOGLE_OAUTH_CLIENT_SECRET=GOCSPX-your-secret
   ```

## MCP Config Update

The `mcp_config.json` has been updated with the `--single-user` flag:

```json
{
  "name": "google-workspace",
  "command": "uvx",
  "args": ["workspace-mcp", "--single-user"],
  ...
}
```

This allows workspace-mcp to use stored credentials without session mapping.

## First-Time Usage Flow

```
User: "List my calendars"
   ↓
System: No email configured
   ↓
Prompt: "Enter your Google email address: "
   ↓
User: "your.email@gmail.com"
   ↓
System: Saves to ~/.avicenna/user_config.json
   ↓
workspace-mcp: No OAuth token found
   ↓
System: Opens browser for authorization
   ↓
User: Grants permissions
   ↓
workspace-mcp: Saves OAuth token
   ↓
Result: "Here are your calendars: ..."

# Future sessions - fully automatic!
User: "What's on my calendar today?"
   ↓
System: Uses saved email from config
   ↓
workspace-mcp: Uses saved OAuth token
   ↓
Result: "You have 3 events today..."
```

## Benefits

✅ **No hardcoding** - email stored in user config, not code  
✅ **Stable** - simple file-based configuration  
✅ **Reliable** - works for any user, any account  
✅ **Malleable** - easy to change via .env, config file, or delete & re-prompt  
✅ **User-friendly** - one-time setup, automatic thereafter  
✅ **Flexible** - supports .env override for multi-user scenarios

## Files Modified

1. `source/avicenna/config.py` - Added user config management
2. `mcp_servers/mcp_client.py` - Added email auto-injection
3. `source/avicenna/providers/gemini.py` - Added email provider logic
4. `mcp_servers/mcp_config_schema.py` - Added --single-user flag
5. `.env` - Added GOOGLE_USER_EMAIL documentation

## Testing

Run this to verify your setup:
```bash
python -m source.avicenna.main
```

When you use a Google tool, you'll be prompted for your email (if not configured).

---

**Last Updated:** January 29, 2026  
**Status:** ✅ IMPLEMENTED AND TESTED
