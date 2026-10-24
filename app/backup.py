import gzip
import logging
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("backup")

BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", "/data/backups"))


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", "postgresql://agt:agt@db:5432/agt")


def list_backups():
    """Liste aller vorhandenen Backups, neueste zuerst."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(BACKUP_DIR.glob("agt_backup_*.sql.gz"), reverse=True)
    result = []
    for f in files:
        stat = f.stat()
        result.append(
            {
                "filename": f.name,
                "size_kb": round(stat.st_size / 1024, 1),
                "created_at": datetime.fromtimestamp(stat.st_mtime),
            }
        )
    return result


def run_backup(retention: int = 14) -> str:
    """Erstellt einen komprimierten pg_dump und löscht alte Backups über das Limit hinaus."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    sql_path = BACKUP_DIR / f"agt_backup_{timestamp}.sql"
    gz_path = BACKUP_DIR / f"agt_backup_{timestamp}.sql.gz"

    cmd = [
        "pg_dump",
        _database_url(),
        "--clean",
        "--if-exists",
        "-f",
        str(sql_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"pg_dump fehlgeschlagen: {result.stderr}")

    with open(sql_path, "rb") as f_in, gzip.open(gz_path, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)
    sql_path.unlink()

    _cleanup_old_backups(retention)
    logger.info(f"Backup erstellt: {gz_path.name}")
    return gz_path.name


def _cleanup_old_backups(retention: int):
    files = sorted(BACKUP_DIR.glob("agt_backup_*.sql.gz"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old_file in files[retention:]:
        old_file.unlink()
        logger.info(f"Altes Backup gelöscht: {old_file.name}")


def restore_backup(filename: str):
    """Spielt ein Backup zurück (überschreibt alle aktuellen Daten)."""
    gz_path = BACKUP_DIR / filename
    if not gz_path.exists() or not gz_path.name.startswith("agt_backup_"):
        raise FileNotFoundError("Backup nicht gefunden")

    sql_path = gz_path.with_suffix("")  # entfernt .gz
    with gzip.open(gz_path, "rb") as f_in, open(sql_path, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)

    try:
        cmd = ["psql", _database_url(), "-f", str(sql_path)]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            raise RuntimeError(f"Restore fehlgeschlagen: {result.stderr}")
    finally:
        sql_path.unlink(missing_ok=True)


def delete_backup(filename: str):
    gz_path = BACKUP_DIR / filename
    if gz_path.exists() and gz_path.name.startswith("agt_backup_"):
        gz_path.unlink()


def backup_path(filename: str) -> Path:
    gz_path = BACKUP_DIR / filename
    if not gz_path.exists() or not gz_path.name.startswith("agt_backup_"):
        raise FileNotFoundError("Backup nicht gefunden")
    return gz_path
