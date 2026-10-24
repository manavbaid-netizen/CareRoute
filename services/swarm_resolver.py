from __future__ import annotations

import logging

from uagents.crypto import Identity
from uagents.resolver import GlobalResolver, Resolver

from config import Config

logger = logging.getLogger("CareRoute.SwarmResolver")


class SwarmResolver(Resolver):
    """
    Composite resolver that maps internal CareRoute swarm agents to their local HTTP endpoints,
    while delegating external agent/user addresses (ASI:One) to GlobalResolver.
    """

    def __init__(
        self,
        routes: dict[str, str] | None = None,
        fallback: Resolver | None = None,
    ):
        self._routes: dict[str, str] = routes or {}
        self._fallback: Resolver = fallback or GlobalResolver()

    def update_routes(self, routes: dict[str, str]) -> None:
        self._routes.update(routes)

    async def resolve(self, destination: str) -> tuple[str | None, list[str]]:
        if destination in self._routes:
            endpoint = self._routes[destination]
            endpoints = [endpoint] if isinstance(endpoint, str) else list(endpoint)
            return destination, endpoints

        # Fallback to Global Almanac Resolver for external ASI:One users
        return await self._fallback.resolve(destination)


def get_swarm_routes() -> dict[str, str]:
    """Calculate deterministic local endpoints for the 4 CareRoute swarm agents."""
    disp_addr = Identity.from_seed(Config.DISPATCHER_SEED, 0).address
    diag_addr = Identity.from_seed(Config.DIAGNOSTIC_SEED, 0).address
    logi_addr = Identity.from_seed(Config.LOGISTICS_SEED, 0).address
    escr_addr = Identity.from_seed(Config.ESCROW_SEED, 0).address

    return {
        disp_addr: f"http://127.0.0.1:{Config.DISPATCHER_PORT}/submit",
        diag_addr: f"http://127.0.0.1:{Config.DIAGNOSTIC_PORT}/submit",
        logi_addr: f"http://127.0.0.1:{Config.LOGISTICS_PORT}/submit",
        escr_addr: f"http://127.0.0.1:{Config.ESCROW_PORT}/submit",
    }


def make_swarm_resolver() -> SwarmResolver:
    """Create a configured SwarmResolver instance with all local routes."""
    return SwarmResolver(routes=get_swarm_routes())
