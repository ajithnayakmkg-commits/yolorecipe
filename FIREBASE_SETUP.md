# Firebase / Firestore setup for this Recipe Generator

## What this version does

The browser does **not** connect directly to Firestore. The flow is:

`Frontend -> Flask API -> Firebase Admin SDK -> Cloud Firestore`

This keeps the service-account private key out of the browser.

The supplied seed dataset contains:
- 100 recipes
- 500 ingredients
- cuisines/styles including Indian regional, Italian, Mexican, Chinese, Japanese, Thai, Korean, Mediterranean, Middle Eastern, Greek, French, Spanish and American dishes.

## 1. Create Firebase project

1. Open the Firebase console.
2. Create a Firebase project.
3. Open **Firestore Database**.
4. Click **Add database**.
5. Choose **Standard edition**.
6. Choose a region close to your users.
7. For this Python server architecture, Production mode is appropriate.

Firebase documents the Firestore creation flow here:
https://firebase.google.com/docs/firestore/manage-databases

## 2. Create a service account

In Firebase:
1. Project settings -> Service accounts.
2. Select Python.
3. Generate a new private key.
4. Download the JSON file.
5. Rename it to `firebase-service-account.json`.
6. Put it somewhere outside the Git repository, or in the project root only if `.gitignore` excludes it.

**Never commit this JSON key to GitHub.**

Firebase's Admin SDK documentation explains service-account authentication:
https://firebase.google.com/docs/admin/setup

## 3. Install Python packages

Open PowerShell in `backend`:

```powershell
cd backend
python -m pip install -r requirements.txt
```

## 4. Configure local credentials

Recommended local method:

```powershell
$env:GOOGLE_APPLICATION_CREDENTIALS="C:\Users\YourName\Downloads\firebase-service-account.json"
```

Or put the variable in `.env`:

```text
GOOGLE_APPLICATION_CREDENTIALS=C:\Users\YourName\Downloads\firebase-service-account.json
```

Do not put the JSON key contents into frontend JavaScript.

## 5. Upload the 100 recipes and 500 ingredients

From the `backend` folder:

```powershell
python seed_firebase.py
```

The script creates/updates these Firestore collections:

```text
recipes/
  R001
  R002
  ...
  R100

ingredients/
  <ingredient-id>
  ...
  500 documents

config/
  ingredient_metadata
```

The seed is repeatable: running it again updates the same document IDs rather than creating duplicate recipe IDs.

## 6. Start the application

```powershell
python app.py
```

Open:

```text
http://127.0.0.1:5000
```

Check the health endpoint:

```text
http://127.0.0.1:5000/api/health
```

A successful Firebase connection should report approximately:

```json
{
  "status": "ok",
  "database": "firebase",
  "recipes_loaded": 100,
  "ingredients_loaded": 500
}
```

## 7. Test the database endpoint

Open:

```text
http://127.0.0.1:5000/api/firebase/recipes
```

You should receive the recipe documents from Firestore.

The old `/api/supabase/recipes` route is retained as a compatibility alias so older frontend builds do not suddenly fail.

## 8. Test recipe matching

PowerShell:

```powershell
$body = @{
  ingredients = @("tomato", "onion", "egg")
  servings = 2
  diet = "any"
} | ConvertTo-Json

Invoke-RestMethod `
  -Uri "http://127.0.0.1:5000/api/recipes" `
  -Method Post `
  -ContentType "application/json" `
  -Body $body
```

The important point is that `/api/recipes` now matches against the recipes loaded from Firestore.

## 9. Render deployment

In Render, create/update the Python web service.

Build command:

```text
pip install -r backend/requirements.txt
```

Start command:

```text
gunicorn --chdir backend app:app
```

Add the secret environment variable:

```text
FIREBASE_CREDENTIALS_JSON
```

Its value must be the **complete contents** of the Firebase service-account JSON.

Do not commit the service-account JSON file.

Because the backend serves the frontend, keep:

```text
API_BASE: ""
```

in `frontend/js/config.js` when both are deployed by the same Flask service.

## 10. Why this architecture avoids frontend/backend connection problems

1. The frontend only calls Flask endpoints.
2. The Firebase Admin SDK is used only on the server.
3. The private service-account key never reaches the browser.
4. Recipe matching remains in the existing Python engine.
5. Firestore data is loaded once when Flask starts instead of making a database query for every recipe calculation.
6. If Firebase is temporarily unavailable, the application falls back to the local JSON dataset instead of crashing.
7. The API response shapes remain compatible with the existing frontend.
