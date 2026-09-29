"""Synthetic large-project benchmark. Never opens an existing verification project."""

import argparse
import json
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.test_dashboard_read_cost import DashboardReadCostTest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, help="Parent for an isolated temporary test project")
    parser.add_argument("--units", type=int, default=1000)
    parser.add_argument("--payload-mib", type=int, default=16)
    args = parser.parse_args()
    if args.units < 1 or args.payload_mib < 1:
        parser.error("units and payload-mib must be positive")
    if args.directory:
        tempfile.tempdir = str(args.directory.resolve(strict=True))
    fixture = DashboardReadCostTest()
    fixture.setUp()
    try:
        store = fixture.fixture.store
        plan = store.workstream("VDOC")
        delivery = next(n for n in plan["desired_state"] if n["role"] == "document-deliverable")
        prototype = delivery["internal_semantic_units"][0]
        padding = "x" * (args.payload_mib * 1024 * 1024 // args.units)
        units = [{**prototype, "id": f"scale-entry-{i}", "content": padding} for i in range(args.units)]
        delivery["internal_semantic_units"].extend(units)
        with store.connect() as connection:
            connection.execute("UPDATE workstreams SET desired_json=? WHERE name='VDOC'",
                               (json.dumps(plan["desired_state"]),))
        writing = next(n for n in plan["desired_state"] if n["role"] == "document-writing-plan")
        delivery = next(n for n in plan["desired_state"] if n["role"] == "document-deliverable")
        review = store.document_delivery_review_state(delivery["id"])
        operations = [
            ("snapshot", store.dashboard_snapshot),
            ("status", store.status),
            ("plan_approval", lambda: store.complete_node_plan_review(
                writing["id"], store._node_plan_digest(plan, writing), "fixture-owner")),
            ("body_approval", lambda: store.review_document_delivery(
                delivery["id"], review["definition_digest"], review["document_digest"],
                "approve", "fixture-owner", "")),
            ("approval_status", lambda: store.approval_status(delivery["id"])),
            ("unchanged_sync", lambda: store.sync_documents([fixture.document["id"]])),
        ]
        def changed_sync():
            fixture.path.write_text("# Updated synthetic verification plan\n", encoding="utf-8")
            return store.sync_documents([fixture.document["id"]])
        operations.append(("changed_sync", changed_sync))
        for label, call in operations:
            start = time.monotonic()
            _result, queries = fixture.traced(call)
            print(json.dumps({"operation": label, "seconds": round(time.monotonic() - start, 3),
                              "sql_statements": len(queries),
                              "definition_reads": sum(q.startswith("SELECT desired_json,") for q in queries),
                              "units": args.units, "payload_mib": args.payload_mib}), flush=True)
    finally:
        fixture.tearDown()


if __name__ == "__main__":
    main()
