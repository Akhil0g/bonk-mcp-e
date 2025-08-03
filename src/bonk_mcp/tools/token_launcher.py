import asyncio
from typing import Dict, List, Optional
import json
import base58
import aiohttp

from mcp.types import TextContent, Tool, ImageContent, EmbeddedResource
from solders.keypair import Keypair

from bonk_mcp.core.letsbonk import launch_token_with_buy
from bonk_mcp.utils import prepare_ipfs
from bonk_mcp.settings import KEYPAIR


class TokenLauncherTool:
    """Tool for launching meme tokens on Solana using the Raydium launchpad"""

    def __init__(self):
        self.name = "launch-token"
        self.description = "Launch a new meme token on Solana using Raydium launchpad, with an optional initial buy."
        self.input_schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Token name"},
                "symbol": {"type": "string", "description": "Token symbol/ticker"},
                "description": {"type": "string", "description": "Token description"},
                "twitter": {"type": "string", "description": "Twitter handle/URL (optional)"},
                "telegram": {"type": "string", "description": "Telegram group URL (optional)"},
                "website": {"type": "string", "description": "Website URL (optional)"},
                "image_url": {"type": "string", "description": "Image URL to use for token"},
                "buy_amount_sol": {"type": "number", "description": "Optional: Amount of SOL to use for an initial buy of the token."},
                "slippage": {"type": "number", "description": "Optional: Slippage percentage for the initial buy (default: 5)."}
            },
            "required": ["name", "symbol", "description", "image_url"]
        }

    async def execute(self, arguments: Dict) -> List[TextContent | ImageContent | EmbeddedResource]:
        """
        Execute the token launcher tool with the provided arguments

        Args:
            arguments: Dictionary containing token configuration

        Returns:
            List of content items with the result
        """
        # Extract arguments
        name = arguments.get("name")
        symbol = arguments.get("symbol")
        description = arguments.get("description")
        twitter = arguments.get("twitter", "")
        telegram = arguments.get("telegram", "")
        website = arguments.get("website", "")
        image_url = arguments.get("image_url", "")
        buy_amount_sol = arguments.get("buy_amount_sol")
        slippage = arguments.get("slippage", 5)  # Default to 5% slippage

        # Validate required arguments
        if not name or not symbol or not description or not image_url:
            return [TextContent(
                type="text",
                text="Error: Missing required parameters. Please provide name, symbol, description, and image_url."
            )]

        # Get the payer keypair from settings
        if not KEYPAIR:
            return [TextContent(
                type="text",
                text="Error: No keypair configured in settings. Please set the KEYPAIR environment variable."
            )]

        try:
            # Convert the private key to a Keypair
            private_key_bytes = base58.b58decode(KEYPAIR)
            payer_keypair = Keypair.from_bytes(private_key_bytes)
        except Exception as e:
            return [TextContent(
                type="text",
                text=f"Error: Invalid keypair format. {str(e)}"
            )]

        # Generate keypair for token mint
        mint_keypair = Keypair()

        # Prepare IPFS metadata - this handles image upload and metadata creation in one step
        print(f"Preparing IPFS metadata for {name} ({symbol})...")
        uri = await prepare_ipfs(
            name=name,
            symbol=symbol,
            description=description,
            twitter=twitter,
            telegram=telegram,
            website=website,
            image_url=image_url
        )

        if not uri:
            return [TextContent(
                type="text",
                text="Error: Failed to prepare IPFS metadata. Please check your image URL and try again."
            )]

        # Launch token
        print(f"Launching token {name} ({symbol})...")
        launch_result = await launch_token_with_buy(
            payer_keypair=payer_keypair,
            mint_keypair=mint_keypair,
            name=name,
            symbol=symbol,
            uri=uri,
            buy_amount_sol=buy_amount_sol,
            slippage=slippage
        )

        # Process results
        if launch_result.get("error"):
            return [TextContent(
                type="text",
                text=f"Error launching token: {launch_result['error']}"
            )]

        # Format successful response
        mint_address = mint_keypair.pubkey()
        pdas = launch_result["pdas"]

        response_text = (
            f"🚀 Successfully launched token: {name} ({symbol})\n\n"
            f"Mint Address: {mint_address}\n"
            f"Launch TX: {launch_result.get('token_tx_signature')}\n"
            f"Pool State: {pdas['pool_state']}\n"
            f"Token URI: {uri}\n\n"
            f"Funded from account: {payer_keypair.pubkey()}\n"
        )

        # Add buy information if it exists
        if launch_result.get("buy_tx_signature"):
            response_text += (
                f"\n✅ Initial buy successful!\n"
                f"Buy TX: {launch_result['buy_tx_signature']}\n"
            )
        elif launch_result.get("buy_error"):
            response_text += (
                f"\n⚠️ Initial buy failed!\n"
                f"Error: {launch_result['buy_error']}\n"
            )


        return [TextContent(
            type="text",
            text=response_text
        )]

    def get_tool_definition(self) -> Tool:
        """Get the tool definition for MCP"""
        return Tool(
            name=self.name,
            description=self.description,
            inputSchema=self.input_schema
        )


# Create instance for export
token_launcher_tool = TokenLauncherTool()