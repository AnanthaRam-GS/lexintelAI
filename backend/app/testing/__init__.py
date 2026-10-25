"""Test-only code for the browser end-to-end runs (step 17, TEST-002).

Nothing here is imported by the application unless ``LEGALAI_E2E_FAKE_PROVIDERS=1`` and ``APP_ENV=test``
(``backend/main.py`` checks both before the import; the startup check refuses the flag in any other environment).
"""
