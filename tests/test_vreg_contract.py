"""Pure approved-scope contracts; no simulator or project state involved."""

import copy
import unittest

from verif_harness import vreg_contract as contract


def configuration(mode="fixed", repeat=1):
    value = {
        "regression_group": "smoke",
        "cases": [{"case_id": "demo_test", "case_digest": "c" * 64}],
        "submit_profile": {
            "schema": "SubmitProfileRef/1", "profile_id": "local",
            "submit_file": "tb/submit.json", "submit_file_digest": "f" * 64,
            "profile_digest": "a" * 64,
            "adapter": {"name": "synthetic-testbench", "version": "1"},
        },
        "seed_mode": mode, "repeat": repeat,
    }
    if mode == "fixed":
        value["seed"] = 17
    return value


def binding():
    return {"round_id": "regression-round:one", "plan_node_id": "workstream:VREG:r1:desired:smoke",
            "plan_revision": 1, "plan_digest": "b" * 64}


def batch(config):
    return {"schema": "RegressionBatchManifest/2", "batch_id": "smoke-one",
            **copy.deepcopy(config), "execution_binding": binding(),
            "runs": [{"case_id": case["case_id"], "iteration": iteration,
                      "seed": config.get("seed", str(iteration + 101))}
                     for case in config["cases"] for iteration in range(config["repeat"])]}


class RegressionContractTest(unittest.TestCase):
    def test_default_repeat_and_numeric_seed(self):
        value = configuration()
        del value["repeat"]
        result = contract.normalize_config(value)
        self.assertEqual(result["repeat"], 1)
        self.assertEqual(result["seed"], "17")

    def test_invalid_modes_counts_and_unresolved_seeds(self):
        for field, value in (("repeat", True), ("repeat", 0), ("repeat", 1.5),
                             ("seed", "random"), ("seed", True), ("seed", 0),
                             ("seed_mode", "sometimes")):
            with self.subTest(field=field, value=value):
                invalid = configuration()
                invalid[field] = value
                with self.assertRaises(ValueError):
                    contract.normalize_config(invalid)
        invalid = configuration("random")
        invalid["seed"] = 1
        with self.assertRaises(ValueError):
            contract.normalize_config(invalid)

    def test_group_identity_ignores_execution_parameters_and_revision(self):
        first = configuration()
        second = configuration("random", 3)
        second["cases"][0]["case_digest"] = "d" * 64
        self.assertEqual(contract.group_identity(first), contract.group_identity(second))
        second["submit_profile"]["profile_id"] = "other"
        self.assertNotEqual(contract.group_identity(first), contract.group_identity(second))

    def test_cases_profile_and_bindings_fail_closed(self):
        invalid = configuration()
        invalid["cases"] *= 2
        with self.assertRaises(ValueError):
            contract.normalize_config(invalid)
        invalid = configuration()
        invalid["submit_profile"]["submit_file"] = "../foreign/submit.json"
        with self.assertRaises(ValueError):
            contract.normalize_config(invalid)
        invalid = binding()
        invalid["plan_revision"] = True
        with self.assertRaises(ValueError):
            contract.normalize_binding(invalid)

    def test_random_and_fixed_execution_are_distinct(self):
        for mode in ("random", "fixed"):
            value = contract.normalize_config(configuration(mode, 3))
            self.assertEqual(contract.execution_blockers(value, [batch(value)], binding()), [])
        value = contract.normalize_config(configuration("random", 3))
        invalid = batch(value)
        invalid["runs"][1]["seed"] = invalid["runs"][0]["seed"]
        self.assertTrue(contract.execution_blockers(value, [invalid], binding()))

    def test_missing_extra_duplicate_and_stale_execution(self):
        value = contract.normalize_config(configuration(repeat=2))
        for mutate in (
            lambda item: item["runs"].pop(),
            lambda item: item["runs"].append(copy.deepcopy(item["runs"][0])),
            lambda item: item.update(regression_group="foreign"),
            lambda item: item["execution_binding"].update(round_id="regression-round:old"),
            lambda item: item["submit_profile"].update(profile_digest="e" * 64),
            lambda item: item["submit_profile"]["adapter"].update(version="old"),
            lambda item: item.update(schema="RegressionBatchManifest/1"),
        ):
            invalid = batch(value)
            mutate(invalid)
            self.assertTrue(contract.execution_blockers(value, [invalid], binding()))


if __name__ == "__main__":
    unittest.main()
