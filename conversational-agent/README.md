# Setup & Run

## Prerequisites

- Python 3.11+
- Node.js 20.19+
- [Docker Desktop](https://www.docker.com/products/docker-desktop/), running
- Chrome or Edge
- API keys: Deepgram, Gemini (Google AI Studio), TypeSafe/Jev

## 1. Clone

```bash
git clone <repository-url>
cd decentralised-ambulance-and-hospital-coordination/conversational-agent
```

## 2. Configure

```bash
cp .env.example .env
```

In `.env`, fill in `DEEPGRAM_API_KEY`, `GEMINI_API_KEY` and `JEV_API_KEY`.
`MONGODB_URI=mongodb://localhost:27017` is already set for the local Docker MongoDB. Replace it only if you use MongoDB Atlas.

## 3. Start MongoDB

With Docker Desktop open, run this in `conversational-agent/`:

```bash
docker compose up -d
```

## 4. Start the backend (terminal 1)

```bash
cd conversational-agent/backend
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

## 5. Start the frontend (terminal 2)

```bash
cd conversational-agent/frontend
npm install
npm run dev
```

## 6. Use it

Open http://localhost:5173, click **Start conversation** and allow the microphone.

## Stop

- Backend and frontend: `Ctrl+C`
- MongoDB: `docker compose down` in `conversational-agent/`

## Next time

Start Docker Desktop, then:
- `docker compose up -d`
- `source .venv/bin/activate && uvicorn main:app --reload --port 8000` in `backend/`
- `npm run dev` in `frontend/`

## Tests

```bash
cd conversational-agent/backend && source .venv/bin/activate && pytest
```
