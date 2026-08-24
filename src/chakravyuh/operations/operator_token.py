"""Issue a high-entropy operator credential and its non-secret configuration hash."""

import argparse
import hashlib
import json
import secrets
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class IssuedOperatorCredential:
    """One-time bearer credential plus the hash safe to place in runtime configuration."""

    principal_id: str
    operator_token: str
    sha256: str
    environment_value: str


def issue_operator_credential(principal_id: str) -> IssuedOperatorCredential:
    """Create an operator credential with at least 256 bits of entropy."""
    if not principal_id.strip() or len(principal_id) > 64:
        msg = "principal must contain between 1 and 64 characters"
        raise ValueError(msg)
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    return IssuedOperatorCredential(
        principal_id=principal_id,
        operator_token=token,
        sha256=token_hash,
        environment_value=json.dumps({principal_id: token_hash}, separators=(",", ":")),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Issue a one-time operator token and its SHA-256 runtime configuration.",
    )
    parser.add_argument("--principal", required=True, help="Stable audited operator identity")
    return parser


def operator_token_main(args: argparse.Namespace) -> int:
    try:
        credential = issue_operator_credential(args.principal)
    except ValueError as failure:
        sys.stderr.write(f"operator credential rejected: {failure}\n")
        return 2
    sys.stderr.write(
        "Store operator_token in a password manager now; only its SHA-256 hash is configured.\n"
    )
    sys.stdout.write(json.dumps(asdict(credential), indent=2, sort_keys=True))
    sys.stdout.write("\n")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return operator_token_main(_parser().parse_args(argv))


def run() -> None:
    raise SystemExit(main())


if __name__ == "__main__":  # pragma: no cover
    run()
