"""Economic portfolio identity, oracle isolation, distribution, and hash tests."""

from collections import Counter

import pytest
from pydantic import ValidationError

from chakravyuh.domain.enums import EntityType, IncidentType
from chakravyuh.domain.recovery_arena import ArenaDatasetRole, create_recovery_arena_contract
from chakravyuh.simulation.recovery_portfolio import (
    ArenaObservedCase,
    ArenaPortfolioManifest,
    RecoveryPortfolio,
    generate_held_out_recovery_portfolio,
    generate_recovery_portfolio,
)


def _portfolio(seed_count: int = 2) -> RecoveryPortfolio:
    contract = create_recovery_arena_contract()
    return generate_recovery_portfolio(
        contract,
        dataset_role=ArenaDatasetRole.VALIDATION,
        seed_start=40_000,
        seed_count=seed_count,
    )


def test_portfolio_rekeys_opaque_cases_and_separates_observed_from_oracle() -> None:
    portfolio = _portfolio()

    assert portfolio.manifest.case_count == 30
    assert len({item.observed.case_id for item in portfolio.cases}) == 30
    assert len({item.observed.observed_case_sha256 for item in portfolio.cases}) == 30
    assert set(Counter(item.oracle.family.value for item in portfolio.cases).values()) == {2}
    for item in portfolio.cases:
        observed_json = item.observed.model_dump_json()
        assert "oracle" not in observed_json
        assert "recoverable" not in observed_json
        assert "expected_incident" not in observed_json
        assert "provider_plan" not in observed_json
        assert all(event.merchant_id == item.observed.merchant_id for event in item.observed.events)
        assert all(
            event.correlation_id == item.observed.correlation_id for event in item.observed.events
        )


def test_portfolio_rekeys_provider_entities_without_cross_case_collisions() -> None:
    portfolio = _portfolio()
    entity_owners: dict[tuple[EntityType, str], str] = {}

    for item in portfolio.cases:
        for event in item.observed.events:
            key = (event.subject.entity_type, event.subject.entity_id)
            previous = entity_owners.setdefault(key, item.observed.case_id)
            assert previous == item.observed.case_id
            if event.subject.entity_type is EntityType.PAYMENT:
                assert event.subject.entity_id.startswith("pay_")
            if event.subject.entity_type is EntityType.RAZORPAY_ORDER:
                assert event.subject.entity_id.startswith("order_")


def test_portfolio_marks_only_bounded_authorized_incidents_action_eligible() -> None:
    portfolio = _portfolio(seed_count=25)

    eligible = [item for item in portfolio.cases if item.oracle.action_eligible]
    assert eligible
    assert all(
        item.oracle.expected_incident_type is IncidentType.AUTHORIZED_NOT_CAPTURED
        and item.oracle.expected_affected_entity is not None
        and item.oracle.expected_affected_entity.entity_id
        == item.oracle.provider_plan.initial_state.payment_id
        and item.observed.merchant_policy.capture_enabled
        and item.oracle.payment_amount.amount_subunits
        <= item.observed.merchant_policy.maximum_capture_subunits
        for item in eligible
    )
    assert all(item.oracle.action_eligible for item in portfolio.cases if item.oracle.recoverable)


def test_portfolio_and_manifest_hashes_are_reproducible() -> None:
    first = _portfolio()
    second = _portfolio()

    assert first == second
    assert len(first.manifest.observed_cases_root_sha256) == 64
    assert len(first.manifest.oracle_cases_root_sha256) == 64
    assert first.manifest.observed_cases_root_sha256 != first.manifest.oracle_cases_root_sha256


def test_locked_held_out_portfolio_has_stable_scale_and_roots() -> None:
    portfolio = generate_held_out_recovery_portfolio()

    assert portfolio.manifest.case_count == 10_005
    assert portfolio.manifest.manifest_sha256 == (
        "00a7a5e66c1dc203a06548adaf186db5931ada9d9d1eb3a47ed8b733b2d27112"
    )
    assert portfolio.manifest.observed_cases_root_sha256 == (
        "172634169db73579a5004564fde0bf281d3ec9233a76840230ebc6164b0fc4a8"
    )
    assert portfolio.manifest.oracle_cases_root_sha256 == (
        "03f094697261edf808a3ef4e324c72da8d03280cf4b5016d4a992bf05fef65f6"
    )


def test_portfolio_retains_exact_amount_consistency() -> None:
    portfolio = _portfolio()

    for item in portfolio.cases:
        payment_id = item.oracle.provider_plan.initial_state.payment_id
        payment_amounts = {
            event.payload.get("amount")
            for event in item.observed.events
            if event.subject.entity_type is EntityType.PAYMENT
            and event.subject.entity_id == payment_id
        }
        assert payment_amounts == {item.oracle.payment_amount.amount_subunits}


@pytest.mark.parametrize(
    ("start", "count"),
    [(39_999, 1), (49_999, 2), (40_000, 0)],
)
def test_portfolio_rejects_out_of_partition_or_empty_ranges(start: int, count: int) -> None:
    contract = create_recovery_arena_contract()

    with pytest.raises(ValueError, match=r"partition|at least"):
        generate_recovery_portfolio(
            contract,
            dataset_role=ArenaDatasetRole.VALIDATION,
            seed_start=start,
            seed_count=count,
        )


def test_observed_case_rejects_oracle_fields_and_hash_tampering() -> None:
    observed = _portfolio(seed_count=1).cases[0].observed

    with pytest.raises(ValidationError, match="extra_forbidden"):
        ArenaObservedCase.model_validate({**observed.model_dump(), "recoverable": True})
    with pytest.raises(ValidationError, match="observed-case hash"):
        ArenaObservedCase.model_validate(
            {**observed.model_dump(), "observed_case_sha256": "f" * 64}
        )


def test_manifest_rejects_distribution_or_hash_tampering() -> None:
    manifest = _portfolio(seed_count=1).manifest

    with pytest.raises(ValidationError, match="family distribution"):
        ArenaPortfolioManifest.model_validate({**manifest.model_dump(), "family_counts": {}})
    with pytest.raises(ValidationError, match="manifest hash"):
        ArenaPortfolioManifest.model_validate(
            {**manifest.model_dump(), "manifest_sha256": "f" * 64}
        )
