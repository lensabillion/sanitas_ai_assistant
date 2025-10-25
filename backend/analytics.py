# backend/analytics.py
import json, os
from typing import List, Optional
from collections import Counter

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from database import SessionLocal
from models import SymptomEvent
from openai import OpenAI
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from openai import OpenAI
oa_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))
router = APIRouter(prefix="/symptoms", tags=["symptom-analytics"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --------- request/response schemas ----------
class LogSymptomRequest(BaseModel):
    text: str
    interpreted_specialties_es: Optional[List[str]] = None
    resolved_specialties: Optional[List[str]] = None
    is_symptom_query: bool = True
    embedding: Optional[List[float]] = None
    force_english: bool = False   # OPTIONAL: set true to translate then embed

class LogSymptomResponse(BaseModel):
    id: int

class ClusterItem(BaseModel):
    cluster_id: int
    size: int
    label: str
    top_terms: List[str]
    top_specialties: List[str]
    example_texts: List[str]

class ClustersResponse(BaseModel):
    total_events: int
    k: int
    clusters: List[ClusterItem]

# --------- helpers ----------
def _embed(texts: List[str]) -> List[List[float]]:
    if not texts:
        return []
    r = oa_client.embeddings.create(model="text-embedding-3-small", input=texts)
    return [d.embedding for d in r.data]

def _translate_to_en(s: str) -> str:
    """Fast, low-temp ‘medical context’ translation to English."""
    msg = oa_client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0,
        messages=[
            {"role":"system","content":
             "Translate the user's medical symptom description to concise English suitable for analytics. Do not add advice."},
            {"role":"user","content": s}
        ]
    )
    return (msg.choices[0].message.content or "").strip()

def _ensure_embeddings(db: Session, rows: List[SymptomEvent]) -> None:
    need = [r for r in rows if not r.embedding]
    if not need:
        return
    texts = [r.text_en or r.text for r in need]
    embs = _embed(texts)
    for r, e in zip(need, embs):
        r.embedding = json.dumps(e)
    db.commit()

def _auto_k(n: int) -> int:
    import math
    if n < 6: return max(1, n)
    return max(2, min(12, int(math.sqrt(n))))

# --------- API: log a symptom ---------
@router.post("/log", response_model=LogSymptomResponse)
def log_symptom(req: LogSymptomRequest, db: Session = Depends(get_db)):
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="text is required")

    text_en = None
    if req.force_english:
        try:
            text_en = _translate_to_en(req.text.strip())
        except Exception:
            text_en = None

    evt = SymptomEvent(
        text=req.text.strip(),
        text_en=text_en,
        interpreted_specialties_es=req.interpreted_specialties_es or [],
        resolved_specialties=req.resolved_specialties or [],
        is_symptom_query=1 if req.is_symptom_query else 0,
        embedding=json.dumps(req.embedding) if req.embedding else None,
    )
    db.add(evt)
    db.commit()
    db.refresh(evt)

    # lazy embedding now to keep later queries snappy
    if not req.embedding and req.is_symptom_query:
        try:
            emb_input = evt.text_en or evt.text
            evt.embedding = json.dumps(_embed([emb_input])[0])
            db.commit()
        except Exception:
            pass

    return LogSymptomResponse(id=evt.id)

# --------- API: clusters for dashboard ---------
@router.get("/clusters", response_model=ClustersResponse)
def clusters(
    days: int = Query(30, ge=1, le=365),
    k: Optional[int] = Query(None, ge=1, le=50),
    min_len: int = Query(6, ge=1),
    db: Session = Depends(get_db),
):
    from datetime import datetime, timedelta
    from sqlalchemy import and_
    from sklearn.cluster import KMeans
    from sklearn.feature_extraction.text import TfidfVectorizer
    import numpy as np

    cutoff = datetime.utcnow() - timedelta(days=days)
    rows: List[SymptomEvent] = (
        db.query(SymptomEvent)
          .filter(and_(SymptomEvent.created_at >= cutoff,
                       SymptomEvent.is_symptom_query == 1))
          .order_by(SymptomEvent.created_at.desc())
          .all()
    )

    rows = [r for r in rows if r.text and len(r.text.strip()) >= min_len]
    total = len(rows)
    if total == 0:
        return ClustersResponse(total_events=0, k=0, clusters=[])

    _ensure_embeddings(db, rows)

    X = [json.loads(r.embedding) for r in rows if r.embedding]
    texts = [ (r.text_en or r.text) for r in rows if r.embedding]
    specs_list = [r.resolved_specialties or [] for r in rows if r.embedding]

    n = len(X)
    if n == 0:
        return ClustersResponse(total_events=0, k=0, clusters=[])

    k_use = min(k or _auto_k(n), n)
    km = KMeans(n_clusters=k_use, n_init="auto", random_state=0)
    labels = km.fit_predict(X)

    # TF-IDF terms for readable labels
    stop = set("""
      i me my we our you your he she it they what which who this that these those
      am is are was were be been being have has had do does did doing a an the and but or
      of at by for with about between into through during before after above below
      to from up down in out on over under again further then once here there when where why how
      yo mi me mis nosotros nos tu tus usted ustedes él ella ellos ellas su sus de la los las un una y o pero
    """.split())
    vec = TfidfVectorizer(max_features=5000, ngram_range=(1,2), stop_words=list(stop))
    tfidf = vec.fit_transform(texts)
    terms = vec.get_feature_names_out()

    clusters: List[ClusterItem] = []
    for cid in range(k_use):
        idxs = np.where(labels == cid)[0]
        if idxs.size == 0: 
            continue
        sub = tfidf[idxs].sum(axis=0)
        sub = np.asarray(sub).ravel()
        top_idx = sub.argsort()[-8:][::-1]
        top_terms = [terms[i] for i in top_idx if sub[i] > 0][:8]

        # pick a human label from top 2–3 terms
        label = " / ".join(top_terms[:3]) if top_terms else f"Cluster {cid}"

        # specialties inside cluster
        from collections import Counter
        spec_counter = Counter()
        for i in idxs:
            spec_counter.update(specs_list[int(i)])
        top_specs = [s for s,_ in spec_counter.most_common(5)]

        example_texts = [texts[int(i)] for i in idxs[:3]]

        clusters.append(ClusterItem(
            cluster_id=cid,
            size=int(idxs.size),
            label=label,
            top_terms=top_terms,
            top_specialties=top_specs,
            example_texts=example_texts
        ))

    clusters.sort(key=lambda c: c.size, reverse=True)
    return ClustersResponse(total_events=n, k=k_use, clusters=clusters)
