import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
REBRAND = ROOT / "rebrand"


def test_every_allowlist_exception_compiles_and_examples_enforce_scope() -> None:
    data = yaml.safe_load((REBRAND / "allowed-legacy-identities.yaml").read_text())

    for exception in data["exceptions"]:
        path_re = re.compile(exception["path_regex"])
        token_re = re.compile(exception["token_regex"])
        assert exception["positive_examples"], exception["id"]
        assert exception["negative_examples"], exception["id"]
        for example in exception["positive_examples"]:
            assert path_re.search(example["path"]), (exception["id"], example)
            assert token_re.search(example["token"]), (exception["id"], example)
        for example in exception["negative_examples"]:
            assert not (
                path_re.search(example["path"])
                and token_re.search(example["token"])
            ), (exception["id"], example)


def test_mapping_order_names_every_replacement_section_once() -> None:
    data = yaml.safe_load((REBRAND / "identity-map.yaml").read_text())
    order = data["replacement_order"]
    replacement_sections = {
        "url_authorities",
        "desktop_and_bundle_ids",
        "protocol_and_headers",
        "service_and_process_names",
        "home_and_state_paths",
        "user_facing_environment",
        "python_namespaces",
        "package_and_commands",
        "display_identity",
    }

    assert len(order) == len(set(order))
    assert set(order) == replacement_sections


def test_owned_legacy_product_urls_are_never_preserved() -> None:
    data = json.loads(
        (REBRAND / "inventory" / "url-authorities.json").read_text()
    )
    product_markers = (
        "nousresearch.github.io/hermes-agent",
        "hermes-agent.nousresearch.com",
        "hermes--agent.nousresearch.com",
        "setup.hermes-agent.nousresearch.com",
    )
    matching = [
        row
        for row in data["entries"]
        if any(marker in row["url"].lower() for marker in product_markers)
    ]

    assert matching
    assert all(row["class"] in {"tutou-github", "agent-tutou-site"} for row in matching)
    assert all(row["replacement"] for row in matching)


def test_curated_inventories_record_the_scanned_source_sha() -> None:
    expected = "703869ebaa299a3c77817b20c5f57bbfa433f365"
    for name in ("url-authorities.json", "path-renames.json"):
        data = json.loads((REBRAND / "inventory" / name).read_text())
        assert data["source_sha"] == expected
