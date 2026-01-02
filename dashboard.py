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

    manuals = database.get_all_manuals(brand=brand)

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
    stats = database.get_stats()
    return jsonify(stats)


@app.route("/api/brands")
def api_brands():
    """Get list of all brands (from both manuals and discovered brands)."""
    # Get brands from manuals table
    manuals = database.get_all_manuals()
    manual_brands = set(m["brand"] for m in manuals)

    # Get discovered brands from brands table
    discovered = database.get_all_brands()
    discovered_brands = set(b["slug"] for b in discovered)

    # Combine and sort
    all_brands = sorted(manual_brands | discovered_brands)
    return jsonify(all_brands)


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
    database.clear_all()
    return jsonify({"status": "ok", "message": "Manuals cleared"})


@app.route("/api/clear-all", methods=["POST"])
def api_clear_all():
    """Clear both manuals and brands from database."""
    database.clear_everything()
    return jsonify({"status": "ok", "message": "Database cleared"})


@app.route("/download/<int:manual_id>")
def download_file(manual_id):
    """Serve a downloaded PDF file."""
    manuals = database.get_all_manuals()
    manual = next((m for m in manuals if m["id"] == manual_id), None)

    if not manual or not manual["downloaded"] or not manual["file_path"]:
        return "File not found", 404

    file_path = Path(manual["file_path"])
    if not file_path.exists():
        return "File not found on disk", 404

    return send_file(file_path, as_attachment=True)


if __name__ == "__main__":
    database.init_db()
    app.run(debug=True, port=5000)
