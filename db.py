from sqlmodel import SQLModel, create_engine, Session
import os

DB_PATH = os.getenv("DB_PATH", "data/events.db")

engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})

def init_db():
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session
