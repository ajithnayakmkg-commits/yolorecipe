"""
firebase_service.py
-------------------
Firebase/Cloud Firestore integration for the recipe generator.

Credentials are never stored in the repository.
Local development:
  - set GOOGLE_APPLICATION_CREDENTIALS to a service-account JSON file, OR
  - set FIREBASE_CREDENTIALS_JSON to the JSON contents.

Render/other hosting:
  - store FIREBASE_CREDENTIALS_JSON as a secret environment variable.
"""
import json
import os
import re
from typing import Optional

import firebase_admin
from firebase_admin import credentials, firestore

_db = None


def init_firebase():
    """Initialise Firebase once and return a Firestore client."""
    global _db
    if _db is not None:
        return _db

    if firebase_admin._apps:
        _db = firestore.client()
        return _db

    raw = os.getenv("FIREBASE_CREDENTIALS_JSON")
    if raw:
        info = json.loads(raw)
        cred = credentials.Certificate(info)
        firebase_admin.initialize_app(cred)
    else:
        # GOOGLE_APPLICATION_CREDENTIALS or Google-hosted ADC.
        firebase_admin.initialize_app()

    _db = firestore.client()
    return _db


def is_configured() -> bool:
    return bool(
        os.getenv("FIREBASE_CREDENTIALS_JSON")
        or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    )


def get_recipes():
    db = init_firebase()
    docs = db.collection("recipes").stream()
    return [doc.to_dict() for doc in docs]


def get_ingredients():
    db = init_firebase()
    docs = db.collection("ingredients").stream()
    return [doc.to_dict() for doc in docs]


def get_metadata():
    db = init_firebase()
    doc = db.collection("config").document("ingredient_metadata").get()
    return doc.to_dict() if doc.exists else {}


def seed_from_json(recipes, ingredient_docs, metadata):
    """
    Upload the complete local dataset to Firestore.

    Firestore batches are limited to 500 writes, so uploads are split into
    chunks. Existing documents with the same IDs are overwritten intentionally.
    """
    db = init_firebase()

    def commit_chunks(items, collection_name):
        for start in range(0, len(items), 450):
            batch = db.batch()
            chunk = items[start:start + 450]
            for item in chunk:
                doc_id = item["id"]
                ref = db.collection(collection_name).document(doc_id)
                batch.set(ref, item)
            batch.commit()

    commit_chunks(recipes, "recipes")
    commit_chunks(ingredient_docs, "ingredients")

    db.collection("config").document("ingredient_metadata").set(metadata)
    return {"recipes": len(recipes), "ingredients": len(ingredient_docs)}


def seed_from_files(data_dir):
    with open(os.path.join(data_dir, "recipes.json"), "r", encoding="utf-8") as f:
        recipes = json.load(f)
    with open(os.path.join(data_dir, "ingredients.json"), "r", encoding="utf-8") as f:
        ingredient_file = json.load(f)

    # Current format keeps the engine-compatible metadata plus an explicit
    # 500-item all_ingredients list.
    if "all_ingredients" in ingredient_file:
        ingredient_docs = ingredient_file["all_ingredients"]
        metadata = {k: v for k, v in ingredient_file.items() if k != "all_ingredients"}
    elif "ingredients" in ingredient_file:
        ingredient_docs = ingredient_file["ingredients"]
        metadata = ingredient_file.get("meta", {})
    else:
        names = set()
        for recipe in recipes:
            for item in recipe.get("core_ingredients", []) + recipe.get("optional_ingredients", []):
                names.add(item["item"])
        ingredient_docs = [
            {"id": re.sub(r"[^a-z0-9]+", "_", n.lower()).strip("_"), "name": n,
             "category": "other", "shelf_life_days": 30}
            for n in sorted(names)
        ]
        metadata = ingredient_file

    return seed_from_json(recipes, ingredient_docs, metadata)


if __name__ == "__main__":
    import pathlib
    seed_from_files(str(pathlib.Path(__file__).resolve().parent / "data"))
    print("Firebase seed completed.")
