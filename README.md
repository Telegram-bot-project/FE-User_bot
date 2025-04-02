# User Bot

Telegram bot used for interacting with users and integrating RAG model.

## Structure

This bot provides the following functions:
- Answering questions using RAG model
- Displaying event information
- Displaying frequently asked questions (FAQ)
- Providing quick access menu

## Required Environment Variables

- `TELEGRAM_BOT_TOKEN`: Telegram bot token from BotFather
- `API_MONGO_URL`: MongoDB API URL
- `API_RAG_URL`: RAG API URL

## Deployment on Render

### Step 1: Register a Render Account

Visit [Render](https://render.com) and register an account if you don't have one.

### Step 2: Create a New Web Service

1. Log in to Render and click on "New +"
2. Select "Web Service"
3. Connect with your GitHub repository or upload directly

### Step 3: Configure Web Service

1. **Name**: Set a name for the service (e.g., telegram-user-bot)
2. **Runtime**: Choose Docker
3. **Root Directory**: Specify the path to the `telegram/user_bot` directory
4. **Build Command**: Leave empty (use Dockerfile)
5. **Start Command**: Leave empty (use CMD in Dockerfile)

### Step 4: Set Up Environment Variables

In the "Environment" section, add the following variables:

- `TELEGRAM_BOT_TOKEN`: Telegram bot token from BotFather
- `API_MONGO_URL`: MongoDB API URL
- `API_RAG_URL`: RAG API URL

### Step 5: Choose a Plan and Deploy

1. Select an appropriate plan (you can use the Free plan for testing)
2. Click "Create Web Service"

## Important Notes

- Ensure API_MONGO_URL and API_RAG_URL are accessible from the internet
- Render's Free plan will pause after 15 minutes of inactivity, slowing down the first response
- Check logs on Render if the bot is not working
- If you encounter a "health check failed" error, check your configuration to ensure the HTTP server is listening on the correct port 