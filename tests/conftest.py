from unittest.mock import MagicMock
import uagents.network
import uagents.agent

# Mock ledger and almanac contract during tests to prevent TCP timeout when offline
mock_ledger = MagicMock()
uagents.network.get_ledger = MagicMock(return_value=mock_ledger)
uagents.network.get_almanac_contract = MagicMock(return_value=None)
uagents.agent.get_ledger = MagicMock(return_value=mock_ledger)
uagents.agent.get_almanac_contract = MagicMock(return_value=None)
