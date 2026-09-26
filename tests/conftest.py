"""
Shared test fixtures.

The library ships an **empty** entity schema. That is a measured decision: the
default it replaced was a logistics schema, and run against 40 real SWE-agent
trajectories it matched prose in every one of them -- see the README. Tests that
want fact extraction therefore have to say which domain they are testing, which
is also what a real caller must do.
"""


import pytest

#: The logistics schema, formerly the library default. Used by tests that were
#: written against the shipping fixture, so they keep testing the same patterns.
from contextgc.schemas import load_schema  # noqa: E402  (after sys.path setup)

LOGISTICS = load_schema("logistics")

#: A minimal schema for the write-path tests, which only need *some* key to be
#: declared, inferred, pinned, or revoked.
MINIMAL = {
    "destination_address": [
        r"(?:deliver to|bring it to|change (?:the )?(?:address|destination) to|reroute (?:the rider )?to|use)\s+"
        r"([A-Za-z0-9\s,-]{4,40}?)(?:\.|\,|$|\bwith\b|\band\b|\bplease\b|\bfor\b)",
    ],
    "gate_code": [r"(?:gate code|passcode|entry code)\s*(?:is|to|=|:)?\s*([0-9]{4,6})"],
    "refund_claim": [r"(?:refund|credit back)\s*(?:of|for)?\s*(?:\u20b9|rs\.?)?\s*([0-9]+)"],
    "dietary_allergy": [r"\b(?:no\s+(?:peanuts?|dairy|gluten|soy|eggs?|nuts?|shellfish))\b",
                        r"\b([A-Za-z]{3,20}?)\s+allergy\b"],
    "target_port": [r"\bport (?:to|is|=|:)\s*(\d{2,5})\b"],
    "cloud_environment": [
        r"\b(?:deploy|release|ship)(?:ed|ing)?\s+(?:to|into)\s+(production|prod|staging|preview|development|dev)\b",
    ],
    "signature_algorithm": [r"\b(RSA-256|Ed25519|HMAC-SHA256|ECDSA)\b"],
    "security_invariant": [r"(NEVER log (?:the )?[A-Za-z0-9_\s]+in plaintext)"],
}
MINIMAL["__immutable__"] = ["dietary_allergy", "security_invariant"]


@pytest.fixture
def logistics_schema():
    return LOGISTICS


@pytest.fixture
def schema():
    return MINIMAL


def make_dag(schema=None):
    """A StateDAG carrying the given schema. The library default is empty."""
    from contextgc.state_dag import StateDAG

    dag = StateDAG()
    for name, patterns in (schema or MINIMAL).items():
        if name == "__immutable__":
            continue
        dag.register_entity_schema(name, patterns)
    dag.immutable_entities.update((schema or MINIMAL).get("__immutable__", ()))
    return dag
