# wAwesomeChat

Multi-provider AI chat app: a `wapyt` widgetset UI running in Pyodide, talking to LiteLLM-backed
BFF classes running server-side in CPython, persisting transcripts and provider credentials to
SQLite/Postgres. It is the first real consumer of the wapyt widgetset — the app that proves the
stack end to end.

## The three repos

```
pytincture/                 the framework — FastAPI server + Pyodide bootstrap + BFF machinery
wa_pytincture_widgetset/    the widgetset — `wapyt`, seven DHTMLX-free widgets (has its own CLAUDE.md)
wAwesomeChat/               this app — consumes both
```

Sibling clones under `~/Development/Pytinc/`. Each has a `CLAUDE.md`; read the widgetset's before
touching UI code and pytincture's before touching packaging, BFFs, or startup.

pyTincture picks the widgetset **from the app's imports** — `chat.py` does `from wapyt.layout import
MainWindow`, and `discover_widgetset` AST-parses that to the pin `wapyt==0.1.0`. There is no config
flag. That resolution needs a wapyt wheel in the modules folder and a hashed asset manifest; both
now exist, built by `wa_pytincture_widgetset/scripts/dev_wheel.sh`. See **Running** below.

`chat.py` must also declare `APP_ENTRYPOINT = "WAwesomeChat"`. pytincture resolves the browser
entrypoint by AST, and its MainWindow-subclass detection
(`pytincture/backend/pages.py:_main_window_base_names`) is **hardcoded to `dhxpyt.layout.MainWindow`**
— it never matches a wapyt base. The only remaining fallback is "top-level name == module name",
which `chat.py`/`WAwesomeChat` does not satisfy. Without the declaration, `/chat` returns HTTP 422
before any Python reaches the browser. Every wapyt app whose class name differs from its filename
hits this.

## Structure

```
src/wawesomechat/           ← this directory IS the pytincture modules_folder
  chat.py        1959 ln  MainWindow subclass + admin/users panels; also the launch entrypoint
  multiaiproxy.py  407 ln  @backend_for_frontend — LiteLLM streaming across 5 providers
  provider_admin.py 174 ln @backend_for_frontend — raw-sqlite3 provider CRUD
  provider_catalog.py 256  DEFAULT_PROVIDER_{CATALOG,SCHEMAS,SECRETS}; SQLite-first, CSV seeds
  storage.py       329 ln  SQLAlchemy: chat_messages / providers / provider_credentials
  config.py        115 ln  .env loader + Settings/DatabaseSettings dataclasses
  seed.py           39 ln  python -m wawesomechat.seed --force
  data/seed_providers.csv  5 providers, initial seed only
tests/                      CPython unit tests (storage + provider_admin BFF)
Containerfile               podman test image; build context is the PARENT dir
.containerignore            written for that parent context
scripts/
  podman_build.sh           builds the image
  podman_run.sh             runs it (--dev / --fg / --shell / --port / --rebuild)
  container_entrypoint.sh   normalizes WA_DB_FILE, optional wheel rebuild, execs app
  push_fly_secrets.py       mirrors .env into Fly secrets
```

`src/wawesomechat` is both a Python package *and* the modules folder pytincture serves. That dual
role is the single most important fact about this repo, and it drives the import convention below.

## Two runtimes, one directory

Every module here is imported under two different names depending on where it runs:

| | Browser (Pyodide) | Server (CPython) |
|---|---|---|
| `chat.py` | the app; `MainWindow` subclass | `__main__`, calls `launch_service` |
| `multiaiproxy` / `provider_admin` | a generated stub, calls over HTTP | the real class, `@backend_for_frontend` |
| `storage` / SQLAlchemy | unavailable | real |

So `chat.py` uses **flat** imports (`from config import settings_from_env`) because pytincture
serves the modules folder flat, while `multiaiproxy.py`, `provider_admin.py` and
`provider_catalog.py` use the `try: from .x / except ImportError: from x` dual form so they work
both ways. `chat.py` does not — it is flat-only, which is why `__init__.py` wraps
`from .chat import WAwesomeChat` in a bare `except` and silently sets it to `None`.

Consequence worth internalising: **`import wawesomechat` succeeding tells you almost nothing.**
`__init__.py` swallows every failure in `chat.py` and the (nonexistent) `app.py`. Backend import
failures inside `chat.py` are swallowed too — `OpenAIProxy = None` and `ChatStorage = None` just
degrade the UI to a local echo responder with no persistence, logging a warning. If chat "works"
but only echoes, the proxy import failed; check `_PROXY_IMPORT_ERROR`. (In the browser `ChatStorage`
is *always* `None` — see **Broken features** below.)

A working send looks like this in the network log:
`POST /chat/classcall/multiaiproxy.py/multiaiproxy/chat_stream`. Backend failures come back
**in-band** and render as an assistant message, e.g. "Backend error: litellm.AuthenticationError:
BedrockException Invalid Authentication" — that is the proxy working correctly with bad credentials,
not a wiring problem.

## Running

Verified working end-to-end on 2026-09-17 (Chromium, real Pyodide boot to `ready`).

```bash
# one-time: build the wapyt dev wheel into the modules folder
cd ../wa_pytincture_widgetset && ./scripts/dev_wheel.sh ../wAwesomeChat/src/wawesomechat

# run
cd ../wAwesomeChat && uv run --directory src/wawesomechat chat.py   # → http://localhost:8070/chat

# unit tests (CPython only, no browser)
uv run --extra dev pytest tests/   # `--extra`, not `--group`: dev is an optional-dependency
```

Rebuild the wheel after **any** edit under `wa_pytincture_widgetset/wapyt/assets/` — pytincture
hash-verifies every asset against the wheel's manifest, so a stale wheel fails closed at
`widgetset-load`. `dev_wheel.sh` regenerates the manifest as part of the build.

`uv` is at `/home/linuxbrew/.linuxbrew/bin/uv` (Homebrew). Host Python is 3.14.7.

### Podman (test container)

```bash
scripts/podman_run.sh              # build if needed, run → http://127.0.0.1:8070/chat
scripts/podman_run.sh --dev        # bind-mount source; edits are live
scripts/podman_run.sh --fg         # foreground, logs to stdout
scripts/podman_run.sh --shell      # shell in the image instead of the app
scripts/podman_build.sh --no-cache # clean rebuild
```

Verified booting to `ready` in Chromium from the container on 2026-09-17, in both normal and
`--dev` mode. Image is ~446 MB.

Four things about this setup are non-obvious enough to be worth knowing before editing it:

- **The build context is the parent directory**, not this repo. `[tool.uv.sources]` resolves wapyt
  and pytincture from sibling checkouts, so the image reproduces the workspace under `/workspace`.
  `podman_build.sh` stages `.containerignore` into the context root and restores it afterwards.
- **`localhost` does not work — use `127.0.0.1`.** It resolves to `::1` first on this host, and
  rootless podman's pasta networking does not forward IPv6 loopback, so a plain
  `--publish 8070:8070` leaves the port dead from the host while it answers fine inside the
  container. The script publishes `127.0.0.1:8070:8070` explicitly.
- **`--env-file` overrides image `ENV`.** `.env.example` ships a *relative* `WA_DB_FILE`, which
  config.py resolves under the package directory — so it silently beat the Containerfile's
  `/data/...` default and put the database in the container's writable layer with the volume
  mounted and empty. The entrypoint now rewrites a relative `WA_DB_FILE` onto `/data`.
- **Never set `ENABLE_USER_LOGIN`+`ENABLE_DEV_EMAIL_LOGIN` or
  `PYTINCTURE_ALLOW_DEVELOPMENT_AUTH_ORIGIN` in the container.** pytincture's
  `_loopback_bind_host()` forces a `127.0.0.1` bind when development auth is on, which from inside
  a container means the published port answers nothing.

Secrets are never baked into a layer — `.containerignore` excludes `.env`, and credentials arrive
through `--env-file` at run time. The entrypoint prints which provider keys are *present* (never
values), because a bad env-file otherwise surfaces much later as an in-band LiteLLM auth error
rendered as a chat message, which reads like an app bug.

Port 8070 is not configurable from the environment: `chat.py` calls `launch_service()` with no port
argument and pytincture never reads `PORT`. The old `Dockerfile`'s `ENV PORT=8080` and `fly.toml`'s
`PORT = '8070'` are both inert. Remap on the host with `--port`.

The `Dockerfile` + `fly.toml` deploy path is still broken and untouched — see **README vs. reality**.
Point it at the Containerfile when you next touch deployment.

### Debugging a browser-side failure

Server logs show almost nothing useful — the app runs in Pyodide. pytincture emits a
`pytincture:lifecycle` event on `window` with stages `preflight → runtime-load → package-install →
widgetset-install → widgetset-load → archive-download → archive-unpack → entrypoint-execution →
ready`. The failing stage names the layer:

| Stage that fails | Look at |
|---|---|
| `widgetset-install` | missing/stale dev wheel in the modules folder |
| `widgetset-load` | asset manifest drift — rebuild the wheel |
| `entrypoint-execution` | the app's own Python; the page error carries the full traceback |

A headless check is in this repo's scratch history: drive Chromium with Playwright, capture
`window.__lc`, and read `pageerror` for the traceback. That is the only way to see the real cause —
an HTTP 200 on `/chat` says nothing about whether the app booted.

## Configuration

`.env` keys, all read through `config.py`:

| Key | Default | Notes |
|---|---|---|
| `WA_DB_URL` | — | full SQLAlchemy URL; overrides `WA_DB_FILE` |
| `WA_DB_FILE` | `wawesomechat.db` | relative names resolve under `src/wawesomechat/`, not the repo root |
| `WA_DB_ECHO` / `WA_DB_POOL_SIZE` | `false` / — | |
| `WA_DEFAULT_MODEL` | `gpt-4o-mini` | model the selector starts on for a first-ever visit; also the proxy's fallback. Reaches the browser via `multiaiproxy.get_default_model()` — `os.getenv` is empty in Pyodide, so it cannot be read client-side |
| `WA_REQUEST_TIMEOUT` | `60.0` | LiteLLM call timeout |
| `WA_PROVIDER_CONFIG` | — | JSON catalog override; invalid JSON prints and falls back silently |
| `WA_CHAT_SESSION` | `local` | transcript session key |
| `WA_SEED_PROVIDERS` / `WA_SEED_FORCE` | `1` / `0` | pull `.env` keys into the DB / overwrite existing |
| `WA_LITELLM_DEBUG` | `0` | |
| `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `AWS_*`, `GEMINI_API_KEY`, `XAI_API_KEY` | — | see `.env.example` |

**Three different `.env` locations are in play and they disagree.** `config.py` resolves
`DEFAULT_ENV_FILE` to `src/.env` (`PACKAGE_ROOT.parent`); `scripts/push_fly_secrets.py` defaults to
`src/wawesomechat/.env`; `.env.example` ships at the repo root. Only the first is what the app
actually reads. `WA_ENV_FILE` overrides it — set that rather than guessing.

## README vs. reality

`README.md` describes an intended shape that the code has since diverged from. Verified gaps — do
not trust the README on these. Items marked ✅ were fixed on 2026-09-17; the README still describes
the old state.

- ✅ **wapyt path case** — `[tool.uv.sources]` pointed at `../wA_pytincture_widgetset`; the directory
  is lowercase, so `uv sync` could not resolve wapyt on Linux. Fixed, and a
  `pytincture = { path = "../pytincture" }` source was added: a bare `>=0.9.25` pin will not select
  the local `1.0.0rc5` pre-release from PyPI, so the app was silently resolving an older published
  pytincture than the widgetset was being built against.
- ✅ **`.env` location** — `config.py` reads `src/.env`; that file now exists (copied from
  `.env.example`). Add real provider keys there.
- ✅ **Pyodide import break** — `config.py` imported `dotenv` unconditionally, which does not exist
  in the browser, so `chat.py:55` killed startup at `entrypoint-execution`. `load_dotenv` is now
  soft-imported to a no-op; there is no filesystem `.env` in Pyodide anyway. Note `provider_catalog`
  also reaches `config`, so guarding only `chat.py` would not have been enough.
- **`app.py` does not exist.** `launch_app` and `get_modules_path` are therefore `None`, and the
  README's `uv run python -c "...launch_app()"` fails. The real entrypoint is `chat.py`'s
  `__main__` block.
- **Version pins are three-way inconsistent**: README says `pytincture==0.9.22`, `pyproject.toml`
  says `pytincture>=0.9.25`, the local checkout is `1.0.0rc5`. The uv source override papers over
  this; the declared pin is still wrong.
- **Port mismatch**: `Dockerfile` sets `PORT=8080` and `EXPOSE 8080`; `fly.toml` sets `PORT=8070`
  and `internal_port = 8070`.
- **The container cannot run as built**: `.dockerignore` excludes both `.env` and the wapyt dev
  wheel, and the Dockerfile never runs `uv sync`.
- README's "suggested next step" #2 (provider/model config surfaces) is **already built** —
  `_build_admin_panel`, `_build_users_panel`, and the `provider_admin` BFF.
- README claims `.env.example` "includes sample keys supplied for local testing". It does not; every
  value is blank. Nothing needs rotating.

## Voice input (STT)

Two modes, local, no cloud — the same split Pantheon uses:

- **Hold-to-talk** (🎤): press and hold, release to transcribe. Text lands in the composer and is
  **not** sent; you are already at the keyboard, so a misheard word is easier to fix first.
- **Continuous** (latching toggle): open mic, RMS energy VAD segments on ~800ms of silence, each
  utterance transcribed and **auto-submitted**. The point is not touching the keyboard at all.

Live/interim transcription was built and then removed: whisper re-transcribes from the start on
every call, so earlier words visibly rewrote themselves mid-sentence. Don't reintroduce it without
a streaming engine.

**This app is STT-only by design — no TTS.** That is not an omission, it is what keeps the feature
simple. Every hard problem in Pantheon's voice stack (half-duplex gating, deferred barge-in,
`looksSelfHeard`, echo suppression — its mic hears its own TTS at +26 dB over the noise floor)
exists *only* because the assistant speaks. With nothing playing back, none of it applies. It also
means no VAD is needed: holding the button already delimits the utterance. Adding TTS later would
drag all of that back in.

```
stt.py          @backend_for_frontend -- faster-whisper base.en, CPU int8
chat.py         handle_voice() -> _transcribe() -> apply_transcript(submit=continuous)
Containerfile   bakes the model at /app/models/whisper (141MB) and sets
                PYTINCTURE_PERMISSIONS_POLICY to allow microphone=(self)
```

Adapted from `~/Development/ai_ecosystem/companion/services/stt.py`, which solved this first.
CPU int8 is deliberate: LM Studio is usually holding most of the 12GB of VRAM, and `base.en`
transcribes a 4-second clip in about **1 second** on CPU. faster-whisper bundles ffmpeg via PyAV,
so the browser's WebM/Opus decodes with no system codec.

| Env | Default | Notes |
|---|---|---|
| `WHISPER_MODEL` | `base.en` | `.en` models are English-only; `stt.py` drops any `language` for them |
| `WHISPER_DEVICE` / `WHISPER_COMPUTE` | `cpu` / `int8` | |
| `WHISPER_CACHE` | `/app/models/whisper` | baked at build time, so no cold-start download |
| `WA_STT_MAX_BYTES` | 8 MiB | guard before base64-decoding |

**Transport.** Audio is base64 over the normal `classcall` BFF, because that transport is JSON.
`BFF_REQUEST_MAX_BYTES` defaults to 1 MiB; after base64's 4/3 inflation that is roughly four
minutes of Opus, and the widget caps a take at `voice_max_seconds` anyway. Raise the env var if
that ever bites.

**The blocker to remember:** pytincture ships `Permissions-Policy: microphone=()`, which blocks
`getUserMedia` outright. The Containerfile sets `PYTINCTURE_PERMISSIONS_POLICY` to allow
`microphone=(self)`. Running outside the container, export it yourself or the mic button disables
itself. `http://127.0.0.1` is a secure context; `http://<lan-ip>` is not.

Image cost: ~446MB → **969MB** (ctranslate2 + PyAV + the model). The documented escape hatch, if
this ever needs to shrink or go faster, is a GPU whisper container on `ai-net` with `WHISPER_*`
pointed at it.

## Model selection

The selector resolves: active chat's model → last explicit pick (`localStorage`
`wawesomechat:lastModel`) → `WA_DEFAULT_MODEL` → first entry in the catalogue. Before
2026-09-17 only the first and last existed, so a fresh browser profile always landed on AWS
Bedrock regardless of configuration.

Two things had to be fixed for `WA_DEFAULT_MODEL` to work at all: `chat.py` read
`CHAT_DEMO_DEFAULT_MODEL` (a leftover from the demo) rather than the documented setting, and it
read it with `os.getenv` from **browser** code, where the environment is empty — so it only ever
returned the hardcoded fallback. It now comes over the BFF in `_ensure_proxy()`, which runs
before `add_chat()`, so the value is present when `ChatConfig` is built.

## Broken features found by running it

Confirmed in a real browser on 2026-09-17.

**Transcript persistence does not work, and cannot in this design.** `chat.py` imports `ChatStorage`
from `storage.py` — a server-side SQLAlchemy module — inside a try/except at module level. SQLAlchemy
is not available in Pyodide and nothing micropip-installs it, so in the browser `ChatStorage` is
`None`, `_init_storage` logs "persistence disabled", and every `_persist_message` call is a no-op.
Verified: after a full send/response round-trip, `chat_messages` held 0 rows while `providers` held
the 5 seeded records (those go through the `provider_admin` BFF, which runs server-side). The README
claim that "the UI automatically persists every user prompt + assistant response" is false.
The fix is to expose persistence as a BFF exactly like `provider_admin` — a `@backend_for_frontend`
class with `record_message`/`history` — so the server owns the database. That is a design change,
not a config fix.

**Icons rendered as literal text** — *fixed 2026-09-17 in the widgetset.* Button labels overwrote
their own buttons and each other because wapyt drew Material Symbols ligature spans whose font was
CSP-blocked. Icons now resolve through `wapyt/assets/icons.js` onto the MDI font pytincture already
serves. Rebuild the dev wheel to pick it up. See the widgetset CLAUDE.md, *Icons: MDI only*.

## Known rough edges

Context for when these surface, not a fix list:

- **Two provider-admin backends with the same method names.** `multiaiproxy.get_provider_snapshot /
  save_provider / delete_provider` (SQLAlchemy, works on any backend) and the whole `provider_admin`
  class (raw `sqlite3`, SQLite-only) duplicate the surface. `chat.py` prefers `provider_admin` via
  `_provider_backend_call` and falls back to the proxy. Changing provider persistence means
  changing both, and `provider_admin` silently does nothing on Postgres.
- **`SYSTEM_PROMPT` (`chat.py:59-219`) is ~160 lines of stale copy** for a different stack: it
  documents `dhxpyt` widgets, embeds a `@pytincture/runtime@0.9.22` CDN page, and contains directly
  contradictory Pyodide advice (an `asyncio.run` example immediately followed by "do NOT use
  `asyncio.run()`"). It ships to the model on every request in a wapyt app.
- **`asyncio.run` is fatal in Pyodide** — it closes the WebLoop for the session. This file correctly
  uses `asyncio.ensure_future`; keep it that way, and note the system prompt tells the *model*
  otherwise.
- **Streaming failures arrive in-band** as `{"error": {...}}` chunks rather than raising.
  `Chat.consume_stream` converts those to `ChatStreamError`; any new stream consumer needs the same
  check or failures render as an empty assistant message.
- `dt.datetime.utcnow()` is used in three places and is deprecated in 3.13.
- `provider_admin` has `print()` debug statements on the snapshot path.
- The default SQLite file lands inside the package dir (`src/wawesomechat/wawesomechat.db`), which
  is also the served modules folder.
- `git log` is two commits deep; there is no history to mine for intent.

## Security notes inherited from the widgetset

The escaping rules in `wa_pytincture_widgetset/CLAUDE.md` are load-bearing here, because this app is
what feeds model output into those widgets: artifact chips carry a per-widget nonce so model output
that merely *looks* like a chip is still escaped, and artifact previews are
`<iframe sandbox="allow-scripts">` — never add `allow-same-origin`. Provider API keys live in
`provider_credentials` with an `is_secret` flag; never log them or echo them back through a BFF
response.
