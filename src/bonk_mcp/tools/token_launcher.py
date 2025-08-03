"""
A modified version of the LetsBonk MCP token launcher that supports an
initial buy directly after launching a token.  This script extends the
existing MCP server for LetsBonk by adding support for an `initial_buy_amount`
and a `minimum_token_out` parameter.  When provided, the launcher will
create the token on the Raydium launchpad and then execute a buy
transaction on the newly minted token using the same payer keypair.

The code below is designed to live alongside the existing `bonk_mcp` package.
It re‑uses helper functions from that package, such as `prepare_ipfs` for
metadata hosting, `create_token` for constructing the launch transaction,
and `create_buy_tx` for constructing a buy transaction.  If you place this
file in your MCP server and register the `TokenLauncherWithBuyTool` with
Claude or Cursor, you can automate the full “create then buy” workflow.

NOTE:  This script assumes that all dependencies from the original
`bonk_mcp` project are available in your environment.  You must also set
`KEYPAIR` and `RPC_URL` environment variables (or edit the import from
`bonk_mcp.settings`) to specify your Solana keypair and RPC endpoint.

Usage example (as an asynchronous function):

    from bonk_mcp_with_buy import token_launcher_with_buy_tool
    await token_launcher_with_buy_tool.execute({
        "name": "MyToken",
        "symbol": "MYT",
        "description": "My first token",
        "image_url": "/path/to/image.png",
        "initial_buy_amount": 0.1,
        "minimum_token_out": 0
    })

"""

import asyncio
import base58
from typing import Dict, List, Optional

from mcp.types import TextContent, Tool, ImageContent, EmbeddedResource
from solders.keypair import Keypair

# Import helpers from the existing bonk_mcp package.  These imports
# reuse your configured RPC client and environment variables.  If they
# fail, ensure that bonk_mcp is installed and properly configured.
from bonk_mcp.utils import prepare_ipfs, send_and_confirm_transaction
from bonk_mcp.core.letsbonk import (
    create_token,
    create_buy_tx,
    derive_pdas,
)
from bonk_mcp.settings import KEYPAIR


class TokenLauncherWithBuyTool:
    """
    Extended token launcher tool for LetsBonk that supports an initial dev buy.

    This tool mirrors the existing `launch-token` tool but adds two new
    optional fields:

    * `initial_buy_amount` – the amount of SOL to spend buying your own token
      immediately after launch.  Defaults to 0 (no buy).
    * `minimum_token_out` – a lower bound on the number of base tokens to
      receive from the buy (to control slippage).  Defaults to 0.

    When an `initial_buy_amount` greater than zero is provided, the tool will
    perform the buy transaction after the token is successfully created.
    """

    def __init__(self) -> None:
        # Define metadata used by the MCP registry
        self.name = "launch-token-with-buy"
        self.description = (
            "Launch a new meme token on Solana using Raydium and optionally "
            "perform an initial buy of your own token."
        )
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
                    "description": (
                        "Amount of SOL to spend buying your own token. "
                        "Use 0 to skip the initial buy."
                    ),
                    "minimum": 0,
                },
                "minimum_token_out": {
                    "type": "number",
                    "description": (
                        "Minimum number of tokens to receive from the initial buy "
                        "(slippage tolerance)."
                    ),
                    "minimum": 0,
                },
            },
            # Require the standard fields for launching plus the optional buy
            "required": ["name", "symbol", "description", "image_url"],
        }

    async def execute(self, arguments: Dict) -> List[TextContent | ImageContent | EmbeddedResource]:
        """Execute the token launcher with an optional initial buy."""
        name = arguments.get("name")
        symbol = arguments.get("symbol")
        description = arguments.get("description")
        twitter = arguments.get("twitter", "")
        telegram = arguments.get("telegram", "")
        website = arguments.get("website", "")
        image_url = arguments.get("image_url")
        # Coerce numeric values and fall back to zero
        initial_buy_amount: float = float(arguments.get("initial_buy_amount", 0) or 0)
        minimum_token_out: float = float(arguments.get("minimum_token_out", 0) or 0)

        # Validate required fields
        if not name or not symbol or not description or not image_url:
            return [
                TextContent(
                    type="text",
                    text=(
                        "Error: Missing required parameters. "
                        "Please provide name, symbol, description, and image_url."
                    ),
                )
            ]

        # Ensure a keypair is configured in the environment
        if not KEYPAIR:
            return [
                TextContent(
                    type="text",
                    text=(
                        "Error: No keypair configured in settings. "
                        "Please set the KEYPAIR environment variable."
                    ),
                )
            ]

        # Decode the payer keypair from base58
        try:
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

        # Prepare IPFS metadata; this will upload the image and create metadata
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
            return [
                TextContent(
                    type="text",
                    text=f"Error: Failed to prepare IPFS metadata. {str(e)}",
                )
            ]
        if not uri:
            return [
                TextContent(
                    type="text",
                    text="Error: Failed to prepare IPFS metadata. Please check your image URL and try again.",
                )
            ]

        # Step 1: Create the token
        try:
            create_txn, base_token_account = await create_token(
                payer_keypair=payer_keypair,
                mint_keypair=mint_keypair,
                name=name,
                symbol=symbol,
                uri=uri,
            )
            # Send the creation transaction (sign with payer and mint)
            create_success = await send_and_confirm_transaction(
                create_txn, payer_keypair, mint_keypair
            )
        except Exception as e:
            return [
                TextContent(
                    type="text",
                    text=f"Error launching token: {str(e)}",
                )
            ]
        if not create_success:
            return [
                TextContent(
                    type="text",
                    text="Error: Token creation failed.",
                )
            ]

        # Build the response text with launch details
        pdas = await derive_pdas(mint_keypair.pubkey())
        response_lines = [
            f"Successfully launched token: {name} ({symbol})",
            "",
            f"Mint Address: {mint_keypair.pubkey()}",
            f"Pool State: {pdas['pool_state']}",
            f"Token URI: {uri}",
            f"Image URL: {image_url}",
            "",
            f"Funded from account: {payer_keypair.pubkey()}",
        ]

        # Step 2: Optionally perform the initial buy
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
                    response_lines.append(
                        f"Token launched, but initial buy failed."
                    )
            except Exception as e:
                response_lines.append("")
                response_lines.append(
                    f"Token launched, but initial buy failed: {str(e)}"
                )

        # Return the assembled response
        return [
            TextContent(
                type="text",
                text="\n".join(response_lines),
            )
        ]

    def get_tool_definition(self) -> Tool:
        """Return the MCP tool definition for registration."""
        return Tool(
            name=self.name,
            description=self.description,
            inputSchema=self.input_schema,
        )


# Instantiate a default instance for export.  Many MCP clients expect a
# module‑level variable named `<tool_name>_tool` for discovery.
token_launcher_with_buy_tool = TokenLauncherWithBuyTool()
