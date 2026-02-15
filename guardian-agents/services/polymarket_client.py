"""
Polymarket Client — Lean wrapper for CLOB execution + Gamma market discovery.

Extracted from https://github.com/Polymarket/agents — only the pieces we need:
  - CLOB client init + credential derivation
  - On-chain token approvals (USDC + CTF → exchange contracts)
  - Gamma API for market/event discovery (find BTC 1h markets)
  - Order placement (limit + market)
  - Order selling (for early exits)
  - Balance checking

We do NOT use their LLM/RAG/superforecaster pipeline.
Our signal generation comes entirely from our own agents (Hawk, Quant, Sentinel).
"""

import logging
import time
from typing import Optional

import requests
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, MarketOrderArgs, OrderType
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

from config.settings import settings

logger = logging.getLogger(__name__)

# ── Polygon contract addresses (from Polymarket/agents) ──────────────────────
USDC_ADDRESS = Web3.to_checksum_address("0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174")
CTF_ADDRESS = Web3.to_checksum_address("0x4D97DCd97eC945f40cF65F87097ACe5EA0476045")
CTF_EXCHANGE = Web3.to_checksum_address("0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E")
NEG_RISK_CTF_EXCHANGE = Web3.to_checksum_address("0xC5d563A36AE78145C45a50134d48A1215220f80a")
NEG_RISK_ADAPTER = Web3.to_checksum_address("0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296")

# Standard ERC-20 approve ABI (only what we need)
ERC20_APPROVE_ABI = [
    {
        "inputs": [
            {"name": "spender", "type": "address"},
            {"name": "amount", "type": "uint256"},
        ],
        "name": "approve",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "owner", "type": "address"},
            {"name": "spender", "type": "address"},
        ],
        "name": "allowance",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "account", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]

# ERC-1155 setApprovalForAll ABI
ERC1155_APPROVAL_ABI = [
    {
        "inputs": [
            {"name": "operator", "type": "address"},
            {"name": "approved", "type": "bool"},
        ],
        "name": "setApprovalForAll",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "account", "type": "address"},
            {"name": "operator", "type": "address"},
        ],
        "name": "isApprovedForAll",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
]

MAX_ALLOWANCE = 2**256 - 1


class PolymarketClient:
    """
    Lean Polymarket execution client.

    Handles CLOB order placement and Gamma API market discovery.
    Does NOT make trading decisions — that's our agents' job.
    """

    def __init__(self):
        self._private_key = settings.polymarket.private_key
        self._chain_id = settings.polymarket.chain_id
        self._clob_url = settings.polymarket.host
        self._gamma_url = settings.polymarket.gamma_url

        self._clob: Optional[ClobClient] = None
        self._w3: Optional[Web3] = None
        self._wallet_address: Optional[str] = None
        self._initialized = False

    def initialize(self):
        """
        Initialize CLOB client, derive API credentials, set up Web3.
        Call once at startup.
        """
        if self._initialized:
            return

        if not self._private_key:
            logger.warning("No POLY_PRIVATE_KEY set — running in read-only mode")
            self._initialized = True
            return

        # Web3 for on-chain operations (approvals, balance checks)
        self._w3 = Web3(Web3.HTTPProvider(settings.polymarket.rpc_url))
        self._w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

        account = self._w3.eth.account.from_key(self._private_key)
        self._wallet_address = account.address
        logger.info(f"Polymarket wallet: {self._wallet_address}")

        # CLOB client
        self._clob = ClobClient(
            self._clob_url,
            key=self._private_key,
            chain_id=self._chain_id,
        )

        # Derive or load API credentials
        try:
            creds = self._clob.create_or_derive_api_creds()
            self._clob.set_api_creds(creds)
            logger.info("CLOB API credentials derived successfully")
        except Exception as e:
            logger.error(f"Failed to derive CLOB API credentials: {e}")
            raise

        self._initialized = True
        logger.info("PolymarketClient initialized")

    # ── Token approvals (one-time setup) ─────────────────────────────────────

    def ensure_approvals(self):
        """
        Approve USDC and CTF tokens to Polymarket exchange contracts.
        Checks existing allowances first — only sends tx if needed.
        """
        if not self._w3 or not self._wallet_address:
            logger.warning("No wallet configured — skipping approvals")
            return

        usdc = self._w3.eth.contract(address=USDC_ADDRESS, abi=ERC20_APPROVE_ABI)
        ctf = self._w3.eth.contract(address=CTF_ADDRESS, abi=ERC1155_APPROVAL_ABI)

        # Approve USDC to both exchanges
        for exchange_name, exchange_addr in [
            ("CTF Exchange", CTF_EXCHANGE),
            ("Neg Risk CTF Exchange", NEG_RISK_CTF_EXCHANGE),
        ]:
            allowance = usdc.functions.allowance(self._wallet_address, exchange_addr).call()
            if allowance < MAX_ALLOWANCE // 2:
                logger.info(f"Approving USDC to {exchange_name}...")
                self._send_approve_tx(usdc, exchange_addr, MAX_ALLOWANCE)
            else:
                logger.info(f"USDC already approved for {exchange_name}")

        # Approve CTF (ERC-1155) to both exchanges + neg risk adapter
        for operator_name, operator_addr in [
            ("CTF Exchange", CTF_EXCHANGE),
            ("Neg Risk CTF Exchange", NEG_RISK_CTF_EXCHANGE),
            ("Neg Risk Adapter", NEG_RISK_ADAPTER),
        ]:
            approved = ctf.functions.isApprovedForAll(self._wallet_address, operator_addr).call()
            if not approved:
                logger.info(f"Approving CTF to {operator_name}...")
                self._send_set_approval_tx(ctf, operator_addr)
            else:
                logger.info(f"CTF already approved for {operator_name}")

    def _send_approve_tx(self, contract, spender: str, amount: int):
        """Send an ERC-20 approve transaction."""
        tx = contract.functions.approve(spender, amount).build_transaction({
            "from": self._wallet_address,
            "nonce": self._w3.eth.get_transaction_count(self._wallet_address),
            "gas": 100_000,
            "gasPrice": self._w3.eth.gas_price,
            "chainId": self._chain_id,
        })
        signed = self._w3.eth.account.sign_transaction(tx, self._private_key)
        tx_hash = self._w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = self._w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        logger.info(f"Approve tx confirmed: {receipt.transactionHash.hex()}")

    def _send_set_approval_tx(self, contract, operator: str):
        """Send an ERC-1155 setApprovalForAll transaction."""
        tx = contract.functions.setApprovalForAll(operator, True).build_transaction({
            "from": self._wallet_address,
            "nonce": self._w3.eth.get_transaction_count(self._wallet_address),
            "gas": 100_000,
            "gasPrice": self._w3.eth.gas_price,
            "chainId": self._chain_id,
        })
        signed = self._w3.eth.account.sign_transaction(tx, self._private_key)
        tx_hash = self._w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = self._w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        logger.info(f"SetApprovalForAll tx confirmed: {receipt.transactionHash.hex()}")

    # ── Gamma API — market discovery ─────────────────────────────────────────

    def find_btc_hourly_market(self) -> Optional[dict]:
        """
        Search Gamma API for the currently active BTC 1-hour prediction market.

        Returns market dict with keys: condition_id, question, tokens, etc.
        Returns None if no active market found.
        """
        try:
            # Search for active BTC markets
            params = {
                "active": "true",
                "closed": "false",
                "archived": "false",
                "limit": 50,
            }
            resp = requests.get(
                f"{self._gamma_url}/markets",
                params=params,
                timeout=10,
            )
            resp.raise_for_status()
            markets = resp.json()

            # Filter for BTC hourly markets
            btc_hourly = []
            for m in markets:
                question = (m.get("question") or "").lower()
                description = (m.get("description") or "").lower()
                combined = question + " " + description

                is_btc = any(kw in combined for kw in ["btc", "bitcoin"])
                is_hourly = any(kw in combined for kw in [
                    "1 hour", "1-hour", "one hour", "hourly",
                    "next hour", "1h",
                ])
                is_up_down = any(kw in combined for kw in [
                    "up or down", "higher or lower", "above or below",
                    "increase", "decrease", "rise or fall",
                ])

                if is_btc and (is_hourly or is_up_down):
                    btc_hourly.append(m)

            if not btc_hourly:
                logger.warning("No active BTC hourly markets found on Polymarket")
                return None

            # Pick the one with the most liquidity / most recent
            best = max(btc_hourly, key=lambda m: float(m.get("volume", 0) or 0))

            # Normalize token structure
            tokens = []
            clob_token_ids = best.get("clobTokenIds", [])
            outcomes = best.get("outcomes", [])
            outcome_prices = best.get("outcomePrices", [])

            for i, token_id in enumerate(clob_token_ids):
                outcome = outcomes[i] if i < len(outcomes) else f"outcome_{i}"
                price_str = outcome_prices[i] if i < len(outcome_prices) else "0.5"
                tokens.append({
                    "token_id": token_id,
                    "outcome": outcome,
                    "price": float(price_str),
                })

            result = {
                "condition_id": best.get("conditionId"),
                "question_id": best.get("questionId"),
                "question": best.get("question"),
                "tokens": tokens,
                "end_date": best.get("endDate"),
                "volume": best.get("volume"),
                "liquidity": best.get("liquidity"),
            }

            logger.info(
                f"Found BTC market: {result['question']} | "
                f"Tokens: {len(tokens)} | Vol: {result['volume']}"
            )
            return result

        except requests.RequestException as e:
            logger.error(f"Gamma API request failed: {e}")
            return None
        except Exception as e:
            logger.error(f"Market discovery failed: {e}")
            return None

    # ── Order execution ──────────────────────────────────────────────────────

    def place_limit_order(
        self,
        token_id: str,
        side: str,
        size: float,
        price: float,
    ) -> Optional[dict]:
        """
        Place a limit order on the Polymarket CLOB.

        Args:
            token_id: The CLOB token ID (YES or NO token)
            side: "BUY" or "SELL"
            size: Number of shares
            price: Price per share (0.01 - 0.99)

        Returns:
            Order response dict or None on failure.
        """
        if not self._clob:
            logger.error("CLOB client not initialized")
            return None

        try:
            clob_side = side.upper()
            resp = self._clob.create_and_post_order(
                OrderArgs(
                    price=price,
                    size=size,
                    side=clob_side,
                    token_id=token_id,
                )
            )
            logger.info(
                f"Limit order placed: {clob_side} {size:.4f} @ ${price:.4f} "
                f"(token: {token_id[:12]}...)"
            )
            return resp
        except Exception as e:
            logger.error(f"Limit order failed: {e}")
            return None

    def place_market_order(
        self,
        token_id: str,
        amount: float,
    ) -> Optional[dict]:
        """
        Place a Fill-or-Kill market order on the Polymarket CLOB.

        Args:
            token_id: The CLOB token ID
            amount: USDC amount to spend

        Returns:
            Order response dict or None on failure.
        """
        if not self._clob:
            logger.error("CLOB client not initialized")
            return None

        try:
            order_args = MarketOrderArgs(token_id=token_id, amount=amount)
            signed_order = self._clob.create_market_order(order_args)
            resp = self._clob.post_order(signed_order, orderType=OrderType.FOK)
            logger.info(
                f"Market order placed: ${amount:.2f} USDC on {token_id[:12]}..."
            )
            return resp
        except Exception as e:
            logger.error(f"Market order failed: {e}")
            return None

    def get_order_book(self, token_id: str) -> Optional[dict]:
        """Fetch the order book for a token from the CLOB."""
        if not self._clob:
            return None
        try:
            return self._clob.get_order_book(token_id)
        except Exception as e:
            logger.error(f"Order book fetch failed: {e}")
            return None

    def get_price(self, token_id: str) -> Optional[float]:
        """Get the current mid price for a token from the CLOB."""
        if not self._clob:
            return None
        try:
            book = self._clob.get_order_book(token_id)
            if book:
                bids = book.get("bids", [])
                asks = book.get("asks", [])
                if bids and asks:
                    best_bid = float(bids[0]["price"])
                    best_ask = float(asks[0]["price"])
                    return (best_bid + best_ask) / 2
            return None
        except Exception as e:
            logger.error(f"Price fetch failed: {e}")
            return None

    # ── Balance ──────────────────────────────────────────────────────────────

    def get_usdc_balance(self) -> float:
        """Get wallet USDC balance on Polygon."""
        if not self._w3 or not self._wallet_address:
            return 0.0
        try:
            usdc = self._w3.eth.contract(address=USDC_ADDRESS, abi=ERC20_APPROVE_ABI)
            raw = usdc.functions.balanceOf(self._wallet_address).call()
            return raw / 1e6  # USDC has 6 decimals
        except Exception as e:
            logger.error(f"USDC balance check failed: {e}")
            return 0.0

    # ── Health ───────────────────────────────────────────────────────────────

    @property
    def is_ready(self) -> bool:
        """True if the client is initialized and can execute trades."""
        return self._initialized and self._clob is not None

    @property
    def is_read_only(self) -> bool:
        """True if no private key is configured (can only read markets)."""
        return not self._private_key

    @property
    def wallet_address(self) -> Optional[str]:
        return self._wallet_address
