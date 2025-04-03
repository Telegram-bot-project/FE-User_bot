# Telegram User Bot for Solana SuperTeam

A Telegram bot that provides information about Solana SuperTeam events, FAQs, and general assistance.

## Features

- Event information and updates
- FAQ system with interactive buttons
- Assistant contact information
- Knowledge base integration
- Redis caching (optional)
- Webhook support for deployment

## Requirements

- Python 3.8+
- Redis (optional)
- Telegram Bot Token
- MongoDB API URL
- RAG API URL

## Environment Variables

Create a `.env` file with the following variables:

```env
TELEGRAM_BOT_TOKEN=your_bot_token
API_MONGO_URL=your_mongo_api_url
API_RAG_URL=your_rag_api_url
REDIS_URL=your_redis_url
USE_REDIS=true
WEBHOOK_URL=your_webhook_url
```

## Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/telegram-user-bot.git
cd telegram-user-bot
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Run the bot:
```bash
python user_bot.py
```

## Deployment on Render

1. Fork this repository
2. Create a new Web Service on Render
3. Connect your GitHub repository
4. Add environment variables in Render dashboard
5. Deploy!

## Development

- The bot supports both polling and webhook modes
- Redis is optional and will fallback to in-memory cache if unavailable
- Health check endpoint available at `/health`

## Contributing

1. Fork the repository
2. Create your feature branch
3. Commit your changes
4. Push to the branch
5. Create a new Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details. 