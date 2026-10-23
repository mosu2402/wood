"""Restore a backup. STOP THE SERVER FIRST.
Usage:  python -m scripts.restore backups/luxe_20260101_210000_auto.db
A safety copy of the current database is taken before restoring."""
import sys
from pathlib import Path

from app.backup import restore_backup


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    path = Path(sys.argv[1]).resolve()
    answer = input(f"Restore {path.name}? Current data will be replaced (a safety copy is kept). Type YES: ")
    if answer.strip() != "YES":
        print("Cancelled.")
        return
    safety = restore_backup(path)
    print("Restored. Safety copy of the previous data:", safety)


if __name__ == "__main__":
    main()
