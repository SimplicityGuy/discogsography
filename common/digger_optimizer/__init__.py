"""Pure-function bundle optimizer for the Digger feature.

Imported by both api/ (interactive runs) and digger/ (scheduled runs).
No I/O — all dependencies pass in as Pydantic inputs.

Public API:
- pareto_bundles(input: OptimizerInput) -> OptimizerOutput   (added in the pareto module)

Submodules:
- models: input/output Pydantic types
- filtering: condition/price filter
- shipping: per-seller shipping cost estimation
- greedy: greedy reference implementation (also ILP warm-start)
- ilp: pulp-based optimal solver
- pareto: 4-variant coordinator

NOTE: ``pareto_bundles`` is re-exported from this package root once the pareto
module lands (Task 6). Until then only the model types are exported so the
package imports cleanly while the solver modules are built up incrementally.
"""

from __future__ import annotations

from common.digger_optimizer.models import (
    Bundle,
    BundleName,
    Coverage,
    Listing,
    OptimizerDiagnostics,
    OptimizerInput,
    OptimizerOutput,
    OrderLine,
    ReleaseConstraint,
    Seller,
    SellerOrder,
    ShippingPolicyRegion,
)


__all__ = [
    "Bundle",
    "BundleName",
    "Coverage",
    "Listing",
    "OptimizerDiagnostics",
    "OptimizerInput",
    "OptimizerOutput",
    "OrderLine",
    "ReleaseConstraint",
    "Seller",
    "SellerOrder",
    "ShippingPolicyRegion",
]
