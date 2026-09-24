from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from verif_harness.document_authoring import (
    AUTHORING_CONTRACT_SCHEMA,
    AUTHORING_DOCUMENT_ORDER,
    load_authoring_profiles,
)
from verif_harness.store import ProjectStore, VDOC_DOCUMENTS


class VerificationDocumentAuthoringTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "rtl").mkdir()
        (self.root / "specs").mkdir()
        (self.root / "tb").mkdir()
        (self.root / "scripts").mkdir()
        (self.root / "rtl/dut.sv").write_text(
            """
module child(input logic clk, input logic rst_n);
endmodule

module dut(
  input logic clk,
  input logic rst_n,
  input logic valid,
  output logic ready,
  input logic [7:0] data,
  output logic irq
);
  child u_child(.clk(clk), .rst_n(rst_n));
endmodule
""".strip() + "\n",
            encoding="utf-8",
        )
        (self.root / "specs/design_spec.md").write_text(
            "# Design Spec\nREQ-001: The DUT must accept a transaction only on valid and ready.\n",
            encoding="utf-8",
        )
        (self.root / "specs/micro_arch_spec.md").write_text(
            "# Micro Architecture\nSPEC-FIFO-001: The internal FIFO must preserve transaction order.\n",
            encoding="utf-8",
        )
        (self.root / "specs/interface_spec.md").write_text(
            "# Interface Spec\nINTF-001: valid must remain asserted until ready completes the handshake.\n",
            encoding="utf-8",
        )
        (self.root / "specs/register_spec.md").write_text(
            "# Register Spec\nCSR-001: CSR CTRL must enable the interface.\n"
            "ERR-001: An error interrupt must assert irq on FIFO overflow.\n",
            encoding="utf-8",
        )
        (self.root / "tb/tb_top.sv").write_text(
            "module tb_top; dut u_dut(); endmodule\n", encoding="utf-8",
        )
        (self.root / "reference_model.py").write_text(
            "def predict(value):\n    return value\n", encoding="utf-8",
        )
        (self.root / "scripts/run_regression.py").write_text(
            "raise SystemExit(0)\n", encoding="utf-8",
        )
        self.store = ProjectStore(self.root)
        self.store.bootstrap(
            runtime="none", rtl_roots=["rtl"], docs_roots=["specs"],
            verif_root="verification", dut_top="dut",
            dut_top_file="rtl/dut.sv",
            testbench_root="tb", reference_model="reference_model.py",
            verification_scripts=["scripts/run_regression.py"],
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def authoring_proposal(self) -> dict:
        return self.store.build_vdoc_authoring_proposal()

    def register_authoring_plan(self) -> tuple[dict, dict]:
        proposal = self.authoring_proposal()
        path = self.root / ".verif-harness/proposals/vdoc-authoring.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(proposal), encoding="utf-8")
        plan = self.store.design_workstream(
            "VDOC", None, [], [], [], None, [], str(path),
        )
        return proposal, plan

    @staticmethod
    def delivery_proposal(authoring: dict) -> dict:
        nodes = []
        for item in authoring["nodes"]:
            document_key = item["document_key"]
            nodes.append({
                **{key: value for key, value in item.items() if key != "authoring_contract"},
                "key": document_key.replace("-", "_") + "_delivery",
                "title": f"{document_key} 正文验收",
                "role": "document-deliverable",
                "parent_key": item["key"],
                "statement": f"{document_key} 正文按已批准 authoring contract 撰写并等待独立验收。",
                "deliverables": [f"当前 DUT 的 {document_key} 正文"],
            })
        return {"schema": "DesiredStateProposal/1", "workstream": "VDOC", "nodes": nodes}

    def test_profile_registry_exactly_matches_real_vdoc_catalog(self) -> None:
        profiles = load_authoring_profiles()
        self.assertEqual(set(profiles), set(VDOC_DOCUMENTS))
        self.assertEqual(tuple(AUTHORING_DOCUMENT_ORDER), tuple(VDOC_DOCUMENTS))
        self.assertEqual(
            {key: profile["filename"] for key, profile in profiles.items()},
            {key: value[0] for key, value in VDOC_DOCUMENTS.items()},
        )

    def test_generation_is_grounded_and_never_emits_final_documents(self) -> None:
        proposal = self.authoring_proposal()
        self.assertEqual(len(proposal["nodes"]), 8)
        self.assertEqual({item["role"] for item in proposal["nodes"]}, {"document-writing-plan"})
        self.assertFalse((self.root / "verification/docs/verification").exists())

        assertion = next(
            item for item in proposal["nodes"] if item["document_key"] == "assertion-plan"
        )
        contract = assertion["authoring_contract"]
        self.assertEqual(contract["schema"], AUTHORING_CONTRACT_SCHEMA)
        self.assertEqual(
            {source["path"] for source in contract["source_snapshot"]},
            {
                ".harness-config.json", "rtl/dut.sv", "specs/design_spec.md",
                "specs/interface_spec.md", "specs/micro_arch_spec.md",
                "specs/register_spec.md", "tb/tb_top.sv", "reference_model.py",
                "scripts/run_regression.py",
            },
        )
        self.assertEqual(
            {
                source["kind"] for source in contract["source_snapshot"]
                if source["path"] in {
                    "tb/tb_top.sv", "reference_model.py",
                    "scripts/run_regression.py",
                }
            },
            {
                "verification-testbench", "reference-model-implementation",
                "verification-script",
            },
        )
        self.assertEqual(
            {item["name"] for item in contract["dut_scope"]["ports"]},
            {"clk", "rst_n", "valid", "ready", "data", "irq"},
        )
        self.assertEqual(
            {(item["name"], item["detail"]) for item in contract["dut_scope"]["hierarchy"]},
            {("u_child", "direct child module child")},
        )
        self.assertTrue(any(
            item["name"].upper() == "INTF-001"
            for item in contract["dut_scope"]["protocols"]
        ))
        self.assertTrue(any(
            item["name"].upper() == "CSR-001"
            for item in contract["dut_scope"]["registers"]
        ))
        joined_rules = " ".join(contract["domain_rules"]).lower()
        for required in (
            "temporal", "invariant", "assert/assume/cover", "sim/formal",
            "vacuity", "activation", "x/illegal",
        ):
            self.assertIn(required, joined_rules)

    def test_missing_specs_are_explicit_gaps_not_fabricated_facts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "rtl").mkdir()
            (root / "rtl/dut.sv").write_text(
                "module dut(input logic clk); endmodule\n", encoding="utf-8",
            )
            store = ProjectStore(root)
            store.bootstrap(
                runtime="none", rtl_roots=["rtl"], verif_root="verification",
                dut_top="dut", dut_top_file="rtl/dut.sv",
            )
            proposal = store.build_vdoc_authoring_proposal()
            contract = proposal["nodes"][0]["authoring_contract"]
            gaps = {item["missing_source"]: item for item in contract["source_gaps"]}
            self.assertIn("design-spec", gaps)
            self.assertTrue(gaps["design-spec"]["blocks_document_authoring"])
            self.assertEqual(contract["dut_scope"]["interfaces"], [])
            self.assertEqual(contract["dut_scope"]["registers"], [])
            self.assertFalse(any(
                source["kind"].endswith("spec")
                for source in contract["source_snapshot"]
            ))

    def test_graph_dependencies_and_source_changes_invalidate_downstream(self) -> None:
        authoring, plan = self.register_authoring_plan()
        authoring_nodes = [
            item for item in plan["desired_state"]
            if isinstance(item.get("authoring_contract"), dict)
        ]
        self.assertEqual(len(authoring_nodes), 8)
        self.store.review_workstream("VDOC", "approve", "alice", "authoring plans reviewed")

        delivery = self.delivery_proposal(authoring)
        delivery_path = self.root / ".verif-harness/proposals/vdoc-delivery.json"
        delivery_path.write_text(json.dumps(delivery), encoding="utf-8")
        registered = self.store.design_workstream(
            "VDOC", None, [], [], [], None, [], str(delivery_path),
        )
        delivery_nodes = [
            item for item in registered["desired_state"]
            if item.get("role") == "document-deliverable"
        ]
        self.assertEqual(len(delivery_nodes), 8)

        with sqlite3.connect(self.store.database) as connection:
            edge_counts = dict(connection.execute(
                "SELECT origin, COUNT(*) FROM edges "
                "WHERE origin IN ('authoring-source','authoring-profile','authoring-contract') "
                "GROUP BY origin"
            ).fetchall())
        self.assertGreater(edge_counts.get("authoring-source", 0), 0)
        self.assertGreater(edge_counts.get("authoring-profile", 0), 0)
        self.assertEqual(edge_counts.get("authoring-contract"), 8)

        changed = self.store.record_change("rtl/dut.sv", "rtl-change", "r2")
        affected = set(changed["affected"])
        self.assertTrue({item["id"] for item in authoring_nodes}.issubset(affected))
        self.assertTrue({item["id"] for item in delivery_nodes}.issubset(affected))

    def test_stale_source_digest_rejects_registration(self) -> None:
        proposal = self.authoring_proposal()
        path = self.root / "vdoc-authoring.json"
        path.write_text(json.dumps(proposal), encoding="utf-8")
        with (self.root / "rtl/dut.sv").open("a", encoding="utf-8") as stream:
            stream.write("// RTL changed after authoring snapshot\n")
        with self.assertRaisesRegex(ValueError, "sha256 与当前文件不一致"):
            self.store.design_workstream(
                "VDOC", None, [], [], [], None, [], str(path),
            )

    def test_reserved_authoring_node_cannot_bypass_structured_contract(self) -> None:
        proposal = self.authoring_proposal()
        del proposal["nodes"][0]["authoring_contract"]
        path = self.root / "missing-authoring-contract.json"
        path.write_text(json.dumps(proposal), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "必须携带当前 profile 生成的 authoring_contract"):
            self.store.design_workstream(
                "VDOC", None, [], [], [], None, [], str(path),
            )


if __name__ == "__main__":
    unittest.main()
