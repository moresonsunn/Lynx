"""
Database Migration for High-Impact Features
Run this script to add new tables for analytics, multi-server, mods, backups, and player features
"""

from sqlalchemy import create_engine, inspect
from database import Base, engine, SessionLocal
from models import (
    # Existing models
    User, ScheduledTask, BackupTask, IntegrityReport, ServerPerformance, 
    PlayerAction, UserAPIKey, UserTwoFactor, AuditLog, UserSession,
    Permission, Role,
    # New High-Impact Feature models
    ServerMetrics, PerformanceAlert, CrashReport,
    ServerGroup, ServerGroupMember, BulkOperation, ServerClone,
    ModVersion, ModConflict, ClientModpack,
    BackupConfig, BackupHistory,
    PlayerProfile, TemporaryBan, PlayerSession
)


def check_table_exists(table_name: str) -> bool:
    """Check if a table exists in the database"""
    inspector = inspect(engine)
    return table_name in inspector.get_table_names()


def migrate_database():
    """Create new tables for high-impact features"""
    
    print("🚀 Starting database migration for High-Impact Features...")
    
    # List of new tables to create
    new_tables = [
        ('server_metrics', 'Server Performance Monitoring'),
        ('performance_alerts', 'Performance Alerts'),
        ('crash_reports', 'Crash Reports'),
        ('server_groups', 'Server Groups'),
        ('server_group_members', 'Server Group Members'),
        ('bulk_operations', 'Bulk Operations'),
        ('server_clones', 'Server Clones'),
        ('mod_versions', 'Mod Versions'),
        ('mod_conflicts', 'Mod Conflicts'),
        ('client_modpacks', 'Client Modpacks'),
        ('backup_configs', 'Backup Configurations'),
        ('backup_history', 'Backup History'),
        ('player_profiles', 'Player Profiles'),
        ('temporary_bans', 'Temporary Bans'),
        ('player_sessions', 'Player Sessions'),
    ]
    
    # Check which tables already exist
    existing_tables = []
    new_tables_to_create = []
    
    for table_name, description in new_tables:
        if check_table_exists(table_name):
            existing_tables.append(f"  ✓ {description} ({table_name})")
        else:
            new_tables_to_create.append(f"  + {description} ({table_name})")
    
    if existing_tables:
        print("\n📦 Existing tables:")
        for table in existing_tables:
            print(table)
    
    if new_tables_to_create:
        print("\n✨ Creating new tables:")
        for table in new_tables_to_create:
            print(table)
        
        # Create all tables
        Base.metadata.create_all(bind=engine)
        print("\n✅ All new tables created successfully!")
    else:
        print("\n✅ All tables already exist. No migration needed.")
    
    # Verify all tables were created
    print("\n🔍 Verifying database schema...")
    all_exist = True
    for table_name, description in new_tables:
        if not check_table_exists(table_name):
            print(f"  ❌ Failed to create: {description} ({table_name})")
            all_exist = False
    
    if all_exist:
        print("  ✓ All tables verified!")
    
    print("\n" + "="*60)
    print("📊 Database Migration Summary:")
    print("="*60)
    print(f"Total tables: {len(new_tables)}")
    print(f"Already existed: {len(existing_tables)}")
    print(f"Newly created: {len(new_tables_to_create)}")
    print("="*60)
    
    if not all_exist:
        print("\n⚠️  WARNING: Some tables failed to create. Check error messages above.")
        return False
    
    print("\n🎉 Migration completed successfully!")
    print("\nNew features available:")
    print("  • Server Performance Monitoring & Analytics")
    print("  • Multi-Server Management")
    print("  • Enhanced Modpack Features")
    print("  • Advanced Backup System")
    print("  • Player Experience Enhancements")
    
    return True


if __name__ == "__main__":
    try:
        success = migrate_database()
        exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ Migration failed with error: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
