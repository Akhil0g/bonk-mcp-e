"""
Updated Token Launcher Tool with optional initial buy support.

This module extends the original `TokenLauncherTool` from the bonk‑mcp project
by adding two optional fields: ``initial_buy_amount`` and
``minimum_token_out``.  When provided, the tool will perform an initial buy of
your token immediately after launch using the same payer keypair.  The code is
based on the upstream ``src/bonk_mcp/tools/token_launcher.py`` from
https://github.com/letsbonk-ai/bonk-mcp, with modifications to support the
dev buy.

Place this file into ``src/bonk_mcp/tools/`` in your forked repository,
replacing the existing ``token_launcher.py`` or renaming it appropriately.

"""

import asyncio
import base58
from typing import Dict, List, Optional

from mcp.types import TextContent, Tool, ImageContent, EmbeddedResource
from solders.keypair import Keypair

from bonk_mcp.core.letsbonk import (
    launch_token_with_buy,
    create_buy_tx,
)
from bonk_mcp.utils import prepare_ipfs, send_and_confirm_transaction
from bonk_mcp.settings import KEYPAIR


class TokenLauncherTool:
    """Tool for launching meme tokens on Solana using the Raydium launchpad.

    Extended to support an optional dev buy via the ``initial_buy_amount`` and
    ``minimum_token_out`` parameters.  If a non‑zero ``initial_buy_amount`` is
    provided, the tool will perform a buy transaction immediately after the
    token launch.  ``minimum_token_out`` can be set to impose a slippage
    tolerance on the buy.
    """

    def __init__(self) -> None:
        self.name = "launch-token"
        self.description = (
            "Launch a new meme token on Solana using the Raydium launchpad. "
            "Optionally perform an initial buy of your own token."
        )
        # Extend the input schema to include initial buy parameters
        self.input_schema: Dict = {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Token name"},
                "symbol": {"type": "string", "description": "Token symbol/ticker"},
                "description": {"type": "string", "description": "Token description"},
                "twitter": {"type": "string", "description": "Twitter handle/URL (optional)"},
                "telegram": {"type": "string", "description": "Telegram group URL (optional)"},
                "website": {"type": "string", "description": "Website URL (optional)"},
                "image_url": {"type": "string", "description": "Image URL to use for token"},
                "initial_buy_amount": {
                    "type": "number",
                    "description": "Amount of SOL to spend for an initial buy after launch (optional)",
                    "minimum": 0,
                },
                "minimum_token_out": {
                    "type": "number",
                    "description": "Minimum number of tokens expected from the initial buy (slippage tolerance)",
                    "minimum": 0,
                },
            },
            "required": ["name", "symbol", "description", "image_url"],
        }

    async def execute(self, arguments: Dict) -> List[TextContent | ImageContent | EmbeddedResource]:
        """
        Execute the token launcher tool with the provided arguments.

        Args:
            arguments: Dictionary containing token configuration.

        Returns:
            List of content items with the result.
        """
        # Extract required arguments
        name = arguments.get("name")
        symbol = arguments.get("symbol")
        description = arguments.get("description")
        twitter = arguments.get("twitter", "")
        telegram = arguments.get("telegram", "")
        website = arguments.get("website", "")
        image_url = arguments.get("image_url", "")

        # Parse optional buy parameters, defaulting to zero
        initial_buy_amount: float = float(arguments.get("initial_buy_amount", 0) or 0)
        minimum_token_out: float = float(arguments.get("minimum_token_out", 0) or 0)

        # Validate required arguments
        if not name or not symbol or not description or not image_url:
            return [
                TextContent(
                    type="text",
                    text=(
                        "Error: Missing required parameters. Please provide name, "
                        "symbol, description, and image_url."
                    ),
                )
            ]

        # Ensure a keypair is configured
        if not KEYPAIR:
            return [
                TextContent(
                    type="text",
                    text=(
                        "Error: No keypair configured in settings. Please set the "
                        "KEYPAIR environment variable."
                    ),
                )
            ]

        try:
            # Convert the private key string to a Keypair
            private_key_bytes = base58.b58decode(KEYPAIR)
            payer_keypair = Keypair.from_bytes(private_key_bytes)
        except Exception as e:
            return [
                TextContent(
                    type="text",
                    text=f"Error: Invalid keypair format. {str(e)}",
                )
            ]

        # Generate a fresh keypair for the new token mint
        mint_keypair = Keypair()

        # Prepare IPFS metadata (uploads image and constructs the URI)
        try:
            uri = await prepare_ipfs(
                name=name,
                symbol=symbol,
                description=description,
                twitter=twitter,
                telegram=telegram,
                website=website,
                image_url=image_url,
            )
        except Exception as e:
            uri = None
        if not uri:
            return [
                TextContent(
                    type="text",
                    text="Error: Failed to prepare IPFS metadata. Please check your image URL and try again.",
                )
            ]

        # Launch the token using the existing helper
        launch_result = await launch_token_with_buy(
            payer_keypair=payer_keypair,
            mint_keypair=mint_keypair,
            name=name,
            symbol=symbol,
            uri=uri,
        )

        # Check for errors
        if launch_result.get("error"):
            return [
                TextContent(
                    type="text",
                    text=f"Error launching token: {launch_result['error']}",
                )
            ]

        # Format response with launch information
        mint_address = mint_keypair.pubkey()
        pdas = launch_result.get("pdas", {})
        response_lines = [
            f"Successfully launched token: {name} ({symbol})",
            "",
            f"Mint Address: {mint_address}",
            f"Pool State: {pdas.get('pool_state')}",
            f"Token URI: {uri}",
            f"Image URL: {image_url}",
            "",
            f"Funded from account: {payer_keypair.pubkey()}",
        ]

        # Optionally perform the initial buy
        if initial_buy_amount > 0:
            try:
                buy_txn, additional_signers = await create_buy_tx(
                    payer_keypair=payer_keypair,
                    mint_pubkey=mint_keypair.pubkey(),
                    amount_in=initial_buy_amount,
                    minimum_amount_out=minimum_token_out,
                )
                buy_success = await send_and_confirm_transaction(
                    buy_txn, payer_keypair, *additional_signers
                )
                if buy_success:
                    response_lines.append("")
                    response_lines.append(
                        f"Initial buy succeeded: spent {initial_buy_amount} SOL"
                    )
                else:
                    response_lines.append("")
                    response_lines.append("Token launched, but initial buy failed.")
            except Exception as e:
                response_lines.append("")
                response_lines.append(f"Token launched, but initial buy failed: {str(e)}")

        # Return the assembled response
        return [TextContent(type="text", text="\n".join(response_lines))]

    def get_tool_definition(self) -> Tool:
        """Return the MCP tool definition."""
        return Tool(
            name=self.name,
            description=self.description,
            inputSchema=self.input_schema,
        )


# Export an instance for MCP registration
token_launcher_tool = TokenLauncherTool()
