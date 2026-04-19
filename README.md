# sahayak

eligibility matching for 3,400+ indian government welfare schemes.
conversational api, bilingual (en/hi), with explainability.

## quick start

```bash
pip install -e .
export GEMINI_API_KEY=your-key
uvicorn src.conversation.interfaces.web:app --reload --port 8000
```

open http://localhost:8000

## structure

- `src/` — conversation engine, matching engine, fastapi server
- `parsed_schemes/` — 68 batch files, 3,400 schemes, 20,718 rules
- `public/` — static assets (maps, pdf, landing page)
- `api/index.py` — vercel serverless entry
- `vercel.json` — vercel routing config

## deploy

### vercel (static + serverless api)

```bash
git push
# then: https://vercel.com/new → import repo
# set GEMINI_API_KEY in env vars
```

live at `https://your-project.vercel.app`

### render (websocket support)

https://dashboard.render.com → select repo → render detects render.yaml

set GEMINI_API_KEY and deploy.

## env vars

```bash
GEMINI_API_KEY          # required
OPENROUTER_API_KEY      # optional fallback
TELEGRAM_BOT_TOKEN      # optional alerts
TELEGRAM_CHAT_ID        # optional alerts
```

see `.env.example`

## maps

- `/ambiguity-map-global.html` — all 1,199 ambiguities
- `/ambiguity-map-anchor-schemes.html` — 12 priority schemes
- `/report.pdf` — technical report

open in browser, no server needed (maps load `rules_data.js` from same dir).

## api

- `POST /api/chat` — http
- `WS /ws/chat` — websocket (vercel will fall back to http post)
- `GET /health` — liveness

