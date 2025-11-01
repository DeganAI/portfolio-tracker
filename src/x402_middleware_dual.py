"""
x402 Payment Verification Middleware - Dual Facilitator Support

Verifies payments via both Daydreams and Coinbase CDP facilitators
"""
import logging
import json
import base64
import aiohttp
from typing import Optional, List, Tuple
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


class X402Middleware(BaseHTTPMiddleware):
    """
    Middleware for x402 payment verification with dual facilitator support

    Tries multiple facilitators in order:
    1. Daydreams facilitator (primary)
    2. Coinbase CDP facilitator (fallback + Bazaar registration)
    """

    def __init__(
        self,
        app,
        payment_address: str,
        base_url: str,
        facilitator_urls: List[str] = None,
        free_mode: bool = False,
    ):
        super().__init__(app)
        self.payment_address = payment_address
        self.base_url = base_url
        self.free_mode = free_mode

        # Default to both facilitators if not specified
        if facilitator_urls is None:
            self.facilitator_urls = [
                "https://facilitator.daydreams.systems",
                "https://api.cdp.coinbase.com/platform/v2/x402/facilitator"
            ]
        else:
            self.facilitator_urls = facilitator_urls

        logger.info(f"x402 Middleware initialized (FREE_MODE={free_mode}, facilitators={self.facilitator_urls})")

    async def verify_payment_with_facilitator(
        self,
        facilitator_url: str,
        payment_header: str,
        resource_url: str,
        amount_required: str,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Verify payment via a specific facilitator

        Returns: (is_valid, error_message, facilitator_name)
        """
        try:
            # Decode X-Payment header
            try:
                payment_payload = json.loads(base64.b64decode(payment_header))
            except Exception as e:
                return False, f"Invalid payment header format: {str(e)}", None

            # Construct verification request
            verification_request = {
                "paymentPayload": payment_payload,
                "paymentRequirements": {
                    "scheme": "exact",
                    "network": "base",
                    "maxAmountRequired": amount_required,
                    "resource": resource_url,
                    "description": "x402 micropayment",
                    "mimeType": "application/json",
                    "payTo": self.payment_address,
                    "maxTimeoutSeconds": 30,
                    "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",  # USDC on Base
                }
            }

            # Call facilitator /verify endpoint
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{facilitator_url}/verify",
                    json=verification_request,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.debug(f"Facilitator {facilitator_url} returned {response.status}: {error_text}")
                        return False, f"Payment verification failed: {error_text}", None

                    result = await response.json()

                    if result.get("isValid"):
                        facilitator_name = facilitator_url.split("//")[1].split("/")[0]
                        logger.info(f"Payment verified via {facilitator_name} for payer: {result.get('payer')}")
                        return True, None, facilitator_name
                    else:
                        reason = result.get("invalidReason", "Unknown reason")
                        logger.debug(f"Payment invalid at {facilitator_url}: {reason}")
                        return False, reason, None

        except aiohttp.ClientError as e:
            logger.debug(f"Facilitator {facilitator_url} connection error: {str(e)}")
            return False, f"Facilitator unavailable: {str(e)}", None
        except Exception as e:
            logger.debug(f"Payment verification error with {facilitator_url}: {str(e)}")
            return False, f"Verification error: {str(e)}", None

    async def verify_payment(
        self,
        payment_header: str,
        resource_url: str,
        amount_required: str,
    ) -> tuple[bool, Optional[str]]:
        """
        Verify payment via all configured facilitators in order

        Returns: (is_valid, error_message)
        """
        last_error = "No facilitators configured"

        for facilitator_url in self.facilitator_urls:
            is_valid, error_message, facilitator_name = await self.verify_payment_with_facilitator(
                facilitator_url=facilitator_url,
                payment_header=payment_header,
                resource_url=resource_url,
                amount_required=amount_required,
            )

            if is_valid:
                # Payment verified successfully
                return True, None

            # Store error for reporting if all facilitators fail
            last_error = error_message

        # All facilitators failed
        logger.warning(f"Payment verification failed with all facilitators. Last error: {last_error}")
        return False, last_error

    def create_402_response(self, resource_url: str, description: str) -> JSONResponse:
        """Create HTTP 402 Payment Required response"""
        metadata = {
            "x402Version": 1,
            "accepts": [
                {
                    "scheme": "exact",
                    "network": "base",
                    "maxAmountRequired": "50000",  # 0.05 USDC (6 decimals)
                    "resource": resource_url,
                    "description": description,
                    "mimeType": "application/json",
                    "payTo": self.payment_address,
                    "maxTimeoutSeconds": 30,
                    "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",  # USDC on Base
                }
            ]
        }
        return JSONResponse(content=metadata, status_code=402)

    async def dispatch(self, request: Request, call_next):
        """Process request and verify payment if required"""

        # Skip payment verification in free mode
        if self.free_mode:
            logger.debug("FREE_MODE enabled, skipping payment verification")
            return await call_next(request)

        # Skip verification for health check and metadata endpoints
        skip_paths = ["/health", "/.well-known", "/docs", "/redoc", "/openapi.json"]
        # Check for exact root path match separately
        if request.url.path == "/" or any(request.url.path.startswith(path) for path in skip_paths):
            return await call_next(request)

        # Check for payment endpoints (those that require payment)
        # These are typically POST endpoints that provide actual functionality
        requires_payment = (
            request.method == "POST" and
            "/entrypoints/" in request.url.path
        )

        if not requires_payment:
            # Allow GET requests through (they're for discovery/metadata)
            return await call_next(request)

        # Check for X-Payment header
        payment_header = request.headers.get("X-Payment")

        if not payment_header:
            logger.info(f"Payment required for {request.url.path}, no X-Payment header provided")
            return self.create_402_response(
                resource_url=str(request.url),
                description="Payment required to access this resource"
            )

        # Verify payment via facilitators
        is_valid, error_message = await self.verify_payment(
            payment_header=payment_header,
            resource_url=str(request.url),
            amount_required="50000"  # 0.05 USDC
        )

        if not is_valid:
            logger.warning(f"Payment verification failed: {error_message}")
            return JSONResponse(
                status_code=402,
                content={
                    "error": "Payment verification failed",
                    "message": error_message,
                    "x402Version": 1,
                    "accepts": [{
                        "scheme": "exact",
                        "network": "base",
                        "maxAmountRequired": "50000",
                        "resource": str(request.url),
                        "description": "Payment required to access this resource",
                        "mimeType": "application/json",
                        "payTo": self.payment_address,
                        "maxTimeoutSeconds": 30,
                        "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
                    }]
                }
            )

        # Payment verified, proceed with request
        logger.info(f"Payment verified, processing request to {request.url.path}")
        return await call_next(request)
