import threading
import logging
from flask import Flask, render_template
from flask_socketio import SocketIO
from src.config import engine, CLIENT_NAME, FLASK_WEB_PORT, client_sockets
from src.database import (
    initialize_database,
    get_last_block_hash,
    get_ledger_blocks,
    get_ledger_blocks_before,
)
from src.blockchain import calculate_hash, broadcast_block_to_peers, validate_chain
from src.utils import get_utc_timestamp, convert_utc_to_local, safe_emit, set_socketio
from src.peer_discovery import start_tcp_server, connect_to_peers, periodic_ledger_sync
from src.connect_tunnel_interface import monitor_tunnel_status
from sqlalchemy import text

app = Flask(
    __name__
)  # Flask will automatically look for 'templates' and 'static' folders
socketio = SocketIO(app, logger=False, engineio_logger=False, cors_allowed_origins="*")

# Set the global reference
set_socketio(socketio)


@app.route("/")
def index():
    return render_template("chat.html", client_name=CLIENT_NAME)


@socketio.on("send_message")
def handle_send_message(msg):
    utc_timestamp = get_utc_timestamp()
    prev_hash = get_last_block_hash()
    block_hash = calculate_hash(CLIENT_NAME, utc_timestamp, msg, prev_hash)
    block = {
        "sender": CLIENT_NAME,
        "timestamp": utc_timestamp,
        "message": msg,
        "prev_hash": prev_hash,
        "hash": block_hash,
    }
    try:
        with engine.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO messages (sender, timestamp, message) VALUES (:sender, :timestamp, :message)"
                ),
                {"sender": CLIENT_NAME, "timestamp": utc_timestamp, "message": msg},
            )
            conn.execute(
                text(
                    "INSERT INTO ledger (sender, timestamp, message, prev_hash, hash) VALUES (:sender, :timestamp, :message, :prev_hash, :hash)"
                ),
                block,
            )
            conn.commit()
    except Exception as e:
        logging.error(f"[DB Error] {e}")
    block_with_display = block.copy()
    block_with_display["display_timestamp"] = convert_utc_to_local(utc_timestamp)
    safe_emit("receive_message", block_with_display, to_all=True)
    broadcast_block_to_peers(block, client_sockets)
    logging.info(f"[Send Message] Message sent and broadcasted by {CLIENT_NAME}")


@socketio.on("refresh_chat")
def handle_refresh_chat(data=None):
    limit = data.get("limit", 50) if data else 50
    safe_emit("chat_history", get_ledger_blocks(0, limit))


@socketio.on("load_older_messages")
def handle_load_older_messages(data):
    before_timestamp = data.get("before_timestamp")
    limit = data.get("limit", 20)
    if before_timestamp:
        older_messages = get_ledger_blocks_before(before_timestamp, limit)
        safe_emit("older_messages", older_messages)
    else:
        safe_emit("older_messages", [])


@socketio.on("check_new_messages")
def handle_check_new_messages():
    safe_emit("chat_history", get_ledger_blocks(0, 50))


if __name__ == "__main__":
    # Initialize database
    initialize_database()

    # Validate blockchain
    if not validate_chain():
        logging.warning("[Startup] Local chain invalid. Sync may be needed.")

    # Start tunnel monitoring thread
    logging.info("[Startup] Starting tunnel monitor...")
    threading.Thread(target=monitor_tunnel_status, daemon=True).start()

    # Start TCP server thread
    logging.info("[Startup] Starting TCP server...")
    threading.Thread(target=start_tcp_server, daemon=True).start()

    # Start peer connection thread
    logging.info("[Startup] Starting peer connections...")
    threading.Thread(target=connect_to_peers, daemon=True).start()

    # Start periodic sync thread
    logging.info("[Startup] Starting periodic ledger sync...")
    threading.Thread(target=periodic_ledger_sync, daemon=True).start()

    # Start Flask web server
    logging.info(f"[Web] Starting chat app on port {FLASK_WEB_PORT}")
    socketio.run(app, host="0.0.0.0", port=FLASK_WEB_PORT, debug=False)
