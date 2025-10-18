# Doctors Chatbot

- Backend: FastAPI (`backend/`)
- Frontend: Static HTML/JS/CSS (`frontend/`)

## Local dev

```bash
cd backend
python load_data.py
export OPENAI_API_KEY=sk-...   # or use .env with python-dotenv
uvicorn main:app --reload
