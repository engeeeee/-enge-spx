"""Public identity and the previous release's on-disk compatibility identifiers."""
from pathlib import Path

APP_NAME = "ENGE SPX"
APP_ID = "ENGE.SPX"
MAINTAINER = "engeeeee"
REPOSITORY = "engeeeee/-enge-spx"
PROJECT_URL = "https://github.com/" + REPOSITORY
DATA_DIRECTORY = "ENGE-SPX"
PACKAGE_RESOURCES = Path(__file__).resolve().parent / "resources"
ICONS = PACKAGE_RESOURCES / "icons"
CONTAINERS = PACKAGE_RESOURCES / "containers"

# Compatibility values are deliberately kept for existing 0.1/0.2 installations.
# Their containers, mounts and browser protocol must survive the product rename.
LEGACY_DATA_DIRECTORY = "EgressWorkbenchWindows"
LEGACY_APP_ID = "EgressWorkbench.Windows"
LEGACY_LABEL_ROOT = "io.egress-workbench.windows"
