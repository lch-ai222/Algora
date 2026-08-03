"""mini_store — a small inventory/ordering domain used as an internal SWE benchmark.

Cross-module by design: orders depend on inventory + cart + pricing + discounts, so a
realistic fix often spans reading several modules. Each seeded defect is localized to one
function and marked, so regression tests on the other modules stay green at the base commit.
"""

from mini_store.version import VERSION as __version__

__all__ = ["__version__"]
