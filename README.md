# Formly

Turn a sentence into a 3D model you can rotate, inspect and download.

Type *"A futuristic cyberpunk helmet"*, and Formly calls a hosted text-to-3D
model, validates the returned asset, and renders it in the browser as an
interactive, downloadable `.glb`.

---

## Demo

**Not yet deployed.** The application is verified working end to end locally —
prompt → AI generation → validated GLB → interactive render → download. See
[Running locally](#running-locally).

If the free GPU quota happens to be exhausted when you open it, the 3D viewer
is still fully usable via the pre-generated [demo assets](#demo-assets) —
rotate, zoom, reset and download all work without the AI service. Deployment is a matter of running the
blueprints in [Deployment](#deployment) against a Render and a Vercel account
and setting two environment variables.

> **One thing to do first:** generation needs a free Hugging Face token. See
> [The HF token](#the-hf-token) — without it the anonymous GPU quota runs out
> almost immediately and every generation fails with a (correctly handled)
> "service is busy" error.

---

## Architecture

```
                         USER
                          │
                          ▼
              ┌───────────────────────┐
              │      Next.js UI       │
              │  prompt · states ·    │
              │  R3F viewer · download│
              └───────────┬───────────┘
                          │  HTTPS  POST /api/generate
                          ▼
              ┌───────────────────────┐
              │        FastAPI        │
              │  validate prompt      │
              │  GenerationProvider   │
              │  validate GLB         │
              │  TTL asset store      │
              └───────────┬───────────┘
                          │  gradio_client
                          ▼
              ┌───────────────────────┐
              │  hysts/Shap-E Space   │
              │  (HF ZeroGPU, A10G)   │
              └───────────┬───────────┘
                          │
                          ▼
                     GLB bytes
                          │
                          ▼
              ┌───────────────────────┐
              │   GLB validation      │
              │  magic · length ·     │
              │  JSON chunk · meshes  │
              └───────────┬───────────┘
                          │  GET /api/models/{id}.glb
                          ▼
              ┌───────────────────────┐
              │  React Three Fiber    │
              │  rotate · zoom · pan  │
              │  reset · fullscreen   │
              └───────────────────────┘
```

Two services, no database, no queue, no cache layer. The backend is the only
component that knows which AI provider is in use.

---

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| UI | **Next.js 15** + React 19 + TypeScript | App Router, static export of a single page, first-class Vercel deploy. |
| Styling | **Tailwind CSS** | Small token set kept in one config; no runtime CSS-in-JS cost. |
| 3D | **React Three Fiber**, **three.js**, **drei** | Declarative three.js that lives inside React state instead of beside it. |
| API | **FastAPI** + **Pydantic v2** | Async, typed request validation, generated OpenAPI docs for free. |
| Provider client | **gradio_client** | Speaks the HF Space protocol and survives its version changes. |
| AI | **Shap-E** on a Hugging Face Space | See [AI model](#ai-model). |

---

## Why GLB?

glTF is the runtime format for 3D on the web; GLB is its single-file binary
form. It matters here because:

- **One file.** Geometry, materials and textures are in a single binary, so
  "download the model" is one HTTP response with one filename — no zip, no
  sidecar `.bin` or texture files to keep in sync.
- **Native to the renderer.** three.js ships `GLTFLoader`; no conversion step
  between what the provider returns and what the browser draws.
- **No transcoding.** Shap-E's Space already emits `.glb`, so Formly never
  re-encodes the asset. The bytes the provider produced are the bytes the user
  downloads — which also means validation applies to exactly what ships.
- **Portable.** The downloaded file opens in Blender, Windows 3D Viewer, Xcode
  and most DCC tools without conversion.

OBJ/STL were rejected: no material or colour support in a single file, which
would discard Shap-E's vertex colours entirely.

---

## Why React Three Fiber?

Raw three.js is imperative and keeps its own object graph, which fights React's
state model — you end up hand-writing mount/unmount, resize and disposal logic.
R3F renders three.js *as* a React tree, so:

- The viewer is a component that takes a `url` prop; swapping models is a key
  change, not a manual teardown.
- `drei` supplies `OrbitControls` and `useGLTF` (with caching and Suspense
  integration), which is most of the viewer's behaviour.
- Cleanup is a `useEffect` return, so GPU resources are disposed on the same
  path React already uses.

The cost is a ~600 KB dependency. That is why the viewer is behind
`next/dynamic` — it is not in the initial bundle (**first load is 108 KB**;
three.js loads only once there is a model to show).

---

## Why FastAPI?

The generation step is a slow network call to a Python-ecosystem service.

- **The client library is Python.** `gradio_client` is the maintained way to
  call an HF Space. Using it from Node would mean reimplementing the Space's
  SSE protocol by hand.
- **Async fits the workload.** A request spends ~10–40 s waiting on a remote
  GPU. FastAPI holds that on the event loop instead of a thread per request.
- **Validation is declarative.** Pydantic turns prompt rules into a schema, and
  invalid input is rejected before any GPU quota is spent.
- **Typed by default**, with OpenAPI docs at `/docs` for free.

---

## AI model

**Provider:** [`hysts/Shap-E`](https://huggingface.co/spaces/hysts/Shap-E) — a
Hugging Face Space running OpenAI's [Shap-E](https://github.com/openai/shap-e)
on ZeroGPU (A10G).
**Inference mechanism:** remote call to the Space's `/text-to-3d` endpoint via
`gradio_client`. No model weights are downloaded and no GPU is needed locally.
**Licensing:** Shap-E is **MIT** licensed (model and code), which is fine for an
assessment and for commercial use. The Space is public and free to call.

### How it was chosen

Three approaches were tested before writing any application code:

| Candidate | Result | Verdict |
|---|---|---|
| **HF Serverless Inference API** | `openai/shap-e` returns an empty `inferenceProviderMapping` — no provider serves text-to-3D. | **Rejected**: not available at any price. |
| **`prithivMLmods/TRELLIS.2-Text-to-3D`** | Reachable, but the pipeline is 3 chained stateful calls (`generate_txt2img` → `preprocess_image` → `generate_3d`) bound to a session, two of which consume GPU quota. | **Not selected** for the default path; later implemented as an experimental provider. |
| **`hysts/Shap-E`** | One call → a `.glb` directly. Measured **10-18 s** warm; output verified as valid glTF 2.0. | **Selected.** |

The deciding factor was reliability per unit of complexity: one call that
returns the target format, at a quarter of the GPU cost, beats a three-call
pipeline. See [Provider evaluation](#provider-evaluation) for the full
comparison — including why no relative quality claim is made.

### Measured behaviour

These are measured numbers, not estimates:

- **Generation latency:** 9.9 s, 13.9 s and 17.7 s across three real runs
  (64 steps), excluding retries against a flapping Space.
- **Asset size:** 2.2-4.3 MB, scaling with mesh density.
- **Output shape:** `POSITION` + `COLOR_0`, **no normals, no materials**.

That last point drove a real fix in the viewer: glTF's default material is
`metalness = 1`, which renders almost black without an environment map, and
missing normals mean nothing is shaded. `ModelViewer` therefore computes vertex
normals and substitutes a neutral dielectric material when it finds the
unusable default. Without that, every generated model renders as a dark blob.

### Limitations

Being honest about what Shap-E is:

- **Blobby, low-fidelity meshes.** It produces recognisable shapes, not clean
  topology. A "helmet" is a helmet-ish form with coloured regions.
- **Vertex colours, not textures.** No UV maps, no PBR materials.
- **No control.** No seed pinning in the UI, no negative prompts, no style
  parameters exposed.
- **Shared, flapping infrastructure.** This is the real operational risk, and
  it is worse than "it sleeps". The Space is public and its ZeroGPU quota is
  shared. During testing it reported `stage: RUNNING` with a healthy replica
  while **returning HTTP 502 on roughly 60% of probes** — alternating 200/502
  within seconds. A single generation needs several sequential HTTP calls
  (config, API info, queue join, SSE stream), so per-attempt success is well
  below that 40%. Retries are not defensive padding here; they are what makes
  the feature work at all.

### Replacing it

Implement `GenerationProvider` (one method, `async generate(prompt) -> GeneratedAsset`),
register it in `services/generation/registry.py`, and set `PROVIDER`. Nothing
in the routes, schemas or frontend refers to Shap-E.

---

## Provider evaluation

Shap-E's weakness is obvious: *"A tiger"* returns a recognisable but blobby
animal. So newer text-to-3D models were evaluated to see whether one could do
materially better **within the ₹0 / no-local-GPU constraints**.

### The structural finding

**No text-to-3D model is served by any Hugging Face inference provider.**
Querying `?pipeline_tag=text-to-3d&inference_provider=all` returns **zero**
models, and `inferenceProviderMapping` is empty for `openai/shap-e`,
`microsoft/TRELLIS-text-xlarge`, `microsoft/TRELLIS.2-4B`, `tencent/Hunyuan3D-2`
and `tencent/Hunyuan3D-2.1`.

That matters more than any single candidate: the only free remote path for
*any* of these models is a hosted ZeroGPU Space, so **every candidate draws on
the same shared GPU quota**. The comparison is therefore not "which model is
best" but "which model is best *per GPU-second of a free allowance*".

### Candidates

| Candidate | Text-to-3D? | Outcome |
|---|---|---|
| `tencent/Hunyuan3D-2` | Signature has `caption` | **Disabled server-side.** A live call returns `Text to 3D is disable. Please enable it by 'python gradio_app.py --enable_t23d'`. Image-to-3D only as hosted. |
| `tencent/Hunyuan3D-2mini-Turbo` | — | Unreachable: `Internal Server Error` on every connect attempt. |
| `microsoft/TRELLIS.2` (official) | No | Image-only (`/image_to_3d`, `/extract_glb`). Would need our own text→image stage. |
| `gokaygokay/Flux-TRELLIS` | Yes | Unreachable: 404 on the Gradio API. |
| `HorizonRobotics/EmbodiedGen-Text-to-3D` | Yes | Intermittently 502; a 13-endpoint robotics pipeline emitting URDF. Far more integration surface than this product needs. |
| **`prithivMLmods/TRELLIS.2-Text-to-3D`** | **Yes** | **The only viable alternative.** Three stages → GLB. Implemented as `PROVIDER=trellis`. |
| `hysts/Shap-E` (incumbent) | Yes | One call → GLB. |

### Cost, measured from the Spaces themselves

Read out of each Space's source rather than estimated:

| | Pipeline stages we call | Stages that consume GPU quota | Declared reservation | Quota per model |
|---|---|---|---|---|
| Shap-E | 1 (`/text-to-3d`) | **1** | 60 s (confirmed by its own quota error: *"60s requested vs. 0s left"*) | **~60 GPU-s** |
| TRELLIS.2 | 3 | **2** | `@spaces.GPU(size="xlarge", duration=120)` on each GPU stage | **~240 GPU-s, on a larger tier** |

To be exact about TRELLIS, since stage count and GPU-call count are not the
same number: the provider drives **three** endpoints —
`/generate_txt2img`, `/preprocess_image`, `/generate_3d` — but only **two**
carry a `@spaces.GPU` decorator in the Space's `app.py`
(`generate_txt2img` at line 195 and `generate_3d` at line 221, both
`size="xlarge", duration=120`). `preprocess_image` does background removal and
cropping without a GPU allocation, so it costs latency but not quota.

**TRELLIS therefore reserves ~4x more of the one resource we are actually
constrained by**, before accounting for the `xlarge` size multiplier.

### The quality test, and why it is incomplete

The intended benchmark was five prompts (tiger, treasure chest, gaming
controller, wooden chair, Japanese pagoda) through both providers.

It could not be completed. After a modest amount of testing — a handful of
Shap-E generations and a few candidate probes — the free account hit:

```
You have exceeded your ZeroGPU runs limit.
Subscribe to Hugging Face PRO to get 40 min of ZeroGPU quota a day
```

Retries every three minutes over the following window never recovered enough
quota to complete a single TRELLIS generation.

That failure is not a side note; **it is the most decisive result in this
evaluation.** A provider that cannot complete one generation during an
evaluation session, at 4x the quota cost per model, cannot be relied on to
survive an assessor clicking through several prompts.

**No comparative quality claim is made in either direction.** TRELLIS produced
no output to judge, so this README does not assert that it is better than
Shap-E, and it does not assert that Shap-E is better than it. The benchmark
that would have settled it did not run. What *is* observable is absolute and
stated plainly elsewhere: Shap-E's own meshes are blobby, vertex-coloured and
untextured — that is a property of the output we did see, not a ranking against
output we did not.

### Licensing

| Component | Licence |
|---|---|
| Shap-E | **MIT** — clean, commercial-friendly |
| TRELLIS.2-4B | MIT |
| Z-Image-Turbo (TRELLIS text→image stage) | Apache-2.0 |
| **BRIA RMBG-2.0** (TRELLIS background-removal stage) | **CC BY-NC 4.0, gated** |
| Hunyuan3D-2 / 2.1 | `license:other` (Tencent Community Licence) |

The TRELLIS pipeline is therefore **effectively non-commercial**, because one
stage is CC BY-NC and access-gated. Fine for an assessment; a real constraint
beyond one. Shap-E is plain MIT end to end.

### Decision

**Shap-E remains the default provider.** It was selected for this assessment
on the criteria that could actually be verified under the constraints:
**reliability, latency, free availability, licensing, and integration
complexity.**

Output quality is deliberately absent from that list. It is the one criterion
the evaluation could not measure comparatively, so it played no part in the
decision.

The verified reasoning:

1. **Reliability** — Shap-E completed real generations repeatedly during this
   work. TRELLIS never completed one, at 4x the quota cost per attempt.
2. **Latency** — Shap-E measured 9.9 s, 13.9 s and 17.7 s across three real
   runs. TRELLIS has no measured figure, because nothing finished.
3. **Free availability** — both share one ZeroGPU ceiling; Shap-E fits under it
   roughly 4x more often (~60 GPU-s vs ~240 per model).
4. **Licensing** — MIT end to end, versus a pipeline whose background-removal
   stage is CC BY-NC 4.0 and access-gated.
5. **Integration complexity** — a single call returning GLB, versus a stateful
   three-endpoint pipeline on a single-maintainer community Space.

**TRELLIS is kept, not deleted** — implemented behind the same
`GenerationProvider` interface so the architecture demonstrably supports more
than one model, and so the comparison can be finished later with quota
available. It is **experimental and unverified**, and it is **backend
configuration only**:

```bash
PROVIDER=trellis   # server-side env var; not a user-facing feature
```

There is deliberately **no user-facing model selection**. `POST /api/generate`
accepts a prompt and nothing else; a `provider` field sent by a client is
ignored, and a test asserts that. The frontend has no model picker and no
knowledge of which provider is configured. Exposing an unverified provider to
users would let them select a path that has never produced a model.

There is also **no automatic fallback** between providers. Silently switching
models would hide which one produced a result and could quadruple an already
slow generation.

> **Status of the TRELLIS provider: EXPERIMENTAL / UNVERIFIED.** Its pipeline
> logic, retry classification, GLB selection, timeout and error mapping are
> covered by unit tests against a mocked Gradio client, and a
> `FORMLY_LIVE_TESTS=1` test checks the live Space still exposes the three
> endpoints without spending GPU time. **A full live generation through it has
> never been executed.** Given that a `gradio_client` kwarg rename previously
> broke the Shap-E path in a way only a live call exposed, assume this provider
> does not work until someone proves it does.

---

## Engineering decisions

**A provider abstraction, and nothing more.**
`GenerationProvider` is the one abstraction in the backend, because the model
is the component most likely to be replaced. There is no repository layer, no
service locator and no dependency-injection container — the app has one
meaningful seam and it is that one.

**Synchronous generation, deliberately.**
Generation takes ~10–40 s, which fits inside an HTTP request. A job queue would
mean a broker, a worker, a status endpoint and polling in the UI — real
infrastructure to avoid a wait the user is already expecting. The limit is
stated plainly under [Scaling](#scaling).

**No database.**
Nothing is persisted by product decision (no generation history). A generated
asset is only needed between the POST that creates it and the GET that renders
it, so it lives in a TTL- and size-bounded store on the instance. Adding
Postgres to hold rows nobody reads would be infrastructure for its own sake.

**Retry with backoff, because the Space flaps.**
Measured repeatedly: the Space returns HTTP 502 for stretches of requests, then
serves normally — while reporting itself healthy. The provider retries the
whole connect+predict cycle and drops its cached client between attempts, so a
restarted Space cannot leave a stale config behind.

Retry classification is deliberate, because not every failure deserves another
try:

| Failure | Retried? | Why |
|---|---|---|
| 502 / config fetch / connection | **yes** | The Space is flapping; the next attempt often lands on a healthy replica. |
| Quota exceeded | no | Will not pass on a retry; retrying only makes the user wait longer. |
| Timeout | no | The next attempt would blow the same budget again. |
| `TypeError` (bad call signature) | no | That is our bug, not a flaky upstream. |

The budget was tuned against real behaviour, not guessed: an initial
3-attempt/4s-backoff budget gave up after ~26s while the Space was still
failing. It is now 4 attempts with 10s linear backoff (~60s of waiting), which
is why the UI surfaces elapsed time and says the GPU may be waking up.

**Validate the provider's output.**
A truncated download or an HTML 502 page saved with a `.glb` extension would
sail past a size check and fail confusingly in the browser. `validate_glb`
parses the container: magic bytes, version, declared-vs-actual length, JSON
chunk, and at least one primitive with `POSITION` data. Failure returns a
controlled 502; the API never reports success for an asset it could not verify.

**Two bugs worth naming**, both found by testing rather than review.

*The timeout did nothing.* `anyio.to_thread.run_sync` shields its worker thread
from cancellation by default, so `fail_after` never fired and a hung Space
would have hung the request indefinitely. The fix is `abandon_on_cancel=True`,
and `test_provider_timeout_is_not_retried` fails without it.

*The authenticated path was never exercised.* `gradio_client` 2.x renamed
`Client(hf_token=...)` to `token=`. Because the token branch only runs when
`HF_TOKEN` is set, every anonymous test passed while the configured-token path
raised `TypeError` on the first real call. The lesson is the general one —
**a conditional branch that only runs in production is untested by
default** — so it is now covered two ways: a test asserting the kwarg exists on
`Client.__init__` (so a dependency bump fails loudly), and a `TypeError` guard
that refuses to retry our own signature errors.

---

## Error handling

Every failure has one owner and one message. The frontend only ever reads
`{ success, error }`.

| Failure | Status | What the user sees |
|---|---|---|
| Empty / whitespace prompt | 422 | "Please describe the object you want to create." (caught client-side too, so no round trip) |
| Prompt too long (>300) | 422 | "Prompt must be 300 characters or fewer." |
| Unsupported characters | 422 | "Prompt contains unsupported characters." |
| Provider asleep / unreachable | 502 | "The generation service is unavailable" |
| Provider quota exhausted | 502 | "The generation service is busy right now" |
| Provider timeout | 502 | "Generation took too long" |
| Asset failed validation | 502 | "The generated model could not be loaded" |
| Too many requests | 429 | "Too many generations from this client." + `Retry-After` |
| Anything unexpected | 500 | "Something went wrong" (detail logged, never returned) |

**The rule that matters most:** if a generation fails while a valid model is
already on screen, the model stays. The error appears as a banner beneath the
viewer rather than replacing it — losing work you already have is worse than
the failure itself.

Internal detail never reaches the client; provider messages and stack traces go
to logs, and a test asserts a secret in an exception body does not appear in
the response.

---

## Running locally

Two terminals. Python 3.11+ and Node 20+.

**1. Backend**

```bash
cd backend
python -m venv .venv
```

```bash
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate
```

```bash
pip install -r requirements-dev.txt
cp .env.example .env    # then paste your HF_TOKEN into it
uvicorn app.main:app --reload --port 8000
```

API docs: <http://localhost:8000/docs> · Health: <http://localhost:8000/api/health>

**2. Frontend**

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

Open <http://localhost:3000>.

**Tests**

```bash
cd backend && .venv/Scripts/python -m pytest -q
```

```bash
cd frontend && npm run typecheck && npm run build
```

---

## Demo assets

Formly ships a small set of pre-generated example GLB assets so the 3D
experience remains demonstrable when the free external inference provider is
temporarily unavailable.

They exist because live generation depends on Hugging Face's **free ZeroGPU
capacity**, which is shared and exhausts after a modest number of generations.
When it is spent, every generation returns a controlled error — and without
examples, someone opening the app would have nothing to look at.

**They are not a fallback AI provider.** Nothing is generated when you click
one. Each file was produced earlier by the same Shap-E provider the live app
uses, then committed and served as a static file:

| Example | Triangles | Size |
|---|---|---|
| Japanese Pagoda | 115,712 | 2.2 MB |
| Cyberpunk Helmet | 214,268 | 4.1 MB |

They are deliberately real Shap-E output rather than hand-modelled meshes. An
example should show what this product actually produces — blobby vertex colours
included. A clean hand-made asset would flatter the model.

**How the distinction is kept honest:**

- Selecting an example **never calls `/api/generate`**.
- The viewer badge reads **"Example model"**, versus **"Generated with AI"**.
- The stats line reads `pre-generated example` instead of a fabricated timing.
- Downloads are named `formly-example-<id>.glb`.
- A failed generation keeps whatever is on screen, and an example stays
  labelled as an example — it is never relabelled as a new result.

Assets are fetched **on demand**, not at page load, so the initial bundle is
unaffected (109 kB first load).

### Adding more examples

Generate one with the running app (or the provider directly), drop the `.glb`
into `frontend/public/examples/`, and add an entry to
`frontend/lib/examples.ts`. Tests in `backend/tests/test_example_assets.py`
validate the file is real GLB and that the manifest's stated size and triangle
count match the bytes on disk, so drift fails loudly.

Note that the root `.gitignore` excludes `*.glb`; the examples directory is
explicitly re-included, which is what keeps them present in production.

---

## The HF token

Generation works without a token, but barely: anonymous calls share a small
per-IP ZeroGPU quota and in practice hit

```
You have exceeded your ZeroGPU quota (60s requested vs. 0s left).
```

after a handful of generations. Formly handles this correctly — it returns a
clean "the generation service is busy right now" rather than failing oddly —
but you will not get many models out of it.

1. Create a free account at <https://huggingface.co>.
2. Generate a **read** token at <https://huggingface.co/settings/tokens>.
3. Put it in `backend/.env` as `HF_TOKEN=hf_...`.

The token is read by the backend only and is never sent to the browser.

---

## Environment variables

Documented in [`.env.example`](.env.example) (root, annotated) and
[`backend/.env.example`](backend/.env.example).

| Variable | Where | Default | Purpose |
|---|---|---|---|
| `HF_TOKEN` | backend | *(none)* | Raises ZeroGPU quota. Secret. |
| `PROVIDER` | backend | `shap-e` | Provider to build: `shap-e` or `trellis`. |
| `HF_SPACE` | backend | `hysts/Shap-E` | Space backing the Shap-E provider. |
| `TRELLIS_SPACE` | backend | `prithivMLmods/TRELLIS.2-Text-to-3D` | Space used when `PROVIDER=trellis`. |
| `TRELLIS_RESOLUTION` | backend | `1024` | TRELLIS output resolution. |
| `TRELLIS_MAX_ATTEMPTS` | backend | `2` | Fewer than Shap-E: each attempt costs ~240 GPU-s. |
| `TRELLIS_TIMEOUT_SECONDS` | backend | `600` | Three sequential stages need a longer budget. |
| `INFERENCE_STEPS` | backend | `64` | Shap-E sampling steps. |
| `GUIDANCE_SCALE` | backend | `15.0` | Prompt adherence. |
| `PROVIDER_MAX_ATTEMPTS` | backend | `4` | Retries for a flapping Space. |
| `PROVIDER_BACKOFF_SECONDS` | backend | `10.0` | Linear backoff between retries. |
| `PROVIDER_TIMEOUT_SECONDS` | backend | `300` | Hard cap per generation. |
| `ASSET_TTL_SECONDS` | backend | `3600` | How long a generated GLB is retrievable. |
| `MAX_STORED_ASSETS` | backend | `64` | Bound on the in-process store. |
| `CORS_ORIGINS` | backend | localhost:3000 | Exact allowed origins, comma separated. |
| `RATE_LIMIT_REQUESTS` | backend | `10` | Generations per IP per window. |
| `NEXT_PUBLIC_API_BASE_URL` | frontend | localhost:8000 | Backend base URL. Public by design. |

---

## Deployment

**Backend → Render (free).** [`render.yaml`](render.yaml) is a working
blueprint. Point Render at the repo, then set `HF_TOKEN` and `CORS_ORIGINS`
(the exact Vercel URL) in the dashboard. A [`Dockerfile`](backend/Dockerfile) is
included for Hugging Face Spaces or any container host.

**Frontend → Vercel (free).** Import the repo with root directory `frontend`;
[`vercel.json`](frontend/vercel.json) supplies the framework preset and security
headers. Set `NEXT_PUBLIC_API_BASE_URL` to the Render URL.

**Order matters:** deploy the backend first, set `NEXT_PUBLIC_API_BASE_URL`,
then deploy the frontend, then set `CORS_ORIGINS` to the real frontend origin
and redeploy the backend.

**Post-deploy checklist**

- [ ] `GET /api/health` returns `{"status":"ok","scope":"api-only",...}`
      (liveness of the API only — it does **not** confirm the GPU Space is up)
- [ ] A generation from the deployed UI returns a model
- [ ] The GLB loads in the viewer over HTTPS
- [ ] Download produces `formly-<slug>.glb`
- [ ] A cross-origin request from an unlisted origin is refused
- [ ] Tested from a clean browser session

**Cold starts compound.** On the free tier the Render instance sleeps after
~15 minutes *and* the HF Space sleeps independently. The first generation after
a quiet period can therefore take noticeably longer than the measured 10 s. The
provider's retry loop absorbs the Space's 502s; the UI shows elapsed seconds so
the wait is visible rather than mysterious.

---

## Scaling

Current design is one synchronous instance. The path to higher concurrency,
**not implemented here**:

```
Frontend → API → Job queue → GPU workers → Object storage
                     │
                     └── job status endpoint (UI polls)
```

For higher concurrency, generation should become asynchronous and move to a
worker-based architecture with object storage and job status tracking. The
current implementation stays synchronous because generation fits in a request
and the hosting constraints make that practical.

**What breaks first, in order:**

1. **Shared GPU quota.** The single hard ceiling. One public Space cannot serve
   many concurrent users; this needs dedicated inference (Replicate, fal, or
   self-hosted GPU workers) before anything else matters.
2. **Request-bound generation.** Long-held connections do not survive typical
   60 s platform proxy timeouts at scale → move to a queue + job status.
3. **In-process asset store.** Not shared between instances, so a second
   instance can 404 the first's asset → move to S3/R2 with presigned URLs.
4. **In-process rate limiter.** Per-process counters → move to Redis.

**For 1,000 concurrent users:** a queue, a pool of dedicated GPU workers,
object storage with a CDN in front of the GLBs, and a cache keyed on the
normalised prompt (identical prompts are common and generation is the expensive
part).

---

## Limitations

- **Not deployed yet** — runs locally; blueprints are ready.
- **Mesh quality is Shap-E's**: blobby, vertex-coloured, no clean topology.
  An alternative provider (`PROVIDER=trellis`) is implemented but is
  **experimental and unverified**, and costs ~4x the GPU quota per model; see
  [Provider evaluation](#provider-evaluation).
- **The free ZeroGPU quota is the real ceiling.** It is shared across every
  Space and exhausts after a modest number of generations, after which *all*
  providers fail with "generation temporarily unavailable". This is the single
  biggest practical constraint on the product, and it is why the cheaper model
  is the default. The [demo assets](#demo-assets) keep the 3D experience
  usable when it happens, but they do not restore live generation.
- **Only two demo assets ship.** More were intended, but the GPU quota was
  exhausted before they could be generated, and hand-made substitutes would
  misrepresent the model's real output. Adding more is a two-step change
  documented above.
- **The TRELLIS provider has not been run live end to end** — unit-tested
  against a mocked client only, because the quota ran out during evaluation.
- **No generation history** — a reload loses the model; assets expire after an
  hour. This is a product decision, not an oversight.
- **Single instance assumed.** The asset store and rate limiter are per-process.
- **Rate limiting is by IP**, so users behind one NAT share a bucket. It is an
  abuse guard, not a security control.
- **No auth, no payments** — out of scope by design.
- **Frontend tests are typecheck + build plus manual browser verification**;
  there is no Playwright/RTL suite. The UI states were verified in a real
  browser (see below), but that is not automated.
- **`npm audit` reports advisories in transitive build-time dependencies** of
  Next.js (`postcss`). `npm audit fix --force` would downgrade Next and break
  the build; these are not runtime-exposed. Next itself is pinned to **15.5.26**,
  which patches CVE-2025-66478 (15.1.6, the version originally installed, is
  vulnerable).

---

## What was actually verified

Claims in this README that were executed, not assumed:

### The full flow, in a browser

Typing *"A small Japanese pagoda"* and pressing Generate produced a recognisable
tiered pagoda — three roofs, a spire and a base platform, with Shap-E's vertex
colours intact — rendered live in the viewer:

- **Generated in 13.9 s**: 115,712 triangles, 2.2 MB.
- **Rotate** (drag) and **Reset View** both behaved correctly; reset restored
  the original three-quarter framing.
- **Download** fetched cross-origin from the browser returned HTTP 200,
  `model/gltf-binary`, `attachment; filename="formly-small-japanese-pagoda.glb"`,
  2,315,368 bytes, valid glTF 2.0 with a declared length matching the payload.
- **A failed generation did not destroy the existing model.** With the backend
  stopped, clicking Generate again left the pagoda rendered and the download
  link live, showing the error as a banner beneath the viewer — the behaviour
  the brief calls for, verified deliberately rather than assumed.

### Everything else

- **Backend: 95 tests pass** (`pytest`) — prompt validation, provider failure,
  quota, timeout, signature errors, invalid-asset fail-closed, store
  TTL/eviction, filename sanitisation, rate limiting, CORS, error-envelope
  shape, and the `gradio_client` kwarg contract.
- **A second real generation** via the API: 17.69 s, 84,102 vertices / 168,244
  triangles / 3.37 MB; the render and download endpoints returned
  byte-identical payloads with correct headers.
- **Validator accepts real provider output** and rejects an HTML 502 page, a
  JSON error body, a truncated file and a mesh with no `POSITION`.
- **Viewer interactions measured from the canvas** (against real Shap-E
  output): model fills 65.6% of viewport height; zoom in 359 px → 516 px and
  out to 195 px; pan moved the centroid 421 → 591 px; **Reset restored framing
  exactly** (318×359 → 318×359).
- **UI states** — empty, filled-from-example (does not auto-generate), loading,
  error with "Try Again" — verified in-browser against the running backend.
- **Mobile at 375×812**: no horizontal overflow.
- **Production build succeeds**; first load 108 KB with three.js lazy-loaded.

**Still not verified:** the same flow through a *deployed* stack, since
deployment is pending. Fullscreen was implemented but not exercised in the
embedded test browser.

---

## Future improvements

Not implemented:

- Asynchronous job processing with a queue and status polling
- Dedicated GPU workers
- Object storage (S3/R2) + CDN for generated assets
- Generation history
- Model selection in the UI (the provider seam already supports it)
- Prompt-keyed caching
- Higher concurrency (see [Scaling](#scaling))
- Automated frontend and end-to-end test suites

---

## Project structure

```
formly/
├── backend/
│   ├── app/
│   │   ├── main.py                      # app factory, CORS, error envelope
│   │   ├── config.py                    # settings
│   │   ├── routes/{generation,health}.py
│   │   ├── schemas/generation.py        # Pydantic request/response
│   │   └── services/
│   │       ├── store.py                 # TTL asset store
│   │       ├── naming.py                # filename sanitisation
│   │       ├── rate_limit.py
│   │       └── generation/
│   │           ├── base.py              # GenerationProvider + errors
│   │           ├── hf_space.py          # shared Space failure classification
│   │           ├── shap_e.py            # default provider (1 call -> GLB)
│   │           ├── trellis.py           # opt-in provider (3 stages -> GLB)
│   │           ├── registry.py          # provider selection
│   │           └── validator.py         # GLB structural validation
│   ├── tests/                           # 95 tests
│   └── Dockerfile
├── frontend/
│   ├── app/{layout,page}.tsx
│   ├── components/
│   │   ├── ModelViewer.tsx              # R3F canvas, framing, materials
│   │   ├── PromptInput.tsx
│   │   ├── ExamplePrompts.tsx
│   │   ├── ViewerControls.tsx
│   │   ├── GenerationState.tsx
│   │   └── EmptyState.tsx
│   └── lib/{api,types,format}.ts
├── render.yaml
└── .env.example
```

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
  "generation_seconds": 10.4,
  "vertex_count": 107106,
  "triangle_count": 214268,
  "byte_size": 4285948
}
```

Errors are always `{ "success": false, "error": "<message>" }`.

`GET /api/models/{id}.glb` — the asset, for rendering
`GET /api/models/{id}/download` — the asset, as an attachment
`GET /api/health` — liveness of **this API only**. It deliberately does not
probe the provider, so a 200 does not mean generation currently works:

```json
{
  "status": "ok",
  "scope": "api-only",
  "format": "glb",
  "provider": { "name": "shap-e", "space": "hysts/Shap-E", "upstream_health": "not_checked" }
}
```
