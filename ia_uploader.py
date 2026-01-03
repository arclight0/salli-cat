#!/usr/bin/env python3
"""Internet Archive uploader for manual PDFs (ManualsLib, ManualsBase, etc.)."""

import logging
import re
from pathlib import Path

import internetarchive as ia

import database

logger = logging.getLogger(__name__)


def sanitize_xml_string(text: str) -> str:
    """
    Remove XML-incompatible characters from a string.

    XML 1.0 only allows: #x9 | #xA | #xD | [#x20-#xD7FF] | [#xE000-#xFFFD]
    """
    if not text:
        return text
    # Remove control characters (0x00-0x1F except tab, newline, carriage return)
    cleaned = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', text)
    return cleaned


def sanitize_identifier(text: str) -> str:
    """
    Create a valid Internet Archive identifier from text.

    IA identifiers must be 5-100 chars, alphanumeric with underscores/dashes.
    """
    # Replace spaces and special chars with underscores
    identifier = re.sub(r'[^a-zA-Z0-9_-]', '_', text)
    # Collapse multiple underscores
    identifier = re.sub(r'_+', '_', identifier)
    # Remove leading/trailing underscores
    identifier = identifier.strip('_')
    # Ensure minimum length
    if len(identifier) < 5:
        identifier = identifier + '_manual'
    # Truncate if too long
    if len(identifier) > 100:
        identifier = identifier[:100]
    return identifier


def build_upload_metadata(manual: dict) -> dict:
    """
    Build metadata dict for an Internet Archive upload.

    Returns dict with: identifier, title, metadata, local_file, remote_filename
    """
    file_path = manual.get("file_path")
    source = manual.get("source", "manualslib")

    # Create identifier based on source
    if source == "manualsbase":
        source_id = manual.get("source_id")
        if source_id:
            identifier = f"manualsbase-id-{source_id}"
        else:
            identifier = sanitize_identifier(f"manualsbase-{manual['brand']}-{manual['model']}")
        subjects = ["manualsbase", "manuals"]
    elif source == "manualzz":
        source_id = manual.get("source_id")
        if source_id:
            identifier = f"manualzz-id-{source_id}"
        else:
            identifier = sanitize_identifier(f"manualzz-{manual['brand']}-{manual['model']}")
        subjects = ["manualzz", "manuals"]
    else:
        # ManualsLib (default)
        manualslib_id = manual.get("manualslib_id") or manual.get("source_id")
        if manualslib_id:
            identifier = f"manualslib-id-{manualslib_id}"
        else:
            identifier = sanitize_identifier(f"manualslib-{manual['brand']}-{manual['model']}")
        subjects = ["manualslib", "manuals"]

    # Build title: "Brand Model Document Type"
    brand = sanitize_xml_string(manual.get("brand", "Unknown"))
    model = sanitize_xml_string(manual.get("model", ""))
    doc_type = sanitize_xml_string(manual.get("doc_type", "Manual"))

    # Clean up model field - remove brand prefix if present
    if model.lower().startswith(brand.lower()):
        model = model[len(brand):].strip()

    # Don't append doc_type if model already contains it
    if doc_type.lower() in model.lower():
        title = f"{brand} {model}".strip()
    else:
        title = f"{brand} {model} {doc_type}".strip()

    # Remote filename: use original_filename, fallback to local filename
    remote_filename = manual.get("original_filename")
    if not remote_filename:
        remote_filename = Path(file_path).name if file_path else "manual.pdf"
    remote_filename = sanitize_xml_string(remote_filename)

    # Build metadata
    metadata = {
        "mediatype": "texts",
        "title": title,
        "subject": subjects,
    }

    # Add description
    if manual.get("doc_description"):
        metadata["description"] = sanitize_xml_string(manual["doc_description"])

    # Add source URL
    if manual.get("manual_url"):
        metadata["source"] = sanitize_xml_string(manual["manual_url"])

    # Add checksums as external identifiers (searchable on IA)
    external_ids = []
    if manual.get("file_md5"):
        external_ids.append(f"urn:md5:{manual['file_md5']}")
    if manual.get("file_sha1"):
        external_ids.append(f"urn:sha1:{manual['file_sha1']}")
    if external_ids:
        metadata["external-identifier"] = external_ids

    return {
        "identifier": identifier,
        "title": title,
        "metadata": metadata,
        "local_file": file_path,
        "remote_filename": remote_filename,
    }


def upload_manual_to_ia(manual: dict) -> str | None:
    """
    Upload a manual to Internet Archive.

    Args:
        manual: Database record dict with file_path, doc_description, brand, model, manualslib_id

    Returns:
        Archive.org URL if successful, None otherwise
    """
    upload_info = build_upload_metadata(manual)

    file_path = upload_info["local_file"]
    if not file_path or not Path(file_path).exists():
        logger.error(f"File not found: {file_path}")
        return None

    identifier = upload_info["identifier"]
    remote_filename = upload_info["remote_filename"]
    metadata = upload_info["metadata"]

    logger.info(f"Uploading to Internet Archive: {identifier}")
    logger.info(f"  Title: {upload_info['title']}")
    logger.info(f"  Local file: {file_path}")
    logger.info(f"  Remote filename: {remote_filename}")

    try:
        # Check if item already exists
        item = ia.get_item(identifier)
        if item.exists:
            logger.info(f"Item already exists: https://archive.org/details/{identifier}")
            return f"https://archive.org/details/{identifier}"

        # Upload with custom remote filename
        # files dict maps remote filename -> local path
        result = ia.upload(
            identifier,
            files={remote_filename: file_path},
            metadata=metadata,
            verbose=True,
        )

        # Check result
        if result and all(r.status_code == 200 for r in result):
            archive_url = f"https://archive.org/details/{identifier}"
            logger.info(f"Upload successful: {archive_url}")
            return archive_url
        else:
            logger.error(f"Upload failed: {result}")
            return None

    except Exception as e:
        logger.error(f"Upload error: {e}")
        return None


def get_uploadable_manuals(source: str = "manualslib", limit: int = None) -> list[dict]:
    """
    Get manuals that are downloaded but not yet uploaded to Internet Archive.

    Args:
        source: Filter by source (default: manualslib)
        limit: Maximum number to return

    Returns:
        List of manual dicts
    """
    conn = database.get_connection()
    cursor = conn.cursor()

    query = """
        SELECT * FROM manuals
        WHERE downloaded = 1
          AND archived = 0
          AND file_path IS NOT NULL
    """
    params = []

    if source:
        query += " AND source = ?"
        params.append(source)

    query += " ORDER BY brand, model"

    if limit:
        query += " LIMIT ?"
        params.append(limit)

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def upload_all_pending(
    source: str = "manualslib",
    limit: int = None,
) -> tuple[int, int]:
    """
    Upload all pending manuals to Internet Archive.

    Args:
        source: Filter by source
        limit: Maximum number to upload

    Returns:
        Tuple of (successful_count, failed_count)
    """
    manuals = get_uploadable_manuals(source=source, limit=limit)
    logger.info(f"Found {len(manuals)} manuals to upload")

    success = 0
    failed = 0

    for manual in manuals:
        archive_url = upload_manual_to_ia(manual)

        if archive_url:
            database.update_archived(manual["id"], archive_url)
            success += 1
        else:
            failed += 1

    logger.info(f"Upload complete. Success: {success}, Failed: {failed}")
    return success, failed


def print_upload_preview(manual: dict):
    """Print a detailed preview of what would be uploaded."""
    upload_info = build_upload_metadata(manual)

    print("=" * 70)
    print(f"Identifier:      {upload_info['identifier']}")
    print(f"Title:           {upload_info['title']}")
    print(f"Local file:      {upload_info['local_file']}")
    print(f"Remote filename: {upload_info['remote_filename']}")
    print(f"URL:             https://archive.org/details/{upload_info['identifier']}")
    print()
    print("Metadata:")
    for key, value in upload_info['metadata'].items():
        if isinstance(value, list):
            print(f"  {key}: {', '.join(value)}")
        else:
            print(f"  {key}: {value}")
    print()


if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s"
    )

    parser = argparse.ArgumentParser(description="Upload manuals to Internet Archive")
    parser.add_argument("--source", default="manualslib", help="Source to upload from")
    parser.add_argument("--limit", type=int, help="Max number to upload")
    parser.add_argument("--dry-run", action="store_true", help="Show detailed preview of what would be uploaded")
    args = parser.parse_args()

    database.init_db()

    if args.dry_run:
        manuals = get_uploadable_manuals(source=args.source, limit=args.limit)
        print(f"Would upload {len(manuals)} manual(s):\n")
        for m in manuals:
            print_upload_preview(m)
    else:
        success, failed = upload_all_pending(
            source=args.source,
            limit=args.limit,
        )
        print(f"Done. Success: {success}, Failed: {failed}")
