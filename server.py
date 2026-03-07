# WhatsApp Bot Service - FastAPI Implementation
# Connects WhatsApp → Database → Agent → MCP Tools
# Added deploy.yml for auto deployment

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorClient
import os
import uvicorn
from dotenv import load_dotenv
from contextlib import asynccontextmanager
import httpx
from datetime import datetime
import json

# Load environment variables from .env file
load_dotenv()

# MongoDB Atlas connection string from environment variable
MONGODB_URL = os.getenv("MONGODB_URL")
# Agent service URL from environment variable
AGENT_URL = os.getenv("AGENT_URL", "https://newapi.alumnx.com/agrigpt/agent/chat")
# Speech service URL for translation (set in Vercel/Deployment environment)
SPEECH_SERVICE_URL = os.getenv("SPEECH_SERVICE_URL", "https://newapi.alumnx.com/agrigpt/speech")

print("\n" + "="*80)
print("🚀 WHATSAPP BOT SERVICE - STARTUP CONFIGURATION")
print("="*80)
print(f"MONGODB_URL: {MONGODB_URL[:50]}..." if MONGODB_URL else "MONGODB_URL: NOT SET")
print(f"AGENT_URL: {AGENT_URL}")
print(f"SPEECH_SERVICE_URL: {SPEECH_SERVICE_URL}")
print("="*80 + "\n")

# Global variables for MongoDB client and collections
client = None
db = None
users_collection = None
messages_collection = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for FastAPI app
    Handles startup and shutdown events
    """
    # Startup: Connect to MongoDB Atlas
    global client, db, users_collection
    print("\n📊 STARTING UP - CONNECTING TO MONGODB...")
    
    client = AsyncIOMotorClient(MONGODB_URL)
    try:
        # Ping MongoDB to verify connection
        await client.admin.command('ping')
        print("✅ Successfully connected to MongoDB Atlas!")
        
        # Set database and collection references AFTER client is initialized
        db = client.agriculture
        users_collection = db.users
        messages_collection = db.messages
        print("✅ Database and collection references set successfully!")
        print(f"📦 Database: {db.name}")
        print(f"📦 Collections: {users_collection.name}, {messages_collection.name}\n")
        
    except Exception as e:
        print(f"❌ Failed to connect to MongoDB: {e}\n")
    
    yield
    
    # Shutdown: Close MongoDB connection
    if client:
        client.close()
        print("❌ MongoDB connection closed")

# Initialize FastAPI app with lifespan handler
app = FastAPI(
    title="WhatsApp Bot Service",
    description="Service to handle WhatsApp messages and interact with AI agent",
    version="2.0.0",
    lifespan=lifespan
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("WHATSAPP_ORIGIN")] if os.getenv("WHATSAPP_ORIGIN") else ["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ============================================================================
# PYDANTIC MODELS
# ============================================================================

class WhatsAppRequest(BaseModel):
    """Request model for incoming WhatsApp messages"""
    chatId: str
    phoneNumber: str
    message: str
    language: str = "en"

class WhatsAppResponse(BaseModel):
    """Response model for WhatsApp messages"""
    chatId:str
    phoneNumber: str
    message: str
    language: str = "en"
    timestamp: str = None
    status: str = "success"

class HealthResponse(BaseModel):
    """Health check response model"""
    status: str
    service: str
    version: str
    timestamp: str
    dependencies: dict

# ============================================================================
# API ENDPOINTS
# ============================================================================

@app.get("/")
async def root():
    """
    Root endpoint - Returns service information and available endpoints
    
    Returns:
        dict: Service status and endpoint information
    """
    return {
        "status": "healthy",
        "service": "WhatsApp Bot Service",
        "version": "2.0.0",
        "description": "Handles WhatsApp messages and routes to AI agent",
        "endpoints": {
            "root": "GET / (Service info)",
            "health": "GET /health (Health check)",
            "whatsapp": "POST /whatsapp (Main WhatsApp endpoint)",
            "docs": "GET /docs (Swagger UI)",
            "redoc": "GET /redoc (ReDoc UI)"
        }
    }

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Health check endpoint - Returns service health status and database connection
    
    Returns:
        dict: Health status of the service and its dependencies
    """
    # Check database connection
    db_status = "disconnected"
    try:
        if client:
            await client.admin.command('ping')
            db_status = "connected"
    except Exception as e:
        print(f"🔴 Health check - Database error: {str(e)}")
        db_status = f"error: {str(e)}"
    
    # Check agent service availability
    agent_status = "unknown"
    if AGENT_URL:
        try:
            async with httpx.AsyncClient(timeout=5) as http_client:
                response = await http_client.get(f"{AGENT_URL.replace('/chat', '')}/docs")
                if response.status_code == 200:
                    agent_status = "healthy"
                else:
                    agent_status = f"unhealthy ({response.status_code})"
        except:
            agent_status = "unreachable"
    else:
        agent_status = "not configured"
    
    return {
        "status": "healthy" if db_status == "connected" else "degraded",
        "service": "WhatsApp Bot Service",
        "version": "2.0.0",
        "timestamp": datetime.utcnow().isoformat(),
        "dependencies": {
            "database": db_status,
            "agent_service": agent_status
        }
    }

def detect_language(text: str) -> str:
    """
    Detect if text is Telugu, Hindi, or English based on character ranges
    """
    # Telugu range: 0C00–0C7F
    # Hindi/Devanagari range: 0900–097F
    
    telugu_chars = 0
    hindi_chars = 0
    
    for char in text:
        cp = ord(char)
        if 0x0C00 <= cp <= 0x0C7F:
            telugu_chars += 1
        elif 0x0900 <= cp <= 0x097F:
            hindi_chars += 1
            
    if telugu_chars > 0 and telugu_chars >= hindi_chars:
        return "te"
    if hindi_chars > 0:
        return "hi"
    return "en"

# ============================================================================
# DATABASE OPERATIONS
# ============================================================================

async def query_database(phoneNumber: str) -> dict:
    """
    Query MongoDB for user data by phone number
    If user doesn't exist, create a new user with just the phone number
    
    Args:
        phoneNumber: User's phone number
        
    Returns:
        dict: User data from database
    """
    print(f"\n📱 DATABASE QUERY - Phone: {phoneNumber}")
    
    try:
        # Check if users_collection is initialized
        if users_collection is None:
            print("❌ Database not initialized")
            raise HTTPException(status_code=500, detail="Database not initialized")
        
        # Search for existing user by phone number
        user_data = await users_collection.find_one({"phoneNumber": phoneNumber})
        
        if user_data:
            # User exists, remove MongoDB's internal _id field
            user_data.pop('_id', None)
            # Convert datetime to ISO string for JSON serialization
            if 'createdAt' in user_data and isinstance(user_data['createdAt'], datetime):
                user_data['createdAt'] = user_data['createdAt'].isoformat()
            print(f"✅ Found existing user with phone number: {phoneNumber}")
            print(f"   User data: {user_data}")
            return user_data
        else:
            # User doesn't exist, create new user
            print(f"📝 Creating new user with phone number: {phoneNumber}")
            created_at = datetime.utcnow()
            new_user = {
                "phoneNumber": phoneNumber,
                "createdAt": created_at,
                "messageCount": 0,
                "lastMessage": None
            }
            
            # Insert new user into database
            result = await users_collection.insert_one(new_user)
            print(f"✅ Created new user with ID: {result.inserted_id}")
            
            # Return the new user data (without _id and datetime converted to string)
            new_user.pop('_id', None)
            new_user['createdAt'] = created_at.isoformat()
            return new_user
            
    except Exception as e:
        # Handle any database errors
        print(f"❌ Database error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

async def update_user_message_count(phoneNumber: str) -> None:
    """
    Update user's message count and last message timestamp
    
    Args:
        phoneNumber: User's phone number
    """
    try:
        if users_collection is None:
            return
        
        await users_collection.update_one(
            {"phoneNumber": phoneNumber},
            {
                "$inc": {"messageCount": 1},
                "$set": {"lastMessage": datetime.utcnow()}
            }
        )
        print(f"✅ Updated message count for user: {phoneNumber}")
    except Exception as e:
        print(f"⚠️  Could not update message count: {str(e)}")

async def save_chat_message(phoneNumber: str, role: str, content: str, chatId: str, content_en: str = None) -> None:
    """
    Save a message to the database with optional English translation for context
    """
    try:
        if messages_collection is None:
            return
        
        message_doc = {
            "phoneNumber": phoneNumber,
            "chatId": chatId,
            "role": role, # 'user' or 'assistant'
            "content": content,
            "content_en": content_en or content, # Fallback to native if no EN provided
            "timestamp": datetime.utcnow()
        }
        await messages_collection.insert_one(message_doc)
        print(f"💾 Saved {role} message to database (EN: {content_en is not None})")
    except Exception as e:
        print(f"⚠️  Failed to save message: {e}")

async def get_recent_history(phoneNumber: str, limit: int = 5) -> str:
    """
    Retrieve the last N messages in English to provide context to the AI
    """
    try:
        if messages_collection is None:
            return ""
        
        cursor = messages_collection.find({"phoneNumber": phoneNumber}).sort("timestamp", -1).limit(limit)
        history = await cursor.to_list(length=limit)
        
        if not history:
            return ""
            
        # Reverse to get chronological order
        history.reverse()
        
        context = "\n--- Recent Conversation History (for context) ---\n"
        for msg in history:
            prefix = "User" if msg['role'] == 'user' else "AgriGPT"
            # Use English content for the AI engine
            msg_content = msg.get('content_en', msg.get('content', ''))
            context += f"{prefix}: {msg_content}\n"
        context += "--- End of History ---\n\n"
        return context
    except Exception as e:
        print(f"⚠️  Error fetching history: {e}")
        return ""

# ============================================================================
# AGENT COMMUNICATION
# ============================================================================

async def send_to_agent(chatId: str, message: str, user_data: dict, language: str = "en") -> str:
    """
    Send user message to external agent service via POST request
    """
    phone_number = user_data.get('phoneNumber', 'unknown')
    
    print(f"\n🤖 CALLING AGENT SERVICE")
    print(f"   Agent URL: {AGENT_URL}")
    print(f"   Chat Id: {chatId}")
    print(f"   User: {phone_number}")
    print(f"   Message: {message[:100]}...")        
    
    try:
        payload = {
            "chatId": chatId,
            "phone_number": phone_number,
            "message": message,
            "language": language
        }

        print(f"📤 Sending payload to agent: {json.dumps(payload)}")

        # Use httpx async client to make POST request to agent
        async with httpx.AsyncClient() as http_client:
            response = await http_client.post(
                AGENT_URL,
                json=payload,
                headers={
                    "accept": "application/json",
                    "Content-Type": "application/json"
                },
                timeout=120.0  # 120 second timeout
            )

            print(f"📥 Received response - Status: {response.status_code}")
            response.raise_for_status()

            agent_data = response.json()
            print(f"📦 Response data: {agent_data}")

            # Agent returns bare "Not found" for new chat sessions that have no
            # Gemini history yet. Retry using the Gemini-enabled fallback thread
            # ("1") so the user always gets a real answer. The user's own chatId
            # is still tried first — "1" is only used internally here.
            if agent_data.get("response", "").strip() == "Not found in knowledge base":
                print("⚠️  KB returned no answer — retrying via Gemini fallback thread...")
                fallback_payload = {
                    "chatId": "1",
                    "phone_number": phone_number,
                    "message": message
                }
                fb_response = await http_client.post(
                    AGENT_URL,
                    json=fallback_payload,
                    headers={
                        "accept": "application/json",
                        "Content-Type": "application/json"
                    },
                    timeout=120.0
                )
                if fb_response.status_code == 200:
                    fb_data = fb_response.json()
                    if fb_data.get("response", "").strip() not in ("", "Not found in knowledge base"):
                        print(f"✅ Gemini fallback response received")
                        return fb_data

            return agent_data
            
    except httpx.TimeoutException:
        # Handle timeout errors - agent service is taking too long
        error_msg = f"Agent service timeout for user {phone_number}"
        print(f"⏱️  {error_msg}")
        return {
            "response": "Sorry, our service is taking longer than expected. Please try again in a few moments.",
            "sources": []
        }
        
    except httpx.HTTPStatusError as e:
        # Handle HTTP status errors (4xx, 5xx)
        status_code = e.response.status_code
        print(f"❌ Agent service HTTP error: {status_code}")
        print(f"   Response: {e.response.text[:200]}")
        
        error_msg = ""
        if status_code == 405:
            error_msg = "Sorry, our AI assistant is currently unavailable. We're working to restore the service. Please try again later."
        elif status_code == 422:
            error_msg = "Sorry, there was an issue with your request format. Please try again."
        elif status_code >= 500:
            error_msg = "Sorry, our AI assistant is experiencing technical difficulties. Please try again in a few minutes."
        elif status_code >= 400:
            error_msg = "Sorry, we're unable to process your request right now. Please try again later."
        else:
            error_msg = f"Agent error: {status_code}"
        
        return {
            "response": error_msg,
            "sources": []
        }
            
    except httpx.ConnectError as e:
        # Handle connection errors - service is down or unreachable
        print(f"🔌 Agent service connection error: {str(e)}")
        print(f"   Agent URL: {AGENT_URL}")
        return {
            "response": "Sorry, our AI assistant is currently offline. We're working to restore the service. Please check back soon.",
            "sources": []
        }
        
    except httpx.RequestError as e:
        # Handle other request errors
        print(f"📡 Agent service request error: {str(e)}")
        return {
            "response": "Sorry, we're having trouble connecting to our AI assistant. Please try again in a few moments.",
            "sources": []
        }
        
    except ValueError as e:
        # JSON decode error
        print(f"📋 JSON parsing error: {str(e)}")
        return {
            "response": "Sorry, we received an invalid response from our AI assistant. Please try again.",
            "sources": []
        }
        
    except Exception as e:
        # Handle any other unexpected errors
        print(f"⚠️  Unexpected agent communication error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            "response": "Sorry, something went wrong. Please try again later.",
            "sources": []
        }

# ============================================================================
# MAIN WHATSAPP ENDPOINT
# ============================================================================

@app.post("/whatsapp", response_model=WhatsAppResponse)
async def handle_whatsapp_request(req: WhatsAppRequest):
    """
    Main endpoint to handle incoming WhatsApp messages
    
    Flow:
    1. Validate request
    2. Query database for user data (create if doesn't exist)
    3. Send query to agent
    4. Update user message count
    5. Return agent response to WhatsApp
    
    Args:
        req: WhatsAppRequest containing phoneNumber and message
        
    Returns:
        WhatsAppResponse: Agent's response with metadata
    """
    print("\n" + "🌟"*40)
    print(f"📲 NEW WHATSAPP MESSAGE")
    print("🌟"*40)
    print(f"Chat Id:{req.chatId}")
    print(f"Phone: {req.phoneNumber}")
    print(f"Message: {req.message[:100]}...")
    print("🌟"*40 + "\n")
    
    try:
        # Step 1: Detect/Verify Language
        # Use provided language or auto-detect from the message text
        detected_lang = req.language
        if not detected_lang or detected_lang == "en":
            detected_lang = detect_language(req.message)
            print(f"🔍 Auto-detected language: {detected_lang}")

        # Step 2: Query the database for user's data (creates user if not exists)
        print("Step 1️⃣: Querying database...")
        user_data = await query_database(req.phoneNumber)
        print(f"✅ Got user data\n")

        # Step 2.2: Translate User Message to English if native
        english_message = req.message
        if detected_lang != "en":
            print(f"Step 1️⃣.2: Translating user message from {detected_lang} to English...")
            try:
                speech_svc_base = os.getenv("SPEECH_SVC_URL", "http://localhost:8001")
                speech_svc_url = f"{speech_svc_base}/translate"
                async with httpx.AsyncClient() as http_client:
                    trans_resp = await http_client.post(
                        speech_svc_url,
                        json={"text": req.message, "target_lang": "en", "source_lang": detected_lang},
                        timeout=20.0
                    )
                    if trans_resp.status_code == 200:
                        english_message = trans_resp.json().get("translated_text", req.message)
                        print(f"✅ User message translated to EN: {english_message[:100]}...")
            except Exception as e:
                print(f"⚠️ User translation failed: {e}")

        # Step 2.5: Get recent chat history to provide context (in English)
        print("Step 1️⃣.5: Fetching conversation history...")
        history_context = await get_recent_history(req.phoneNumber)
        
        # Save user message to DB (both versions)
        await save_chat_message(req.phoneNumber, "user", req.message, req.chatId, english_message)

        # Step 3: Send the user query to the agent (with history context and language)
        print("Step 2️⃣: Sending to agent...")
        contextual_query = f"{history_context}Farmer's current question: {english_message}" if history_context else english_message
        agent_response_en = await send_to_agent(req.chatId, contextual_query, user_data, detected_lang)
        
        # Save AI response to DB (initially as assistant role)
        ai_msg_en = str(agent_response_en)
        print(f"✅ Got agent response (EN): {ai_msg_en[:100]}...\n")

        # Step 4: Update user message count
        await update_user_message_count(req.phoneNumber)

        # Step 5: Translate agent response back to detected language
        final_message = ai_msg_en
        if detected_lang != "en":
            print(f"Step 4️⃣: Translating response back to {detected_lang}...")
            try:
                speech_svc_base = os.getenv("SPEECH_SVC_URL", "http://localhost:8001")
                speech_svc_url = f"{speech_svc_base}/translate"
                async with httpx.AsyncClient() as http_client:
                    trans_resp = await http_client.post(
                        speech_svc_url,
                        json={"text": ai_msg_en, "target_lang": detected_lang, "source_lang": "en"},
                        timeout=30.0
                    )
                    if trans_resp.status_code == 200:
                        final_message = trans_resp.json().get("translated_text", ai_msg_en)
                        print(f"✅ AI Response translated to {detected_lang}")
                    else:
                        print(f"⚠️ AI Translation to {detected_lang} failed, using English.")
            except Exception as e:
                print(f"⚠️ AI Translation error: {e}")

        # Save AI response to DB
        await save_chat_message(req.phoneNumber, "assistant", final_message, req.chatId, ai_msg_en)

        # Step 7: Prepare and return response - matching agent service payload
        response_data = {
            "chatId": req.chatId,
            "phoneNumber": req.phoneNumber,
            "message": final_message,
            "language": detected_lang,
            "timestamp": datetime.utcnow().isoformat(),
            "status": "success"
# ADMIN ENDPOINTS (For Dashboard)
# ============================================================================

@app.get("/admin/users")
async def get_all_users():
    """Returns list of users for Admin Dashboard"""
    try:
        cursor = users_collection.find().sort("createdAt", -1)
        users = await cursor.to_list(length=100)
        for u in users:
            u["_id"] = str(u["_id"])
            if isinstance(u.get("createdAt"), datetime):
                u["createdAt"] = u["createdAt"].isoformat()
        return users
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/admin/stats")
async def get_stats():
    """Returns overall platform statistics"""
    try:
        user_count = await users_collection.count_documents({})
        msg_count = await messages_collection.count_documents({})
        
        # Get users from last 7 days (mock logic for demo if no timestamps)
        return {
            "totalUsers": user_count,
            "totalMessages": msg_count,
            "activeSessions": 5, # Placeholder for demo
            "platformHealth": "Healthy"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# RUN
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    
    print("\n" + "="*80)
    print("🚀 STARTING WHATSAPP BOT SERVICE")
    print("="*80)
    print("Run with: uvicorn server:app --host 0.0.0.0 --port 8000")
    print("Or use the command below:")
    print("  uvicorn server:app --reload")
    print("="*80 + "\n")
    
    uvicorn.run(app, host="0.0.0.0", port=8000)