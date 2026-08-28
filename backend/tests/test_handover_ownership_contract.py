import json
from pathlib import Path


def test_required_logic_ownership_fields_are_classified_once():
    contract_path = Path(__file__).parents[2] / "docs" / "contracts" / "handover-ownership-fields.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    allowed = {"OPERATIONAL_OWNER", "HISTORICAL_ACTOR", "ACCESS_DERIVED", "UNRELATED"}
    fields = contract["fields"]
    paths = [field["path"] for field in fields]

    assert len(paths) == len(set(paths))
    assert all(field["classification"] in allowed for field in fields)
    assert {
        "clients.created_by",
        "clients.original_created_by",
        "tracked_products.user_id",
        "tracked_products.original_user_id",
        "place_track_target.created_by",
        "place_track_target.original_created_by",
        "client_analyses.created_by",
        "reports.created_by",
    }.issubset(paths)
