"""Read-only compatibility with the already released Windows 0.2 runtime ABI.

New images use SPX paths and labels. These fixed recipe hashes identify the exact
previous images, allowing existing project writable layers and browser data to
stay in place during the branding migration.
"""
LEGACY_RECIPES = {
    "gateway": "748b028b2822",
    "work": "1772f9458ddd",
    "browser": "24f9e76b0177",
}
LEGACY_RUNTIME_DIRECTORY = "/opt/ewb"
LEGACY_BROWSER_TOKEN = "EWB_BROWSER_TOKEN"

