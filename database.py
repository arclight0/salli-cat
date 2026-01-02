import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "manuals.db"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    # Brands table - discovered brands with TV category
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS brands (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            slug TEXT UNIQUE NOT NULL,
            brand_url TEXT,
            tv_categories TEXT,
            tv_category_urls TEXT,
            all_categories TEXT,
            scraped INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Migration for brands table
    for col, coltype in [
        ("tv_categories", "TEXT"),
        ("tv_category_urls", "TEXT"),
        ("all_categories", "TEXT"),
    ]:
        try:
            cursor.execute(f"ALTER TABLE brands ADD COLUMN {col} {coltype}")
        except sqlite3.OperationalError:
            pass

    # Manuals table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS manuals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            brand TEXT NOT NULL,
            model TEXT NOT NULL,
            model_url TEXT,
            model_id TEXT,
            doc_type TEXT,
            doc_description TEXT,
            manual_url TEXT UNIQUE NOT NULL,
            manualslib_id TEXT,
            downloaded INTEGER DEFAULT 0,
            archived INTEGER DEFAULT 0,
            file_path TEXT,
            archive_url TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Migration: add columns if they don't exist (for existing databases)
    for col, coltype in [
        ("manualslib_id", "TEXT"),
        ("archived", "INTEGER DEFAULT 0"),
        ("archive_url", "TEXT"),
        ("model_url", "TEXT"),
        ("model_id", "TEXT"),
        ("doc_description", "TEXT"),
        ("source", "TEXT DEFAULT 'manualslib'"),
        ("source_id", "TEXT"),
        ("category", "TEXT"),
        ("file_sha1", "TEXT"),
        ("file_md5", "TEXT"),
        ("file_size", "INTEGER"),
        ("scraped_at", "TEXT"),
        ("downloaded_at", "TEXT"),
        ("archive_checked_at", "TEXT"),
        ("original_filename", "TEXT"),
    ]:
        try:
            cursor.execute(f"ALTER TABLE manuals ADD COLUMN {col} {coltype}")
        except sqlite3.OperationalError:
            pass  # Column already exists

    # Create indexes (after migrations so columns exist)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_brand ON manuals(brand)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_downloaded ON manuals(downloaded)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_archived ON manuals(archived)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_source ON manuals(source)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_brands_slug ON brands(slug)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_brands_scraped ON brands(scraped)")

    conn.commit()
    conn.close()


def add_manual(
    brand: str,
    model: str,
    manual_url: str,
    manualslib_id: str = None,
    model_url: str = None,
    model_id: str = None,
    doc_type: str = None,
    doc_description: str = None,
    source: str = "manualslib",
    source_id: str = None,
    category: str = None,
) -> int | None:
    conn = get_connection()
    cursor = conn.cursor()
    scraped_at = datetime.now().isoformat()
    try:
        cursor.execute("""
            INSERT INTO manuals (brand, model, model_url, model_id, doc_type, doc_description, manual_url, manualslib_id, source, source_id, category, scraped_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (brand, model, model_url, model_id, doc_type, doc_description, manual_url, manualslib_id, source, source_id, category, scraped_at))
        conn.commit()
        return cursor.lastrowid
    except sqlite3.IntegrityError:
        # Already exists
        return None
    finally:
        conn.close()


def get_manual_by_url(manual_url: str) -> dict | None:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM manuals WHERE manual_url = ?", (manual_url,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


# Brand management functions

def add_brand(
    name: str,
    slug: str,
    brand_url: str = None,
    tv_categories: str = None,
    tv_category_urls: str = None,
    all_categories: str = None,
) -> int | None:
    """Add a discovered brand to the database. Returns id if new, None if exists."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO brands (name, slug, brand_url, tv_categories, tv_category_urls, all_categories)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (name, slug, brand_url, tv_categories, tv_category_urls, all_categories))
        conn.commit()
        return cursor.lastrowid
    except sqlite3.IntegrityError:
        # Already exists
        return None
    finally:
        conn.close()


def get_all_brands(scraped: bool = None) -> list[dict]:
    """Get all discovered brands, optionally filtered by scraped status."""
    conn = get_connection()
    cursor = conn.cursor()

    query = "SELECT * FROM brands WHERE 1=1"
    params = []

    if scraped is not None:
        query += " AND scraped = ?"
        params.append(1 if scraped else 0)

    query += " ORDER BY name"

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_unscraped_brands() -> list[dict]:
    """Get brands that haven't been scraped yet."""
    return get_all_brands(scraped=False)


def mark_brand_scraped(brand_id: int):
    """Mark a brand as scraped."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE brands SET scraped = 1 WHERE id = ?", (brand_id,))
    conn.commit()
    conn.close()


def get_brand_by_slug(slug: str) -> dict | None:
    """Get a brand by its slug."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM brands WHERE slug = ?", (slug,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_brand_stats() -> dict:
    """Get statistics about discovered brands."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) as total FROM brands")
    total = cursor.fetchone()["total"]

    cursor.execute("SELECT COUNT(*) as scraped FROM brands WHERE scraped = 1")
    scraped = cursor.fetchone()["scraped"]

    conn.close()

    return {
        "total": total,
        "scraped": scraped,
        "pending": total - scraped
    }


def update_downloaded(manual_id: int, file_path: str, file_sha1: str = None, file_md5: str = None, file_size: int = None, original_filename: str = None):
    conn = get_connection()
    cursor = conn.cursor()
    downloaded_at = datetime.now().isoformat()
    cursor.execute("""
        UPDATE manuals
        SET downloaded = 1, file_path = ?, file_sha1 = ?, file_md5 = ?, file_size = ?, downloaded_at = ?, original_filename = ?
        WHERE id = ?
    """, (file_path, file_sha1, file_md5, file_size, downloaded_at, original_filename, manual_id))
    conn.commit()
    conn.close()


def update_archived(manual_id: int, archive_url: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE manuals
        SET archived = 1, archive_url = ?
        WHERE id = ?
    """, (archive_url, manual_id))
    conn.commit()
    conn.close()


def update_manualslib_id(manual_id: int, manualslib_id: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE manuals
        SET manualslib_id = ?
        WHERE id = ?
    """, (manualslib_id, manual_id))
    conn.commit()
    conn.close()


def get_manuals_needing_archive_check(limit: int = 100) -> list[dict]:
    """Get manuals that have a manualslib_id but haven't been checked on archive.org recently.

    Returns manuals where:
    - manualslib_id is set (so we can check archive.org)
    - archived = 0 (not already marked as archived)
    - downloaded = 0 (not already downloaded locally)
    - archive_checked_at is NULL or older than 7 days
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM manuals
        WHERE manualslib_id IS NOT NULL
          AND archived = 0
          AND downloaded = 0
          AND (archive_checked_at IS NULL
               OR datetime(archive_checked_at) < datetime('now', '-7 days'))
        ORDER BY archive_checked_at ASC NULLS FIRST
        LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def update_archive_checked(manual_id: int, is_archived: bool, archive_url: str = None):
    """Update the archive check status for a manual."""
    conn = get_connection()
    cursor = conn.cursor()
    checked_at = datetime.now().isoformat()
    if is_archived and archive_url:
        cursor.execute("""
            UPDATE manuals
            SET archived = 1, archive_url = ?, archive_checked_at = ?
            WHERE id = ?
        """, (archive_url, checked_at, manual_id))
    else:
        cursor.execute("""
            UPDATE manuals
            SET archive_checked_at = ?
            WHERE id = ?
        """, (checked_at, manual_id))
    conn.commit()
    conn.close()


def get_archive_check_stats() -> dict:
    """Get statistics about archive checking progress."""
    conn = get_connection()
    cursor = conn.cursor()

    # Total with manualslib_id (checkable)
    cursor.execute("SELECT COUNT(*) FROM manuals WHERE manualslib_id IS NOT NULL")
    total_checkable = cursor.fetchone()[0]

    # Already archived
    cursor.execute("SELECT COUNT(*) FROM manuals WHERE archived = 1")
    archived = cursor.fetchone()[0]

    # Checked but not archived
    cursor.execute("""
        SELECT COUNT(*) FROM manuals
        WHERE archive_checked_at IS NOT NULL AND archived = 0
    """)
    checked_not_archived = cursor.fetchone()[0]

    # Never checked
    cursor.execute("""
        SELECT COUNT(*) FROM manuals
        WHERE manualslib_id IS NOT NULL AND archive_checked_at IS NULL AND archived = 0
    """)
    never_checked = cursor.fetchone()[0]

    conn.close()

    return {
        "total_checkable": total_checkable,
        "archived": archived,
        "checked_not_archived": checked_not_archived,
        "never_checked": never_checked,
    }


def get_all_manuals(brand: str = None, downloaded: bool = None, source: str = None) -> list[dict]:
    conn = get_connection()
    cursor = conn.cursor()

    query = "SELECT * FROM manuals WHERE 1=1"
    params = []

    if brand:
        query += " AND brand = ?"
        params.append(brand)

    if downloaded is not None:
        query += " AND downloaded = ?"
        params.append(1 if downloaded else 0)

    if source:
        query += " AND source = ?"
        params.append(source)

    query += " ORDER BY brand, model"

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_undownloaded_manuals(brand: str = None, include_archived: bool = False, source: str = None) -> list[dict]:
    """Get manuals that haven't been downloaded. By default excludes archived manuals."""
    conn = get_connection()
    cursor = conn.cursor()

    query = "SELECT * FROM manuals WHERE downloaded = 0"
    params = []

    if not include_archived:
        query += " AND archived = 0"

    if brand:
        query += " AND brand = ?"
        params.append(brand)

    if source:
        query += " AND source = ?"
        params.append(source)

    query += " ORDER BY brand, model"

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_stats(source: str = None) -> dict:
    conn = get_connection()
    cursor = conn.cursor()

    source_filter = ""
    params = []
    if source:
        source_filter = " WHERE source = ?"
        params = [source]

    cursor.execute(f"SELECT COUNT(*) as total FROM manuals{source_filter}", params)
    total = cursor.fetchone()["total"]

    cursor.execute(f"SELECT COUNT(*) as downloaded FROM manuals WHERE downloaded = 1{' AND source = ?' if source else ''}", params)
    downloaded = cursor.fetchone()["downloaded"]

    cursor.execute(f"SELECT COUNT(*) as archived FROM manuals WHERE archived = 1{' AND source = ?' if source else ''}", params)
    archived = cursor.fetchone()["archived"]

    by_brand_query = """
        SELECT brand,
               COUNT(*) as total,
               SUM(CASE WHEN downloaded = 1 THEN 1 ELSE 0 END) as downloaded,
               SUM(CASE WHEN archived = 1 THEN 1 ELSE 0 END) as archived
        FROM manuals
    """
    if source:
        by_brand_query += " WHERE source = ?"
    by_brand_query += " GROUP BY brand ORDER BY brand"

    cursor.execute(by_brand_query, params)
    by_brand = [dict(row) for row in cursor.fetchall()]

    # Also get stats by source
    cursor.execute("""
        SELECT COALESCE(source, 'manualslib') as source,
               COUNT(*) as total,
               SUM(CASE WHEN downloaded = 1 THEN 1 ELSE 0 END) as downloaded,
               SUM(CASE WHEN archived = 1 THEN 1 ELSE 0 END) as archived
        FROM manuals
        GROUP BY source
        ORDER BY source
    """)
    by_source = [dict(row) for row in cursor.fetchall()]

    conn.close()

    return {
        "total": total,
        "downloaded": downloaded,
        "archived": archived,
        "pending": total - downloaded - archived,
        "by_brand": by_brand,
        "by_source": by_source,
    }


def clear_all():
    """Delete all records from the manuals table."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM manuals")
    conn.commit()
    conn.close()


def clear_manuals_by_source(source: str):
    """Delete all manuals from a specific source."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM manuals WHERE source = ?", (source,))
    conn.commit()
    conn.close()


def clear_brands():
    """Delete all records from the brands table."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM brands")
    conn.commit()
    conn.close()


def clear_everything():
    """Delete all records from both manuals and brands tables."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM manuals")
    cursor.execute("DELETE FROM brands")
    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print(f"Database initialized at {DB_PATH}")
