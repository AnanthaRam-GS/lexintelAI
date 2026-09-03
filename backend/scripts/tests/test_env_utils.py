"""Tests for the development environment loader."""

from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from backend.scripts.env_utils import load_project_env
from backend.scripts.indiankanoon_client import check_config


class EnvUtilsTest(unittest.TestCase):
    def test_missing_env_is_safe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            missing = Path(tmp_dir) / ".env"
            with patch.dict(os.environ, {}, clear=True):
                load_project_env(missing)
                self.assertNotIn("INDIAN_KANOON_API_TOKEN", os.environ)

    def test_loads_simple_values_and_ignores_comments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            env_path = Path(tmp_dir) / ".env"
            env_path.write_text(
                "\n# comment\nINDIAN_KANOON_API_TOKEN=test-token-placeholder\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                load_project_env(env_path)
                self.assertEqual(
                    os.environ["INDIAN_KANOON_API_TOKEN"],
                    "test-token-placeholder",
                )

    def test_preserves_value_containing_equals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            env_path = Path(tmp_dir) / ".env"
            env_path.write_text("SAMPLE=value=with=equals\n", encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                load_project_env(env_path)
                self.assertEqual(os.environ["SAMPLE"], "value=with=equals")

    def test_handles_simple_quotes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            env_path = Path(tmp_dir) / ".env"
            env_path.write_text(
                "SINGLE='quoted-value'\nDOUBLE=\"quoted value\"\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                load_project_env(env_path)
                self.assertEqual(os.environ["SINGLE"], "quoted-value")
                self.assertEqual(os.environ["DOUBLE"], "quoted value")

    def test_existing_process_env_is_not_overridden(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            env_path = Path(tmp_dir) / ".env"
            env_path.write_text(
                "INDIAN_KANOON_API_TOKEN=file-token-placeholder\n",
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {"INDIAN_KANOON_API_TOKEN": "process-token-placeholder"},
                clear=True,
            ):
                load_project_env(env_path)
                self.assertEqual(
                    os.environ["INDIAN_KANOON_API_TOKEN"],
                    "process-token-placeholder",
                )

    def test_secret_value_is_not_printed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            env_path = Path(tmp_dir) / ".env"
            env_path.write_text(
                "INDIAN_KANOON_API_TOKEN=test-token-placeholder\n",
                encoding="utf-8",
            )
            output = io.StringIO()
            with patch.dict(os.environ, {}, clear=True):
                with redirect_stdout(output):
                    load_project_env(env_path)

            self.assertNotIn("test-token-placeholder", output.getvalue())

    def test_lookup_can_use_project_root_independent_of_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            nested = root / "nested"
            nested.mkdir()
            env_path = root / ".env"
            env_path.write_text(
                "INDIAN_KANOON_API_TOKEN=test-token-placeholder\n",
                encoding="utf-8",
            )
            with patch("backend.scripts.env_utils.project_root", return_value=root):
                with patch.dict(os.environ, {}, clear=True):
                    old_cwd = Path.cwd()
                    try:
                        os.chdir(nested)
                        load_project_env()
                    finally:
                        os.chdir(old_cwd)
                    self.assertEqual(
                        os.environ["INDIAN_KANOON_API_TOKEN"],
                        "test-token-placeholder",
                    )

    def test_check_config_reports_configured_without_printing_token(self) -> None:
        output = io.StringIO()
        with patch.dict(
            os.environ,
            {"INDIAN_KANOON_API_TOKEN": "test-token-placeholder"},
            clear=True,
        ):
            with redirect_stdout(output):
                result = check_config()

        self.assertEqual(result, 0)
        self.assertIn("token is configured", output.getvalue())
        self.assertNotIn("test-token-placeholder", output.getvalue())


if __name__ == "__main__":
    unittest.main()
