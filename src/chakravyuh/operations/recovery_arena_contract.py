"""Print the locked Recovery Arena contract and held-out manifest."""

import json
import sys

from chakravyuh.domain.recovery_arena import (
    create_held_out_manifest,
    create_recovery_arena_contract,
)


def main() -> None:
    contract = create_recovery_arena_contract()
    manifest = create_held_out_manifest(contract)
    sys.stdout.write(
        json.dumps(
            {
                "contract": contract.model_dump(mode="json"),
                "held_out_manifest": manifest.model_dump(mode="json"),
            },
            indent=2,
            sort_keys=True,
        )
    )
    sys.stdout.write("\n")


if __name__ == "__main__":  # pragma: no cover
    main()
