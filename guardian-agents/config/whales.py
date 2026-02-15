"""
Tracked whale wallet addresses on Hyperliquid.

These addresses are publicly queryable on-chain. The list can be expanded
by analyzing large position holders via Hyperliquid's clearinghouse state.

Labels are for internal reference only.
"""

TRACKED_WHALES: list[dict] = [
    # ---- Known large BTC traders on Hyperliquid ----
    # These are placeholder addresses - replace with actual whale addresses
    # discovered through on-chain analysis or tools like CoinGlass/CoinAnk.
    #
    # To find whales:
    #   1. Query Hyperliquid leaderboard
    #   2. Monitor large trades via WebSocket
    #   3. Use CoinGlass whale tracker (coinglass.com/hyperliquid)
    #   4. Track addresses with >$1M BTC positions
    #
    # Format: {"address": "0x...", "label": "descriptive name", "min_position_usd": threshold}
]

# Minimum BTC position size (USD) to consider an address a "whale"
WHALE_POSITION_THRESHOLD_USD = 500_000

# How many top addresses to track from leaderboard
LEADERBOARD_TRACK_COUNT = 50

# Position change threshold to trigger alert (percentage)
POSITION_CHANGE_ALERT_PCT = 10.0
