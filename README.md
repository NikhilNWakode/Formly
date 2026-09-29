# Formly

Turn a sentence into a 3D model you can rotate, inspect and download.

Type *"A futuristic cyberpunk helmet"*, and Formly calls a hosted text-to-3D
model, validates the returned asset, and renders it in the browser as an
interactive, downloadable `.glb`.

---

## Status

Runs end to end locally. Not yet deployed — see [Deployment](#deployment).

Live generation depends on Hugging Face's **free ZeroGPU capacity**, which is
shared and exhausts after a modest number of generations. When it does, the API
returns a controlled error and the [demo assets](#demo-assets) keep the 3D
viewer fully usable.

---

## Architecture

```
  USER
    |
    v
+------------------+     HTTPS      +------------------+
|    Next.js UI    | -------------> |     FastAPI      |
|  prompt, states  |  POST /api/    |  validate prompt |
|  R3F viewer      |     generate   |  provider call   |
|  download        | <------------- |  validate GLB    |
+------------------+   model_url    |  TTL asset store |
    |                               +--------+---------+
    | GET /api/models/{id}.glb               |
    |                                        v  gradio_client
    |                               +------------------+
    |                               |  hysts/Shap-E    |
    |                               |  HF ZeroGPU A10G |
    |                               +--------+---------+
    |                                        |
    |                                   GLB bytes
    v
React Three Fiber: rotate / zoom / pan / reset / fullscreen
```

Two services. No database, no queue, no cache layer. Only the backend knows
which AI provider is in use.

---

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| UI | Next.js 15, React 19, TypeScript | Single static page, first-class Vercel deploy |
| Styling | Tailwind CSS | Small token set in one config, no runtime CSS cost |
| 3D | React Three Fiber, three.js, drei | Declarative three.js that lives inside React state |
| API | FastAPI, Pydantic v2 | Async, typed validation, OpenAPI for free |
| Provider client | gradio_client | Speaks the HF Space protocol and survives its changes |
| AI | Shap-E on a Hugging Face Space | See [AI model](#ai-model) |

---

## Key decisions

**Why GLB.** One binary file holds geometry, materials and colours, so
"download the model" is a single response with a single filename. three.js
loads it natively via `GLTFLoader`, and Shap-E's Space already emits `.glb`, so
Formly never re-encodes — the bytes validated are the bytes downloaded. OBJ/STL
were rejected: no single-file colour support, which would discard Shap-E's
vertex colours entirely.

**Why React Three Fiber.** Raw three.js keeps its own object graph and fights
React's state model. R3F renders three.js *as* a React tree, so swapping models
is a key change rather than manual teardown, and GPU cleanup happens on the
same path React already uses. The ~600 KB cost is why the viewer sits behind
`next/dynamic` — first load is **109 kB**.

**Why FastAPI.** `gradio_client` is the maintained way to call an HF Space, and
it is Python. A request spends 10–40 s waiting on a remote GPU, which async
holds on the event loop rather than a thread per request. Pydantic rejects bad
prompts before any GPU quota is spent.

**Why no database.** Nothing is persisted by product decision — there is no
generation history. An asset is only needed between the POST that creates it
and the GET that renders it, so it lives in a TTL- and size-bounded in-process
store.

**Why no queue.** Generation takes 10–40 s, which fits inside an HTTP request.
A queue would add a broker, a worker, a status endpoint and UI polling to hide
a wait the user already expects. The limit is stated under [Scaling](#scaling).

---

## AI model

**Provider:** [`hysts/Shap-E`](https://huggingface.co/spaces/hysts/Shap-E) — a
Hugging Face Space running OpenAI's [Shap-E](https://github.com/openai/shap-e)
on ZeroGPU (A10G), called via `gradio_client` at `/text-to-3d`. No weights are
downloaded and no local GPU is needed.

**Licence:** MIT (model and code). The Space is public and free to call.

**Measured latency:** 9.9 s, 13.9 s and 17.7 s across three real runs at 64
steps, excluding retries. Assets are 2–4 MB.

**Output shape:** `POSITION` + `COLOR_0`, with **no normals and no materials**.
This drove a real fix in the viewer: glTF's default material is `metalness = 1`,
which renders near-black without an environment map, and missing normals mean
nothing is shaded. `ModelViewer` computes vertex normals and substitutes a
neutral material when it finds the unusable default.

**Limitations:** blobby, low-fidelity meshes; vertex colours rather than
textures; no seed or style control exposed; and a shared, flapping Space — it
reported itself healthy while returning HTTP 502 on ~60% of probes during
testing, which is why retries exist.

**Replacing it:** implement `GenerationProvider` (one method,
`async generate(prompt) -> GeneratedAsset`), register it in
`services/generation/registry.py`, and set `PROVIDER`. Nothing in the routes,
schemas or frontend refers to Shap-E.

---

## Provider evaluation

Shap-E's weakness is visible: *"A tiger"* returns a recognisable but blobby
animal. Alternatives were evaluated under the ₹0 / no-local-GPU constraints.

**The structural finding:** no text-to-3D model is served by any Hugging Face
inference provider (`?pipeline_tag=text-to-3d&inference_provider=all` returns
zero). Hosted ZeroGPU Spaces are the only free path, so **every candidate draws
on the same shared quota**.

| Candidate | Outcome |
|---|---|
| `tencent/Hunyuan3D-2` | Text-to-3D **disabled server-side** (`Text to 3D is disable...`). Image-only as hosted. |
| `tencent/Hunyuan3D-2mini-Turbo` | Unreachable (`Internal Server Error`) |
| `microsoft/TRELLIS.2` | Image-only; no text endpoint |
| `gokaygokay/Flux-TRELLIS` | Unreachable (404) |
| `HorizonRobotics/EmbodiedGen` | Intermittent 502; 13-endpoint robotics/URDF pipeline |
| `prithivMLmods/TRELLIS.2-Text-to-3D` | Viable — implemented as an experimental provider |
| **`hysts/Shap-E`** | **Selected** |

**Cost, read from the Spaces' source:** Shap-E uses **1** GPU call (~60 GPU-s).
TRELLIS drives three endpoints of which **two** carry
`@spaces.GPU(size="xlarge", duration=120)` — ~240 GPU-s on a larger tier, at
least **4x** more of the resource we are constrained by.

**Licensing:** Shap-E is MIT end to end. The TRELLIS pipeline includes BRIA
RMBG-2.0, which is CC BY-NC 4.0 and access-gated — effectively non-commercial.

**No comparative quality claim is made in either direction.** The benchmark did
not run: the free quota was exhausted before a single TRELLIS generation
completed, so there was no output to judge.

**Decision.** Shap-E is the default, selected on the criteria that could be
verified — reliability, latency, free availability, licensing and integration
complexity. Output quality is deliberately absent from that list.

TRELLIS is kept behind the same interface as
**`PROVIDER=trellis` — experimental and unverified** (unit-tested against a
mocked client; no live generation has ever completed through it). It is backend
configuration only: there is no user-facing model selection, and there is no
automatic fallback between providers.

---

## Demo assets

Formly ships pre-generated example GLBs so the 3D experience stays
demonstrable when the free inference provider is unavailable.

| Example | Triangles | Size |
|---|---|---|
| Japanese Pagoda | 115,712 | 2.2 MB |
| Cyberpunk Helmet | 214,268 | 4.1 MB |

**They are not a fallback AI provider.** Nothing is generated when you click
one. Each was produced earlier by the same Shap-E provider, then committed and
served as a static file — deliberately real Shap-E output rather than
hand-modelled meshes, so an example shows what the product actually produces.

How the distinction stays honest:

- Selecting an example **never calls `/api/generate`**
- The viewer badge reads **"Example model"** vs **"Generated with AI"**
- Stats read `pre-generated example` instead of a fabricated timing
- Downloads are named `formly-example-<id>.glb`
- A failed generation keeps what is on screen, still labelled as an example

Assets are fetched on demand, not at page load. To add more: drop a `.glb` into
`frontend/public/examples/` and add an entry to `frontend/lib/examples.ts` —
tests verify the file is valid GLB and that the manifest matches the bytes on
disk. Note the root `.gitignore` excludes `*.glb`; the examples directory is
explicitly re-included, which is what keeps them present in production.

---

## Error handling

The frontend only ever reads `{ success, error }`.

| Failure | Status | User sees |
|---|---|---|
| Empty / short / long / unsupported prompt | 422 | Specific validation message (also caught client-side) |
| Provider asleep or unreachable | 502 | "The generation service is unavailable" |
| Upstream GPU quota exhausted | 502 | "Generation temporarily unavailable" + capacity note |
| Provider timeout | 502 | "Generation took too long" |
| Asset failed validation | 502 | "The generated model could not be loaded" |
| Too many requests | 429 | Rate-limit message + `Retry-After` |
| Anything unexpected | 500 | "Something went wrong" (detail logged only) |

**The rule that matters most:** if a generation fails while a valid model is on
screen, the model stays and the error appears as a banner beneath it.

Provider detail, stack traces and secrets never reach the client; a test
asserts a secret in an exception body does not appear in the response.

**Retry classification:** 502s and connection errors are retried with capped
backoff; quota, timeouts and call-signature errors are not, since a retry
cannot fix them and only makes the user wait.

---

## Running locally

Two terminals. Python 3.11+ and Node 20+.

**Backend**

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env            # paste your HF_TOKEN into it
uvicorn app.main:app --reload --port 8000
```

**Frontend**

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

Open <http://localhost:3000>. API docs at <http://localhost:8000/docs>.

> Generation needs a free Hugging Face **read** token from
> <https://huggingface.co/settings/tokens>. Without one, the anonymous GPU
> quota runs out almost immediately. The token is backend-only and is never
> sent to the browser.

---

## Environment variables

Full annotated list in [`.env.example`](.env.example).

| Variable | Where | Default | Purpose |
|---|---|---|---|
| `HF_TOKEN` | backend | *(none)* | Raises ZeroGPU quota. **Secret.** |
| `PROVIDER` | backend | `shap-e` | `shap-e` or `trellis` (experimental) |
| `HF_SPACE` | backend | `hysts/Shap-E` | Space backing the Shap-E provider |
| `INFERENCE_STEPS` | backend | `64` | Sampling steps |
| `PROVIDER_MAX_ATTEMPTS` | backend | `6` | Retries for a flapping Space |
| `PROVIDER_TIMEOUT_SECONDS` | backend | `300` | Hard cap per generation |
| `ASSET_TTL_SECONDS` | backend | `3600` | How long a GLB stays retrievable |
| `CORS_ORIGINS` | backend | localhost:3000 | Exact allowed origins, comma separated |
| `RATE_LIMIT_REQUESTS` | backend | `10` | Generations per IP per window |
| `NEXT_PUBLIC_API_BASE_URL` | frontend | localhost:8000 | Backend base URL (public by design) |

---

## Deployment

**Backend → Render (free).** [`render.yaml`](render.yaml) is a working
blueprint: point Render at the repo, then set `HF_TOKEN` and `CORS_ORIGINS` in
the dashboard. A [`Dockerfile`](backend/Dockerfile) is included for any
container host.

**Frontend → Vercel (free).** Import the repo with **root directory
`frontend`**; [`vercel.json`](frontend/vercel.json) supplies the preset and
security headers. Set `NEXT_PUBLIC_API_BASE_URL` to the Render URL.

**Order matters:** deploy the backend, set `NEXT_PUBLIC_API_BASE_URL`, deploy
the frontend, then set `CORS_ORIGINS` to the real frontend origin (no trailing
slash) and let the backend redeploy.

**Cold starts compound.** On free tiers the Render instance sleeps after ~15
minutes *and* the HF Space sleeps independently, so the first generation after
a quiet period is slow. Warm both before a demo.

---

## Testing

```bash
cd backend && .venv/Scripts/python -m pytest -q     # 118 passed, 1 skipped
cd frontend && npm run typecheck && npm run build
```

Covers prompt validation, provider failure/quota/timeout/signature errors,
invalid-asset fail-closed, store TTL and eviction, filename sanitisation, rate
limiting, CORS, the error envelope, provider registry and API-contract parity
across providers, plus demo-asset validity and manifest drift.

External inference is always mocked — **the suite never consumes GPU quota**.
One opt-in test (`FORMLY_LIVE_TESTS=1`) checks a Space's endpoints still exist
without spending GPU time.

Frontend verification is typecheck + production build plus manual browser
testing; there is no automated component suite.

---

## Scaling

Current design is one synchronous instance. What breaks first, in order:

1. **Shared GPU quota** — the hard ceiling. Needs dedicated inference before
   anything else matters.
2. **Request-bound generation** — long-held connections do not survive typical
   60 s platform proxy timeouts at scale → queue + job status.
3. **In-process asset store** — not shared between instances → object storage
   with presigned URLs.
4. **In-process rate limiter** → Redis.

For 1,000 concurrent users: a queue, dedicated GPU workers, object storage
behind a CDN, and a cache keyed on the normalised prompt.

---

## Limitations

- **Not deployed yet** — blueprints are ready.
- **Mesh quality is Shap-E's**: blobby, vertex-coloured, untextured.
- **The free ZeroGPU quota is the real ceiling** and is shared across all
  Spaces. Demo assets keep the viewer usable, but do not restore generation.
- **Only two demo assets ship** — more were intended, but the quota was
  exhausted before they could be generated, and hand-made substitutes would
  misrepresent the model's real output.
- **The TRELLIS provider has never run live** — mocked unit tests only.
- **Single instance assumed**: asset store and rate limiter are per-process.
- **Rate limiting is by IP**, so users behind one NAT share a bucket. It is an
  abuse guard, not a security control.
- **No auth, no payments, no generation history** — out of scope by design.
- `npm audit` reports advisories in transitive build-time dependencies of
  Next.js; `--force` would downgrade Next and break the build. Next is pinned
  to **15.5.26**, which patches CVE-2025-66478.

---

## Future improvements

Not implemented: asynchronous job processing with a queue, dedicated GPU
workers, object storage plus CDN, generation history, user-facing model
selection, prompt-keyed caching, and automated frontend/E2E suites.

---

## API

`POST /api/generate`

```json
{ "prompt": "A futuristic cyberpunk helmet" }
```

```json
{
  "success": true,
  "model_url": "/api/models/<id>.glb",
  "download_url": "/api/models/<id>/download",
  "filename": "formly-futuristic-cyberpunk-helmet.glb",
  "format": "glb",
  "provider": "shap-e",
  "generation_seconds": 17.69,
  "vertex_count": 84102,
  "triangle_count": 168244,
  "byte_size": 3365592
}
```

Errors are always `{ "success": false, "error": "<message>" }`.

`GET /api/models/{id}.glb` — the asset, for rendering
`GET /api/models/{id}/download` — the asset, as an attachment
`GET /api/health` — liveness of **this API only**; it does not probe the
provider, so a 200 does not mean generation currently works

---

## Project structure

```
formly/
├── backend/
│   ├── app/
│   │   ├── main.py                  # app factory, CORS, error envelope
│   │   ├── config.py                # settings
│   │   ├── routes/                  # generation, health
│   │   ├── schemas/                 # Pydantic request/response
│   │   └── services/
│   │       ├── store.py             # TTL asset store
│   │       ├── naming.py            # filename sanitisation
│   │       ├── rate_limit.py
│   │       └── generation/
│   │           ├── base.py          # GenerationProvider + errors
│   │           ├── hf_space.py      # shared failure classification
│   │           ├── shap_e.py        # default provider
│   │           ├── trellis.py       # experimental provider
│   │           ├── registry.py      # provider selection
│   │           └── validator.py     # GLB structural validation
│   ├── tests/                       # 118 tests
│   └── Dockerfile
├── frontend/
│   ├── app/                         # layout, page
│   ├── components/                  # ModelViewer, PromptInput, ExampleModels, ...
│   ├── lib/                         # api, types, examples, format
│   └── public/examples/             # pre-generated demo GLBs
├── render.yaml
└── .env.example
```
