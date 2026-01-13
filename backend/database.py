from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, Text, ForeignKey, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
from datetime import datetime
import os
import secrets



DATABASE_URL = os.getenv("DATABASE_URL") or "sqlite:///./minecraft_controller.db"




if os.getenv("USE_POSTGRES", "false").lower() == "true" and not os.getenv("DATABASE_URL"):
    DATABASE_URL = "postgresql://postgres:postgres123@db:5432/minecraft_controller"


connect_args = {}
engine_kwargs = {
    
    "pool_size": 20,  
    "max_overflow": 40,  
    "pool_timeout": 60,  
    "pool_recycle": 3600,  
    "pool_pre_ping": True,  
    "echo": False  
}

if "sqlite" in DATABASE_URL:
    connect_args = {"check_same_thread": False}
    
    engine_kwargs.update({
        "pool_size": 10,  
        "max_overflow": 20,
        "poolclass": None  
    })
elif "postgresql" in DATABASE_URL:
    
    engine_kwargs.update({
        "pool_size": 25,  
        "max_overflow": 50
    })

engine = create_engine(DATABASE_URL, connect_args=connect_args, **engine_kwargs)


SessionLocal = sessionmaker(
    autocommit=False, 
    autoflush=False, 
    bind=engine,
    
    expire_on_commit=False  
)


Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
        
        db.commit()
    except Exception as e:
        
        db.rollback()
        raise e
    finally:
        
        db.close()


class DatabaseSession:
    def __init__(self):
        self.db = None
    
    def __enter__(self):
        self.db = SessionLocal()
        return self.db
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.db.rollback()
        else:
            self.db.commit()
        self.db.close()


def get_db_session():
    """Get a database session for manual management.
    Remember to call session.close() when done!
    """
    return SessionLocal()


def get_connection_pool_status():
    """Get database connection pool status for monitoring."""
    try:
        pool = engine.pool
        return {
            "pool_size": pool.size(),
            "checked_in": pool.checkedin(),
            "checked_out": pool.checkedout(),
            "overflow": pool.overflow(),
            "total_connections": pool.size() + pool.overflow()
        }
    except Exception as e:
        return {"error": str(e)}

def health_check_db():
    """Quick database health check."""
    try:
        with DatabaseSession() as db:
            
            db.execute(text("SELECT 1"))
            return True
    except Exception as e:
        print(f"Database health check failed: {e}")
        return False


def cleanup_expired_sessions():
    """Clean up expired database sessions and connections."""
    try:
        
        engine.dispose()
        print("Database connection pool cleaned up")
    except Exception as e:
        print(f"Error during connection cleanup: {e}")


def init_db():
    """Initialize the database and create tables."""
    
    
    import models  
    
    
    Base.metadata.create_all(bind=engine)
    print("Database tables created successfully")

    
    try:
        from sqlalchemy import text as _text
        with engine.begin() as conn:
            
            try:
                conn.execute(_text("DROP TABLE IF EXISTS server_templates"))
                print("Dropped legacy table: server_templates (if existed)")
            except Exception as _e:
                print(f"Warning: could not drop legacy server_templates table: {_e}")
            conn.execute(_text("CREATE INDEX IF NOT EXISTS idx_audit_logs_timestamp ON audit_logs (timestamp)"))
            conn.execute(_text("CREATE INDEX IF NOT EXISTS idx_audit_logs_user_id ON audit_logs (user_id)"))
            conn.execute(_text("CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON audit_logs (action)"))
        print("Database indexes ensured for audit_logs")
    except Exception as e:
        print(f"Warning: could not create indexes (non-fatal): {e}")
    
    
    db = SessionLocal()
    try:
        
        from user_service import UserService
        user_service = UserService(db)
        
        
        user_service.initialize_default_permissions_and_roles()
        
        
        admin_user = user_service.get_user_by_username("admin")
        if not admin_user:
            initial_password = "admin123"
            admin_user = user_service.create_user(
                username="admin",
                email="admin@localhost",
                password=initial_password,
                role="admin",
                full_name="Administrator"
            )
            print(f"Default admin user created: username=admin, password={initial_password}")
        else:
            print("Default admin user already exists")
    except Exception as e:
        print(f"Error initializing database: {e}")
        db.rollback()
    finally:
        db.close()
