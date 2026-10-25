"""TEMPORARY (step 17 acceptance): a deliberately failing test, to show CI turns red. Reverted in the next commit."""

import unittest


class DeliberateFailure(unittest.TestCase):
    def test_ci_must_turn_red(self) -> None:
        self.assertEqual(1 + 1, 3, "deliberate failure: CI must report this run as failed")


if __name__ == "__main__":
    unittest.main()
