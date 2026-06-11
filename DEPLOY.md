# Deploy to a public URL — Render (backend) + Vercel (frontend)

Get a live link judges can click in ~10 minutes. Two services:

- **Backend** (FastAPI, the visitor food chat + dashboard data) → **Render** free web service.
  Render runs a *persistent* process, so the ~13k-business cache survives between requests and
  the visitor chat answers in well under 10s after the first warm call.
- **Frontend** (Next.js 14, fan UI at `/fan`) → **Vercel**.

> Why not all-Vercel? Vercel's Python runtime is *serverless*: every cold request would reload
> ~13k docs (slow, no in-memory cache), and the owner agent's `npx mongodb-mcp-server` subprocess
> can't spawn there. Render keeps one process alive — the right fit. (Frontend on Vercel is ideal.)

---

## 1. Push to GitHub

From the repo root (`D:\World Cup\matchday-local`):

```bash
git add -A
git commit -m "Deploy config: Render backend + Vercel frontend"
# Create the repo and push (uses your gh/git credentials):
gh repo create matchday-local --public --source=. --remote=origin --push
# …or if the remote already exists:  git push -u origin main
```

`backend/.env` is git-ignored — your secrets are NOT pushed. You'll paste them into the hosts below.

---

## 2. Atlas → Network Access → add `0.0.0.0/0`  ⚠️ CRITICAL

Cloud hosts (Render/Vercel) use **dynamic outbound IPs**. Without this, the deployed backend
**cannot reach your database** and every endpoint fails.

1. MongoDB Atlas → your project → **Network Access** → **Add IP Address**.
2. Choose **ALLOW ACCESS FROM ANYWHERE** (`0.0.0.0/0`) → Confirm.

(Auth still protects the cluster via the user/password in `MONGODB_URI`.)

---

## 3. Deploy the backend on Render

1. Go to <https://render.com> → sign in with GitHub → **New** → **Blueprint**.
2. Pick the `matchday-local` repo. Render reads **`render.yaml`** at the root and configures the
   web service automatically (build, start, health check, `$PORT` binding — all handled).
3. It will prompt for the secret env vars marked `sync:false`. Paste these **from your local
   `backend/.env`**:

   | Env var          | Value (from `backend/.env`)                              | Required |
   |------------------|----------------------------------------------------------|----------|
   | `MONGODB_URI`    | your full `mongodb+srv://…` string                       | **yes**  |
   | `GOOGLE_API_KEY` | your AI Studio key — owner agent only; leave blank for the fan demo | no |

   (`MONGODB_DB`, `ATLAS_VECTOR_INDEX`, `ALLOWED_ORIGIN`, `GEMINI_MODEL` are pre-filled in
   `render.yaml` — no action needed.)
4. **Apply / Create**. First build takes a few minutes. When live, copy the service URL, e.g.
   `https://matchday-local-api.onrender.com`.
5. Confirm: open `https://<your-render-url>/api/health` → you should see
   `{"ok":true,"mongo":true,...}`.

> The blueprint installs the **lean** `backend/requirements-deploy.txt` (no google-adk/MCP) —
> the fan-facing demo needs nothing more. To also run the owner agent (`/api/chat`), edit
> `render.yaml`'s `buildCommand` to `pip install -r backend/requirements.txt`, set `GOOGLE_API_KEY`,
> and note Render free may need a paid plan for the heavier bundle + Node for the MCP subprocess.
> Without it, `/api/chat` just returns a clean "agent not configured" message; everything else works.

---

## 4. Deploy the frontend on Vercel

1. Go to <https://vercel.com> → **Add New… → Project** → import the same `matchday-local` repo.
2. **Root Directory** → set to **`frontend`**  (click *Edit* next to Root Directory). Vercel
   auto-detects Next.js — leave build/output settings at their defaults.
3. **Environment Variables** → add:

   | Name                   | Value                                            |
   |------------------------|--------------------------------------------------|
   | `NEXT_PUBLIC_API_BASE` | your Render backend URL (e.g. `https://matchday-local-api.onrender.com`) — **no trailing slash** |

4. **Deploy**. When done, Vercel gives you the public link, e.g.
   `https://matchday-local.vercel.app`.

---

## 5. Test the live URL

- Open `https://<your-vercel-url>/fan` — the fan UI.
- Ask the chat: **"best tacos near the stadium"** → it should return 3 local picks.
- (First request after the backend has been idle may take ~30–50s — Render free spins down idle
  services. Hit `/api/health` once to wake it before the demo.)

That's the live, judge-clickable link. Done.
