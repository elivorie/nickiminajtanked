JUNO BOT — RAILWAY READY

What's changed:
- removed Replit-only files
- removed keep_alive / Flask dependency if it was present
- added requirements.txt
- added railway.json
- added Procfile
- main entry file is: main.py

Railway variables to add:
- DISCORD_TOKEN = your bot token

Start command:
- python main.py

Notes:
- if this bot uses SQLite or local JSON, those files are included
- local file data can reset on redeploy unless you add persistent storage later
- if you want, move to Railway Postgres later for permanent storage
