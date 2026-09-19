"""Which edition (Free / Starter / Pro / Studio) this copy of ftw-slo is.

The kit build writes _edition.py into each edition; this repository is the Free edition.
"""
try:
    from ._edition import ALL_TEMPLATES, EDITION
except ImportError:  # source checkout
    EDITION = "free"
    ALL_TEMPLATES = {}

RANK = {"free": 0, "starter": 1, "pro": 2, "studio": 3}
FEATURES = {
    "crd": "pro",
    "dashboards": "pro",
    "importers": "pro",
    "tenancy": "studio",
    "report": "studio",
    "helm": "studio",
}


def has(feature):
    return RANK[EDITION] >= RANK[FEATURES[feature]]


def missing_message(feature, what):
    return f"{what} is included in the {FEATURES[feature].title()} edition (this is {EDITION.title()})"
