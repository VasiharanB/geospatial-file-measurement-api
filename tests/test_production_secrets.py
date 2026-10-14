"""
Automated Tests for Missing and Default Production Secrets
==========================================================
Verifies that:
1. Missing API_KEY_PEPPER in production raises RuntimeError.
2. Default API_KEY_PEPPER in production raises RuntimeError.
3. Missing AUTH_SECRET_KEY in production raises RuntimeError.
4. Default AUTH_SECRET_KEY in production raises RuntimeError.
5. Secrets shorter than 32 characters in production raise RuntimeError.
6. Valid 32+ character secrets in production pass validation.
7. Default secrets in local development (is_prod=False) pass with warning.
8. Environment detection accurately flags production vs local development.
"""

import os
import pathlib
import sys
import unittest

WORKSPACE_DIR = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE_DIR))

from main import (
    DEV_DEFAULT_AUTH_SECRET,
    DEV_DEFAULT_PEPPER,
    is_production_environment,
    validate_production_secrets,
)


class TestProductionSecretsValidation(unittest.TestCase):
    def test_missing_pepper_in_production_raises_runtime_error(self):
        with self.assertRaises(RuntimeError) as ctx:
            validate_production_secrets(None, "valid_auth_secret_with_32_chars_minimum!", is_prod=True)
        self.assertIn("API_KEY_PEPPER is missing or using an insecure development default", str(ctx.exception))

    def test_empty_pepper_in_production_raises_runtime_error(self):
        with self.assertRaises(RuntimeError) as ctx:
            validate_production_secrets("   ", "valid_auth_secret_with_32_chars_minimum!", is_prod=True)
        self.assertIn("API_KEY_PEPPER is missing or using an insecure development default", str(ctx.exception))

    def test_default_pepper_in_production_raises_runtime_error(self):
        with self.assertRaises(RuntimeError) as ctx:
            validate_production_secrets(DEV_DEFAULT_PEPPER, "valid_auth_secret_with_32_chars_minimum!", is_prod=True)
        self.assertIn("API_KEY_PEPPER is missing or using an insecure development default", str(ctx.exception))

    def test_missing_auth_secret_in_production_raises_runtime_error(self):
        with self.assertRaises(RuntimeError) as ctx:
            validate_production_secrets("valid_pepper_secret_with_32_chars_min!", None, is_prod=True)
        self.assertIn("AUTH_SECRET_KEY is missing or using an insecure development default", str(ctx.exception))

    def test_empty_auth_secret_in_production_raises_runtime_error(self):
        with self.assertRaises(RuntimeError) as ctx:
            validate_production_secrets("valid_pepper_secret_with_32_chars_min!", "   ", is_prod=True)
        self.assertIn("AUTH_SECRET_KEY is missing or using an insecure development default", str(ctx.exception))

    def test_default_auth_secret_in_production_raises_runtime_error(self):
        with self.assertRaises(RuntimeError) as ctx:
            validate_production_secrets("valid_pepper_secret_with_32_chars_min!", DEV_DEFAULT_AUTH_SECRET, is_prod=True)
        self.assertIn("AUTH_SECRET_KEY is missing or using an insecure development default", str(ctx.exception))

    def test_short_pepper_in_production_raises_runtime_error(self):
        with self.assertRaises(RuntimeError) as ctx:
            validate_production_secrets("short_pepper_under_32", "valid_auth_secret_with_32_chars_minimum!", is_prod=True)
        self.assertIn("must be at least 32 characters", str(ctx.exception))

    def test_short_auth_secret_in_production_raises_runtime_error(self):
        with self.assertRaises(RuntimeError) as ctx:
            validate_production_secrets("valid_pepper_secret_with_32_chars_min!", "short_auth_under_32", is_prod=True)
        self.assertIn("must be at least 32 characters", str(ctx.exception))

    def test_valid_secrets_in_production_succeeds(self):
        # Should not raise any exception
        validate_production_secrets(
            "production_pepper_token_at_least_32_characters_long",
            "production_auth_secret_token_at_least_32_characters_long",
            is_prod=True,
        )

    def test_local_development_allows_defaults(self):
        # In development mode (is_prod=False), default secrets must be allowed
        validate_production_secrets(DEV_DEFAULT_PEPPER, DEV_DEFAULT_AUTH_SECRET, is_prod=False)

    def test_environment_detection(self):
        # Test ENVIRONMENT=production
        old_env = os.environ.get("ENVIRONMENT")
        try:
            os.environ["ENVIRONMENT"] = "production"
            self.assertTrue(is_production_environment())
            os.environ["ENVIRONMENT"] = "development"
            # When DATABASE_URL is sqlite, should return False
            if "DATABASE_URL" in os.environ and not os.environ["DATABASE_URL"].startswith("sqlite"):
                pass
            else:
                self.assertFalse(is_production_environment())
        finally:
            if old_env is not None:
                os.environ["ENVIRONMENT"] = old_env
            else:
                os.environ.pop("ENVIRONMENT", None)


if __name__ == "__main__":
    unittest.main()
