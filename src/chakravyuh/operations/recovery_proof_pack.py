"""Build and verify the deterministic, revision-bound Recovery Arena proof pack."""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import html
import io
import json
import re
import shutil
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from chakravyuh.domain.recovery_arena import (
    ArenaStrategyName,
    RecoveryArenaContract,
    create_recovery_arena_contract,
)
from chakravyuh.simulation.recovery_baselines import (
    ArenaScoredCaseResult,
    run_baseline_tournament,
)
from chakravyuh.simulation.recovery_portfolio import (
    ArenaCaseFamily,
    RecoveryPortfolio,
    generate_held_out_recovery_portfolio,
)
from chakravyuh.simulation.recovery_tournament import (
    ArenaTournamentStrategyMetrics,
    ChakravyuhScoredCaseResult,
    RecoveryArenaTournamentReport,
    run_recovery_tournament,
)

PROOF_PACK_VERSION = "recovery-arena-proof-pack-v1"
CASE_RECORD_VERSION = "recovery-arena-proof-case-v1"
_CONTENT_FILES = ("cases.jsonl", "strategy-summary.csv", "index.html")
_CHECKSUM_FILES = (*_CONTENT_FILES, "manifest.json")
_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_REVISION_PATTERN = r"^[0-9a-f]{40}$"
_MAX_FILE_BYTES = 256 * 1024 * 1024


class ProofPackVerificationError(ValueError):
    """The proof pack failed a deterministic integrity or trust-anchor check."""


class ProofArtifact(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    sha256: str = Field(pattern=_SHA256_PATTERN)
    size_bytes: int = Field(ge=1, le=_MAX_FILE_BYTES)


class RecoveryProofCase(BaseModel):
    """One case binding observed input, hidden evaluation, all outcomes, and source revision."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    record_version: str = CASE_RECORD_VERSION
    case_index: int = Field(ge=0)
    case_id: str = Field(pattern=r"^case_[0-9a-f]{32}$")
    code_revision: str = Field(pattern=_REVISION_PATTERN)
    contract_sha256: str = Field(pattern=_SHA256_PATTERN)
    portfolio_manifest_sha256: str = Field(pattern=_SHA256_PATTERN)
    tournament_report_sha256: str = Field(pattern=_SHA256_PATTERN)
    observed_case_sha256: str = Field(pattern=_SHA256_PATTERN)
    oracle_case_sha256: str = Field(pattern=_SHA256_PATTERN)
    family: ArenaCaseFamily
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    payment_amount_subunits: int = Field(ge=0)
    action_eligible: bool
    recoverable: bool
    no_intervention: ArenaScoredCaseResult
    retry_all: ArenaScoredCaseResult
    chakravyuh: ChakravyuhScoredCaseResult
    case_binding_sha256: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_binding(self) -> RecoveryProofCase:
        result_ids = {
            self.no_intervention.case_id,
            self.retry_all.case_id,
            self.chakravyuh.case_id,
        }
        if result_ids != {self.case_id}:
            raise ValueError("proof-case strategy results must match the case identity")
        if self.no_intervention.strategy is not ArenaStrategyName.NO_INTERVENTION:
            raise ValueError("proof-case no-intervention result has the wrong strategy")
        if self.retry_all.strategy is not ArenaStrategyName.RETRY_ALL:
            raise ValueError("proof-case retry-all result has the wrong strategy")
        if _model_hash(self, exclude={"case_binding_sha256"}) != self.case_binding_sha256:
            raise ValueError("proof-case binding hash does not match its canonical content")
        return self


class RecoveryProofPackManifest(BaseModel):
    """Trust anchor for all human- and machine-readable proof artifacts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    proof_pack_version: str = PROOF_PACK_VERSION
    code_revision: str = Field(pattern=_REVISION_PATTERN)
    contract_sha256: str = Field(pattern=_SHA256_PATTERN)
    portfolio_manifest_sha256: str = Field(pattern=_SHA256_PATTERN)
    baseline_report_sha256: str = Field(pattern=_SHA256_PATTERN)
    tournament_report_sha256: str = Field(pattern=_SHA256_PATTERN)
    case_count: int = Field(ge=1)
    cases_root_sha256: str = Field(pattern=_SHA256_PATTERN)
    strategies: tuple[ArenaTournamentStrategyMetrics, ...]
    artifacts: dict[str, ProofArtifact]
    tournament_passed: bool
    proof_root_sha256: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_manifest(self) -> RecoveryProofPackManifest:
        if tuple(item.strategy for item in self.strategies) != tuple(ArenaStrategyName):
            raise ValueError("proof pack requires all strategies in canonical order")
        if any(item.case_count != self.case_count for item in self.strategies):
            raise ValueError("proof-pack strategy case counts must match the case ledger")
        if set(self.artifacts) != set(_CONTENT_FILES):
            raise ValueError("proof-pack artifact manifest is incomplete")
        if not self.tournament_passed:
            raise ValueError("proof pack cannot seal a failed tournament")
        if _model_hash(self, exclude={"proof_root_sha256"}) != self.proof_root_sha256:
            raise ValueError("proof-pack root does not match its canonical content")
        return self


async def build_recovery_proof_pack(
    output_dir: Path,
    *,
    code_revision: str,
    contract: RecoveryArenaContract | None = None,
    portfolio: RecoveryPortfolio | None = None,
) -> RecoveryProofPackManifest:
    """Evaluate a portfolio, atomically write every artifact, and verify the result."""

    _validate_revision(code_revision)
    locked = contract or create_recovery_arena_contract()
    evaluated = portfolio or generate_held_out_recovery_portfolio(locked)
    report, chakravyuh_results, baseline_report = await run_recovery_tournament(evaluated, locked)
    if not report.passed:
        raise ValueError("recovery tournament failed; refusing to seal a proof pack")
    baseline_report_again, baseline_results = await run_baseline_tournament(evaluated, locked)
    if baseline_report_again != baseline_report:
        raise ValueError("baseline replay diverged while preparing per-case evidence")
    records = _case_records(
        evaluated,
        report,
        baseline_results,
        chakravyuh_results,
        code_revision=code_revision,
    )
    content = {
        "cases.jsonl": b"".join(
            _canonical_json_bytes(item.model_dump(mode="json")) + b"\n" for item in records
        ),
        "strategy-summary.csv": _strategy_csv(report),
        "index.html": _summary_html(report, evaluated, code_revision).encode(),
    }
    manifest = _manifest(report, baseline_report.report_sha256, content, records, code_revision)
    manifest_bytes = (
        json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True).encode() + b"\n"
    )
    files = {**content, "manifest.json": manifest_bytes}
    checksums = "".join(f"{_sha256(files[name])}  {name}\n" for name in sorted(files)).encode()
    _atomic_write(output_dir, {**files, "SHA256SUMS": checksums})
    return verify_recovery_proof_pack(
        output_dir,
        expected_code_revision=code_revision,
        expected_proof_root=manifest.proof_root_sha256,
    )


def verify_recovery_proof_pack(
    input_dir: Path,
    *,
    expected_code_revision: str | None = None,
    expected_proof_root: str | None = None,
) -> RecoveryProofPackManifest:
    """Verify outer file checksums, typed content, per-case bindings, and trust anchors."""

    root = input_dir.resolve(strict=True)
    if not root.is_dir():
        raise ProofPackVerificationError("proof-pack path is not a directory")
    paths = {name: _safe_file(root, name) for name in (*_CHECKSUM_FILES, "SHA256SUMS")}
    expected_sums = "".join(
        f"{_sha256(_read_bounded(paths[name]))}  {name}\n" for name in sorted(_CHECKSUM_FILES)
    ).encode()
    if _read_bounded(paths["SHA256SUMS"]) != expected_sums:
        raise ProofPackVerificationError("SHA256SUMS does not match the proof artifacts")
    try:
        manifest = RecoveryProofPackManifest.model_validate_json(
            _read_bounded(paths["manifest.json"])
        )
    except ValueError as error:
        raise ProofPackVerificationError("manifest validation failed") from error
    if expected_code_revision is not None and manifest.code_revision != expected_code_revision:
        raise ProofPackVerificationError("proof pack is bound to a different code revision")
    if expected_proof_root is not None and manifest.proof_root_sha256 != expected_proof_root:
        raise ProofPackVerificationError("proof pack root does not match the trusted root")
    for name in _CONTENT_FILES:
        body = _read_bounded(paths[name])
        artifact = manifest.artifacts[name]
        if artifact.sha256 != _sha256(body) or artifact.size_bytes != len(body):
            raise ProofPackVerificationError(f"manifest binding failed for {name}")
    bindings: list[str] = []
    previous_case_id = ""
    with paths["cases.jsonl"].open("rb") as stream:
        for index, raw_line in enumerate(stream):
            if not raw_line.endswith(b"\n") or len(raw_line) > 1_000_000:
                raise ProofPackVerificationError("case ledger has an invalid line boundary")
            try:
                record = RecoveryProofCase.model_validate(json.loads(raw_line))
            except (json.JSONDecodeError, ValueError) as error:
                raise ProofPackVerificationError("case ledger validation failed") from error
            if raw_line != _canonical_json_bytes(record.model_dump(mode="json")) + b"\n":
                raise ProofPackVerificationError("case ledger is not canonically encoded")
            if record.case_index != index or record.case_id <= previous_case_id:
                raise ProofPackVerificationError("case ledger order or index is invalid")
            if (
                record.code_revision != manifest.code_revision
                or record.contract_sha256 != manifest.contract_sha256
                or record.portfolio_manifest_sha256 != manifest.portfolio_manifest_sha256
                or record.tournament_report_sha256 != manifest.tournament_report_sha256
            ):
                raise ProofPackVerificationError("case ledger is not bound to its manifest")
            previous_case_id = record.case_id
            bindings.append(record.case_binding_sha256)
    if len(bindings) != manifest.case_count or _merkle_root(bindings) != manifest.cases_root_sha256:
        raise ProofPackVerificationError("case count or Merkle root does not match the manifest")
    return manifest


def _case_records(
    portfolio: RecoveryPortfolio,
    report: RecoveryArenaTournamentReport,
    baseline_results: tuple[ArenaScoredCaseResult, ...],
    chakravyuh_results: tuple[ChakravyuhScoredCaseResult, ...],
    *,
    code_revision: str,
) -> tuple[RecoveryProofCase, ...]:
    baseline_by_key = {(item.strategy, item.case_id): item for item in baseline_results}
    chakravyuh_by_id = {item.case_id: item for item in chakravyuh_results}
    records: list[RecoveryProofCase] = []
    for index, case in enumerate(sorted(portfolio.cases, key=lambda item: item.observed.case_id)):
        case_id = case.observed.case_id
        draft = RecoveryProofCase.model_construct(
            record_version=CASE_RECORD_VERSION,
            case_index=index,
            case_id=case_id,
            code_revision=code_revision,
            contract_sha256=report.contract_sha256,
            portfolio_manifest_sha256=report.portfolio_manifest_sha256,
            tournament_report_sha256=report.report_sha256,
            observed_case_sha256=case.observed.observed_case_sha256,
            oracle_case_sha256=case.oracle.oracle_sha256,
            family=case.oracle.family,
            currency=case.oracle.payment_amount.currency,
            payment_amount_subunits=case.oracle.payment_amount.amount_subunits,
            action_eligible=case.oracle.action_eligible,
            recoverable=case.oracle.recoverable,
            no_intervention=baseline_by_key[(ArenaStrategyName.NO_INTERVENTION, case_id)],
            retry_all=baseline_by_key[(ArenaStrategyName.RETRY_ALL, case_id)],
            chakravyuh=chakravyuh_by_id[case_id],
            case_binding_sha256="0" * 64,
        )
        records.append(
            RecoveryProofCase.model_validate(
                {
                    **draft.model_dump(mode="json"),
                    "case_binding_sha256": _model_hash(draft, exclude={"case_binding_sha256"}),
                }
            )
        )
    return tuple(records)


def _manifest(
    report: RecoveryArenaTournamentReport,
    baseline_report_sha256: str,
    content: dict[str, bytes],
    records: tuple[RecoveryProofCase, ...],
    code_revision: str,
) -> RecoveryProofPackManifest:
    draft = RecoveryProofPackManifest.model_construct(
        proof_pack_version=PROOF_PACK_VERSION,
        code_revision=code_revision,
        contract_sha256=report.contract_sha256,
        portfolio_manifest_sha256=report.portfolio_manifest_sha256,
        baseline_report_sha256=baseline_report_sha256,
        tournament_report_sha256=report.report_sha256,
        case_count=len(records),
        cases_root_sha256=_merkle_root([item.case_binding_sha256 for item in records]),
        strategies=report.strategies,
        artifacts={
            name: ProofArtifact(sha256=_sha256(body), size_bytes=len(body))
            for name, body in content.items()
        },
        tournament_passed=report.passed,
        proof_root_sha256="0" * 64,
    )
    return RecoveryProofPackManifest.model_validate(
        {
            **draft.model_dump(mode="json"),
            "proof_root_sha256": _model_hash(draft, exclude={"proof_root_sha256"}),
        }
    )


def _strategy_csv(report: RecoveryArenaTournamentReport) -> bytes:
    stream = io.StringIO(newline="")
    fields = (
        "strategy",
        "case_count",
        "action_attempt_count",
        "incorrect_action_count",
        "confirmed_recovery_count",
        "confirmed_recovered_revenue_subunits",
        "net_recovery_value_subunits",
        "results_root_sha256",
    )
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for item in report.strategies:
        writer.writerow({field: getattr(item, field) for field in fields})
    return stream.getvalue().encode()


def _summary_html(
    report: RecoveryArenaTournamentReport,
    portfolio: RecoveryPortfolio,
    code_revision: str,
) -> str:
    rows = "".join(
        "<tr>"
        f"<td>{html.escape(item.strategy.value)}</td>"
        f"<td>{item.action_attempt_count:,}</td>"
        f"<td>{item.incorrect_action_count:,}</td>"
        f"<td>{item.confirmed_recovery_count:,}</td>"
        f"<td>{item.net_recovery_value_subunits / 100:,.2f}</td>"
        "</tr>"
        for item in report.strategies
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Chakravyuh Recovery Arena Proof</title>
<style>
body{{margin:0;background:#0b0a07;color:#f5efe3;font:16px system-ui,sans-serif}}
main{{max-width:1100px;margin:auto;padding:5vw}}
h1{{font-size:clamp(2.8rem,8vw,6.5rem);line-height:.88;letter-spacing:-.06em}}
p{{color:#b9b1a3;line-height:1.6}}
.tag{{color:#e9ad45;text-transform:uppercase;letter-spacing:.16em}}
table{{width:100%;border-collapse:collapse;margin:3rem 0}}
th,td{{padding:1rem;border:1px solid #39342b;text-align:right}}
th:first-child,td:first-child{{text-align:left}}
code{{word-break:break-all;color:#63d9a0}}
</style>
</head>
<body><main>
<p class="tag">Phase 12 · sealed offline evidence</p>
<h1>Recovery Arena<br>proof pack.</h1>
<p>{portfolio.manifest.case_count:,} held-out synthetic journeys. Revenue is counted only after an
authoritative confirmation webhook.</p>
<table><thead><tr><th>Strategy</th><th>Actions</th><th>Incorrect</th><th>Confirmed</th>
<th>Net INR</th></tr></thead><tbody>{rows}</tbody></table>
<p>Code revision<br><code>{html.escape(code_revision)}</code></p>
<p>Tournament SHA-256<br><code>{html.escape(report.report_sha256)}</code></p>
<p>This is deterministic synthetic INR evidence, not a production SLA or merchant revenue claim.</p>
</main></body></html>
"""


def _atomic_write(output_dir: Path, files: dict[str, bytes]) -> None:
    target = output_dir.expanduser()
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        raise FileExistsError("proof-pack output directory already exists")
    temporary = Path(tempfile.mkdtemp(prefix=".recovery-proof-", dir=parent))
    try:
        for name, body in files.items():
            (temporary / name).write_bytes(body)
        temporary.replace(target)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _safe_file(root: Path, name: str) -> Path:
    path = root / name
    if path.is_symlink() or not path.is_file() or path.resolve().parent != root:
        raise ProofPackVerificationError(f"missing or unsafe proof artifact: {name}")
    return path


def _read_bounded(path: Path) -> bytes:
    if path.stat().st_size > _MAX_FILE_BYTES:
        raise ProofPackVerificationError(f"proof artifact exceeds size limit: {path.name}")
    return path.read_bytes()


def _validate_revision(value: str) -> None:
    if re.fullmatch(_REVISION_PATTERN, value) is None:
        raise ValueError("code revision must be a full lowercase 40-character Git SHA")


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _model_hash(model: BaseModel, *, exclude: set[str]) -> str:
    return _sha256(_canonical_json_bytes(model.model_dump(mode="json", exclude=exclude)))


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()


def _merkle_root(hashes: Sequence[str]) -> str:
    if not hashes:
        raise ValueError("proof Merkle root requires at least one case")
    layer = [bytes.fromhex(value) for value in hashes]
    while len(layer) > 1:
        if len(layer) % 2:
            layer.append(layer[-1])
        layer = [
            hashlib.sha256(layer[index] + layer[index + 1]).digest()
            for index in range(0, len(layer), 2)
        ]
    return layer[0].hex()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="build the full held-out proof pack")
    build.add_argument("--output-dir", type=Path, required=True)
    build.add_argument("--code-revision", required=True)
    verify = commands.add_parser("verify", help="verify an existing proof pack")
    verify.add_argument("--input-dir", type=Path, required=True)
    verify.add_argument("--expected-code-revision")
    verify.add_argument("--expected-proof-root")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        if args.command == "build":
            _validate_revision(args.code_revision)
            manifest = asyncio.run(
                build_recovery_proof_pack(args.output_dir, code_revision=args.code_revision)
            )
        else:
            manifest = verify_recovery_proof_pack(
                args.input_dir,
                expected_code_revision=args.expected_code_revision,
                expected_proof_root=args.expected_proof_root,
            )
    except (OSError, ValueError) as error:
        sys.stderr.write(f"recovery proof pack rejected: {error}\n")
        return 2
    sys.stdout.write(json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True))
    sys.stdout.write("\n")
    return 0


def run() -> None:
    raise SystemExit(main())


if __name__ == "__main__":  # pragma: no cover
    run()
