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
        print("✅ Database and collection references set successfully!")
        print(f"📦 Database: {db.name}")
        print(f"📦 Collection: {users_collection.name}\n")
        
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
    """Response model for WhatsApp messages - Matches agent service payload"""
    chatId: str
    phone_number: str  # Changed from phoneNumber to match agent service
    response: str      # Changed from message to match agent service
    sources: list = [] # Added sources list from agent service

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

# ============================================================================
# AGENT COMMUNICATION
# ============================================================================

async def send_to_agent(chatId: str, message: str, user_data: dict) -> str:
    """
    Send user message to external agent service via POST request
    Wait for agent's response and return it
    
    Agent Request Format:
        POST /chat
        {
            "message": "user message here"
        }
    
    Agent Response Format:
        {
            "response": "agent response here"
        }
    
    Args:
        message: User's message/query
        user_data: User's data from database (for logging)
        
    Returns:
        str: Agent's response text or error message if service unavailable
    """
    phone_number = user_data.get('phoneNumber', 'unknown')
    
    print(f"\n🤖 CALLING AGENT SERVICE")
    print(f"   Agent URL: {AGENT_URL}")
    print(f"   Chat Id: {chatId}")
    print(f"   User: {phone_number}")
    print(f"   Message: {message[:100]}...")
    
    try:
        # Prepare payload for agent service
        # Note: External agent service expects a JSON object with a 'message' field.
        payload = {
            "chatId": chatId,
            "phone_number": phone_number,
            "message": message
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
        # Step 1: Validate request
        if not req.phoneNumber or not req.message or not req.chatId:
            print("❌ Invalid request - missing phoneNumber or message or chatId")
            raise HTTPException(status_code=400, detail="phoneNumber, message and chatId are required")
        
        # Step 2: Query the database for user's data (creates user if not exists)
        print("Step 1️⃣: Querying database...")
        user_data = await query_database(req.phoneNumber)
        print(f"✅ Got user data: {user_data}\n")

        # Step 3: Send the user query to the agent
        print("Step 2️⃣: Sending to agent...")
        agent_response = await send_to_agent(req.chatId, req.message, user_data)
        print(f"✅ Got agent response: {str(agent_response)[:100]}...\n")

        # Step 4: Update user message count
        print("Step 3️⃣: Updating user statistics...")
        await update_user_message_count(req.phoneNumber)
        print("✅ Updated user statistics\n")

        # Step 5: Extract response and sources from agent
        agent_response_text = agent_response.get("response", "")
        agent_sources = agent_response.get("sources", [])
        
        # Step 6: Translate agent response if necessary
        final_message = agent_response_text
        if req.language and req.language != "en":
            print(f"Step 4️⃣: Translating response to {req.language}...")
            try:
                speech_svc_url = f"{SPEECH_SERVICE_URL}/translate"
                async with httpx.AsyncClient() as http_client:
                    trans_resp = await http_client.post(
                        speech_svc_url,
                        json={
                            "text": agent_response_text,
                            "target_lang": req.language,
                            "source_lang": "en"
                        },
                        timeout=30.0
                    )
                    if trans_resp.status_code == 200:
                        final_message = trans_resp.json().get("translated_text", agent_response_text)
                        print(f"✅ Translated response: {final_message[:100]}...")
                    else:
                        print(f"⚠️ Translation failed (status {trans_resp.status_code}), sending English.")
            except Exception as e:
                print(f"⚠️ Translation error: {str(e)}, sending English.")

        # Step 7: Prepare and return response - matching agent service payload
        response_data = {
            "chatId": req.chatId,
            "phone_number": req.phoneNumber,
            "response": final_message,
            "sources": agent_sources
        }
        
        print("✅ WHATSAPP REQUEST COMPLETE")
        print(f"Response: {json.dumps(response_data, indent=2)}\n")
        
        return response_data
        
    except HTTPException as e:
        print(f"\n❌ HTTP Exception: {e.detail}\n")
        raise
        
    except Exception as e:
        print(f"\n❌ Unexpected error: {str(e)}\n")
        import traceback
        traceback.print_exc()
        
        # Return error response - matching agent service payload
        return {
            "chatId": req.chatId,
            "phone_number": req.phoneNumber,
            "response": "Sorry, something went wrong processing your request. Please try again later.",
            "sources": []
        }

# ============================================================================
# ERROR HANDLERS
# ============================================================================

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Custom HTTP exception handler"""
    print(f"\n❌ HTTP Exception - Status: {exc.status_code}, Detail: {exc.detail}\n")
    return {
        "error": exc.detail,
        "status_code": exc.status_code,
        "timestamp": datetime.utcnow().isoformat()
    }

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Custom general exception handler"""
    print(f"\n❌ General Exception: {str(exc)}\n")
    return {
        "error": "Internal server error",
        "detail": str(exc),
        "timestamp": datetime.utcnow().isoformat()
    }

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