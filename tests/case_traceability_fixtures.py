"""Synthetic per-case design references; never real DUT specifications."""
import hashlib
from pathlib import Path


def traceability_fixture(root: Path, case_id="demo_test", artifacts=None):
    def source(path, content):
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return {"path": path, "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                "version": "synthetic-r1", "locator": "用例定义 / " + case_id}
    listing = source("design/testcase_list.md", "# 用例清单\n\n" + case_id + "：检查握手结果。\n")
    spec = {"id": "spec-handshake", "kind": "specification",
            **source("design/spec.md", "# 接口规格\n\n握手只接受一次传输。\n")}
    rtl = {"id": "rtl-handshake", "kind": "rtl",
           **source("design/dut.sv", "module synthetic_dut; endmodule\n")}
    if artifacts is not None:
        for ref, kind in ((listing, "document"), (spec, "document"), (rtl, "source")):
            artifacts.append({"path": ref["path"], "sha256": ref["sha256"],
                              "kind": kind, "analyzed_by": ["xverif"]})
    return {"schema": "CaseTraceability/1", "verification_points": ["VP-HANDSHAKE"],
            "testcase_list": listing, "sources": [spec, rtl],
            "expected_result": {"description": "握手只接受一次传输。", "check_method": "scoreboard 统计接受次数。",
                                "basis_source_ids": [spec["id"]], "status": "specified"}}
