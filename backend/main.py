import os, json, unicodedata
from typing import List, Set, Dict
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func, select

from database import SessionLocal
from models import Doctor, DoctorSpecialty

# --- Optional: load .env from project root or backend folder ---
try:
    from dotenv import load_dotenv
    load_dotenv()  # loads .env if present
except Exception:
    pass

# --- OpenAI client ---
from openai import OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

app = FastAPI(title="Doctor Matcher API")

# Allow frontend (any origin while developing)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# ---------- DB dependency ----------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ---------- Schemas ----------
class MatchRequest(BaseModel):
    symptoms: str  # raw user message

class MatchBySpecialtiesRequest(BaseModel):
    specialties_es: List[str]  # e.g. ["Cardiología","Neumología"]

# ---------- Helpers ----------
def _norm(s: str) -> str:
    """Lowercase + accent-insensitive string."""
    s = unicodedata.normalize("NFD", s or "")
    return "".join(ch for ch in s if unicodedata.category(ch) != "Mn").lower().strip()

@app.on_event("startup")
def build_specialty_index():
    """Index Spanish specialty labels that exist in DB for robust matching."""
    db = SessionLocal()
    try:
        idx: Dict[str, Set[str]] = {}
        for (spec,) in db.execute(select(DoctorSpecialty.specialty)).all():
            if not spec:
                continue
            idx.setdefault(_norm(spec), set()).add(spec)
        app.state.specialty_index = idx
        print(f"[startup] specialties indexed: {len(idx)} unique normalized labels")
    finally:
        db.close()

def _resolve_to_db_labels(input_specs: List[str]) -> Set[str]:
    """
    Map possibly variant inputs (accents/case/extra words) to exact DB labels.
    Strategy:
      1) exact normalized key hit (fast path)
      2) fuzzy: substring in either direction (norm-in-norm)
    """
    idx: Dict[str, Set[str]] = getattr(app.state, "specialty_index", {})
    out: Set[str] = set()
    inputs_norm = [_norm(s) for s in (input_specs or [])]

    # exact hits
    for k in inputs_norm:
        out.update(idx.get(k, set()))

    # fuzzy substring matches
    all_db_norm_to_orig = [(k, orig) for k, originals in idx.items() for orig in originals]
    for inp in inputs_norm:
        for norm_db, orig_db in all_db_norm_to_orig:
            if inp and (inp in norm_db or norm_db in inp):
                out.add(orig_db)

    return out

def _score_doctor_by_overlap(d: Doctor, targets_norm: Set[str]) -> int:
    have = {_norm(s.specialty) for s in d.specialties}
    return len(have & targets_norm)

def _top3_from_resolved(db: Session, resolved_labels: Set[str]):
    """Query doctors for given Spanish labels and return top-3 by overlap."""
    if not resolved_labels:
        return []

    q = (
        db.query(Doctor)
          .join(DoctorSpecialty)
          .filter(func.lower(DoctorSpecialty.specialty).in_([x.lower() for x in resolved_labels]))
          .distinct(Doctor.id)
          .limit(50)
          .all()
    )

    targets = {_norm(x) for x in resolved_labels}
    scored = []
    for d in q:
        score = _score_doctor_by_overlap(d, targets)
        if score > 0:
            scored.append((score, d))
    scored.sort(key=lambda t: (-t[0], (t[1].name or "").lower()))
    top = []
    for score, d in scored[:3]:
        specs = [s.specialty for s in d.specialties]
        overlap = [s for s in specs if _norm(s) in targets]
        top.append({
            "name": d.name,
            "specialization": "; ".join(specs),
            "contact": d.phones_normalized or d.phones or "N/A",
            "match_score": float(score),
            "match_reason": f"Matched specialties (ES): {', '.join(overlap)}",
        })
    return top

# ---------- Routes ----------
@app.get("/")
def home():
    return {"message": "Doctor Matcher API is running"}

@app.post("/triage")
def triage(req: MatchRequest, db: Session = Depends(get_db)):
    """
    1) Use GPT to classify if the message is a symptom query.
    2) If yes: get Spanish specialties + empathetic opening_message -> DB search -> top-3 doctors.
       If no: return a polite message; no specialties/doctors.
    """
    if client is None:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY not configured")

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.3,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a compassionate medical routing assistant for a clinic. "
                        "Return ONLY JSON with keys 'is_symptom_query', 'opening_message', and 'specialties_es'. "
                        "'is_symptom_query' must be a boolean indicating whether the user's message is about "
                        "their own health symptoms (e.g., pain, fever, cough, dizziness, etc.). "
                        "If 'is_symptom_query' is false, set 'specialties_es' to an empty array and write "
                        "opening_message' should be empathetic, non-diagnostic, and invite them to view suggested doctors. "
                        "The opening_message MUST be written in **English**, friendly, and natural sounding (never in Spanish). "
                        "Never include treatment, urgent instructions, news, or external information."
                        "If 'is_symptom_query' is true, 'specialties_es' must be an array of Spanish medical "
                        "specialties relevant to the described symptoms (for database matching). "
                        "'opening_message' should be empathetic, non-diagnostic, and invite them to view suggested doctors. "
                        "Never include treatment, urgent instructions, news, or external information."
                    ),
                },
                {"role": "user", "content": f"User message: {req.symptoms}"},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "DoctorTriageResponse",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "is_symptom_query": {"type": "boolean"},
                            "opening_message": {"type": "string", "minLength": 10, "maxLength": 300},
                            "specialties_es": {
                                "type": "array",
                                "items": {"type": "string"},
                                "minItems": 0
                            }
                        },
                        "required": ["is_symptom_query", "opening_message", "specialties_es"],
                        "additionalProperties": False,
                    },
                    "strict": True,
                },
            },
        )
        msg = resp.choices[0].message
        if hasattr(msg, "parsed") and msg.parsed:
            is_symptom = bool(msg.parsed.get("is_symptom_query", False))
            opening_message = (msg.parsed.get("opening_message", "") or "").strip()
            specialties_es = msg.parsed.get("specialties_es", []) if is_symptom else []
        else:
            parsed = json.loads(msg.content)
            is_symptom = bool(parsed.get("is_symptom_query", False))
            opening_message = (parsed.get("opening_message", "") or "").strip()
            specialties_es = parsed.get("specialties_es", []) if is_symptom else []
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"OpenAI error: {e}")

    # If not a symptom query: return friendly message; no specialties/doctors
    if not is_symptom:
        return {
            "disclaimer": "This system is for informational purposes only and does not provide medical advice.",
            "opening_message": opening_message or
                "Hi! I can help find doctors based on symptoms. Please describe what you’re feeling.",
            "interpreted_specialties_es_in": [],
            "resolved_specialties_in_db": [],
            "matched_doctors": [],
        }

    # Resolve specialties to DB labels and search
    resolved = _resolve_to_db_labels(specialties_es)
    doctors = _top3_from_resolved(db, resolved)

    return {
        "disclaimer": "This system is for informational purposes only and does not provide medical advice.",
        "opening_message": opening_message,
        "interpreted_specialties_es_in": specialties_es,
        "resolved_specialties_in_db": sorted(resolved),
        "matched_doctors": doctors,
    }

@app.post("/match_doctors_by_specialties")
def match_doctors_by_specialties(req: MatchBySpecialtiesRequest, db: Session = Depends(get_db)):
    resolved = _resolve_to_db_labels(req.specialties_es)
    doctors = _top3_from_resolved(db, resolved)
    return {
        "disclaimer": "This system is for informational purposes only and does not provide medical advice.",
        "interpreted_specialties_es_in": req.specialties_es,
        "resolved_specialties_in_db": sorted(resolved),
        "matched_doctors": doctors,
    }
