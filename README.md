# Telegram Coin & Dice Bot (Render-ready)
Flip a coin and roll dice via Telegram commands.

## Commands
- `/flip` or `/coin` – heads/tails
- `/roll` – roll a 6-sided die (1–6)


#Deploy to Render

1. Fork/Upload this repo to your GitHub.


2. On Render → New → Web Service → Connect your repo.


3. Set:

Environment: Python 3

Build command:
```
pip install -r requirements.txt
```

Start command:
```
gunicorn -w 1 -t 0 app:app
```

-w 1 ensures one worker (so only one polling thread runs).

-t 0 disables timeout for long polling.




4. Environment Variables (Render → Environment):

BOT_TOKEN = your Telegram Bot token from @BotFather (REQUIRED)

(Optional) LOG_CHAT_ID = a chat or user ID to receive startup logs (bot must have chatted there once). Not required.

(Optional) tune polling vars (POLL_TIMEOUT_SEC, POLL_SLEEP_SEC). Defaults are fine.



5. Deploy. Health endpoint is /health. If all good you’ll see { "ok": true, ... }.



Notes

This app uses long polling (no webhook). That’s simpler on Render and works fine on free/Starter tiers.

Gunicorn worker count must be 1 to avoid duplicate pollers.

The Flask server exists to satisfy Render’s HTTP requirement and to expose health endpoints.


License

MIT – do whatever, just keep the notice.
