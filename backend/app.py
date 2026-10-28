"""
app.py
------
Flask API for the Intelligent Web-Based Recipe Generator.

The frontend talks only to this Flask API. Flask talks to Cloud Firestore
through firebase_service.py. A local JSON fallback is retained so a missing
Firebase credential never prevents the application from starting.
"""
import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory

try:
    from flask_cors import CORS
except ImportError:
    CORS = None

import detector
import recipe_engine
from diet_planner import build_plan, daily_energy_needs
from recipe_engine import expiry_report, get_recipe, match_recipes
from firebase_service import get_ingredients, get_metadata, get_recipes, is_configured

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"
DATA_DIR = Path(__file__).resolve().parent / "data"
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
MAX_UPLOAD_MB = 8

load_dotenv(ENV_FILE)

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024

if CORS:
    CORS(app)

DATABASE_MODE = "local"


def load_dataset():
    """
    Prefer Firestore when configured and populated; otherwise keep the local
    JSON dataset. This makes first-run and temporary Firebase outages safe.
    """
    global DATABASE_MODE

    if not is_configured():
        DATABASE_MODE = "local"
        return

    try:
        db_recipes = get_recipes()
        db_ingredients = get_ingredients()
        metadata = get_metadata()

        if not db_recipes:
            DATABASE_MODE = "local-empty"
            return

        # Replace the engine's in-memory dataset with Firestore data.
        recipe_engine.RECIPES = db_recipes

        if metadata:
            recipe_engine.INGREDIENT_DATA = metadata
            recipe_engine.SYNONYMS = metadata.get("synonyms", {})
            recipe_engine.SUBSTITUTIONS = metadata.get("substitutions", {})
            recipe_engine.STAPLES = set(metadata.get("staples", []))
            recipe_engine.SHELF_LIFE = metadata.get("shelf_life_days", {})
            recipe_engine.CATEGORIES = metadata.get("categories", {})

        recipe_engine.DATABASE_INGREDIENT_NAMES = sorted(
            {str(x.get("name", "")).strip().lower()
             for x in db_ingredients if x.get("name")}
        )
        DATABASE_MODE = "firebase"
        print(
            f"[firebase] loaded {len(db_recipes)} recipes and "
            f"{len(db_ingredients)} ingredients from Firestore"
        )
    except Exception as exc:
        DATABASE_MODE = "local-error"
        print(f"[firebase] unavailable, using local JSON fallback: {exc}")


load_dataset()


# ---------------------------------------------------------------- frontend ---
@app.route("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory(FRONTEND_DIR, filename)


# --------------------------------------------------------------------- API ---
@app.route("/api/health")
def health():
    return jsonify({
        "status": "ok",
        "database": DATABASE_MODE,
        "server_detector": "yolo" if detector.is_available() else "browser-fallback",
        "recipes_loaded": len(recipe_engine.RECIPES),
        "ingredients_loaded": len(recipe_engine.all_ingredient_names()),
    })


@app.route("/api/ingredients")
def ingredients():
    # Firestore has the complete 500-item list; local mode uses the recipe engine.
    if DATABASE_MODE == "firebase":
        try:
            docs = get_ingredients()
            names = sorted({x["name"] for x in docs if x.get("name")})
            return jsonify({"ingredients": names})
        except Exception as exc:
            print(f"[firebase] ingredient read failed: {exc}")
    return jsonify({"ingredients": recipe_engine.all_ingredient_names()})


@app.route("/api/detect", methods=["POST"])
def detect_route():
    if "image" not in request.files:
        return jsonify({"error": "Attach the photo as a form field named 'image'."}), 400

    file = request.files["image"]
    if not file.filename:
        return jsonify({"error": "No file was selected."}), 400

    try:
        confidence = float(request.form.get("confidence", 0.35))
    except ValueError:
        confidence = 0.35

    result = detector.detect(file.read(), confidence=confidence)
    return jsonify(result)


@app.route("/api/recipes", methods=["POST"])
def recipes_route():
    body = request.get_json(silent=True) or {}
    ingredients_in = body.get("ingredients", [])
    if not ingredients_in:
        return jsonify({"error": "Send at least one ingredient."}), 400

    matches = match_recipes(
        available_ingredients=ingredients_in,
        servings=body.get("servings", 2),
        diet=body.get("diet", "any"),
        meal_type=body.get("meal_type"),
        max_time=body.get("max_time"),
        exclude=body.get("exclude", []),
        limit=body.get("limit", 10),
    )
    return jsonify({"count": len(matches), "recipes": matches})


@app.route("/api/recipe/<recipe_id>")
def recipe_route(recipe_id):
    servings = request.args.get("servings", 2, type=int)
    recipe = get_recipe(recipe_id, servings=servings)
    if not recipe:
        return jsonify({"error": f"No recipe with id {recipe_id}."}), 404
    return jsonify(recipe)


@app.route("/api/diet-plan", methods=["POST"])
def diet_plan_route():
    body = request.get_json(silent=True) or {}
    plan = build_plan(
        available_ingredients=body.get("ingredients", []),
        days=body.get("days", 3),
        people=body.get("people", 1),
        diet=body.get("diet", "any"),
        exclude=body.get("exclude", []),
        target_calories=body.get("target_calories"),
        profile=body.get("profile"),
    )
    return jsonify(plan)


@app.route("/api/energy-needs", methods=["POST"])
def energy_route():
    body = request.get_json(silent=True) or {}
    return jsonify(daily_energy_needs(
        age=body.get("age", 22),
        sex=body.get("sex", "male"),
        weight_kg=body.get("weight_kg", 65),
        height_cm=body.get("height_cm", 170),
        activity=body.get("activity", "moderate"),
        goal=body.get("goal", "maintain"),
    ))


@app.route("/api/pantry/expiry", methods=["POST"])
def expiry_route():
    body = request.get_json(silent=True) or {}
    return jsonify({"items": expiry_report(body.get("pantry", []))})


@app.route("/api/firebase/recipes")
def firebase_recipes():
    """Diagnostic endpoint: return recipes currently stored in Firestore."""
    try:
        return jsonify(get_recipes())
    except Exception as exc:
        return jsonify({"error": "Could not load Firebase recipes", "details": str(exc)}), 503


# Keep the old route name temporarily so older frontend builds do not break.
@app.route("/api/supabase/recipes")
def legacy_database_recipes():
    return firebase_recipes()


@app.errorhandler(413)
def too_large(_):
    return jsonify({"error": f"That photo is over {MAX_UPLOAD_MB} MB. Try a smaller one."}), 413


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"Recipe Generator running on http://127.0.0.1:{port}")
    app.run(host="0.0.0.0", port=port, debug=True)
