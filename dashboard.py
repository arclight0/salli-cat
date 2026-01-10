#!/usr/bin/env python3
from flask import Flask, render_template, jsonify, request, send_file
from pathlib import Path

import database

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/manuals")
def api_manuals():
    brand = request.args.get("brand")
    status = request.args.get("status")
    source = request.args.get("source")

    manuals = database.get_all_manuals(brand=brand, source=source)

    # Filter by status
    if status == "downloaded":
        manuals = [m for m in manuals if m["downloaded"]]
    elif status == "archived":
        manuals = [m for m in manuals if m["archived"] and not m["downloaded"]]
    elif status == "pending":
        manuals = [m for m in manuals if not m["downloaded"] and not m["archived"]]

    return jsonify(manuals)


@app.route("/api/stats")
def api_stats():
    source = request.args.get("source")
    stats = database.get_stats(source=source)
    return jsonify(stats)


@app.route("/api/brands")
def api_brands():
    """Get list of all brands (from both manuals and discovered brands)."""
    source = request.args.get("source")

    # Get brands from manuals table
    manuals = database.get_all_manuals(source=source)
    manual_brands = set(m["brand"] for m in manuals)

    # Get discovered brands from brands table (only for manualslib or no source filter)
    if not source or source == "manualslib":
        discovered = database.get_all_brands()
        discovered_brands = set(b["slug"] for b in discovered)
        all_brands = sorted(manual_brands | discovered_brands)
    else:
        all_brands = sorted(manual_brands)

    return jsonify(all_brands)


@app.route("/api/sources")
def api_sources():
    """Get list of all sources in the database."""
    stats = database.get_stats()
    sources = [s["source"] for s in stats.get("by_source", [])]
    return jsonify(sources)


@app.route("/api/discovered-brands")
def api_discovered_brands():
    """Get all discovered brands with their metadata."""
    brands = database.get_all_brands()
    return jsonify(brands)


@app.route("/api/brand-stats")
def api_brand_stats():
    """Get statistics about discovered brands."""
    stats = database.get_brand_stats()
    return jsonify(stats)


@app.route("/api/clear-brands", methods=["POST"])
def api_clear_brands():
    """Clear all discovered brands from database."""
    database.clear_brands()
    return jsonify({"status": "ok", "message": "Brands cleared"})


@app.route("/api/clear-manuals", methods=["POST"])
def api_clear_manuals():
    """Clear all manuals from database."""
    source = request.args.get("source")
    if source:
        database.clear_manuals_by_source(source)
        return jsonify({"status": "ok", "message": f"{source} manuals cleared"})
    else:
        database.clear_all()
        return jsonify({"status": "ok", "message": "All manuals cleared"})


@app.route("/api/clear-all", methods=["POST"])
def api_clear_all():
    """Clear both manuals and brands from database."""
    database.clear_everything()
    return jsonify({"status": "ok", "message": "Database cleared"})


@app.route("/download/<int:manual_id>")
def download_file(manual_id):
    """Serve the primary file variant with the original filename."""
    manuals = database.get_all_manuals()
    manual = next((m for m in manuals if m["id"] == manual_id), None)

    if not manual or not manual["downloaded"]:
        return "File not found", 404

    # Get primary variant, fallback to legacy file_path
    primary = database.get_primary_variant(manual_id)
    if primary:
        file_path = Path(primary["file_path"])
    elif manual.get("file_path"):
        file_path = Path(manual["file_path"])
    else:
        return "File not found", 404

    if not file_path.exists():
        return "File not found on disk", 404

    # Use the original filename if stored, otherwise generate one from model/doc_type
    original_filename = manual.get("original_filename")
    if not original_filename:
        model = manual.get("model", "manual")
        doc_type = manual.get("doc_type", "")
        if doc_type:
            original_filename = f"{model}_{doc_type}.pdf"
        else:
            original_filename = f"{model}.pdf"
        original_filename = "".join(c if c.isalnum() or c in " ._-" else "_" for c in original_filename)

    return send_file(file_path, as_attachment=True, download_name=original_filename)


@app.route("/download/<int:manual_id>/<variant_type>")
def download_variant(manual_id, variant_type):
    """Serve a specific file variant."""
    manuals = database.get_all_manuals()
    manual = next((m for m in manuals if m["id"] == manual_id), None)

    if not manual or not manual["downloaded"]:
        return "File not found", 404

    variant = database.get_variant_by_type(manual_id, variant_type)
    if not variant:
        return f"Variant '{variant_type}' not found", 404

    file_path = Path(variant["file_path"])
    if not file_path.exists():
        return "File not found on disk", 404

    # Use the original filename, append variant type if not 'original'
    original_filename = manual.get("original_filename", "manual.pdf")
    if variant_type != "original":
        name_parts = original_filename.rsplit(".", 1)
        if len(name_parts) == 2:
            original_filename = f"{name_parts[0]}_{variant_type}.{name_parts[1]}"
        else:
            original_filename = f"{original_filename}_{variant_type}"

    return send_file(file_path, as_attachment=True, download_name=original_filename)


@app.route("/api/variants/<int:manual_id>")
def api_variants(manual_id):
    """Get all file variants for a manual."""
    variants = database.get_file_variants(manual_id)
    return jsonify(variants)


@app.route("/api/variant-stats")
def api_variant_stats():
    """Get statistics about file variants."""
    stats = database.get_variant_stats()
    return jsonify(stats)


if __name__ == "__main__":
    database.init_db()
    app.run(debug=True, port=5000)
