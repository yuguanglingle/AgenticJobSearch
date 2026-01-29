"""Shared database utilities for all agents."""
import os
from pathlib import Path
from typing import Any, Optional
from sqlmodel import create_engine, Session, select, SQLModel


def get_engine(db_path: Optional[str] = None) -> Any:
    """Get or create database engine.
    
    Args:
        db_path: Path to database file. If not provided, uses DB_PATH env var
                or defaults to data/app.db in the agents directory.
                
    Returns:
        SQLAlchemy engine instance.
    """
    if not db_path:
        db_path = os.getenv("DB_PATH")
    
    if not db_path:
        base_dir = Path(__file__).resolve().parent.parent
        db_path = str(base_dir / "data" / "app.db")
    
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    return create_engine(f"sqlite:///{db_path}")


def init_db(db_path: Optional[str] = None) -> Any:
    """Initialize database tables.
    
    Args:
        db_path: Path to database file.
        
    Returns:
        SQLAlchemy engine instance.
    """
    engine = get_engine(db_path)
    SQLModel.metadata.create_all(engine)
    return engine


def get_session(db_path: Optional[str] = None) -> Session:
    """Create a new database session.
    
    Args:
        db_path: Path to database file.
        
    Returns:
        SQLModel Session instance.
    """
    engine = get_engine(db_path)
    return Session(engine)
