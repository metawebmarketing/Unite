# Unite

Implementation scaffold for the Unite social network plan.

## Backend setup

1. `python -m pip install -r backend/requirements.txt`
2. `python backend/manage.py migrate`
3. `cd backend && python -m daphne -b 127.0.0.1 -p 8000 config.asgi:application`

### Sentiment ranking runtime requirements

- Real-time sentiment ranking uses the Hugging Face Transformers pipeline with:
  - model: `cardiffnlp/twitter-xlm-roberta-base-sentiment`
  - packages: `transformers`, `sentencepiece`, and `protobuf` (included in `backend/requirements.txt`)
- Runtime is configured for fully local inference (`UNITE_SENTIMENT_LOCAL_FILES_ONLY = True`), so the backend does not call Hugging Face Hub during normal server operation.
- Ensure model files are present locally in the Hugging Face cache or set `UNITE_SENTIMENT_MODEL_PATH` to a local model directory.
- PyTorch must be available in the same Python environment as the backend server.
- Quick runtime check:
  - `python -c "import torch, transformers; print(torch.__version__, transformers.__version__)"`
- If PyTorch is missing in your environment, install it from the official selector:
  - [PyTorch Get Started](https://pytorch.org/get-started/locally/)

## Frontend setup

1. `cd frontend`
2. `npm install`
3. `npm run dev`

## Run locally (backend + frontend)

1. Start backend (from repo root):
   - `python -m pip install -r backend/requirements.txt`
   - `python backend/manage.py migrate`
   - `cd backend && python -m daphne -b 127.0.0.1 -p 8000 config.asgi:application`
   - (`runserver` works for basic HTTP endpoints, but realtime notifications/websockets require Daphne/ASGI)
2. Start frontend in a second terminal:
   - `cd frontend`
   - `npm install`
   - `npm run dev`
3. Open these local URLs:
   - Frontend app: `http://localhost:5173`
   - Backend API base: `http://localhost:8000/api/v1`
   - Django admin (optional): `http://localhost:8000/admin`

## First run installer

- On a fresh database, open `http://localhost:5173/install`.
- Create the master admin account.
- Optional: enable the checkbox to queue demo seed data (configurable users/posts) in the background.
- Demo post/reply/quote text now comes from `backend/apps/install/data/demo_posts_10000.json` (10,000 fixed entries) to emulate realistic content instead of ad-hoc template text.
- Seeded demo posts/interactions now also generate ranking signals and profile rollups, so seeded accounts immediately include sentiment/rank data.
- After install completes once, `/install` is locked and the app uses normal login/signup flows.

## Local test routes

- Authentication flow:
  - `http://localhost:5173/signup`
  - `http://localhost:5173/login`
  - `http://localhost:5173/forgot-password`
- Main app flow (after auth):
  - onboarding is now step 2 inside the signup modal (not a nav link)
  - `http://localhost:5173/profile-generation`
  - `http://localhost:5173/` (feed)
  - `http://localhost:5173/compose`
  - `http://localhost:5173/profile`
- Ops/admin surfaces:
  - `http://localhost:5173/ads-lab`
  - `http://localhost:5173/ai-audit`
  - `http://localhost:5173/policy-lab`
  - `http://localhost:5173/theme-studio`

## Admin labs and audit usage

- Log in with a staff/superuser account (created during `/install` or via Django admin).
- Open labs from the left navigation in feed (shown only to staff users):
  - **Policy Lab**: create/list policy packs and preview region policy behavior.
  - **Ads Lab**: manage ad slot configs, campaign/experiment targeting, and review ad metrics.
  - **AI Audit**: inspect AI action audit records with filtering by user/action/method/status.
- Feed config diagnostics in the right rail are visible only for staff users.

## Verification

- Backend tests: `python backend/manage.py test apps.install apps.accounts apps.connections apps.posts apps.feed apps.interests apps.policy apps.ai_accounts apps.ads apps.themes -v 2`
- Frontend typecheck/build: `cd frontend && npm run build`

## LLM Integration Guide (API + On-Server)

The current profile generation task in `backend/apps/accounts/tasks.py` uses a deterministic scorer (`_build_profile_vector`).  
If you want to use an LLM, keep the same output contract and replace only the scoring step.

### 1) Required output contract

Your LLM integration should return the same structure currently stored in `Profile.algorithm_vector`:

- `interest_count`
- `interest_tokens`
- `interest_weights`
- `positive_dialogue_bias`
- `recency_weight`
- `signal_totals`

This keeps feed ranking compatible with existing logic in feed/services.

### 2) Add a provider abstraction

Create a service module (recommended path: `backend/apps/accounts/llm_service.py`) with a single interface:

- `generate_profile_vector(profile: Profile) -> dict`

Then in `backend/apps/accounts/tasks.py`, replace:

- `vector = _build_profile_vector(profile)`

with:

- `vector = generate_profile_vector(profile)`

Keep `evaluate_profile_content(...)` and task status updates unchanged.

### 3) Configure provider mode in settings

Add these settings to `backend/config/settings/base.py` (or environment-specific settings):

- `UNITE_LLM_MODE = "disabled" | "api" | "local"`
- `UNITE_LLM_TIMEOUT_SECONDS = 20`
- `UNITE_LLM_MAX_RETRIES = 2`

For API mode:

- `UNITE_LLM_API_BASE_URL` (example: provider endpoint or gateway)
- `UNITE_LLM_API_KEY`
- `UNITE_LLM_MODEL_NAME`

For local/on-server mode:

- `UNITE_LLM_LOCAL_ENDPOINT` (example: `http://127.0.0.1:11434` for Ollama/OpenAI-compatible bridge)
- `UNITE_LLM_MODEL_NAME`

### 4) API provider flow

In `llm_service.py`:

1. Build a compact prompt from profile interests, recent posts, and recent interactions.
2. Send request to provider with strict timeout/retry limits.
3. Require JSON response only (no prose).
4. Validate and clamp all fields (types, ranges, max token count).
5. On failure, fall back to deterministic `_build_profile_vector(profile)`.

Recommended safeguards:

- Never log raw API keys.
- Add request id + profile id in logs for traceability.
- Reject malformed responses before writing to DB.

### 5) Local/on-server model flow

Use the same `generate_profile_vector(...)` interface, but call a local inference endpoint running on the same host/VPC.

Recommended runtime pattern:

1. Run model server as a separate process/container.
2. Call local endpoint from Celery task (`generate_algorithm_profile`) so web requests remain fast.
3. Apply the same schema validation and deterministic fallback.
4. Cache repeated prompts briefly when useful to reduce GPU/CPU load.

### 6) Minimal testing checklist

- Unit test: valid LLM JSON maps correctly to `algorithm_vector`.
- Unit test: malformed LLM output triggers deterministic fallback.
- Integration test: `generate_algorithm_profile` sets status `ready` and persists vector.
- Integration test: provider timeout/error sets fallback vector and does not break feed.
- Regression test: feed ranking still works with generated `interest_weights`.

### 7) Rollout recommendation

- Start with `UNITE_LLM_MODE="disabled"` in production.
- Enable for staff/test accounts first (feature-flag by user/account tier).
- Monitor task latency, failure rates, and ranking quality.
- Gradually raise traffic share after stability checks.

## Notable Implemented Modules

- Auth/account flows:
  - one-time installer status/run: `GET /api/v1/install/status`, `POST /api/v1/install/run`
  - `POST /api/v1/auth/signup`
  - `POST /api/v1/auth/login`
  - `POST /api/v1/auth/password-reset/request`
  - `POST /api/v1/auth/password-reset/confirm`
  - profile image upload endpoint with optimization/crop inputs: `POST /api/v1/profile/image`
- Feed engine with cursor pagination, deterministic suggestion cadence, ad injection hooks, feed cache headers, and interest mode filtering.
  - `GET /api/v1/feed?mode=interest&interest_tag=...`
  - optional response slimming with `fields` query param (example: `GET /api/v1/feed?mode=both&fields=id,content,created_at`)
  - ranking now consumes weighted profile interests (`algorithm_vector.interest_weights`) derived from onboarding + post/interaction history
  - configurable max injection guardrail via `UNITE_MAX_INJECTION_RATIO` and `GET /api/v1/feed/config` (staff only)
  - account-type throttling scopes for write actions (`post_write_ai`, `post_react_ai`, `connect_action_ai`)
  - safety suppression prevents flagged post/profile entities from being surfaced in feed posts/suggestions
  - long feed windowed rendering in frontend to reduce DOM load
  - suggestion injector now serves interest-based user recommendations with connected-user exclusion and diversity injection
  - profile-generation progress route (`/profile-generation`) for non-ready algorithm states after login/onboarding
- Interest surfaces:
  - `GET /api/v1/interests/top`
  - `GET /api/v1/interests/top-posts?tag=...`
  - `GET /api/v1/interests/suggest?selected=tech,ai&query=sec`
- Offline/PWA reliability:
  - manifest + service worker
  - stale-while-revalidate feed caching
  - IndexedDB queued writes with background replay
  - route-level lazy loading for non-critical screens
  - cached theme tokens applied before first paint to reduce theme flash
- Idempotency/replay protection:
  - `Idempotency-Key` support on post create/react
  - replay conflict detection and response replay
  - sync metrics endpoint: `GET /api/v1/posts/sync/metrics`
  - sync event ingest endpoint: `POST /api/v1/posts/sync/events`
- Anti-spam post protections:
  - burst-posting guardrail (`UNITE_SPAM_BURST_WINDOW_SECONDS`, `UNITE_SPAM_BURST_MAX_POSTS`)
  - repeated-link guardrail (`UNITE_SPAM_LINK_WINDOW_SECONDS`, `UNITE_SPAM_LINK_MAX_POSTS`)
- Policy management:
  - list/create packs: `GET/POST /api/v1/policy/packs`
  - resolve policy with rollout behavior: `POST /api/v1/policy/resolve`
- AI account transparency:
  - AI signup with stricter throttle: `POST /api/v1/ai/signup`
  - AI action audit feed: `GET /api/v1/ai/audit`
  - AI post create/react and authenticated write actions are audit-logged server-side
  - profile and feed payloads expose `is_ai_account` / AI badge flags for visible labeling
  - staff users can filter global AI audits (`user_id`, `action_name`, `method`, `status_code`, `limit`)
  - frontend AI audit console route: `/ai-audit`
- Ads reporting hooks:
  - ingest feed ad events: `POST /api/v1/ads/events`
  - aggregate ad delivery metrics: `GET /api/v1/ads/metrics` with optional `region` and `campaign` filters
  - manage regional ad slot intervals: `GET/POST /api/v1/ads/configs` and `PATCH /api/v1/ads/configs/{id}`
  - ad configs now support targeting hooks (`campaign_key`, `experiment_key`, `account_tier_target`, `target_interest_tags`) used by feed ad injection
  - injected ad items include `ad_event_key`, `campaign_key`, `ad_config_id`, `targeting_reason`, and `experiment_key`
  - frontend feed emits impression/click events for injected ads
  - frontend Ads Lab route: `/ads-lab`
- Algorithm scheduling hardening:
  - periodic profile refresh now uses cooldown and activity thresholds (`UNITE_PROFILE_REFRESH_COOLDOWN_SECONDS`, `UNITE_PROFILE_REFRESH_MIN_POSTS`, `UNITE_PROFILE_REFRESH_MIN_INTERACTIONS`)
- Theme validation:
  - strict token schema checks for required semantic keys and value ranges before activation
- Access and UX hardening:
  - `/compose`, `/profile`, `/theme-studio`, `/policy-lab`, `/ads-lab`, `/ai-audit` redirect to login when unauthenticated
  - Policy Lab / Ads Lab / AI Audit links and routes are staff-only in the frontend
  - Compose/Profile/Theme Studio render as modal-style flows with close/cancel controls
  - signup is a stepped modal flow with onboarding interests as chips and default + dynamic suggestions
