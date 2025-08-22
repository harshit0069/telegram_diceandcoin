import os
import time
import random
import signal
import threading
import sys
from typing import Optional

import requests
from flask import Flask, jsonify

# ================== CONFIG ==================
BOT_TOKEN = os.getenv("BOT_TOKEN")  # REQUIRED on Render

# Polling knobs (sane defaults)
POLL_TIMEOUT_SEC = int(os.getenv("POLL_TIMEOUT_SEC", 50))   # Telegram long-poll timeout (max 50)
POLL_SLEEP_SEC   = float(os.getenv("POLL_SLEEP_SEC", 0.5))   # small gap between polls

# Optional: log a startup message to this chat id if set
LOG_CHAT_ID = os.getenv("LOG_CHAT_ID")
# ===========================================

app = Flask(__name__)

# Shared state
state_lock = threading.Lock()
last_update_id: Optional[int] = None
started_at_ts = time.time()

# ---------- Helpers ----------

def ensure_env_or_die():
    if not BOT_TOKEN:
        print("[BOOT] Missing required env var: BOT_TOKEN")
        print("[BOOT] Set it on Render dashboard (Environment) and redeploy.")
        sys.exit(1)


def tg_api(method: str, **params):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    try:
        r = requests.post(url, json=params, timeout=POLL_TIMEOUT_SEC + 10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"[TG API ERROR] {method}: {e}")
        return {"ok": False, "error": str(e)}


def send_message(chat_id: str | int, text: str):
    payload = {"chat_id": chat_id, "text": text}
    resp = tg_api("sendMessage", **payload)
    if not resp.get("ok"):
        print(f"[TG SEND FAIL] {resp}")


def handle_command(chat_id: int, text: str):
    t = text.strip().lower()

    if t.startswith("/flip") or t.startswith("/coin"):
        result = random.choice(["HEADS", "TAILS"])  # unbiased
        send_message(chat_id, f"🪙 {result}")
        return

    if t.startswith("/roll"):
        roll = random.randint(1, 6)
        send_message(chat_id, f"🎲 d6 → {roll}")
        return

    # Fallback
    send_message(chat_id, "🤖 Unknown command. Try /flip or /roll")


# ---------- Polling Thread ----------

def poll_loop():
    global last_update_id
    ensure_env_or_die()

    if LOG_CHAT_ID:
        try:
            send_message(LOG_CHAT_ID, "✅ Bot started on Render (polling mode)")
        except Exception:
            pass

    print("== Telegram poller started ==")
    while True:
        try:
            params = {
                "timeout": POLL_TIMEOUT_SEC,
                "allowed_updates": ["message"],
            }
            with state_lock:
                if last_update_id is not None:
                    params["offset"] = last_update_id + 1

            r = requests.get(
                f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
                params=params,
                timeout=POLL_TIMEOUT_SEC + 10,
            )
            data = r.json()
            if not data.get("ok"):
                print(f"[getUpdates NOT OK] {data}")
                time.sleep(2)
                continue

            for upd in data.get("result", []):
                with state_lock:
                    last_update_id = upd["update_id"]

                msg = upd.get("message")
                if not msg:
                    continue
                chat_id = msg.get("chat", {}).get("id")
                text = msg.get("text") or ""
                if not chat_id or not text:
                    continue

                try:
                    handle_command(chat_id, text)
                except Exception as e:
                    print(f"[HANDLE ERROR] {e}")

            time.sleep(POLL_SLEEP_SEC)
        except Exception as e:
            print(f"[POLL ERROR] {e}")
            time.sleep(2)


# ---------- Flask endpoints ----------
@app.route("/")
def root():
    return "OK", 200


@app.route("/health")
def health():
    with state_lock:
        st = {
            "ok": True,
            "last_update_id": last_update_id,
            "uptime_sec": round(time.time() - started_at_ts, 2),
        }
    return jsonify(st), 200


# ---------- Start threads & signals ----------
poller_thread = None


def start_poller_once():
    global poller_thread
    if poller_thread is None:
        poller_thread = threading.Thread(target=poll_loop, daemon=True)
        poller_thread.start()


def handle_shutdown(sig, frame):
    print(f"[SHUTDOWN] signal={sig}, exiting...")
    sys.exit(0)


signal.signal(signal.SIGTERM, handle_shutdown)
signal.signal(signal.SIGINT, handle_shutdown)

start_poller_once()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, threaded=True)