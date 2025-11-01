"""
Portfolio Aggregator - Aggregate balances and calculate total value
"""
import logging
import aiohttp
from typing import Dict, List, Optional
from dataclasses import dataclass
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class PortfolioSummary:
    """Portfolio summary result"""
    wallet_address: str
    total_value_usd: float
    chains_count: int
    tokens_count: int
    native_value_usd: float
    erc20_value_usd: float
    breakdown_by_chain: List[Dict]
    breakdown_by_token: List[Dict]
    warnings: List[str]
    timestamp: str


class PortfolioAggregator:
    """Aggregate portfolio balances and calculate total value"""

    def __init__(self, price_oracle_url: Optional[str] = None):
        """
        Initialize aggregator

        Args:
            price_oracle_url: URL of price oracle service (optional)
        """
        self.price_oracle_url = price_oracle_url

    async def aggregate_portfolio(
        self,
        wallet_address: str,
        balances: List[Dict]
    ) -> PortfolioSummary:
        """
        Aggregate portfolio balances and calculate total value

        Args:
            wallet_address: Wallet address
            balances: List of balance data from all chains

        Returns:
            PortfolioSummary with aggregated data
        """
        # Filter out errors
        valid_balances = [b for b in balances if not b.get("error")]

        if not valid_balances:
            return self._create_empty_portfolio(wallet_address, balances)

        # Fetch prices for all tokens
        balances_with_prices = await self._enrich_with_prices(valid_balances)

        # Calculate totals
        total_value = sum(b.get("value_usd", 0) for b in balances_with_prices)
        native_value = sum(
            b.get("value_usd", 0) for b in balances_with_prices
            if b.get("token_type") == "native"
        )
        erc20_value = sum(
            b.get("value_usd", 0) for b in balances_with_prices
            if b.get("token_type") == "erc20"
        )

        # Group by chain
        by_chain = defaultdict(lambda: {"value_usd": 0, "tokens": []})
        for balance in balances_with_prices:
            chain_id = balance["chain_id"]
            by_chain[chain_id]["chain_id"] = chain_id
            by_chain[chain_id]["chain_name"] = balance.get("chain_name", f"Chain {chain_id}")
            by_chain[chain_id]["value_usd"] += balance.get("value_usd", 0)
            by_chain[chain_id]["tokens"].append({
                "symbol": balance.get("symbol"),
                "balance": balance.get("balance"),
                "value_usd": balance.get("value_usd", 0)
            })

        # Sort by value
        breakdown_by_chain = sorted(
            list(by_chain.values()),
            key=lambda x: x["value_usd"],
            reverse=True
        )

        # Group by token (across all chains)
        by_token = defaultdict(lambda: {"balance": 0, "value_usd": 0, "chains": []})
        for balance in balances_with_prices:
            symbol = balance.get("symbol", "UNKNOWN")
            by_token[symbol]["symbol"] = symbol
            by_token[symbol]["balance"] += balance.get("balance", 0)
            by_token[symbol]["value_usd"] += balance.get("value_usd", 0)
            by_token[symbol]["chains"].append(balance.get("chain_name"))

        breakdown_by_token = sorted(
            list(by_token.values()),
            key=lambda x: x["value_usd"],
            reverse=True
        )

        # Generate warnings
        warnings = self._generate_warnings(balances_with_prices, total_value)

        # Count unique values
        chains_count = len(set(b["chain_id"] for b in valid_balances))
        tokens_count = len(valid_balances)

        return PortfolioSummary(
            wallet_address=wallet_address,
            total_value_usd=round(total_value, 2),
            chains_count=chains_count,
            tokens_count=tokens_count,
            native_value_usd=round(native_value, 2),
            erc20_value_usd=round(erc20_value, 2),
            breakdown_by_chain=breakdown_by_chain,
            breakdown_by_token=breakdown_by_token,
            warnings=warnings,
            timestamp=""  # Will be set by caller
        )

    async def _enrich_with_prices(self, balances: List[Dict]) -> List[Dict]:
        """Fetch prices and add value_usd to each balance"""
        enriched = []

        for balance in balances:
            balance_copy = balance.copy()

            # Get price
            price_usd = await self._get_token_price(
                balance.get("contract_address") or "native",
                balance.get("chain_id"),
                balance.get("symbol")
            )

            # Calculate value
            if price_usd is not None and balance.get("balance"):
                balance_copy["price_usd"] = price_usd
                balance_copy["value_usd"] = price_usd * balance.get("balance", 0)
            else:
                balance_copy["price_usd"] = None
                balance_copy["value_usd"] = 0

            enriched.append(balance_copy)

        return enriched

    async def _get_token_price(
        self,
        token_address: str,
        chain_id: int,
        symbol: str
    ) -> Optional[float]:
        """
        Get token price from price oracle or fallback

        Args:
            token_address: Token address or "native"
            chain_id: Chain ID
            symbol: Token symbol

        Returns:
            Price in USD or None
        """
        # If we have price oracle URL, use it
        if self.price_oracle_url and token_address != "native":
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        f"{self.price_oracle_url}/entrypoints/price-oracle/invoke",
                        json={
                            "token_address": token_address,
                            "chain_id": chain_id
                        },
                        timeout=aiohttp.ClientTimeout(total=10)
                    ) as response:
                        if response.status == 200:
                            data = await response.json()
                            return data.get("price_usd")
            except Exception as e:
                logger.warning(f"Price oracle fetch failed: {e}")

        # Fallback to hardcoded prices for major tokens
        return self._get_fallback_price(symbol)

    def _get_fallback_price(self, symbol: str) -> Optional[float]:
        """Fallback prices for major tokens (rough estimates)"""
        fallback_prices = {
            "ETH": 3000.0,
            "BNB": 600.0,
            "MATIC": 1.0,
            "AVAX": 40.0,
            "USDC": 1.0,
            "USDT": 1.0,
            "DAI": 1.0,
            "WETH": 3000.0,
            "WBNB": 600.0,
            "WMATIC": 1.0,
        }
        return fallback_prices.get(symbol)

    def _generate_warnings(
        self,
        balances: List[Dict],
        total_value: float
    ) -> List[str]:
        """Generate warnings about portfolio"""
        warnings = []

        # Check for tokens without prices
        no_price_count = sum(1 for b in balances if b.get("price_usd") is None)
        if no_price_count > 0:
            warnings.append(
                f"ℹ️ {no_price_count} token(s) missing price data - using fallback estimates"
            )

        # Check for low total value
        if total_value < 1:
            warnings.append(
                "ℹ️ Portfolio value below $1 USD"
            )

        # Check for concentration
        if balances:
            max_value = max(b.get("value_usd", 0) for b in balances)
            if total_value > 0 and (max_value / total_value) > 0.9:
                warnings.append(
                    "⚠️ Portfolio highly concentrated in single asset"
                )

        return warnings

    def _create_empty_portfolio(
        self,
        wallet_address: str,
        balances: List[Dict]
    ) -> PortfolioSummary:
        """Create empty portfolio result"""
        errors = [b.get("error") for b in balances if b.get("error")]
        warnings = ["🚫 No valid balances found"]
        if errors:
            warnings.append(f"ℹ️ {len(errors)} chain(s) failed to fetch")

        return PortfolioSummary(
            wallet_address=wallet_address,
            total_value_usd=0.0,
            chains_count=0,
            tokens_count=0,
            native_value_usd=0.0,
            erc20_value_usd=0.0,
            breakdown_by_chain=[],
            breakdown_by_token=[],
            warnings=warnings,
            timestamp=""
        )
