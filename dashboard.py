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
    """Get list of all brands in the database."""
    manuals = database.get_all_manuals()
    brands = sorted(set(m["brand"] for m in manuals))
    return jsonify(brands)


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
