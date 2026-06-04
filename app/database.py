import os
from datetime import datetime
from sqlalchemy import create_engine, Column, String, Integer, Float, Boolean, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./store_intelligence.db")

# SQLite specific arguments to enable WAL mode and prevent threading locks
connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False, "timeout": 30}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ORM Model for Store Events
class EventModel(Base):
    __tablename__ = "events"

    event_id = Column(String, primary_key=True, index=True)
    store_id = Column(String, index=True, nullable=False)
    camera_id = Column(String, index=True, nullable=False)
    visitor_id = Column(String, index=True, nullable=False)
    event_type = Column(String, index=True, nullable=False)
    timestamp = Column(DateTime, index=True, nullable=False)
    zone_id = Column(String, nullable=True)
    dwell_ms = Column(Integer, default=0)
    is_staff = Column(Boolean, default=False)
    confidence = Column(Float, default=1.0)
    
    # Metadata fields (flattened for SQL efficiency)
    queue_depth = Column(Integer, nullable=True)
    sku_zone = Column(String, nullable=True)
    session_seq = Column(Integer, default=0)

# ORM Model for POS Transactions
class PosTransactionModel(Base):
    __tablename__ = "pos_transactions"

    order_id = Column(String, primary_key=True, index=True)
    order_timestamp = Column(DateTime, index=True, nullable=False)
    store_id = Column(String, index=True, nullable=False)
    product_id = Column(String, nullable=False)
    brand_name = Column(String, nullable=True)
    total_amount = Column(Float, nullable=False)

def init_db():
    Base.metadata.create_all(bind=engine)
    
    # Enable WAL mode for SQLite to support concurrent reads/writes
    if DATABASE_URL.startswith("sqlite"):
        with engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA journal_mode=WAL;")
            conn.exec_driver_sql("PRAGMA synchronous=NORMAL;")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
