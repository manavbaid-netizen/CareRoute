"""CareRoute Autonomous Agent Swarm.

Lazy module attributes via PEP 562 to prevent circular imports
and accidental multi-agent port-binding when running sub-agents individually.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agents.diagnostic_worker import diagnostic_worker
    from agents.dispatcher import dispatcher, set_worker_addresses
    from agents.escrow_worker import escrow_worker, execute_patient_checkin
    from agents.logistics_worker import logistics_worker

__all__ = [
    "diagnostic_worker",
    "dispatcher",
    "escrow_worker",
    "execute_patient_checkin",
    "logistics_worker",
    "set_worker_addresses",
]


def __getattr__(name: str) -> Any:
    if name == "diagnostic_worker":
        from agents.diagnostic_worker import diagnostic_worker as dw

        return dw
    if name == "dispatcher":
        from agents.dispatcher import dispatcher as disp

        return disp
    if name == "set_worker_addresses":
        from agents.dispatcher import set_worker_addresses as swa

        return swa
    if name == "escrow_worker":
        from agents.escrow_worker import escrow_worker as ew

        return ew
    if name == "execute_patient_checkin":
        from agents.escrow_worker import execute_patient_checkin as epc

        return epc
    if name == "logistics_worker":
        from agents.logistics_worker import logistics_worker as lw

        return lw
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
