from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from enge_spx.engine import Engine
from enge_spx.network_policy import MODE, validate
from enge_spx.state import SPXError, Store


class NetworkPolicyTests(unittest.TestCase):
    def test_network_policy_rejects_ipv6_driver_ownership_and_nonisolated_internal_bridge(self):
        with tempfile.TemporaryDirectory() as folder:
            engine = Engine(Store(Path(folder)))
            good = {"Labels": {engine.owner: engine.store.instance}, "Internal": True, "Driver": "bridge", "EnableIPv6": False, "Options": {MODE: "isolated"}}
            validate(engine, good, True)
            for key, value in (("Internal", False), ("Driver", "host"), ("EnableIPv6", True), ("Options", {}), ("Labels", {engine.owner: "foreign"})):
                changed = deepcopy(good); changed[key] = value
                with self.subTest(key=key), self.assertRaises(SPXError):
                    validate(engine, changed, True)


if __name__ == "__main__":
    unittest.main()
