# Project Siesta - Setup Guide

## Error Fix: Telegram Token Error

The error you encountered was due to missing or invalid Telegram credentials. This guide will help you set up the bot correctly.

## Prerequisites

1. Python 3.8 or higher
2. MongoDB database
3. Telegram account

## Step-by-Step Setup

### 1. Get Telegram API Credentials

1. Go to https://my.telegram.org/apps
2. Log in with your phone number
3. Create a new application
4. You will receive:
   - `APP_ID` (also called api_id) - a number like 12345678
   - `API_HASH` - a string like "0123456789abcdef0123456789abcdef"

### 2. Create a Telegram Bot

1. Open Telegram and search for [@BotFather](https://t.me/botfather)
2. Send `/newbot` command
3. Follow the instructions to create your bot
4. You will receive a `TG_BOT_TOKEN` like "123456789:ABCdefGHIjklMNOpqrsTUVwxyz"
5. Save the bot username (e.g., @YourBotName)

### 3. Get Your Telegram User ID

1. Search for [@userinfobot](https://t.me/userinfobot) on Telegram
2. Start the bot and it will show your User ID (a number like 123456789)
3. This will be your `ADMINS` value

### 4. Configure the .env File

Edit the `.env` file in the project root with your credentials:

```env
# Replace these with your actual values
TG_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
APP_ID=12345678
API_HASH=0123456789abcdef0123456789abcdef
BOT_USERNAME=YourBotName
ADMINS=123456789

# MongoDB configuration (NEW FORMAT)
MONGODB_URI=mongodb://localhost:27017/
MONGODB_DB=siesta_bot

# Legacy support (will be deprecated)
# DATABASE_URL=mongodb://localhost:27017/projectsiesta
```

### 5. Install Dependencies

```bash
pip install -r requirements.txt
```

### 6. Run the Bot

```bash
python -m bot
```

## Common Issues

### Issue: "Telegram token error Session.py :line 15 :line 12 :line 37 Rpc_error.py :line 9"

**Cause:** Missing or invalid Telegram credentials in .env file

**Solution:** 
- Ensure .env file exists in the project root
- Verify all required fields are filled with correct values
- Check that TG_BOT_TOKEN is valid and not expired
- Ensure APP_ID is a number (no quotes)
- Ensure API_HASH is correct

### Issue: Database connection error

**Cause:** MongoDB is not running or DATABASE_URL is incorrect

**Solution:**
- Start MongoDB service
- Verify DATABASE_URL is correct
- For local MongoDB: `mongodb://localhost:27017/projectsiesta`

### Issue: Bot starts but doesn't respond

**Cause:** Not an admin or bot is not added to group

**Solution:**
- Ensure your User ID is in the ADMINS list
- Send /start command to the bot directly

## Optional Services Configuration

The bot supports multiple music services. Configure them in .env if needed:

- **Qobuz**: QOBUZ_EMAIL, QOBUZ_PASSWORD
- **Deezer**: DEEZER_ARL (or EMAIL/PASSWORD)
- **Tidal**: TIDAL_REFRESH_TOKEN
- **Beatport**: BEATPORT_USERNAME, BEATPORT_PASSWORD

## Need Help?

If you continue to experience issues:
1. Check the log.txt file for detailed error messages
2. Ensure all dependencies are installed
3. Verify Python version is 3.8+
4. Make sure MongoDB is running

