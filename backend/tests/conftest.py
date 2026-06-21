import os

# Keep the unit suite hermetic regardless of a developer's local .env: environment
# variables take precedence over the .env file in pydantic-settings, so pin the
# integration toggles off here before the app (and its cached Settings) load.
os.environ["USE_DATABASE"] = "false"
os.environ["USE_QDRANT"] = "false"
os.environ["USE_BACKGROUND_WORKER"] = "false"
os.environ["USE_AGNO"] = "false"
os.environ["REQUIRE_AUTH"] = "false"
# Keep the MinerU sidecar out of the hermetic suite (no netstat/taskkill, no spawn).
os.environ["MINERU_API_AUTOSTART"] = "false"
os.environ["PHOENIX_ENDPOINT"] = ""
# Point the LLM at an unreachable endpoint so synthesis deterministically uses
# its extractive fallback in unit tests (live LLM behaviour is covered by e2e).
os.environ["LITELLM_BASE_URL"] = "http://127.0.0.1:9/v1"
os.environ["SYNTHESIS_TIMEOUT_SECONDS"] = "0.1"
