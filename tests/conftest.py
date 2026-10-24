import os
from unittest.mock import MagicMock

os.environ["CAREROUTE_TEST_MODE"] = "1"

import uagents.agent
import uagents.network

from config import Config

Config.USE_AGENTVERSE = False

# Mock ledger and almanac contract during tests to prevent TCP timeout when offline
mock_ledger = MagicMock()
uagents.network.get_ledger = MagicMock(return_value=mock_ledger)
uagents.network.get_almanac_contract = MagicMock(return_value=None)
uagents.agent.get_ledger = MagicMock(return_value=mock_ledger)
uagents.agent.get_almanac_contract = MagicMock(return_value=None)
