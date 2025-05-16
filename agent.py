import asyncio
import websockets
import os
import pty
import select
import logging
from datetime import datetime, timezone
import sys
import traceback
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

# Constants for retry logic
INITIAL_RETRY_DELAY = 2
MAX_RETRY_DELAY = 60
MAX_RETRIES = 10
AUDIT_LOG_FILE = "command_audit.log"

def audit_command(data: str):
    timestamp = datetime.now(tz=timezone.utc).isoformat()
    with open(AUDIT_LOG_FILE, "a") as f:
        f.write(f"{timestamp} | {data.strip()}\n")

async def handle_shell(uri):
    retry_delay = INITIAL_RETRY_DELAY
    retries = 0

    while retries < MAX_RETRIES:
        try:
            logging.info(f"🔌 Attempting to connect to dashboard at {uri}")
            async with websockets.connect(uri) as websocket:
                logging.info("✅ Connected to dashboard")

                # Fork PTY and start real shell
                pid, master_fd = pty.fork()
                if pid == 0:
                    # Child process: replace with the shell
                    shell = os.environ.get("SHELL", "/bin/bash")
                    os.execvp(shell, [shell])
                else:
                    # Parent process: communicate with shell through master_fd

                    async def read_from_shell():
                        while True:
                            await asyncio.sleep(0.01)
                            if select.select([master_fd], [], [], 0)[0]:
                                output = os.read(master_fd, 1024)
                                if output:
                                    try:
                                        await websocket.send(output.decode(errors="ignore"))
                                        logging.debug(f"⬆️  Sent output: {output[:50].decode(errors='ignore')}...")
                                    except Exception as e:
                                        logging.error(f"Error sending output to websocket: {e}")
                                        break

                    async def write_to_shell():
                        buffer = ""
                        while True:
                            try:
                                data = await websocket.recv()
                            except websockets.ConnectionClosed:
                                logging.info("WebSocket closed by server/client")
                                break

                            os.write(master_fd, data.encode())

                            # Audit command when Enter is pressed
                            if data in ("\n", "\r"):
                                if buffer.strip():
                                    audit_command(buffer)
                                    logging.info(f"📝 Audited command: {buffer.strip()}")
                                buffer = ""
                            elif data == "\x7f":  # Backspace
                                buffer = buffer[:-1]
                            else:
                                buffer += data

                    retry_delay = INITIAL_RETRY_DELAY
                    retries = 0

                    await asyncio.gather(read_from_shell(), write_to_shell())

        except websockets.ConnectionClosed as e:
            logging.warning(f"🔌 Connection closed: {e}")
        except Exception as e:
            logging.error(f"❌ Unexpected error:\n{traceback.format_exc()}")

        retries += 1
        logging.info(f"🔁 Retrying in {retry_delay}s (attempt {retries}/{MAX_RETRIES})...")
        await asyncio.sleep(retry_delay)
        retry_delay = min(retry_delay * 2, MAX_RETRY_DELAY)

    logging.critical("🛑 Max retries reached. Exiting agent.")
    sys.exit(1)

if __name__ == "__main__":
    try:
        asyncio.run(handle_shell("ws://localhost:8000/ws/agent"))
    except KeyboardInterrupt:
        logging.info("🛑 Agent manually stopped by user (KeyboardInterrupt)")