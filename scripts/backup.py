"""Make a backup now. Schedule this daily with Windows Task Scheduler or cron:
    python -m scripts.backup            (keeps the last BACKUP_KEEP automatic backups)"""
from app.backup import create_backup

if __name__ == "__main__":
    print("Backup saved:", create_backup("auto"))
