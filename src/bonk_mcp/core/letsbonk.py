"""
Letsbonk - A Raydium Launchpad library for Solana

This library provides functions for creating and interacting with tokens
on the Raydium Launchpad platform.
"""

import struct
import traceback
import asyncio
from solana.transaction import AccountMeta, Transaction
from solders.pubkey import Pubkey
from solders.instruction import Instruction
from solders.keypair import Keypair
from typing import Dict, Optional, Tuple, List, Union

from bonk_mcp.utils import (
    buffer_from_string,
    setup_transaction,
    create_or_get_token_account,
    create_temporary_wsol_account,
    get_close_wsol_instruction,
    send_and_confirm_transaction,
    calculate_tokens_receive
)

# Import settings
from bonk_mcp.settings import (
    client,
    KEYPAIR,
    TOKEN_DECIMAL,
    SOL_DECIMAL,
    SYSTEM_PROGRAM,
    TOKEN_PROGRAM,
    ASSOC_TOKEN_ACC_PROG,
    METAPLEX_PROGRAM,
    RENT,
    RAYDIUM_LAUNCHPAD_PROGRAM,
    RAYDIUM_AUTHORITY,
    GLOBAL_CONFIG,
    PLATFORM_CONFIG,
    EVENT_AUTHORITY,
    WSOL_TOKEN,
    LAUNCHPAD_POOL_SEED,
    LAUNCHPAD_POOL_VAULT_SEED
)


def create_launch_instruction(
    mint_keypair: Keypair,
    payer_keypair: Keypair,
    pool_state_pda: Pubkey,
    base_vault_pda: Pubkey,
    quote_vault_pda: Pubkey,
    metadata_pda: Pubkey,
    name: str,
    symbol: str,
    uri: str,
    decimals: int = 6,
    supply: str = "1000000000000000",
    base_sell: str = "793100000000000",
    quote_raising: str = "85000000000"
) -> Instruction:
    """
    Create a launch instruction for a new token on Raydium Launchpad

    Args:
        mint_keypair: The keypair for the new token mint
        payer_keypair: The keypair that will pay for the transaction
        pool_state_pda: The PDA for the pool state
        base_vault_pda: The PDA for the base token vault
        quote_vault_pda: The PDA for the quote token (WSOL) vault
        metadata_pda: The PDA for the token metadata
        name: Token name
        symbol: Token symbol/ticker
        uri: Token metadata URI
        decimals: Token decimals (default: 6)
        supply: Total supply (default: 10^15 = 1 quadrillion)
        base_sell: Total tokens to sell (default: 7.931 × 10^14 = 79.31% of supply)
        quote_raising: Total SOL to raise in lamports (default: 85 SOL)

    Returns:
        Instruction for creating the token on Raydium Launchpad
    """
    # Serialize mint parameters from the instruction JSON provided
    mint_params = bytearray()
    # Decimals (u8)
    mint_params.extend(struct.pack("<B", decimals))
    # Name (string)
    mint_params.extend(buffer_from_string(name))
    # Symbol (string)
    mint_params.extend(buffer_from_string(symbol))
    # URI (string)
    mint_params.extend(buffer_from_string(uri))

    # Serialize curve parameters
    curve_params = bytearray()
    # Variant discriminator for Constant (0 = Constant)
    curve_params.extend(struct.pack("<B", 0))
    # Supply (u64)
    curve_params.extend(struct.pack("<Q", int(supply)))
    # Total base sell (u64)
    curve_params.extend(struct.pack("<Q", int(base_sell)))
    # Total quote fund raising (u64)
    curve_params.extend(struct.pack("<Q", int(quote_raising)))
    # Migrate type (u8)
    curve_params.extend(struct.pack("<B", 1))

    # Serialize vesting parameters
    vesting_params = bytearray()
    # Total locked amount (u64)
    vesting_params.extend(struct.pack("<Q", int("0")))
    # Cliff period (u64)
    vesting_params.extend(struct.pack("<Q", int("0")))
    # Unlock period (u64)
    vesting_params.extend(struct.pack("<Q", int("0")))

    # Instruction discriminator - Note: This is a placeholder, use the real one if known
    # In Anchor programs, this is usually the first 8 bytes of the SHA256 hash of the instruction name
    instruction_discriminator = bytes.fromhex("afaf6d1f0d989bed")

    # Combine all data
    data = bytearray()
    data.extend(instruction_discriminator)
    data.extend(mint_params)
    data.extend(curve_params)
    data.extend(vesting_params)

    # Account metas based on the screenshot
    keys = [
        # Payer
        AccountMeta(pubkey=payer_keypair.pubkey(),
                    is_signer=True, is_writable=True),

        # Creator
        AccountMeta(pubkey=payer_keypair.pubkey(),
                    is_signer=True, is_writable=True),

        # Global Config
        AccountMeta(pubkey=GLOBAL_CONFIG, is_signer=False, is_writable=False),

        # Platform Config
        AccountMeta(pubkey=PLATFORM_CONFIG,
                    is_signer=False, is_writable=False),

        # Authority
        AccountMeta(pubkey=RAYDIUM_AUTHORITY,
                    is_signer=False, is_writable=False),

        # Pool state (new keypair)
        AccountMeta(pubkey=pool_state_pda,
                    is_signer=False, is_writable=True),

        # Base mint (new token mint)
        AccountMeta(pubkey=mint_keypair.pubkey(),
                    is_signer=True, is_writable=True),

        # Quote token (WSOL)
        AccountMeta(pubkey=WSOL_TOKEN, is_signer=False, is_writable=False),

        # Base vault (new keypair)
        AccountMeta(pubkey=base_vault_pda,
                    is_signer=False, is_writable=True),

        # Quote vault (new keypair)
        AccountMeta(pubkey=quote_vault_pda,
                    is_signer=False, is_writable=True),

        # Metadata account (new keypair)
        AccountMeta(pubkey=metadata_pda,
                    is_signer=False, is_writable=True),

        # Base token program
        AccountMeta(pubkey=TOKEN_PROGRAM,
                    is_signer=False, is_writable=False),

        # Quote token program
        AccountMeta(pubkey=TOKEN_PROGRAM,
                    is_signer=False, is_writable=False),

        # Metadata program
        AccountMeta(pubkey=METAPLEX_PROGRAM,
                    is_signer=False, is_writable=False),

        # System program
        AccountMeta(pubkey=SYSTEM_PROGRAM,
                    is_signer=False, is_writable=False),

        # Rent sysvar
        AccountMeta(pubkey=RENT, is_signer=False, is_writable=False),

        # Event authority
        AccountMeta(pubkey=EVENT_AUTHORITY,
                    is_signer=False, is_writable=False),

        # Raydium program
        AccountMeta(pubkey=RAYDIUM_LAUNCHPAD_PROGRAM,
                    is_signer=False, is_writable=False),
    ]

    return Instruction(RAYDIUM_LAUNCHPAD_PROGRAM, bytes(data), keys)


def create_buy_instruction(
    payer_pubkey: Pubkey,
    pool_state_pda: Pubkey,
    base_vault_pda: Pubkey,
    quote_vault_pda: Pubkey,
    base_mint: Pubkey,
    base_token_account: Pubkey,
    wsol_token_account: Pubkey,
    amount_in: float,
    minimum_amount_out: float,
    share_fee_rate: int = 0
) -> Instruction:
    """
    Create a buy instruction for Raydium Launchpad

    Args:
        payer_pubkey: The user's public key
        pool_state_pda: The pool state PDA
        base_vault_pda: The base token vault PDA
        quote_vault_pda: The quote token (WSOL) vault PDA
        base_mint: The base token mint address
        base_token_account: The user's base token account
        wsol_token_account: The user's WSOL token account
        amount_in: Amount of SOL to spend (in SOL)
        minimum_amount_out: Minimum token amount to receive (in tokens)
        share_fee_rate: Optional share fee rate (default: 0)

    Returns:
        The buy instruction
    """
    # Instruction discriminator for buyExactIn
    instruction_discriminator = bytes.fromhex("faea0d7bd59c13ec")

    # Serialize parameters
    data = bytearray()
    data.extend(instruction_discriminator)

    # Amount in (u64) - convert from SOL to lamports
    data.extend(struct.pack("<Q", int(amount_in * 10**SOL_DECIMAL)))

    # Minimum amount out (u64) - convert from tokens to raw amount
    data.extend(struct.pack("<Q", int(minimum_amount_out * 10**TOKEN_DECIMAL)))

    # Share fee rate (u64)
    data.extend(struct.pack("<Q", share_fee_rate))

    # Account metas
    keys = [
        # Payer
        AccountMeta(pubkey=payer_pubkey, is_signer=True, is_writable=True),

        # Authority
        AccountMeta(pubkey=RAYDIUM_AUTHORITY,
                    is_signer=False, is_writable=False),

        # Global config
        AccountMeta(pubkey=GLOBAL_CONFIG, is_signer=False, is_writable=False),

        # Platform config
        AccountMeta(pubkey=PLATFORM_CONFIG,
                    is_signer=False, is_writable=False),

        # Pool state
        AccountMeta(pubkey=pool_state_pda, is_signer=False, is_writable=True),

        # Base token account (user)
        AccountMeta(pubkey=base_token_account,
                    is_signer=False, is_writable=True),

        # WSOL token account (user)
        AccountMeta(pubkey=wsol_token_account,
                    is_signer=False, is_writable=True),

        # Base vault
        AccountMeta(pubkey=base_vault_pda, is_signer=False, is_writable=True),

        # Quote vault
        AccountMeta(pubkey=quote_vault_pda, is_signer=False, is_writable=True),

        # Base mint
        AccountMeta(pubkey=base_mint, is_signer=False, is_writable=True),

        # Quote mint (WSOL)
        AccountMeta(pubkey=WSOL_TOKEN, is_signer=False, is_writable=False),

        # Token program
        AccountMeta(pubkey=TOKEN_PROGRAM, is_signer=False, is_writable=False),

        # Token program (again)
        AccountMeta(pubkey=TOKEN_PROGRAM, is_signer=False, is_writable=False),

        # Event authority
        AccountMeta(pubkey=EVENT_AUTHORITY,
                    is_signer=False, is_writable=False),

        # Raydium program
        AccountMeta(pubkey=RAYDIUM_LAUNCHPAD_PROGRAM,
                    is_signer=False, is_writable=False),
    ]

    return Instruction(RAYDIUM_LAUNCHPAD_PROGRAM, bytes(data), keys)


async def derive_pdas(
    mint_pubkey: Pubkey
) -> Dict[str, Pubkey]:
    """
    Derive all PDAs needed for Raydium Launchpad operations based on a mint

    Args:
        mint_pubkey: The pubkey of the base token mint

    Returns:
        Dictionary containing all derived PDAs
    """
    quote_mint = WSOL_TOKEN

    # Derive Pool State PDA
    pool_state_pda, _ = Pubkey.find_program_address(
        [LAUNCHPAD_POOL_SEED, bytes(mint_pubkey), bytes(quote_mint)],
        RAYDIUM_LAUNCHPAD_PROGRAM
    )

    # Derive Base Vault PDA
    base_vault_pda, _ = Pubkey.find_program_address(
        [LAUNCHPAD_POOL_VAULT_SEED, bytes(pool_state_pda), bytes(mint_pubkey)],
        RAYDIUM_LAUNCHPAD_PROGRAM
    )

    # Derive Quote Vault PDA
    quote_vault_pda, _ = Pubkey.find_program_address(
        [LAUNCHPAD_POOL_VAULT_SEED, bytes(pool_state_pda), bytes(quote_mint)],
        RAYDIUM_LAUNCHPAD_PROGRAM
    )

    # Derive Metadata PDA
    metadata_pda, _ = Pubkey.find_program_address(
        ["metadata".encode(), bytes(METAPLEX_PROGRAM), bytes(mint_pubkey)],
        METAPLEX_PROGRAM
    )

    return {
        "pool_state": pool_state_pda,
        "base_vault": base_vault_pda,
        "quote_vault": quote_vault_pda,
        "metadata": metadata_pda
    }


async def create_token(
    payer_keypair: Keypair,
    mint_keypair: Keypair,
    name: str,
    symbol: str,
    uri: str,
    decimals: int = 6,
    supply: str = "1000000000000000",
    base_sell: str = "793100000000000",
    quote_raising: str = "85000000000"
) -> Tuple[Transaction, Pubkey]:
    """
    Create a transaction for launching a new token on Raydium Launchpad

    Args:
        payer_keypair: The keypair that will pay for the transaction
        mint_keypair: The keypair for the new token mint
        name: Token name
        symbol: Token symbol/ticker
        uri: Token metadata URI
        decimals: Token decimals (default: 6)
        supply: Total supply (default: 10^15 = 1 quadrillion)
        base_sell: Total tokens to sell (default: 7.931 × 10^14 = 79.31% of supply)
        quote_raising: Total SOL to raise in lamports (default: 85 SOL)

    Returns:
        Tuple of (Transaction, base token account pubkey)
    """
    # Setup transaction
    txn = await setup_transaction(payer_keypair.pubkey())

    # Derive PDAs
    pdas = await derive_pdas(mint_keypair.pubkey())

    # Create launch instruction
    launch_ix = create_launch_instruction(
        mint_keypair=mint_keypair,
        payer_keypair=payer_keypair,
        pool_state_pda=pdas["pool_state"],
        base_vault_pda=pdas["base_vault"],
        quote_vault_pda=pdas["quote_vault"],
        metadata_pda=pdas["metadata"],
        name=name,
        symbol=symbol,
        uri=uri,
        decimals=decimals,
        supply=supply,
        base_sell=base_sell,
        quote_raising=quote_raising
    )
    txn.add(launch_ix)

    # Create token account for the new mint
    base_token_account, base_token_account_ix = await create_or_get_token_account(
        payer_keypair.pubkey(),
        mint_keypair.pubkey()
    )

    if base_token_account_ix:
        txn.add(base_token_account_ix)

    return txn, base_token_account


async def create_buy_tx(
    payer_keypair: Keypair,
    mint_pubkey: Pubkey,
    amount_in: float,
    minimum_amount_out: float
) -> Tuple[Transaction, List[Keypair]]:
    """
    Create a transaction for buying tokens on Raydium Launchpad

    Args:
        payer_keypair: The keypair that will pay for the transaction
        mint_pubkey: The pubkey of the base token mint
        amount_in: Amount of SOL to spend (in SOL)
        minimum_amount_out: Minimum token amount to receive (in tokens)

    Returns:
        Tuple of (Transaction, list of additional signers)
    """
    # Setup transaction
    txn = await setup_transaction(payer_keypair.pubkey())
    additional_signers = []

    # Get token account for the specified mint
    base_token_account, base_token_instruction = await create_or_get_token_account(
        payer_keypair.pubkey(),
        mint_pubkey
    )

    # Create temporary WSOL account
    wsol_token_account, wsol_instructions, wsol_keypair = await create_temporary_wsol_account(
        payer_keypair.pubkey(),
        amount_in
    )
    additional_signers.append(wsol_keypair)

    # Add base token account creation instructions to transaction
    if base_token_instruction:
        txn.add(base_token_instruction)

    # Add WSOL account creation instructions to transaction
    for ix in wsol_instructions:
        txn.add(ix)

    # Derive PDAs
    pdas = await derive_pdas(mint_pubkey)

    # Create buy instruction
    buy_ix = create_buy_instruction(
        payer_pubkey=payer_keypair.pubkey(),
        pool_state_pda=pdas["pool_state"],
        base_vault_pda=pdas["base_vault"],
        quote_vault_pda=pdas["quote_vault"],
        base_mint=mint_pubkey,
        base_token_account=base_token_account,
        wsol_token_account=wsol_token_account,
        amount_in=amount_in,
        minimum_amount_out=minimum_amount_out
    )
    txn.add(buy_ix)

    # Close WSOL account to recover SOL at the end
    close_wsol_ix = await get_close_wsol_instruction(
        wsol_token_account,
        payer_keypair.pubkey()
    )
    txn.add(close_wsol_ix)

    return txn, additional_signers


async def launch_token_with_buy(
    payer_keypair: Keypair,
    mint_keypair: Keypair,
    name: str,
    symbol: str,
    uri: str,
    decimals: int = 6,
    supply: str = "1000000000000000",
    base_sell: str = "793100000000000",
    quote_raising: str = "85000000000",
    buy_amount_sol: Optional[float] = None,
    slippage: int = 5
) -> Dict:
    """
    Launch a new token on Raydium Launchpad and optionally buy it.

    Args:
        payer_keypair: The keypair that will pay for the transaction
        name: Token name
        symbol: Token symbol/ticker
        uri: Token metadata URI
        decimals: Token decimals (default: 6)
        supply: Total supply (default: 10^15 = 1 quadrillion)
        base_sell: Total tokens to sell (default: 7.931 × 10^14 = 79.31% of supply)
        quote_raising: Total SOL to raise in lamports (default: 85 SOL)
        buy_amount_sol: Optional amount of SOL for an initial buy
        slippage: Slippage percentage for the initial buy

    Returns:
        Dictionary with results of the operations
    """
    results = {
        "mint_keypair": None,
        "token_created": False,
        "token_tx_signature": None,
        "base_token_account": None,
        "pdas": {},
        "buy_tx_signature": None,
        "buy_error": None,
        "error": None
    }

    try:
        results["mint_keypair"] = mint_keypair

        print(
            f"Creating token with config: \nName: {name}\nSymbol: {symbol}\nURI: {uri}\nDecimals: {decimals}")

        # Step 1: Create the token
        print("\n===== STEP 1: Creating Token =====")

        create_token_txn, base_token_account = await create_token(
            payer_keypair=payer_keypair,
            mint_keypair=mint_keypair,
            name=name,
            symbol=symbol,
            uri=uri,
            decimals=decimals,
            supply=supply,
            base_sell=base_sell,
            quote_raising=quote_raising
        )

        # Get PDAs for result info
        pdas = await derive_pdas(mint_keypair.pubkey())
        results["pdas"] = pdas
        results["base_token_account"] = base_token_account

        # Print info
        print(f"Base Mint: {mint_keypair.pubkey()}")
        print(f"Quote Mint: {WSOL_TOKEN}")
        print(f"Pool State PDA: {pdas['pool_state']}")
        print(f"Base Vault PDA: {pdas['base_vault']}")
        print(f"Quote Vault PDA: {pdas['quote_vault']}")
        print(f"Metadata PDA: {pdas['metadata']}")
        print(f"Base Token Account: {base_token_account}")

        # Send token creation transaction
        print("Sending token creation transaction...")
        token_success = await send_and_confirm_transaction(create_token_txn, payer_keypair, mint_keypair, confirm=True)

        if not token_success:
            print("Token creation failed.")
            results["error"] = "Token creation failed"
            return results

        print(f"Token creation succeeded! Transaction: {token_success}")
        results["token_created"] = True
        results["token_tx_signature"] = str(token_success)

        # Step 2: Buy the token if requested
        if buy_amount_sol and buy_amount_sol > 0:
            print(f"\n===== STEP 2: Buying Token ({buy_amount_sol} SOL) =====")
            # Add a small delay to allow the network to catch up
            await asyncio.sleep(5)
            try:
                # Calculate minimum tokens to receive based on slippage
                token_info = calculate_tokens_receive(buy_amount_sol, previous_sol=0, slippage=slippage)
                minimum_amount_out = token_info["token_amount"]
                
                print(f"Minimum tokens to receive: {minimum_amount_out} (with {slippage}% slippage)")

                buy_txn, additional_signers = await create_buy_tx(
                    payer_keypair=payer_keypair,
                    mint_pubkey=mint_keypair.pubkey(),
                    amount_in=buy_amount_sol,
                    minimum_amount_out=minimum_amount_out
                )
                
                print("Sending buy transaction...")
                buy_tx_hash = await send_and_confirm_transaction(
                    buy_txn,
                    payer_keypair,
                    *additional_signers,
                    skip_preflight=True,
                    confirm=True
                )

                if buy_tx_hash:
                    print(f"Successfully bought tokens! Transaction: {buy_tx_hash}")
                    results["buy_tx_signature"] = str(buy_tx_hash)
                else:
                    print("Buy transaction failed.")
                    results["buy_error"] = "Failed to execute the initial buy."

            except Exception as e:
                error_msg = f"Error during initial buy: {traceback.format_exc()}"
                print(error_msg)
                results["buy_error"] = str(e)


        return results

    except Exception as e:
        error_msg = f"Error in launch_token_with_buy: {traceback.format_exc()}"
        print(error_msg)
        results["error"] = str(e)
        return results