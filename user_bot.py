import os
import json
import logging
import asyncio
import uuid
from datetime import datetime
import pytz
import aiohttp
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from aiohttp import TCPConnector, ClientTimeout
from functools import lru_cache
import time
import re
from collections import defaultdict
from typing import Dict, Tuple
import hashlib
import base64
from redis.asyncio import Redis, from_url
from asyncio import Lock

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API_MONGO_URL = os.getenv("API_MONGO_URL")
API_RAG_URL = os.getenv("API_RAG_URL")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

# Redis connection pool
redis_pool = None
redis_pool_size = 10

# Debounce locks for user input
input_locks = {}

async def get_redis() -> Redis:
    """
    Get Redis connection from pool with optimized settings
    """
    global redis_pool
    if redis_pool is None:
        redis_pool = await from_url(
            REDIS_URL, 
            encoding="utf-8", 
            decode_responses=True,
            max_connections=redis_pool_size
        )
    return redis_pool

# Cache configuration
CACHE_TTL = {
    'faq': 3600,  # 1 hour
    'events': 1800,  # 30 minutes
    'assistants': 1800,  # 30 minutes
    'rag_response': 300,  # 5 minutes
    'button_data': 1800,  # 30 minutes
}

# API timeout configuration - Reduced for faster responses
API_TIMEOUT = ClientTimeout(total=5, connect=3)

# Rate limiting configuration
RATE_LIMIT = 5  # messages per minute
RATE_LIMIT_WINDOW = 60  # seconds
user_message_counts: Dict[int, Tuple[int, float]] = defaultdict(lambda: (0, time.time()))

# Input validation patterns
ALLOWED_CHARS_PATTERN = re.compile(r'^[a-zA-Z0-9\s.,!?-]+$')
MAX_MESSAGE_LENGTH = 500

# Background cache refresh
async def background_cache_refresh():
    """Refresh cache in background periodically"""
    while True:
        try:
            logger.info("Starting background cache refresh")
            redis = await get_redis()
            session = await get_session()
            
            # Use Redis pipeline for batch operations
            pipeline = redis.pipeline()
            
            # Refresh events cache
            try:
                async with session.get("https://zok213-teleadmindb.hf.space/api/knowledge/closest-events") as response:
                    if response.status == 200:
                        data = await response.json()
                        events = data if isinstance(data, list) else data.get("events", [])
                        pipeline.setex("events_cache", CACHE_TTL['events'], json.dumps(events))
                        logger.info("Background refresh: Events cache prepared")
            except Exception as e:
                logger.error(f"Error refreshing events cache: {e}")
            
            # Refresh FAQ cache
            try:
                async with session.get("https://zok213-teleadmindb.hf.space/api/faq") as response:
                    if response.status == 200:
                        data = await response.json()
                        faqs = data if isinstance(data, list) else data.get("faqs", [])
                        pipeline.setex("faqs_cache", CACHE_TTL['faq'], json.dumps(faqs))
                        logger.info("Background refresh: FAQs cache prepared")
            except Exception as e:
                logger.error(f"Error refreshing FAQs cache: {e}")
                
            # Refresh assistants cache
            try:
                async with session.get("https://zok213-teleadmindb.hf.space/api/sos") as response:
                    if response.status == 200:
                        data = await response.json()
                        assistants = data if isinstance(data, list) else data.get("assistants", [])
                        pipeline.setex("assistants_cache", CACHE_TTL['assistants'], json.dumps(assistants))
                        logger.info("Background refresh: Assistants cache prepared")
            except Exception as e:
                logger.error(f"Error refreshing assistants cache: {e}")
            
            # Execute pipeline
            await pipeline.execute()
            logger.info("Background cache refresh completed")
            
            # Sleep for 15 minutes before next refresh (less than cache TTL)
            await asyncio.sleep(900)  
        except Exception as e:
            logger.error(f"Error in background cache refresh: {e}")
            await asyncio.sleep(60)  # Retry after 1 minute if error

def sanitize_input(text: str) -> str:
    """
    Sanitize user input to prevent injection attacks
    """
    # Remove any HTML-like tags
    text = re.sub(r'<[^>]+>', '', text)
    # Remove any potentially dangerous characters
    text = re.sub(r'[^\w\s.,!?-]', '', text)
    return text[:MAX_MESSAGE_LENGTH]

def is_rate_limited(user_id: int) -> bool:
    """
    Check if user has exceeded rate limit
    """
    current_time = time.time()
    count, window_start = user_message_counts[user_id]
    
    # Reset if window has passed
    if current_time - window_start > RATE_LIMIT_WINDOW:
        user_message_counts[user_id] = (1, current_time)
        return False
    
    # Check if user has exceeded limit
    if count >= RATE_LIMIT:
        return True
    
    # Increment count
    user_message_counts[user_id] = (count + 1, window_start)
    return False

def mask_sensitive_data(data: dict) -> dict:
    """
    Mask sensitive data in logs
    """
    masked_data = data.copy()
    sensitive_fields = ['token', 'password', 'api_key', 'secret']
    
    for key, value in masked_data.items():
        if any(sensitive in key.lower() for sensitive in sensitive_fields):
            masked_data[key] = '***MASKED***'
    
    return masked_data

def hash_user_id(user_id: int) -> str:
    """
    Hash user ID for privacy
    """
    return hashlib.sha256(str(user_id).encode()).hexdigest()[:8]

# Optimized session pool for aiohttp
async def get_session():
    if not hasattr(get_session, 'session'):
        connector = TCPConnector(
            limit=20,  # Increased concurrent connections
            ttl_dns_cache=300,
            use_dns_cache=True,
            force_close=False
        )
        get_session.session = aiohttp.ClientSession(
            connector=connector,
            timeout=API_TIMEOUT,
            headers={'Content-Type': 'application/json'}
        )
    return get_session.session

# Cache for API calls
@lru_cache(maxsize=100)
def cache_key(*args, **kwargs):
    return str(args) + str(kwargs)

# Simple HTTP server for health checks
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health' or self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            
            health_status = {
                "status": "healthy",
                "timestamp": datetime.now().isoformat(),
                "service": "telegram-user-bot"
            }
            
            self.wfile.write(json.dumps(health_status).encode())
        else:
            self.send_response(404)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write("Not Found".encode())
    
    def do_HEAD(self):
        # Render uses HEAD request for health check
        if self.path == '/health' or self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
        else:
            self.send_response(404)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
    
    def log_message(self, format, *args):
        # Silent HTTP server logs or redirect to our logger
        if args[1] == '200':  # Silence successful health checks
            return
        logger.info("%s - %s" % (self.address_string(), format % args))

def start_health_server():
    """
    Start a simple HTTP server for health checks
    Render automatically sets PORT environment variable and expects the
    service to listen on that port
    """
    port = int(os.getenv("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    logger.info(f"Starting health check server on port {port}")
    server.serve_forever()

# Vietnam timezone
vietnam_tz = pytz.timezone('Asia/Ho_Chi_Minh')

# Optimized save session function with background task
async def save_session(user_id, username, first_name, last_name, action, message="", factor="user", max_retries=3):
    """
    Save user interaction to the database with retry mechanism
    """
    session_id = str(uuid.uuid4())
    timestamp = datetime.now(vietnam_tz).isoformat()

    # Ensure username is not null
    if username is None:
        username = ""

    # Ensure first_name and last_name are not null
    if first_name is None:
        first_name = ""
    if last_name is None:
        last_name = ""
    
    # Ensure user_id is an integer for the API
    # If user_id is already a string with 8 chars (hashed), we keep the original ID
    original_user_id = user_id
    if isinstance(user_id, str) and len(user_id) == 8:
        # Log that we're using a hashed ID but API needs integer
        logger.info(f"Using hashed user_id: {user_id}, API expects integer")
        # Since we can't reverse the hash, we'll create a pseudo-numeric ID
        # This is a workaround and ideally we should fix the API to accept string IDs
        numeric_id = int(hashlib.md5(user_id.encode()).hexdigest()[:8], 16) % 1000000000
        user_id = numeric_id

    session_data = {
        "session_id": session_id,
        "user_id": user_id,  # Use integer ID for API compatibility
        "username": username,
        "first_name": first_name,
        "last_name": last_name,
        "timestamp": timestamp,
        "action": action,
        "message": message,
        "factor": factor
    }

    # Create a background task for saving
    async def save_session_background():
        for attempt in range(max_retries):
            try:
                session = await get_session()
                async with session.post(f"{API_MONGO_URL}/session", json=session_data) as response:
                    if response.status == 200:
                        logger.info(f"Session saved: {session_id}")
                        return session_id
                    else:
                        error_text = await response.text()
                        logger.error(f"Failed to save session (attempt {attempt + 1}/{max_retries}): {error_text}")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(1 * (attempt + 1))  # Exponential backoff
            except Exception as e:
                logger.error(f"Error saving session (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(1 * (attempt + 1))
        return None

    # Start background task and return immediately
    asyncio.create_task(save_session_background())
    return session_id

# Function to get events from API with Redis cache - Optimized
async def get_events(message):
    """
    Get events from API with Redis cache
    """
    try:
        # Show immediate response with temporary message
        temp_message = await message.reply_text("📅 *Loading events...*", parse_mode="Markdown")
        
        redis = await get_redis()
        cache_key = "events_cache"
        
        # Try to get from cache first
        cached_events = await redis.get(cache_key)
        if cached_events:
            events = json.loads(cached_events)
            logger.info("Retrieved events from cache")
        else:
            # If not in cache, fetch from API
            session = await get_session()
            async with session.get("https://zok213-teleadmindb.hf.space/api/knowledge/closest-events") as response:
                if response.status == 200:
                    data = await response.json()
                    events = data if isinstance(data, list) else data.get("events", [])
                    
                    # Cache the events
                    await redis.setex(
                        cache_key,
                        CACHE_TTL['events'],
                        json.dumps(events)
                    )
                else:
                    events = []
        
        if not events:
            await temp_message.edit_text("No upcoming events found.")
            return
        
        logger.info(f"Found {len(events)} events")
        
        # Send all events in a single message
        events_text = "📅 *Upcoming Events:*\n\n"
        
        for event in events:
            try:
                name = event.get('name', 'No name')
                address = event.get('address', '')
                description = event.get('description', '')
                price = event.get('price', '')
                time = event.get('time', '')
                date = event.get('date', '')
                
                events_text += f"🎯 *{name}*\n"
                events_text += f"📝 {description}\n"
                events_text += f"📆 {date}\n"
                events_text += f"🕒 {time}\n"
                events_text += f"📍 {address}\n"
                events_text += f"💰 {price}\n\n"
                
            except Exception as e:
                logger.error(f"Error processing event: {e}")
        
        # Update temporary message with final content
        await temp_message.edit_text(events_text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error getting events: {e}")
        await message.reply_text("Unable to fetch events at this time. Please try again later.")

# Function to get assistants from API with Redis cache - Optimized
async def get_assistants(message):
    """
    Get assistants from API with Redis cache
    """
    try:
        # Show immediate response with temporary message
        temp_message = await message.reply_text("🔄 *Loading assistant information...*", parse_mode="Markdown")
        
        redis = await get_redis()
        cache_key = "assistants_cache"
        
        # Try to get from cache first
        cached_assistants = await redis.get(cache_key)
        if cached_assistants:
            assistants = json.loads(cached_assistants)
            logger.info("Retrieved assistants from cache")
        else:
            # If not in cache, fetch from API
            session = await get_session()
            async with session.get("https://zok213-teleadmindb.hf.space/api/sos") as response:
                if response.status == 200:
                    data = await response.json()
                    assistants = data if isinstance(data, list) else data.get("assistants", [])
                    
                    # Cache the assistants
                    await redis.setex(
                        cache_key,
                        CACHE_TTL['assistants'],
                        json.dumps(assistants)
                    )
                else:
                    assistants = []
        
        if not assistants:
            await temp_message.edit_text("No assistants available at the moment.")
            return
        
        assistant_text = "🆘 *Available Assistants:*\n\n"
        
        for item in assistants:
            support_type = item.get('support_type', 'No type')
            phone_number = item.get('phone_number', 'No phone number')
            name = item.get('name', 'No name')
            
            assistant_text += f"👤 *{name}*\n"
            assistant_text += f"🔹 Type: {support_type}\n"
            assistant_text += f"📞 Contact: {phone_number}\n\n"
        
        # Update temporary message with final content
        await temp_message.edit_text(assistant_text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error getting assistants: {e}")
        await message.reply_text("Unable to fetch assistants at this time. Please try again later.")

# Function to get FAQs from API with Redis cache - Optimized
async def get_faqs(message):
    """
    Get FAQs from API with Redis cache
    """
    try:
        # Show immediate response with temporary message
        temp_message = await message.reply_text("🔄 *Loading FAQs...*", parse_mode="Markdown")
        
        redis = await get_redis()
        cache_key = "faqs_cache"
        
        # Try to get from cache first
        cached_faqs = await redis.get(cache_key)
        if cached_faqs:
            faqs = json.loads(cached_faqs)
            logger.info("Retrieved FAQs from cache")
        else:
            # If not in cache, fetch from API
            session = await get_session()
            async with session.get("https://zok213-teleadmindb.hf.space/api/faq") as response:
                if response.status == 200:
                    data = await response.json()
                    faqs = data if isinstance(data, list) else data.get("faqs", [])
                    
                    # Cache the FAQs
                    await redis.setex(
                        cache_key,
                        CACHE_TTL['faq'],
                        json.dumps(faqs)
                    )
                else:
                    faqs = []
        
        # Delete the temporary message
        await temp_message.delete()
        
        if not faqs:
            await message.reply_text("No FAQs available at the moment.")
            return
        
        # Split FAQ list into groups of 5 questions
        faq_groups = [faqs[i:i + 5] for i in range(0, len(faqs), 5)]
        
        for group in faq_groups:
            keyboard = []
            for faq in group:
                faq_id = faq.get('id', '')
                question = faq.get('question', 'No question')
                keyboard.append([InlineKeyboardButton(question, callback_data=f"faq_answer_{faq_id}")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await message.reply_text("📋 *Frequently Asked Questions:*", reply_markup=reply_markup, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error getting FAQs: {e}")
        await message.reply_text("Unable to fetch FAQs at this time. Please try again later.")

# Function to get FAQ answer - Optimized with caching
async def get_faq_answer(message, faq_id):
    """
    Get FAQ answer for a specific question
    """
    try:
        # Show immediate response with temporary message
        temp_message = await message.reply_text("🔄 *Loading answer...*", parse_mode="Markdown")
        
        # Check if faq_id is valid
        if not faq_id or not faq_id.strip():
            await temp_message.edit_text("Invalid FAQ ID. Please try again or select another question.")
            return
            
        logger.info(f"Fetching FAQ answer for ID: {faq_id}")
        
        # Try to get from cache first
        redis = await get_redis()
        cache_key = f"faq_answer:{faq_id}"
        
        cached_answer = await redis.get(cache_key)
        if cached_answer:
            answer_data = json.loads(cached_answer)
            question = answer_data.get('question', 'No question')
            answer = answer_data.get('answer', 'No answer available')
            
            response_text = f"❓ *{question}*\n\n"
            response_text += f"❗ {answer}"
            
            await temp_message.edit_text(response_text, parse_mode="Markdown")
            return
        
        # If not in cache, get from API
        session = await get_session()
        async with session.get(
            "https://zok213-teleadmindb.hf.space/api/faq",
            timeout=aiohttp.ClientTimeout(total=5)
        ) as response:
            if response.status == 200:
                response_text = await response.text()
                logger.info(f"FAQ list response received")
                
                # Parse JSON response 
                all_faqs = await response.json()
                
                # Ensure all_faqs is a list
                if isinstance(all_faqs, dict):
                    all_faqs = all_faqs.get("faqs", [])
                    
                # Find the FAQ with the matching ID
                matched_faq = None
                for faq in all_faqs:
                    if str(faq.get("id")) == str(faq_id):
                        matched_faq = faq
                        break
                
                if matched_faq:
                    question = matched_faq.get("question", "No question")
                    answer = matched_faq.get("answer", "No answer available")
                    
                    logger.info(f"Found FAQ: {question}")
                    
                    # Cache the answer
                    answer_data = {
                        'question': question,
                        'answer': answer
                    }
                    await redis.setex(
                        cache_key,
                        CACHE_TTL['faq'],
                        json.dumps(answer_data)
                    )
                    
                    response_text = f"❓ *{question}*\n\n"
                    response_text += f"❗ {answer}"
                    
                    await temp_message.edit_text(response_text, parse_mode="Markdown")
                else:
                    logger.warning(f"FAQ with ID {faq_id} not found")
                    await temp_message.edit_text("This question is no longer available. Please select another question.")
            else:
                error_text = await response.text()
                logger.error(f"Failed to get FAQ list (status {response.status})")
                await temp_message.edit_text("Unable to fetch FAQ answer at this time. Please try again later.")
    except asyncio.TimeoutError:
        logger.error(f"Timeout getting FAQ answer for ID: {faq_id}")
        await message.reply_text("Request timed out. Please try again later.")
    except Exception as e:
        logger.error(f"Error getting FAQ answer: {e}")
        await message.reply_text("Unable to fetch FAQ answer at this time. Please try again later.")

# Function to get response from RAG model with Redis cache - Optimized
async def get_rag_response(user_message, user_id):
    """
    Get response from RAG model with Redis cache
    """
    try:
        redis = await get_redis()
        # Include user_id in cache key for personalized responses
        cache_key = f"rag_response:{user_id}:{hashlib.md5(user_message.encode()).hexdigest()}"
        
        # Try to get from cache first
        cached_response = await redis.get(cache_key)
        if cached_response:
            logger.info(f"Retrieved RAG response from cache for user {user_id}")
            return cached_response
        
        # If not in cache, get from API
        session = await get_session()
        # Use actual user_id in API call
        payload = {"query": user_message, "user_id": str(user_id)}
        
        logger.info(f"Sending RAG request with user_id: {user_id}")
        
        async with session.post(API_RAG_URL, json=payload) as response:
            if response.status == 200:
                try:
                    response_text = await response.text()
                    result = json.loads(response_text)
                    
                    if isinstance(result, dict):
                        rag_answer = result.get("response", "") or result.get("answer", "") or str(result)
                    else:
                        rag_answer = str(result)
                    
                    if rag_answer:
                        # Cache the response
                        await redis.setex(
                            cache_key,
                            CACHE_TTL['rag_response'],
                            rag_answer
                        )
                        return rag_answer
                    else:
                        return "I don't know how to answer that. Let me forward this to the admin team."
                except json.JSONDecodeError:
                    return "I don't know how to answer that. Let me forward this to the admin team."
            else:
                return "I don't know how to answer that. Let me forward this to the admin team."
    except Exception as e:
        logger.error(f"Error getting RAG response: {e}")
        return "I don't know how to answer that. Let me forward this to the admin team."

# Function to handle the /start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle the /start command
    """
    user = update.effective_user
    
    # Save /start session in background
    asyncio.create_task(save_session(
        user.id, 
        user.username, 
        user.first_name, 
        user.last_name, 
        "/start"
    ))
    
    # Welcome message
    welcome_text = f"Hello {user.first_name}! Welcome to the Solana SuperTeam Bot. I can help you with information about Solana SuperTeam and events."
    
    # Help guide
    help_guide = """
*Available Commands:*
• /start - Start the bot and display main menu
• /events - Show upcoming events
• /faqs - Display frequently asked questions
• /assistants - List available assistants
• /help - Display this help message

*Bot Features:*
• Ask questions about Solana SuperTeam
• Get information about events
• Browse FAQs
• Connect with assistants

Use the buttons below to navigate or type your question anytime.
"""
    
    # Send initial message with help guide
    await update.message.reply_text(welcome_text)
    await update.message.reply_text(help_guide, parse_mode="Markdown")
    
    # Create keyboard buttons in 2x2 grid
    keyboard = [
        [
            InlineKeyboardButton("Knowledge Portal", callback_data="knowledge_portal"),
            InlineKeyboardButton("Solana Summit Event", callback_data="solana_summit")
        ],
        [
            InlineKeyboardButton("Events", callback_data="events"),
            InlineKeyboardButton("Access SolonaSuperTeam", callback_data="access_solona")
        ],
        [
            InlineKeyboardButton("Assistant", callback_data="assistant"),
            InlineKeyboardButton("FAQ", callback_data="faq")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("What would you like to know?", reply_markup=reply_markup)

# Function to handle the /help command
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle the /help command
    """
    user = update.effective_user
    
    # Save /help session in background
    asyncio.create_task(save_session(
        user.id, 
        user.username, 
        user.first_name, 
        user.last_name, 
        "/help"
    ))
    
    help_text = """
*Solana SuperTeam Bot Help*

*Available Commands:*
• /start - Start the bot and display main menu
• /events - Show upcoming events
• /faqs - Display frequently asked questions
• /assistants - List available assistants
• /help - Display this help message

*How to Use:*
1. Use the menu buttons to navigate
2. Type your questions directly
3. Browse FAQs for common questions
4. Check upcoming events with /events
5. Find assistants with /assistants

*Features:*
• Ask about Solana SuperTeam
• Get information about events
• Find answers in FAQs
• Connect with assistants
• Access SolonaSuperTeam website

If you need further assistance, please contact an admin.
"""
    
    await update.message.reply_text(help_text, parse_mode="Markdown")

# Handle button callbacks - Optimized
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle button callbacks
    """
    query = update.callback_query
    await query.answer("Loading...")  # Show loading popup to user
    
    user = query.from_user
    callback_data = query.data
    
    # Save button click session asynchronously without waiting
    asyncio.create_task(save_session(
        user.id, 
        user.username, 
        user.first_name, 
        user.last_name, 
        callback_data
    ))
    
    try:
        if callback_data == "knowledge_portal":
            await query.message.reply_text("What would you like to know about Solana Superteam?")
        
        elif callback_data == "solana_summit":
            await query.message.reply_text("What would you like to know about the Solana Summit event?")
        
        elif callback_data == "events":
            await get_events(query.message)
        
        elif callback_data == "access_solona":
            keyboard = [[InlineKeyboardButton("Access SolonaSuperTeam", url="https://vn.superteam.fun/")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text("Click below to access SolonaSuperTeam:", reply_markup=reply_markup)
        
        elif callback_data == "assistant":
            await get_assistants(query.message)
        
        elif callback_data == "faq":
            await get_faqs(query.message)
        
        elif callback_data.startswith("faq_answer_"):
            faq_id = callback_data.split("_")[-1]
            await get_faq_answer(query.message, faq_id)
            
    except Exception as e:
        logger.error(f"Error handling button callback: {e}")
        await query.message.reply_text("❌ An error occurred. Please try again later.")

# Handle regular text messages - Optimized with debouncing
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle regular text messages by sending to RAG model
    """
    user = update.effective_user
    user_id = user.id
    user_message = update.message.text
    
    # Use debounce lock to prevent spam
    if user_id in input_locks:
        return
    
    input_locks[user_id] = Lock()
    
    try:
        async with input_locks[user_id]:
            # Rate limiting check
            if is_rate_limited(user_id):
                await update.message.reply_text(
                    "You have sent too many messages. Please wait a moment and try again later."
                )
                return
            
            # Input validation
            if not ALLOWED_CHARS_PATTERN.match(user_message):
                await update.message.reply_text(
                    "Your message contains invalid characters. Please use only letters, numbers and basic characters."
                )
                return
            
            # Sanitize input
            sanitized_message = sanitize_input(user_message)
            
            # Show immediate response with temporary message
            temp_message = await update.message.reply_text("Processing your question...")
            
            # Create common session_id for both question and answer
            session_id = str(uuid.uuid4())
            timestamp = datetime.now(vietnam_tz).isoformat()
            
            # Save user message session with the original numeric user_id
            try:
                # Log message processing
                logger.info(f"Processing message from user {user_id}")
                
                # Save user's question in background with original user_id
                asyncio.create_task(
                    save_session(
                        user_id,  # Use original numeric ID
                        user.username, 
                        user.first_name, 
                        user.last_name, 
                        "freely asking",
                        sanitized_message,
                        "user"
                    )
                )
                
                # Get response from RAG model with actual user_id
                rag_response = await get_rag_response(sanitized_message, user_id)
                
                # Save RAG response with same session_id in background
                asyncio.create_task(
                    save_session(
                        user_id,  # Use original numeric ID
                        user.username, 
                        user.first_name, 
                        user.last_name, 
                        "response",
                        rag_response,
                        "RAG"
                    )
                )
                
                # Update temporary message with RAG response
                await temp_message.edit_text(rag_response)
            except Exception as e:
                logger.error(f"Error handling message: {e}")
                await temp_message.edit_text("Sorry, I cannot process your request at this time. Please try again later.")
    finally:
        # Clean up the lock
        if user_id in input_locks:
            del input_locks[user_id]

def main():
    """
    Main function to start the bot
    """
    try:
        # Start health check server in a separate thread for Render
        health_thread = threading.Thread(target=start_health_server, daemon=True)
        health_thread.start()
        logger.info("Health check server started in background thread")
        
        # Create the Application
        application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

        # Start background cache refresh
        loop = asyncio.get_event_loop()
        loop.create_task(background_cache_refresh())
        logger.info("Background cache refresh task started")

        # Add command handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("events", lambda update, context: get_events(update.message)))
        application.add_handler(CommandHandler("faqs", lambda update, context: get_faqs(update.message)))
        application.add_handler(CommandHandler("assistants", lambda update, context: get_assistants(update.message)))
        
        # Add message and callback query handlers
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        application.add_handler(CallbackQueryHandler(button_callback))

        # Start the Bot in webhook mode
        port = int(os.environ.get("PORT", 8080))
        webhook_url = os.environ.get("WEBHOOK_URL")
        
        if webhook_url:
            application.run_webhook(
                listen="0.0.0.0",
                port=port,
                webhook_url=webhook_url
            )
        else:
            # Fallback to polling mode if webhook URL is not set
            application.run_polling()
            
    except Exception as e:
        logger.error(f"Error in main function: {e}")
        raise

if __name__ == "__main__":
    main() 