from sqlalchemy import Column, Integer, String, Text, ForeignKey
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()

class Doctor(Base):
    __tablename__ = "doctors"

    id = Column(Integer, primary_key=True, index=True)
    profile_url = Column(String, unique=True, nullable=True)
    name = Column(String, index=True)
    phones = Column(String)
    phones_normalized = Column(String)
    bio_excerpt = Column(Text)

    specialties = relationship("DoctorSpecialty", back_populates="doctor", cascade="all, delete-orphan")
    centers = relationship("DoctorCenter", back_populates="doctor", cascade="all, delete-orphan")

class DoctorSpecialty(Base):
    __tablename__ = "doctor_specialties"

    id = Column(Integer, primary_key=True, index=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id", ondelete="CASCADE"))
    specialty = Column(String)

    doctor = relationship("Doctor", back_populates="specialties")

class DoctorCenter(Base):
    __tablename__ = "doctor_centers"

    id = Column(Integer, primary_key=True, index=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id", ondelete="CASCADE"))
    center = Column(String)

    doctor = relationship("Doctor", back_populates="centers")
