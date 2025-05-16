import os
import logging
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()


# Set up structured logging
if os.getenv("env") == "prodution":
    loggin_level = logging.INFO
else:
    loggin_level = logging.DEBUG
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=loggin_level
)


app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

agent_ws = None
clients = []

@app.get("/")
async def index():
    try:
        with open("static/terminal.html") as f:
            logging.info("📄 Served terminal.html to browser")
            return HTMLResponse(content=f.read(), status_code=200)
    except Exception as e:
        logging.error(f"Failed to load terminal.html: {e}")
        return HTMLResponse(content="Internal Server Error", status_code=500)

@app.websocket("/ws/agent")
async def agent_socket(websocket: WebSocket):
    global agent_ws
    await websocket.accept()
    agent_ws = websocket
    logging.info("🛰️  Agent connected to /ws/agent")

    try:
        while True:
            data = await websocket.receive_text()
            logging.debug(f"⬅️  Received from agent: {data[:50]}...")
            for client in clients:
                await client.send_text(data)
                logging.debug("➡️  Forwarded output to client")
    except WebSocketDisconnect:
        agent_ws = None
        logging.warning("❌ Agent disconnected")
    except Exception as e:
        agent_ws = None
        logging.error(f"⚠️ Agent connection error: {e}")

@app.websocket("/ws/client")
async def client_socket(websocket: WebSocket):
    await websocket.accept()
    clients.append(websocket)
    logging.info(f"🧑‍💻 Client connected to /ws/client — total: {len(clients)}")

    try:
        while True:
            data = await websocket.receive_text()
            logging.debug(f"⬅️  Received from client: {data}")
            if agent_ws:
                await agent_ws.send_text(data)
                logging.debug("➡️  Sent command to agent")
            else:
                logging.warning("⚠️ No agent connected. Cannot send data.")
    except WebSocketDisconnect:
        clients.remove(websocket)
        logging.warning(f"❌ Client disconnected — total: {len(clients)}")
    except Exception as e:
        clients.remove(websocket)
        logging.error(f"⚠️ Client connection error: {e}")
