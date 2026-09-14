import json
import os
import tempfile
import unittest

from tests import _bootstrap  # noqa: F401
import state as state_mod


MINI_MQ5 = (
    "input double          Risk_Percent        = 1.0;\n"
    "input int             Min_EMA_Distance    = 400;\n"
    "input int             Min_Trade_Distance  = 500;\n"
    "input int             StopLoss_Pips       = 1000;\n"
    "input int             T1_Pips             = 500;\n"
    "input int             T2_Pips             = 1000;\n"
    "input int             T3_Pips             = 1800;\n"
    "input double          T1_ClosePercent     = 33.0;\n"
    "input double          T2_ClosePercent     = 50.0;\n"
    "input int             Entry_Cooldown_Bars = 3;\n"
    "input int             Max_Concurrent_Positions = 2;\n"
)


class TestState(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.mq5 = os.path.join(self.tmp, "HappyBot.mq5")
        with open(self.mq5, "w") as fh:
            fh.write(MINI_MQ5)
        self.state_path = os.path.join(self.tmp, "tuner_state.json")

    def test_init_from_mq5_when_absent(self):
        st = state_mod.load_or_init(self.state_path, self.mq5)
        self.assertEqual(st["iteration"], 0)
        self.assertIsNone(st["best"])
        self.assertEqual(st["current"]["Risk_Percent"], 1.0)
        self.assertEqual(st["current"]["StopLoss_Pips"], 1000)

    def test_init_when_corrupt(self):
        with open(self.state_path, "w") as fh:
            fh.write("{not valid json")
        st = state_mod.load_or_init(self.state_path, self.mq5)
        self.assertEqual(st["current"]["T3_Pips"], 1800)

    def test_atomic_write_valid_json(self):
        st = state_mod.load_or_init(self.state_path, self.mq5)
        state_mod.save(self.state_path, st)
        with open(self.state_path, "r") as fh:
            reloaded = json.load(fh)
        self.assertEqual(reloaded["current"], st["current"])

    def test_best_updates_only_on_improvement(self):
        st = state_mod.load_or_init(self.state_path, self.mq5)
        state_mod.record_iteration(st, {"total_net_profit": 100.0}, 100.0, accepted=True)
        self.assertEqual(st["best"]["score"], 100.0)
        # Non-improving iteration: accepted False, best unchanged.
        state_mod.record_iteration(st, {"total_net_profit": 10.0}, 10.0, accepted=False)
        self.assertEqual(st["best"]["score"], 100.0)
        # Improving iteration.
        state_mod.record_iteration(st, {"total_net_profit": 200.0}, 200.0, accepted=True)
        self.assertEqual(st["best"]["score"], 200.0)

    def test_history_append(self):
        st = state_mod.load_or_init(self.state_path, self.mq5)
        state_mod.record_iteration(st, {"total_net_profit": 5.0}, 5.0, accepted=True)
        state_mod.record_iteration(st, {"total_net_profit": 6.0}, 6.0, accepted=True)
        self.assertEqual(len(st["history"]), 2)
        self.assertEqual(st["history"][0]["iteration"], 1)
        self.assertEqual(st["history"][1]["iteration"], 2)
        self.assertEqual(st["iteration"], 2)

    def test_compute_delta(self):
        d = state_mod.compute_delta({"a": 1, "b": 2}, {"a": 1, "b": 3})
        self.assertNotIn("a", d)
        self.assertEqual(d["b"], [2, 3])


if __name__ == "__main__":
    unittest.main()
