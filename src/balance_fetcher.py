"""
Multi-Chain Balance Fetcher - Get native and token balances across chains
"""
import logging
from typing import Dict, List, Optional
from web3 import Web3
from decimal import Decimal

logger = logging.getLogger(__name__)


class BalanceFetcher:
    """Fetch wallet balances across multiple chains"""

    # ERC20 ABI (minimal)
    ERC20_ABI = [
        {
            "constant": True,
            "inputs": [{"name": "_owner", "type": "address"}],
            "name": "balanceOf",
            "outputs": [{"name": "balance", "type": "uint256"}],
            "type": "function"
        },
        {
            "constant": True,
            "inputs": [],
            "name": "decimals",
            "outputs": [{"name": "", "type": "uint8"}],
            "type": "function"
        },
        {
            "constant": True,
            "inputs": [],
            "name": "symbol",
            "outputs": [{"name": "", "type": "string"}],
            "type": "function"
        },
        {
            "constant": True,
            "inputs": [],
            "name": "name",
            "outputs": [{"name": "", "type": "string"}],
            "type": "function"
        }
    ]

    # Chain configurations
    CHAIN_CONFIG = {
        1: {"name": "Ethereum", "symbol": "ETH", "decimals": 18},
        56: {"name": "BNB Chain", "symbol": "BNB", "decimals": 18},
        137: {"name": "Polygon", "symbol": "MATIC", "decimals": 18},
        42161: {"name": "Arbitrum", "symbol": "ETH", "decimals": 18},
        10: {"name": "Optimism", "symbol": "ETH", "decimals": 18},
        8453: {"name": "Base", "symbol": "ETH", "decimals": 18},
        43114: {"name": "Avalanche", "symbol": "AVAX", "decimals": 18},
    }

    def __init__(self, rpc_urls: Dict[int, str]):
        """
        Initialize with RPC URLs (lazy loading)

        Args:
            rpc_urls: Dict mapping chain_id to RPC URL
        """
        self.rpc_urls = rpc_urls
        self.w3_instances = {}  # Cache for lazy-loaded instances

    def _get_w3(self, chain_id: int) -> Optional[Web3]:
        """Get or create Web3 instance for chain (lazy loading)"""
        if chain_id in self.w3_instances:
            return self.w3_instances[chain_id]

        rpc_url = self.rpc_urls.get(chain_id)
        if not rpc_url:
            return None

        try:
            w3 = Web3(Web3.HTTPProvider(rpc_url))
            self.w3_instances[chain_id] = w3
            logger.info(f"Initialized Web3 for chain {chain_id}")
            return w3
        except Exception as e:
            logger.error(f"Failed to initialize Web3 for chain {chain_id}: {e}")
            return None

    async def get_native_balance(
        self,
        wallet_address: str,
        chain_id: int
    ) -> Dict:
        """
        Get native token balance (ETH, BNB, MATIC, etc)

        Args:
            wallet_address: Wallet address
            chain_id: Blockchain ID

        Returns:
            Dict with balance data
        """
        try:
            w3 = self._get_w3(chain_id)
            if not w3:
                return {
                    "chain_id": chain_id,
                    "error": f"Chain {chain_id} not supported or failed to initialize"
                }

            chain_info = self.CHAIN_CONFIG.get(chain_id, {})

            # Normalize address
            address = self._normalize_address(wallet_address)

            # Get balance
            balance_wei = w3.eth.get_balance(address)
            balance = Decimal(balance_wei) / Decimal(10 ** chain_info.get("decimals", 18))

            return {
                "chain_id": chain_id,
                "chain_name": chain_info.get("name", f"Chain {chain_id}"),
                "token_type": "native",
                "symbol": chain_info.get("symbol", "UNKNOWN"),
                "balance": float(balance),
                "balance_wei": int(balance_wei),
                "decimals": chain_info.get("decimals", 18),
                "contract_address": None
            }

        except Exception as e:
            logger.error(f"Native balance fetch error on chain {chain_id}: {e}")
            return {
                "chain_id": chain_id,
                "error": str(e)
            }

    async def get_token_balance(
        self,
        wallet_address: str,
        token_address: str,
        chain_id: int
    ) -> Dict:
        """
        Get ERC20 token balance

        Args:
            wallet_address: Wallet address
            token_address: Token contract address
            chain_id: Blockchain ID

        Returns:
            Dict with token balance data
        """
        try:
            w3 = self._get_w3(chain_id)
            if not w3:
                return {
                    "chain_id": chain_id,
                    "error": f"Chain {chain_id} not supported or failed to initialize"
                }

            # Normalize addresses
            wallet = self._normalize_address(wallet_address)
            token = self._normalize_address(token_address)

            # Create contract instance
            contract = w3.eth.contract(address=token, abi=self.ERC20_ABI)

            # Get balance
            balance_raw = contract.functions.balanceOf(wallet).call()

            # Get token metadata
            try:
                decimals = contract.functions.decimals().call()
            except:
                decimals = 18

            try:
                symbol = contract.functions.symbol().call()
            except:
                symbol = "UNKNOWN"

            try:
                name = contract.functions.name().call()
            except:
                name = "Unknown Token"

            # Calculate human-readable balance
            balance = Decimal(balance_raw) / Decimal(10 ** decimals)

            return {
                "chain_id": chain_id,
                "chain_name": self.CHAIN_CONFIG.get(chain_id, {}).get("name", f"Chain {chain_id}"),
                "token_type": "erc20",
                "contract_address": token_address.lower(),
                "symbol": symbol,
                "name": name,
                "balance": float(balance),
                "balance_raw": int(balance_raw),
                "decimals": decimals
            }

        except Exception as e:
            logger.error(f"Token balance fetch error: {e}")
            return {
                "chain_id": chain_id,
                "contract_address": token_address.lower(),
                "error": str(e)
            }

    async def get_wallet_tokens(
        self,
        wallet_address: str,
        chain_id: int,
        token_addresses: Optional[List[str]] = None
    ) -> List[Dict]:
        """
        Get all token balances for a wallet

        Args:
            wallet_address: Wallet address
            chain_id: Blockchain ID
            token_addresses: Optional list of specific tokens to check

        Returns:
            List of token balances
        """
        balances = []

        # Always get native balance
        native_balance = await self.get_native_balance(wallet_address, chain_id)
        if not native_balance.get("error"):
            balances.append(native_balance)

        # Get specified token balances
        if token_addresses:
            for token_address in token_addresses:
                token_balance = await self.get_token_balance(
                    wallet_address,
                    token_address,
                    chain_id
                )
                # Only include if balance > 0 or no error
                if not token_balance.get("error"):
                    if token_balance.get("balance", 0) > 0:
                        balances.append(token_balance)

        return balances

    def _normalize_address(self, address: str) -> str:
        """Simple address normalization"""
        address = address.strip()
        if not address.startswith('0x') or len(address) != 42:
            raise ValueError(f"Invalid address: {address}")
        return address
