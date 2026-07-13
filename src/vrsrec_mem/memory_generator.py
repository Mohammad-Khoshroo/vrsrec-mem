"""Memory dump generator/filler.

Generates a complete memory dump CSV with all addresses from
``base_address`` to ``base_address + capacity - 1``, optionally merging
with an existing sparse CSV file. Useful for creating fully-populated
memory images for hardware simulation (e.g. Verilog ``$readmemh`` /
``$readmemb`` inputs) where every address must have a value.

The data is represented either as:

* a **binary string** of length ``data_bits`` (each char is ``'0'``, ``'1'``,
  or ``'x'``) — matches Verilog ``$readmemb``. This is the default and
  matches the format produced by the original ``memory_dump_generator.py``
  script.

* a **hex string** of length ``ceil(data_bits / 4)`` (each char is
  ``0-9a-fA-F`` or ``'x'``) — matches Verilog ``$readmemh``. Selected via
  ``output_format='hex'``.

Fill modes for empty addresses:
    * ``'x'``             — fill with all ``'x'``
    * ``'0'``             — fill with all ``'0'``
    * ``'1'``             — fill with all ``'1'``
    * ``'random'``        — fill with random bits
    * ``'random_with_x'`` — fill with random bits, ~10% chance of all ``'x'``
"""

from __future__ import annotations

import csv
import os
import random
import sys
from typing import Dict, IO, Optional


# Soft safeguard against accidental huge allocations.
DEFAULT_MAX_CAPACITY = 1 << 24  # 16M entries


def generate_random_data(
    data_bits: int,
    include_x: bool = True,
    rng: Optional[random.Random] = None,
) -> str:
    """Generate one random data word as a **binary** string.

    If ``include_x`` is True, there is a ~10% chance the result is all
    ``'x'`` (a don't-care value).
    """
    if data_bits <= 0:
        raise ValueError(f"data_bits must be > 0, got {data_bits}")
    rng = rng or random
    if include_x and rng.randint(0, 9) == 0:
        return "x" * data_bits
    max_val = (1 << data_bits) - 1
    val = rng.randint(0, max_val)
    return f"{val:0{data_bits}b}"


def fill_value(
    fill_mode: str,
    data_bits: int,
    rng: Optional[random.Random] = None,
) -> str:
    """Return a fill value (as a **binary** string) for the given mode."""
    if fill_mode == "x":
        return "x" * data_bits
    if fill_mode == "0":
        return "0" * data_bits
    if fill_mode == "1":
        return "1" * data_bits
    if fill_mode == "random":
        return generate_random_data(data_bits, include_x=False, rng=rng)
    if fill_mode == "random_with_x":
        return generate_random_data(data_bits, include_x=True, rng=rng)
    raise ValueError(f"Unsupported fill mode: {fill_mode}")


# --------------------------------------------------------------------------- #
# Binary <-> hex conversion
# --------------------------------------------------------------------------- #

def _hex_digit_count(data_bits: int) -> int:
    """Number of hex digits needed to represent a value of ``data_bits`` bits."""
    if data_bits <= 0:
        raise ValueError(f"data_bits must be > 0, got {data_bits}")
    return (data_bits + 3) // 4


def binary_to_hex(bin_str: str, data_bits: int) -> str:
    """Convert a binary string to a hex string.

    ``'x'`` bits propagate: any nibble containing an ``'x'`` becomes ``'x'``.
    The output is left-padded with ``'0'`` to ``_hex_digit_count(data_bits)``
    characters, so the output width is consistent.
    """
    if len(bin_str) != data_bits:
        raise ValueError(
            f"binary string length {len(bin_str)} != data_bits {data_bits}"
        )
    hex_len = _hex_digit_count(data_bits)
    # Pad binary string on the left so its length is a multiple of 4.
    pad = (-data_bits) % 4
    padded = ("0" * pad) + bin_str

    out_chars = []
    for i in range(0, len(padded), 4):
        nibble = padded[i:i + 4]
        if "x" in nibble:
            out_chars.append("X")  # uppercase to match the rest of the hex digits
        else:
            out_chars.append(f"{int(nibble, 2):X}")
    # The padded result already has exactly hex_len nibbles; join directly.
    return "".join(out_chars)


def hex_to_binary(hex_str: str, data_bits: int) -> str:
    """Convert a hex string to a binary string of length ``data_bits``.

    ``'x'`` hex digits expand to 4 ``'x'`` bits. The result is truncated
    or left-padded with ``'0'`` to exactly ``data_bits`` characters.
    """
    hex_len = _hex_digit_count(data_bits)
    s = hex_str.strip().upper()
    # Left-pad with '0' up to hex_len characters.
    if len(s) < hex_len:
        s = "0" * (hex_len - len(s)) + s
    if len(s) > hex_len:
        s = s[-hex_len:]  # take the least-significant hex_len digits

    bits = []
    for c in s:
        if c in ("X", "x"):
            bits.append("xxxx")
        else:
            try:
                bits.append(f"{int(c, 16):04b}")
            except ValueError as exc:
                raise ValueError(
                    f"invalid hex character {c!r} in {hex_str!r}"
                ) from exc
    full = "".join(bits)
    # The padded binary string is now hex_len * 4 bits long.
    # Trim from the left to data_bits (drop leading padding bits).
    if len(full) > data_bits:
        full = full[-data_bits:]
    return full


# --------------------------------------------------------------------------- #
# Address parsing
# --------------------------------------------------------------------------- #

def _parse_addr(addr_str: str) -> int:
    """Parse a hex address string, accepting optional '0x' prefix."""
    s = addr_str.strip()
    if s.lower().startswith("0x"):
        s = s[2:]
    return int(s, 16)


def read_sparse_csv(
    input_file: str,
    data_bits: Optional[int] = None,
    input_format: str = "auto",
) -> Dict[int, str]:
    """Read a sparse CSV with header ``address,data``.

    Args:
        input_file: Path to the CSV file.
        data_bits: Width of each data word in bits. Required when
            ``input_format`` is ``'hex'`` (for hex->binary conversion) and
            used for normalization when ``input_format`` is ``'bin'``.
            If ``None`` and ``input_format='auto'``, the bit-width is
            inferred from each row's string length.
        input_format: One of ``'auto'``, ``'bin'``, ``'hex'``.
            * ``'auto'`` — accept either format; values containing only
              ``0``/``1``/``x`` are treated as binary, otherwise as hex.
            * ``'bin'``  — every value is treated as a binary string.
            * ``'hex'``  — every value is treated as a hex string and
              converted to binary.

    Returns:
        Dict of ``{addr: binary_string}``. All values are returned as
        binary strings of length ``data_bits`` (or as-is when
        ``data_bits`` is None).
    """
    if input_format not in ("auto", "bin", "hex"):
        raise ValueError(f"input_format must be 'auto', 'bin', or 'hex'; "
                         f"got {input_format!r}")

    data: Dict[int, str] = {}
    with open(input_file, "r", newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader, None)  # skip header
        for row in reader:
            if len(row) < 2:
                continue
            addr_int = _parse_addr(row[0])
            raw = row[1].strip()

            if input_format == "bin":
                value = raw
                if data_bits is not None and len(value) != data_bits:
                    raise ValueError(
                        f"address 0x{addr_int:X}: binary value {raw!r} "
                        f"has length {len(value)}, expected {data_bits}"
                    )
            elif input_format == "hex":
                if data_bits is None:
                    raise ValueError(
                        "data_bits must be provided when input_format='hex'"
                    )
                value = hex_to_binary(raw, data_bits)
            else:  # auto
                lowered = raw.lower()
                if lowered and all(c in "01x" for c in lowered):
                    value = raw  # treat as binary
                else:
                    if data_bits is None:
                        # Infer bit width: 4 bits per hex digit.
                        data_bits = len(raw) * 4
                    value = hex_to_binary(raw, data_bits)

            data[addr_int] = value
    return data


# --------------------------------------------------------------------------- #
# Core dump generator
# --------------------------------------------------------------------------- #

def generate_memory_dump(
    capacity: int,
    data_bits: int,
    fill_mode: str = "x",
    existing_data: Optional[Dict[int, str]] = None,
    rng: Optional[random.Random] = None,
    normalize_x: bool = True,
    base_address: int = 0,
    max_capacity: Optional[int] = DEFAULT_MAX_CAPACITY,
) -> Dict[int, str]:
    """Generate a complete memory dump of size ``capacity``.

    Args:
        capacity: Number of addresses (``base_address`` to
            ``base_address + capacity - 1`` inclusive).
        data_bits: Width of each data word in bits.
        fill_mode: How to fill empty addresses (see module docstring).
        existing_data: Optional dict of ``{addr: binary_data_string}``
            to merge in. Existing entries take precedence over the fill
            pattern. Addresses outside the ``[base, base+capacity)`` range
            are ignored.
        rng: Optional ``random.Random`` instance for reproducibility.
        normalize_x: If True, any existing data containing ``'x'`` is
            normalized to ``'x' * data_bits`` (so partial-x values get
            expanded to full don't-cares).
        base_address: First address in the dump (default 0).
        max_capacity: Soft safeguard against accidental huge allocations.
            Set to ``None`` to disable.

    Returns:
        Dict mapping ``{base_address..base_address+capacity-1} -> data_string``.
        All values are binary strings of length ``data_bits``.
    """
    if capacity < 0:
        raise ValueError(f"capacity must be >= 0, got {capacity}")
    if data_bits <= 0:
        raise ValueError(f"data_bits must be > 0, got {data_bits}")
    if base_address < 0:
        raise ValueError(f"base_address must be >= 0, got {base_address}")
    if max_capacity is not None and capacity > max_capacity:
        raise ValueError(
            f"capacity {capacity} exceeds max_capacity {max_capacity}. "
            f"Pass max_capacity=None to disable this safeguard."
        )

    existing_data = existing_data or {}
    result: Dict[int, str] = {}

    end_address = base_address + capacity

    for addr in range(base_address, end_address):
        if addr in existing_data:
            data = existing_data[addr]
            if normalize_x and "x" in data.lower():
                data = "x" * data_bits
            result[addr] = data
        else:
            result[addr] = fill_value(fill_mode, data_bits, rng=rng)

    return result


# --------------------------------------------------------------------------- #
# Output helpers
# --------------------------------------------------------------------------- #

def _address_width(max_addr: int) -> int:
    """Pick a reasonable hex digit width for the address column."""
    if max_addr <= 0:
        return 3
    return max(3, len(f"{max_addr:X}"))


def format_data_value(
    bin_str: str,
    data_bits: int,
    output_format: str = "bin",
) -> str:
    """Format a binary-string value for output.

    Args:
        bin_str: Binary string of length ``data_bits``.
        data_bits: Width of the value in bits.
        output_format: ``'bin'`` (binary string, default) or ``'hex'``
            (upper-case hex string).

    Returns:
        The formatted value.
    """
    if output_format == "bin":
        return bin_str
    if output_format == "hex":
        return binary_to_hex(bin_str, data_bits)
    raise ValueError(f"output_format must be 'bin' or 'hex'; got {output_format!r}")


def write_memory_csv(
    memory_data: Dict[int, str],
    output_file: str,
    address_width: Optional[int] = None,
    data_bits: Optional[int] = None,
    output_format: str = "bin",
) -> None:
    """Write a memory dump to a CSV file with columns ``address,data``.

    Args:
        memory_data: Dict of ``{addr: binary_string}``.
        output_file: Output path. Parent dirs are created if needed.
        address_width: Number of hex digits for the address column.
            If None, auto-computed from the maximum address.
        data_bits: Width of each data word in bits. Required when
            ``output_format='hex'``.
        output_format: ``'bin'`` (default) or ``'hex'``.
    """
    if output_format == "hex" and data_bits is None:
        raise ValueError("data_bits is required when output_format='hex'")
    if output_format not in ("bin", "hex"):
        raise ValueError(
            f"output_format must be 'bin' or 'hex'; got {output_format!r}"
        )

    if address_width is None:
        max_addr = max(memory_data.keys()) if memory_data else 0
        address_width = _address_width(max_addr)

    out_dir = os.path.dirname(output_file)
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    fmt = f"0x{{:0{address_width}X}}"
    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["address", "data"])
        for addr in sorted(memory_data.keys()):
            value = format_data_value(
                memory_data[addr],
                data_bits=data_bits or len(memory_data[addr]),
                output_format=output_format,
            )
            writer.writerow([fmt.format(addr), value])