#!/usr/bin/env python3
"""Generate ready/valid UVM driver and monitor classes from a JSON contract."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path


TOP_KEYS = {
    "schema_version", "protocol", "item_type", "driver_class", "driver_base",
    "driver_vif_type", "driver_vif_key", "monitor_class", "monitor_base",
    "monitor_vif_type", "monitor_vif_key",
    "driver_clocking", "monitor_clocking", "valid_signal", "ready_signal",
    "timeout_cycles", "mappings", "plan_refs",
}
MAP_KEYS = {"signal", "item_field"}
IDENT = re.compile(r"[A-Za-z_]\w*")
TYPE = re.compile(r"[A-Za-z_][A-Za-z0-9_:\s.#(),]*")


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def ident(value: object, where: str) -> str:
    if not isinstance(value, str) or not IDENT.fullmatch(value):
        fail(f"unsafe identifier for {where}: {value}")
    return value


def sv_type(value: object, where: str) -> str:
    if not isinstance(value, str) or not TYPE.fullmatch(value.strip()):
        fail(f"unsafe SystemVerilog type for {where}: {value}")
    if any(word in value for word in ("endclass", "endmodule", "endpackage")):
        fail(f"forbidden terminator in {where}")
    return value.strip()


def validate(spec: object) -> dict:
    if not isinstance(spec, dict):
        fail("top level must be an object")
    unknown, missing = set(spec) - TOP_KEYS, TOP_KEYS - set(spec)
    if unknown or missing:
        fail(f"top-level keys unknown={sorted(unknown)} missing={sorted(missing)}")
    if spec["schema_version"] != 1:
        fail("schema_version must be 1")
    if spec["protocol"] != "ready_valid_source":
        fail("only protocol 'ready_valid_source' is implemented")
    for key in (
        "item_type", "driver_class", "monitor_class", "driver_clocking",
        "monitor_clocking", "valid_signal", "ready_signal", "driver_vif_key",
        "monitor_vif_key",
    ):
        spec[key] = ident(spec[key], key)
    for key in ("driver_base", "driver_vif_type", "monitor_base", "monitor_vif_type"):
        spec[key] = sv_type(spec[key], key)
    if not isinstance(spec["timeout_cycles"], int) or not 1 <= spec["timeout_cycles"] <= 1_000_000:
        fail("timeout_cycles must be an integer in [1, 1000000]")
    mappings = spec["mappings"]
    if not isinstance(mappings, list) or not mappings:
        fail("mappings must be a non-empty list")
    checked: list[dict[str, str]] = []
    signals: set[str] = set()
    fields: set[str] = set()
    for index, mapping in enumerate(mappings):
        if not isinstance(mapping, dict) or set(mapping) != MAP_KEYS:
            fail(f"mappings[{index}] must contain exactly {sorted(MAP_KEYS)}")
        signal = ident(mapping["signal"], f"mappings[{index}].signal")
        field = ident(mapping["item_field"], f"mappings[{index}].item_field")
        if signal in signals or field in fields:
            fail("mappings must have unique signals and item fields")
        signals.add(signal)
        fields.add(field)
        checked.append({"signal": signal, "item_field": field})
    refs = spec["plan_refs"]
    if not isinstance(refs, list) or not refs or not all(isinstance(ref, str) and ref.strip() for ref in refs):
        fail("plan_refs must be a non-empty list")
    spec["mappings"] = checked
    return spec


def render_driver(spec: dict) -> str:
    c, cb = spec["driver_class"], spec["driver_clocking"]
    lines = [
        f"// Plan: {'; '.join(spec['plan_refs'])}",
        f"class {c} extends {spec['driver_base']};",
        f"  `uvm_component_utils({c})",
        f"  {spec['driver_vif_type']} vif;",
        "",
        "  function new(string name, uvm_component parent);",
        "    super.new(name, parent);",
        "  endfunction",
        "",
        "  virtual function void build_phase(uvm_phase phase);",
        "    super.build_phase(phase);",
        f"    if (!uvm_config_db #({spec['driver_vif_type']})::get(this, \"\", \"{spec['driver_vif_key']}\", vif))",
        f"      `uvm_fatal(\"{c.upper()}_NO_VIF\", \"virtual interface was not configured\")",
        "  endfunction",
        "",
        "  virtual task run_phase(uvm_phase phase);",
        "    forever begin",
        "      seq_item_port.get_next_item(req);",
        "      drive_item(req);",
        "      seq_item_port.item_done();",
        "    end",
        "  endtask",
        "",
        f"  virtual task drive_item({spec['item_type']} tr);",
        "    int unsigned wait_cycles = 0;",
        f"    vif.{cb}.{spec['valid_signal']} <= 1'b0;",
        f"    @(vif.{cb});",
    ]
    for mapping in spec["mappings"]:
        lines.append(f"    vif.{cb}.{mapping['signal']} <= tr.{mapping['item_field']};")
    lines.extend([
        f"    vif.{cb}.{spec['valid_signal']} <= 1'b1;",
        "    do begin",
        f"      @(vif.{cb});",
        "      wait_cycles++;",
        f"      if (wait_cycles >= {spec['timeout_cycles']}) begin",
        f"        `uvm_fatal(\"{c.upper()}_TIMEOUT\", \"ready timeout while valid is asserted\")",
        "      end",
        f"    end while (!vif.{cb}.{spec['ready_signal']});",
        f"    vif.{cb}.{spec['valid_signal']} <= 1'b0;",
        "  endtask",
        "endclass",
        "",
    ])
    return "\n".join(lines)


def render_monitor(spec: dict) -> str:
    c, cb = spec["monitor_class"], spec["monitor_clocking"]
    item = spec["item_type"]
    lines = [
        f"// Plan: {'; '.join(spec['plan_refs'])}",
        f"class {c} extends {spec['monitor_base']};",
        f"  `uvm_component_utils({c})",
        f"  {spec['monitor_vif_type']} vif;",
        f"  uvm_analysis_port #({item}) ap;",
        "",
        "  function new(string name, uvm_component parent);",
        "    super.new(name, parent);",
        "    ap = new(\"ap\", this);",
        "  endfunction",
        "",
        "  virtual function void build_phase(uvm_phase phase);",
        "    super.build_phase(phase);",
        f"    if (!uvm_config_db #({spec['monitor_vif_type']})::get(this, \"\", \"{spec['monitor_vif_key']}\", vif))",
        f"      `uvm_fatal(\"{c.upper()}_NO_VIF\", \"virtual interface was not configured\")",
        "  endfunction",
        "",
        "  virtual task run_phase(uvm_phase phase);",
        f"    {item} tr;",
        "    forever begin",
        f"      @(vif.{cb});",
        f"      if (vif.{cb}.{spec['valid_signal']} && vif.{cb}.{spec['ready_signal']}) begin",
        f"        tr = {item}::type_id::create(\"tr\", this);",
    ]
    for mapping in spec["mappings"]:
        lines.append(f"        tr.{mapping['item_field']} = vif.{cb}.{mapping['signal']};")
    lines.extend([
        "        ap.write(tr);",
        "      end",
        "    end",
        "  endtask",
        "endclass",
        "",
    ])
    return "\n".join(lines)


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(content, encoding="utf-8")
    os.replace(temp, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--driver-out", type=Path, required=True)
    parser.add_argument("--monitor-out", type=Path, required=True)
    args = parser.parse_args()
    for output in (args.driver_out, args.monitor_out):
        if output.exists():
            fail(f"refusing to overwrite: {output}")
    spec = validate(json.loads(args.spec.read_text(encoding="utf-8")))
    driver, monitor = render_driver(spec), render_monitor(spec)
    atomic_write(args.driver_out, driver)
    atomic_write(args.monitor_out, monitor)
    print(args.driver_out)
    print(args.monitor_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
