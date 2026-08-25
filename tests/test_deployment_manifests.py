"""Production deployment manifest policy tests."""

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_ROOT = ROOT / "deploy" / "kubernetes"


def _documents() -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for path in sorted(MANIFEST_ROOT.glob("*.yaml")):
        if path.name == "kustomization.yaml":
            continue
        documents.extend(
            document
            for document in yaml.safe_load_all(path.read_text())
            if isinstance(document, dict)
        )
    return documents


def _named(kind: str, name: str) -> dict[str, Any]:
    return next(
        document
        for document in _documents()
        if document.get("kind") == kind and document["metadata"]["name"] == name
    )


def test_manifests_commit_no_secret_and_pin_versioned_images() -> None:
    documents = _documents()
    assert all(document.get("kind") != "Secret" for document in documents)
    workload_kinds = {"Deployment", "Job"}
    containers = [
        container
        for document in documents
        if document.get("kind") in workload_kinds
        for container in document["spec"]["template"]["spec"]["containers"]
    ]
    assert containers
    assert all(container["image"].endswith(":0.11.0") for container in containers)
    assert all(":latest" not in container["image"] for container in containers)


def test_every_workload_is_non_root_read_only_and_resource_bounded() -> None:
    workloads = [
        document for document in _documents() if document.get("kind") in {"Deployment", "Job"}
    ]
    assert len(workloads) == 6
    for workload in workloads:
        pod = workload["spec"]["template"]["spec"]
        assert pod["automountServiceAccountToken"] is False
        assert pod["securityContext"]["runAsNonRoot"] is True
        assert pod["securityContext"]["seccompProfile"]["type"] == "RuntimeDefault"
        for container in pod["containers"]:
            security = container["securityContext"]
            assert security["allowPrivilegeEscalation"] is False
            assert security["readOnlyRootFilesystem"] is True
            assert security["capabilities"]["drop"] == ["ALL"]
            assert set(container["resources"]) == {"requests", "limits"}


def test_api_has_zero_downtime_shape_and_dependency_readiness() -> None:
    api = _named("Deployment", "chakravyuh-api")
    container = api["spec"]["template"]["spec"]["containers"][0]

    assert api["spec"]["replicas"] == 3
    assert api["spec"]["strategy"]["rollingUpdate"]["maxUnavailable"] == 0
    assert container["startupProbe"]["httpGet"]["path"] == "/health/live"
    assert container["livenessProbe"]["httpGet"]["path"] == "/health/live"
    assert container["readinessProbe"]["httpGet"]["path"] == "/health/ready"
    assert _named("PodDisruptionBudget", "chakravyuh-api")["spec"]["minAvailable"] == 2


def test_production_config_fails_closed_and_network_is_default_deny() -> None:
    config = _named("ConfigMap", "chakravyuh-runtime")["data"]
    policies = {
        document["metadata"]["name"]
        for document in _documents()
        if document.get("kind") == "NetworkPolicy"
    }

    assert config["CHAKRAVYUH_ENVIRONMENT"] == "production"
    assert config["CHAKRAVYUH_RATE_LIMIT_BACKEND"] == "redis"
    assert config["CHAKRAVYUH_RAZORPAY_ACTIONS_ENABLED"] == "false"
    assert config["CHAKRAVYUH_TEST_CHECKOUT_ENABLED"] == "false"
    assert config["CHAKRAVYUH_TRUSTED_HOSTS"] != '["*"]'
    assert "default-deny" in policies
    assert "allow-dns" in policies
    assert "allow-runtime-dependencies" in policies


def test_migration_is_an_explicit_predeployment_job() -> None:
    migration = _named("Job", "chakravyuh-migrate-0-11-0")
    container = migration["spec"]["template"]["spec"]["containers"][0]

    assert migration["spec"]["backoffLimit"] == 2
    assert container["args"] == ["alembic", "upgrade", "head"]


def test_workloads_receive_only_their_secret_classes() -> None:
    expected = {
        ("Job", "chakravyuh-migrate-0-11-0"): {"chakravyuh-postgres-secrets"},
        ("Deployment", "chakravyuh-api"): {
            "chakravyuh-postgres-secrets",
            "chakravyuh-graph-secrets",
            "chakravyuh-rate-limit-secrets",
            "chakravyuh-operator-secrets",
            "chakravyuh-provider-secrets",
        },
        ("Deployment", "chakravyuh-worker"): {"chakravyuh-postgres-secrets"},
        ("Deployment", "chakravyuh-projector"): {
            "chakravyuh-postgres-secrets",
            "chakravyuh-graph-secrets",
        },
        ("Deployment", "chakravyuh-diagnosis"): {
            "chakravyuh-postgres-secrets",
            "chakravyuh-graph-secrets",
            "chakravyuh-model-secrets",
        },
        ("Deployment", "chakravyuh-web"): set(),
    }
    for (kind, name), expected_names in expected.items():
        container = _named(kind, name)["spec"]["template"]["spec"]["containers"][0]
        observed = {
            source["secretRef"]["name"]
            for source in container.get("envFrom", [])
            if "secretRef" in source
        }
        assert observed == expected_names


def test_web_image_accepts_the_api_origin_at_build_time() -> None:
    dockerfile = (ROOT / "apps" / "web" / "Dockerfile").read_text()

    assert "ARG NEXT_PUBLIC_API_BASE_URL=" in dockerfile
    assert "ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL" in dockerfile
