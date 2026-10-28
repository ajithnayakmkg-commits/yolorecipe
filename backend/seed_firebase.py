from pathlib import Path
from firebase_service import seed_from_files

if __name__ == "__main__":
    result = seed_from_files(str(Path(__file__).resolve().parent / "data"))
    print(f"Uploaded {result['recipes']} recipes and {result['ingredients']} ingredients to Firestore.")
