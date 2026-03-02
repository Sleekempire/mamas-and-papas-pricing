"""
models/optimizer.py — Price optimisation gateway.

Re-exports the price simulation helpers from
optimisation/price_simulator.py as the canonical 'optimizer' entry point
per the modular spec:

    Step 3: Price optimisation
"""
from __future__ import annotations

from optimisation.price_simulator import (  # noqa: F401
    PricePoint,
    SimulationResult,
    simulate_prices,
)

__all__ = ["PricePoint", "SimulationResult", "simulate_prices"]
