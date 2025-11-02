"""
Wallet Portfolio Tracker - Multi-chain portfolio aggregation with valuations

x402-enabled microservice for comprehensive wallet tracking
"""
import logging
import os
import asyncio
from datetime import datetime
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from web3 import Web3

from .balance_fetcher import BalanceFetcher
from .portfolio_aggregator import PortfolioAggregator
from .x402_middleware_dual import X402Middleware

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize FastAPI
app = FastAPI(
    title="Wallet Portfolio Tracker",
    description="Multi-chain wallet portfolio aggregation with real-time valuations across 7+ chains",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration
FREE_MODE = os.getenv("FREE_MODE", "true").lower() == "true"
PAYMENT_ADDRESS = os.getenv("PAYMENT_ADDRESS", "0x01D11F7e1a46AbFC6092d7be484895D2d505095c")
PORT = int(os.getenv("PORT", "8000"))
BASE_URL = os.getenv("BASE_URL", f"http://localhost:{PORT}")
PRICE_ORACLE_URL = os.getenv("PRICE_ORACLE_URL", "https://price-oracle-production-9e7c.up.railway.app")

# RPC URLs
RPC_URLS = {
    1: os.getenv("ETHEREUM_RPC_URL", "https://eth.llamarpc.com"),
    56: os.getenv("BSC_RPC_URL", "https://bsc-dataseed1.binance.org"),
    137: os.getenv("POLYGON_RPC_URL", "https://polygon-rpc.com"),
    42161: os.getenv("ARBITRUM_RPC_URL", "https://arb1.arbitrum.io/rpc"),
    10: os.getenv("OPTIMISM_RPC_URL", "https://mainnet.optimism.io"),
    8453: os.getenv("BASE_RPC_URL", "https://mainnet.base.org"),
    43114: os.getenv("AVALANCHE_RPC_URL", "https://api.avax.network/ext/bc/C/rpc"),
}

# Initialize services with RPC URLs (lazy loading)
balance_fetcher = BalanceFetcher(RPC_URLS)
portfolio_aggregator = PortfolioAggregator(PRICE_ORACLE_URL)

if FREE_MODE:
    logger.warning("Running in FREE MODE - no payment verification")
else:
    logger.info("x402 payment verification enabled")

logger.info(f"Portfolio tracker initialized with {len(RPC_URLS)} chains")
logger.info(f"PORT from environment: {PORT}")
logger.info(f"BASE_URL: {BASE_URL}")

# x402 Payment Middleware
payment_address = PAYMENT_ADDRESS
base_url = BASE_URL.rstrip('/')

app.add_middleware(
    X402Middleware,
    payment_address=payment_address,
    base_url=base_url,
    facilitator_urls=[
        "https://facilitator.daydreams.systems",
        "https://api.cdp.coinbase.com/platform/v2/x402/facilitator"
    ],
    free_mode=FREE_MODE,
)


# Request/Response Models
class PortfolioRequest(BaseModel):
    """Portfolio query request"""
    wallet_address: str = Field(..., description="Wallet address to track")
    chains: Optional[List[int]] = Field(
        default=None,
        description="Specific chains to check (default: all supported chains)"
    )
    tokens: Optional[List[str]] = Field(
        default=None,
        description="Specific token addresses to check (optional)"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "wallet_address": "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
                "chains": [1, 137, 42161],
                "tokens": ["0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"]
            }
        }


class PortfolioResponse(BaseModel):
    """Portfolio response"""
    wallet_address: str
    total_value_usd: float
    chains_count: int
    tokens_count: int
    native_value_usd: float
    erc20_value_usd: float
    breakdown_by_chain: list
    breakdown_by_token: list
    warnings: list
    timestamp: str


# API Endpoints
@app.get("/", response_class=HTMLResponse)
async def landing_page():
    """Landing page with metadata"""
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Wallet Portfolio Tracker</title>
        <meta property="og:title" content="Wallet Portfolio Tracker">
        <meta property="og:description" content="Multi-chain wallet portfolio aggregation with real-time valuations via x402 micropayments">
        <meta property="og:image" content="https://portfolio-tracker-production-5c56.up.railway.app/favicon.ico">
        <link rel="icon" href="/favicon.ico" type="image/svg+xml">
        <style>
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
                max-width: 800px;
                margin: 50px auto;
                padding: 20px;
                background: #f5f5f5;
            }
            .container {
                background: white;
                padding: 40px;
                border-radius: 10px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            }
            h1 {
                color: #333;
                margin-bottom: 20px;
            }
            p {
                color: #666;
                line-height: 1.6;
            }
            .emoji {
                font-size: 48px;
                margin-bottom: 20px;
            }
            .links {
                margin-top: 30px;
            }
            a {
                color: #0066cc;
                text-decoration: none;
                margin-right: 20px;
            }
            a:hover {
                text-decoration: underline;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="emoji">💼</div>
            <h1>Wallet Portfolio Tracker</h1>
            <p>Multi-chain wallet portfolio aggregation with real-time valuations via x402 micropayments.</p>
            <p>Track your entire crypto portfolio across 7+ chains with automatic price fetching and comprehensive breakdowns.</p>
            <div class="links">
                <a href="/docs">API Documentation</a>
                <a href="/.well-known/agent.json">Agent Metadata</a>
                <a href="/.well-known/x402">x402 Metadata</a>
            </div>
        </div>
    </body>
    </html>
    """


@app.get("/favicon.ico")
async def favicon():
    """Favicon endpoint returning SVG with emoji"""
    svg = """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
        <text y="85" font-size="90">💼</text>
    </svg>
    """
    return Response(content=svg, media_type="image/svg+xml")


@app.get("/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "portfolio-tracker",
        "version": "1.0.0",
        "free_mode": FREE_MODE,
        "supported_chains": len(RPC_URLS),
        "chain_ids": list(RPC_URLS.keys())
    }


@app.get("/entrypoints/portfolio-tracker/invoke")
async def get_portfolio_metadata():
    """Returns HTTP 402 with x402 metadata for portfolio tracker entrypoint"""
    return Response(
        status_code=402,
        content='{"error": "Payment Required"}',
        media_type="application/json",
        headers={
            "X-402-Accepts": "base:USDC",
            "X-402-Price": "50000",
            "X-402-Pay-To": payment_address,
            "X-402-Asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            "X-402-Output-Schema": str({
                "input": {
                    "type": "http",
                    "method": "POST",
                    "bodyType": "json",
                    "bodyFields": {
                        "wallet_address": {
                            "type": "string",
                            "required": True,
                            "description": "Wallet address to track"
                        },
                        "chains": {
                            "type": "array",
                            "required": False,
                            "description": "Specific chains to check (default: all supported chains)"
                        },
                        "tokens": {
                            "type": "array",
                            "required": False,
                            "description": "Specific token addresses to check (optional)"
                        }
                    }
                },
                "output": {
                    "type": "object",
                    "description": "Comprehensive wallet portfolio with total value, breakdowns by chain and token"
                }
            })
        }
    )


@app.post(
    "/entrypoints/portfolio-tracker/invoke",
    response_model=PortfolioResponse,
    summary="Get Wallet Portfolio",
    description="Get comprehensive wallet portfolio across multiple chains with valuations"
)
async def get_portfolio(request: PortfolioRequest):
    """
    Get wallet portfolio across multiple chains

    This endpoint:
    - Fetches native token balances (ETH, BNB, MATIC, etc)
    - Fetches ERC20 token balances (if specified)
    - Gets real-time prices from price oracle
    - Calculates total portfolio value
    - Provides breakdown by chain and by token

    Returns:
    - Total portfolio value in USD
    - Native vs ERC20 breakdown
    - Per-chain breakdown with balances
    - Per-token breakdown across all chains
    - Warnings for missing data or issues

    Useful for:
    - Portfolio tracking
    - Net worth calculation
    - Asset allocation analysis
    - Multi-chain balance checking
    """
    try:
        logger.info(f"Fetching portfolio for {request.wallet_address}")

        # Determine which chains to check
        chains_to_check = request.chains if request.chains else list(RPC_URLS.keys())

        # Fetch balances across all chains in parallel
        tasks = []
        for chain_id in chains_to_check:
            if chain_id in RPC_URLS:
                task = balance_fetcher.get_wallet_tokens(
                    request.wallet_address,
                    chain_id,
                    request.tokens
                )
                tasks.append(task)

        # Execute in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Flatten results
        all_balances = []
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Balance fetch error: {result}")
                continue
            if isinstance(result, list):
                all_balances.extend(result)

        # Aggregate portfolio
        portfolio = await portfolio_aggregator.aggregate_portfolio(
            request.wallet_address,
            all_balances
        )

        # Add timestamp
        portfolio.timestamp = datetime.utcnow().isoformat() + "Z"

        return PortfolioResponse(
            wallet_address=portfolio.wallet_address,
            total_value_usd=portfolio.total_value_usd,
            chains_count=portfolio.chains_count,
            tokens_count=portfolio.tokens_count,
            native_value_usd=portfolio.native_value_usd,
            erc20_value_usd=portfolio.erc20_value_usd,
            breakdown_by_chain=portfolio.breakdown_by_chain,
            breakdown_by_token=portfolio.breakdown_by_token,
            warnings=portfolio.warnings,
            timestamp=portfolio.timestamp
        )

    except Exception as e:
        logger.error(f"Portfolio fetch error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Portfolio fetch failed: {str(e)}")


# Agent Discovery Endpoints
@app.get("/.well-known/agent.json")
async def agent_metadata():
    """Agent metadata for service discovery"""
    return {
        "name": "Wallet Portfolio Tracker",
        "description": "Multi-chain wallet portfolio aggregation with real-time valuations. Track your entire crypto portfolio across 7+ chains with automatic price fetching and comprehensive breakdowns.",
        "url": f"{base_url}/",
        "version": "1.0.0",
        "capabilities": {
            "streaming": False,
            "pushNotifications": False,
            "stateTransitionHistory": True,
            "extensions": [
                {
                    "uri": "https://github.com/google-agentic-commerce/ap2/tree/v0.1",
                    "description": "Agent Payments Protocol (AP2)",
                    "required": True,
                    "params": {"roles": ["merchant"]}
                }
            ]
        },
        "defaultInputModes": ["application/json"],
        "defaultOutputModes": ["application/json"],
        "entrypoints": {
            "portfolio-tracker": {
                "description": "Get wallet portfolio across multiple chains",
                "streaming": False,
                "input_schema": {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "type": "object",
                    "properties": {
                        "wallet_address": {"type": "string"},
                        "chains": {"type": "array", "items": {"type": "integer"}},
                        "tokens": {"type": "array", "items": {"type": "string"}}
                    },
                    "required": ["wallet_address"]
                },
                "output_schema": {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "type": "object",
                    "properties": {
                        "total_value_usd": {"type": "number"},
                        "chains_count": {"type": "integer"},
                        "breakdown_by_chain": {"type": "array"},
                        "breakdown_by_token": {"type": "array"}
                    }
                },
                "pricing": {"invoke": "0.05 USDC"}
            }
        },
        "payments": [
            {
                "method": "x402",
                "payee": payment_address,
                "network": "base",
                "endpoint": "https://facilitator.daydreams.systems",
                "priceModel": {"default": "0.05"},
                "extensions": {
                    "x402": {"facilitatorUrl": "https://facilitator.daydreams.systems"}
                }
            }
        ]
    }


@app.get("/.well-known/x402")
async def x402_metadata():
    """x402 payment metadata"""
    return {
        "x402Version": 1,
        "accepts": [
            {
                "scheme": "exact",
                "network": "base",
                "maxAmountRequired": "50000",  # 0.05 USDC
                "resource": f"{base_url}/entrypoints/portfolio-tracker/invoke",
                "description": "Multi-chain wallet portfolio with automatic valuations and comprehensive breakdowns",
                "mimeType": "application/json",
                "payTo": payment_address,
                "maxTimeoutSeconds": 30,
                "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",  # USDC on Base
                "outputSchema": {
                    "input": {
                        "type": "http",
                        "method": "POST",
                        "bodyType": "json",
                        "bodyFields": {
                            "wallet_address": {
                                "type": "string",
                                "required": True,
                                "description": "Wallet address to track"
                            },
                            "chains": {
                                "type": "array",
                                "required": False,
                                "description": "Specific chains to check"
                            }
                        }
                    },
                    "output": {
                        "type": "object",
                        "properties": {
                            "total_value_usd": {"type": "number"},
                            "chains_count": {"type": "integer"},
                            "breakdown_by_chain": {"type": "array"}
                        }
                    }
                },
                "extra": {
                    "supported_chains": [1, 56, 137, 42161, 10, 8453, 43114],
                    "features": [
                        "multi_chain_aggregation",
                        "automatic_pricing",
                        "native_token_tracking",
                        "erc20_token_tracking",
                        "portfolio_breakdown",
                        "total_value_calculation"
                    ],
                    "integrations": ["price_oracle"]
                }
            }
        ]
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
