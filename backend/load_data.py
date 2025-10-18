import math
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import select
from models import Doctor, DoctorSpecialty, DoctorCenter
from database import SessionLocal

# Load your cleaned CSV
df = pd.read_csv("sanitas_doctores_clean.csv", dtype=str).fillna("")

def none(v):
    return None if (v is None or v == "" or (isinstance(v, float) and math.isnan(v))) else v

def split_field(val):
    if not isinstance(val, str):
        return []
    return [x.strip() for x in val.split(";") if x.strip()]

session: Session = SessionLocal()

for _, row in df.iterrows():
    profile_url = row.get("profile_url", "")
    name = row.get("name", "")

    # Try to find existing doctor by profile_url first, else by name
    doc = None
    if profile_url:
        doc = session.execute(select(Doctor).where(Doctor.profile_url == profile_url)).scalar_one_or_none()
    if doc is None and name:
        doc = session.execute(select(Doctor).where(Doctor.name == name)).scalar_one_or_none()

    if doc is None:
        doc = Doctor(
            profile_url=none(profile_url),
            name=none(name),
            phones=none(row.get("phones")),
            phones_normalized=none(row.get("phones_normalized")),
            bio_excerpt=none(row.get("bio_excerpt")),
        )
        session.add(doc)
        session.flush()  # get the new ID
    else:
        # Optional: update if blank values in DB
        for attr in ["phones", "phones_normalized", "bio_excerpt"]:
            val = row.get(attr, "")
            if val and (getattr(doc, attr) in (None, "", "nan")):
                setattr(doc, attr, val)

    # Specialties
    existing_specs = {s.specialty for s in doc.specialties}
    for s in split_field(row.get("specialties", "")):
        if s not in existing_specs:
            session.add(DoctorSpecialty(doctor_id=doc.id, specialty=s))

    # Centers
    existing_centers = {c.center for c in doc.centers}
    for c in split_field(row.get("centers", "")):
        if c not in existing_centers:
            session.add(DoctorCenter(doctor_id=doc.id, center=c))

session.commit()
session.close()

print("Data loaded successfully into sanitas_doctors.db")
