"""Low-cardinality process metrics tests."""

from chakravyuh.observability import ProcessMetrics


async def test_prometheus_metrics_are_bounded_escaped_and_cumulative() -> None:
    metrics = ProcessMetrics(version='0.10.0"dev', environment="test\nlab", actions_enabled=True)
    await metrics.observe(
        method="get",
        route="/v1/operator/incidents/{incident_id}",
        status=200,
        duration_seconds=0.02,
    )
    await metrics.observe(
        method="get",
        route="/v1/operator/incidents/{incident_id}",
        status=200,
        duration_seconds=0.2,
    )
    await metrics.observe(method="post", route="raw-secret", status=500, duration_seconds=-1)
    await metrics.observe(
        method="attacker-method",
        route="/health/live",
        status=999,
        duration_seconds=0,
    )

    body = await metrics.render_prometheus()

    assert 'version="0.10.0\\"dev"' in body
    assert 'environment="test\\nlab"' in body
    assert "chakravyuh_actions_enabled 1" in body
    assert (
        'chakravyuh_http_requests_total{method="GET",'
        'route="/v1/operator/incidents/{incident_id}",status="200"} 2'
    ) in body
    assert 'route="unmatched",status="500"} 1' in body
    assert 'method="OTHER",route="/health/live",status="0"} 1' in body
    assert 'le="0.025"} 1' in body
    assert 'le="0.25"} 2' in body
    assert 'le="+Inf"} 2' in body
    assert "raw-secret" not in body
    assert "attacker-method" not in body
