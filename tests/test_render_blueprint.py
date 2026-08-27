"""Safety contract for the zero-cost Render preview topology."""

from pathlib import Path

import yaml


def test_render_blueprint_uses_only_free_resources_and_secret_placeholders() -> None:
    blueprint = yaml.safe_load(Path("render.yaml").read_text())
    service = blueprint["services"][0]
    database = blueprint["databases"][0]

    assert service["type"] == "web"
    assert service["runtime"] == "docker"
    assert service["plan"] == "free"
    assert database["plan"] == "free"
    assert "chakravyuh-hosted" in service["dockerCommand"]
    assert service["healthCheckPath"] == "/health/live"

    sensitive_suffixes = {
        "_API_KEY",
        "_KEY_SECRET",
        "_PASSWORD",
        "_TOKEN_HASHES",
        "_PRINCIPAL_SCOPES",
        "_WEBHOOK_SECRET",
    }
    environment = {entry["key"]: entry for entry in service["envVars"]}
    for key, entry in environment.items():
        if any(key.endswith(suffix) for suffix in sensitive_suffixes):
            assert entry == {"key": key, "sync": False}


def test_render_blueprint_has_no_redis_dependency() -> None:
    blueprint_text = Path("render.yaml").read_text().lower()

    assert "redis://" not in blueprint_text
    assert "type: worker" not in blueprint_text
