# Deploy notes (Cloud Run + Atlas + Secret Manager)

## 0. Prereqs
- GCP project with billing (use the $100 hackathon credits: forms.gle/xfv9vQzfRfNCCVbG7)
- MongoDB Atlas cluster (free M0 is fine for the MVP)
- `gcloud` CLI authenticated; Node 18+ and Python 3.12 locally

## 1. Enable APIs
```bash
gcloud services enable run.googleapis.com aiplatform.googleapis.com \
  secretmanager.googleapis.com places-backend.googleapis.com
```

## 2. Secrets (never commit keys)
```bash
printf '%s' "$MONGODB_URI"       | gcloud secrets create MONGODB_URI --data-file=-
printf '%s' "$GOOGLE_MAPS_API_KEY"| gcloud secrets create GOOGLE_MAPS_API_KEY --data-file=-
```

## 3. Atlas: create the vector index
On the `businesses` collection, create a Vector Search index named `businesses_vector`:
```json
{
  "fields": [
    { "type": "vector", "path": "embedding", "numDimensions": 1536, "similarity": "cosine" },
    { "type": "filter", "path": "neighborhood_id" }
  ]
}
```
(If you use Gemini `text-embedding-004`, set numDimensions to that model's size, e.g. 768,
and keep `embed_text(dim=...)` consistent.)

## 4. Seed data
```bash
cd backend
pip install -r requirements.txt
python -m backend.seed.seed_atlas --places   # --places does the one live Google Places pull
```

## 5. Deploy backend to Cloud Run
```bash
cd backend
gcloud run deploy matchday-api \
  --source . --region us-central1 --allow-unauthenticated \
  --set-secrets MONGODB_URI=MONGODB_URI:latest,GOOGLE_MAPS_API_KEY=GOOGLE_MAPS_API_KEY:latest \
  --set-env-vars GOOGLE_CLOUD_PROJECT=$PROJECT,GOOGLE_GENAI_USE_VERTEXAI=true,GEMINI_MODEL=gemini-3-pro-preview,MONGODB_DB=matchday_local
# (on Vertex with billing, gemini-3-pro-preview works; on the AI-Studio free tier use gemini-3.1-flash-preview)
```

## 6. Frontend (Firebase Hosting or Cloud Run)
```bash
cd frontend
npm install
echo "NEXT_PUBLIC_API_BASE=https://matchday-api-XXXX.run.app" > .env.local
npm run build && npm start         # or: firebase deploy
```

## 7. Local dev (no cloud)
The app degrades gracefully with NO keys: tools fall back to seeded JSON, the forecast
and plan still render. Good for offline demo recording.
```bash
cd backend && uvicorn app.server:app --reload --port 8080
cd frontend && npm run dev
```
