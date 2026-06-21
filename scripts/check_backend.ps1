$ErrorActionPreference = "Stop"

uv run pytest
uv run ruff check backend scripts
