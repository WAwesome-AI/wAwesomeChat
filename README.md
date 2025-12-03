# wAwesomeChat

Foundational scaffolding for the wAwesomeChat experience powered by `wapyt==0.1.0`,
`pytincture==0.9.22`, and a LiteLLM-backed backend-for-frontend proxy.

The repository now ships:

- PEP 621 packaging and uv metadata wired to local clones of `wapyt` and `pytincture`.
- `.env`-driven configuration with sane defaults for SQLite development, optional
  Postgres overrides, and seedable provider credentials.
- A persistence layer (`wawesomechat.storage.ChatStorage`) for recording chat
  transcripts and securely storing provider metadata/API keys.
- The `MultiAIProxy` backend adopted from the original wapyt example so the UI can talk
  to multiple AI providers through LiteLLM streams.

> **Note:** Secrets are never committed to the repo. Keep real API keys in `.env`; the
> seeding utility reads from there and loads them into SQLite/Postgres when requested.

## Requirements

- Python 3.13+ (wapyt enforces 3.13, so pin it in uv).
- Local sibling clones for the framework dependencies:
  - `../wA_pytincture_widgetset` (exports `wapyt==0.1.0`).
  - `../pytincture` (exports `pytincture==0.9.22`).
- [`uv`](https://github.com/astral-sh/uv) for dependency management.
- `.env` file based on `.env.example` for API keys and database settings.

## Environment + dependency bootstrap

```bash
# From the repo root
uv python pin 3.13

# Optionally scope uv caches to the project to avoid permission surprises
export UV_CACHE_DIR="$(pwd)/.uv_cache"

# Install runtime + dev dependencies (local path overrides included)
uv sync

# Sanity check: load settings and ensure the proxy can instantiate
uv run python -c "from wawesomechat import settings_from_env, MultiAIProxy;\nprint(settings_from_env()); MultiAIProxy()"
```

## Configure `.env`

Copy `.env.example` to `.env` and update it with your secrets:

```bash
cp .env.example .env
```

Key variables:

- `WA_DB_URL` — Full SQLAlchemy URL. Omit to auto-create
  `sqlite:///./wawesomechat.db`. Works with Postgres URLs when the `postgres` extra is
  installed (`uv add --extra postgres .`).
- `WA_DEFAULT_MODEL` — Model the proxy should default to when widgets do not specify
  one explicitly.
- `WA_PROVIDER_CONFIG` — Optional JSON blob that overrides the baked-in provider/model
  catalog.
- `WA_SEED_PROVIDERS` — When set to `1`, `ChatStorage` (and the seed script) will pull
  any available API keys into the database automatically.
- `WA_SEED_FORCE` — When `WA_SEED_PROVIDERS` is enabled, set this to `1` to overwrite
  existing stored secrets.
- `WA_CHAT_SESSION` — Logical session identifier used for persisting chat transcripts
  (defaults to `local`).
- `WA_REQUEST_TIMEOUT` — Seconds before LiteLLM calls time out.
- Provider API keys such as `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `AWS_ACCESS_KEY_ID`,
  etc. (see `.env.example`).

The provided `.env.example` includes sample keys supplied for local testing—treat them as
secrets and rotate them before deploying anywhere public.

The package automatically calls `load_environment()` on import so ad-hoc scripts pick up
these values.

## Database helpers

`wawesomechat.storage.ChatStorage` wraps SQLAlchemy to store chat transcripts and
provider metadata. By default it creates `chat_messages`, `providers`, and
`provider_credentials` inside the SQLite file referenced by `.env`, but it also works
with Postgres or any SQLAlchemy-supported backend. The UI automatically persists every
user prompt + assistant response under the session key defined by `WA_CHAT_SESSION`. You
can also script against it directly:

```python
from wawesomechat import ChatStorage, settings_from_env

settings = settings_from_env()
storage = ChatStorage(settings.database)

for message in storage.history("local", limit=20):
    print(f\"[{message.created_at}] {message.role}: {message.content[:60]}\")
```

To populate the provider metadata tables from your `.env`, run:

```bash
uv run python -m wawesomechat.seed --force
```

## Container + Fly.io deployment

### Build and run with Docker

```bash
docker build -t wawesomechat .
# Ensure you have real secrets in src/wawesomechat/.env or export them manually.
docker run --rm -p 8080:8080 --env-file src/wawesomechat/.env wawesomechat
```

The container listens on `$PORT` (default `8080`). Update any SAML callback values in
`src/wawesomechat/.env` to match the host you expose.

### Deploy to Fly.io

1. [Install `flyctl`](https://fly.io/docs/flyctl/install/) and log in.
2. Launch the app (answer prompts as needed, Fly will reuse the committed `fly.toml`):

   ```bash
   fly launch --copy-config --no-deploy --name <your-app-name>
   ```

3. Mirror the SAML/database secrets from `src/wawesomechat/.env` into Fly:

   ```bash
   python3 scripts/push_fly_secrets.py --app <your-app-name>
   ```

   > **Tip:** Edit the `.env` values before running the script so the SAML URLs match
   > your Fly hostname (e.g., `https://<app>.fly.dev/chat/auth/saml/...`).

4. Deploy:

   ```bash
   fly deploy
   ```

Fly will build the Docker image, run `python -m wawesomechat.app`, and expose the service
on HTTPS automatically. Any additional environment variables you add to
`src/wawesomechat/.env` can be propagated with the same secret-sync script.

## Run the chat experience locally

The working UI from `wA_pytincture_widgetset/tests` now lives directly inside this
package. After syncing dependencies and configuring `.env`, launch it with:

```bash
uv run python -c "from wawesomechat import launch_app; launch_app()"
```

The PyTincture launcher will print a local URL; open it in your browser to access the UI.
Any provider credentials present in `.env`/SQLite are used automatically by the embedded
`MultiAIProxy`.

## Backend-for-frontend proxy

`wawesomechat.multiaiproxy.MultiAIProxy` (aliased as `multiaiproxy`) mirrors the behavior of
`tests/multiaiproxy.py` from `wA_pytincture_widgetset`. It relies on LiteLLM to stream
responses from OpenAI, Anthropic, AWS Bedrock, Google, and xAI. The proxy honors
configuration from `.env` and exposes the `@bff_stream` endpoints the wapyt chat widget
expects.

```python
from wawesomechat import MultiAIProxy

proxy = MultiAIProxy()
for chunk in proxy.chat_stream([
    {"role": "system", "content": "be helpful"},
    {"role": "user", "content": "Ping?"},
]):
    print(chunk)
```

## Project layout

```
.
├── pyproject.toml      # PEP 621 metadata, dependency graph, uv source overrides
├── README.md           # You are here
├── .env.example        # Template for local secrets and DB settings
└── src/
    └── wawesomechat/
        ├── __init__.py
        ├── app.py      # Launch helpers for the PyTincture UI
        ├── chat.py     # Primary UI
        ├── config.py   # .env loader + Settings dataclasses
        ├── multiaiproxy.py  # Backend-for-frontend LiteLLM proxy
        ├── seed.py     # Utility to seed provider metadata/credentials
        └── storage.py  # SQLAlchemy helpers for transcripts + provider data
```

## Suggested next steps

1. Surface stored transcripts inside the UI (e.g., history tab with reload/reset
   actions).
2. Add configuration surfaces for provider credentials/models so non-developers can
   update them without editing `.env`.
3. Extend the test suite to cover storage operations and proxy behavior using mocked
   LiteLLM responses.
