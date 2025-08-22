import os
import re
import time
import json
import math
import random
import signal
import threading
import sys
from typing import Optional, Tuple

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


def send_message(chat_id: str | int, text: str, parse_mode: Optional[str] = None):
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    resp = tg_api("sendMessage", **payload)
    if not resp.get("ok"):
        print(f"[TG SEND FAIL] {resp}")


def parse_roll_arg(s: str) -> Tuple[int, int]:
    """
    Accepts:
      - empty string -> 1d6
      - integer -> 1d<int>
      - NdM like 2d6, 1D20 (case-insensitive)
    Enforces: 1 <= N <= 20, 2 <= M <= 1000
    """
    s = s.strip().lower()
    if not s:
        return 1, 6
    if re.fullmatch(r"\d+", s):
        n, m = 1, int(s)
    else:
        mobj = re.fullmatch(r"(\d{1,2})d(\d{1,4})", s)
        if not mobj:
            raise ValueError("Invalid format. Use /roll, /roll 20, or /roll NdM e.g. 2d6")
        n, m = int(mobj.group(1)), int(mobj.group(2))
    n = max(1, min(n, 20))
    m = max(2, min(m, 1000))
    return n, m


def handle_command(chat_id: int, text: str):
    t = text.strip()
    # remove bot username suffix like /roll@YourBot
    t = re.sub(r"@(\w+)", "", t)

    if t.startswith("/start"):
        send_message(
            chat_id,
            (
                "👋 Namaste! Main ek simple bot hoon.\n\n"
                "Commands:\n"
                "• /flip — flip a coin\n"
                "• /coin — same as /flip\n"
                "• /roll — roll 1–6\n"
                "• /roll NdM — e.g. 2d6, 1d20\n"
                "• /help — show commands\n"
            ),
        )
        return

    if t.startswith("/help"):
        return handle_command(chat_id, "/start")

    if t.startswith("/flip") or t.startswith("/coin"):
        result = random.choice(["HEADS", "TAILS"])  # unbiased
        send_message(chat_id, f"🪙 {result}")
        return

    if t.startswith("/roll"):
        arg = t[len("/roll"):].strip()
        try:
            n, m = parse_roll_arg(arg)
        except ValueError as e:
            send_message(chat_id, f"❌ {e}")
            return

        rolls = [random.randint(1, m) for _ in range(n)]
        total = sum(rolls)
        if n == 1:
            send_message(chat_id, f"🎲 d{m} → {rolls[0]}")
        else:
            send_message(chat_id, f"🎲 {n}d{m} → {rolls} = {total}")
        return

    # Fallback
    send_message(chat_id, "🤖 Unknown command. Type /help")


# ---------- Polling Thread ----------

def poll_loop():
    global last_update_id
    ensure_env_or_die()

    # Log startup (if configured)
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

# Start at import time (so gunicorn worker begins polling immediately)
start_poller_once()


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, threaded=True)