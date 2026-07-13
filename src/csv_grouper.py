"""Group hex-string-addressed CSV data into multi-word groups.

Takes a CSV with columns ``address,data`` (where ``data`` is a hex string
like ``"DE"`` or ``"EFBEADDE"`` — as produced by ``vrsrec-mem
convert --csv --with-address``) and produces a CSV with columns
``address,word-data,decimal``.

The input data column may have any fixed width: a 2-char hex string is
treated as a byte, a 4-char as a halfword, an 8-char as a 32-bit word,
etc. The ``--input-width`` option can force a specific width; otherwise
the width is auto-detected from the first non-empty data value.

Groups are formed by **aligned base address**, not by row index, so
non-contiguous input no longer produces wrong base addresses. Incomplete
or misaligned groups are reported with a warning (or an error in strict
mode).

The output's ``word-data`` column always contains a hex string, and the
``decimal`` column contains the integer value of that hex string (so
``int(word_hex, 16) == decimal`` always holds, regardless of endianness).

Endianness controls the order in which input values are concatenated:
    * ``little`` — input at offset 0 is the least-significant value
    * ``big``    — input at offset 0 is the most-significant value
"""

from __future__ import annotations

import csv
import os
import sys
from typing import Dict, IO, List, Optional, Tuple


def _parse_addr(addr_str: str) -> int:
    s = addr_str.strip()
    if s.lower().startswith("0x"):
        s = s[2:]
    return int(s, 16)


def _detect_hex_width(rows: List[Tuple[int, str]]) -> int:
    """Detect the hex-char width of the data column from the rows."""
    for _, data in rows:
        d = data.strip()
        if d:
            return len(d)
    # No non-empty values — fall back to byte width.
    return 2


def read_byte_csv(
    input_file: str,
    input_width: Optional[int] = None,
) -> Dict[int, str]:
    """Read a CSV with header ``address,data``.

    The ``data`` column is treated as a hex string. The number of hex
    characters per row is either auto-detected from the first non-empty
    row, or forced via ``input_width`` (in **hex characters**).

    Addresses may be in ``"0x123"`` or bare hex form.
    """
    with open(input_file, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None or "address" not in reader.fieldnames \
                or "data" not in reader.fieldnames:
            raise ValueError(
                f"Input CSV must have 'address' and 'data' columns; "
                f"got {reader.fieldnames}"
            )
        rows: List[Tuple[int, str]] = []
        for row in reader:
            addr_int = _parse_addr(row["address"])
            data_str = row["data"].strip()
            rows.append((addr_int, data_str))

    if input_width is None:
        input_width = _detect_hex_width(rows)

    # Validate widths and build the dict.
    data: Dict[int, str] = {}
    for addr_int, data_str in rows:
        if not data_str:
            continue
        if len(data_str) != input_width:
            raise ValueError(
                f"address 0x{addr_int:X}: data {data_str!r} has width "
                f"{len(data_str)} chars, expected {input_width}"
            )
        data[addr_int] = data_str
    return data


def group_hex_to_words(
    hex_data: Dict[int, str],
    group_size: int = 4,
    endian: str = "little",
    strict: bool = False,
    err: IO[str] = sys.stderr,
) -> List[Tuple[int, str, int]]:
    """Group hex-string-addressed data into multi-element word groups.

    Args:
        hex_data: Dict of ``{address: hex_string}``. All hex strings must
            have the same length (e.g. all 2-char for byte input, all
            8-char for 32-bit word input). The unit of ``group_size`` is
            the number of input elements per group, NOT the number of hex
            characters.
        group_size: Number of input elements per group (default 4).
            Example: if the input is byte-level (2-char hex), ``group_size=4``
            produces 32-bit word groups. If the input is already 32-bit
            word-level (8-char hex), ``group_size=2`` produces 64-bit groups.
        endian: ``'little'`` or ``'big'``.
        strict: If True, raise on incomplete/misaligned groups; else warn.
        err: Stream for warnings.

    Returns:
        List of ``(base_address, word_hex, decimal_value)`` tuples,
        sorted by address.
    """
    if group_size < 1:
        raise ValueError(f"group_size must be >= 1, got {group_size}")
    if endian not in ("little", "big"):
        raise ValueError(f"endian must be 'little' or 'big', got {endian}")
    if not hex_data:
        return []

    # All input strings must have the same width.
    widths = {len(v) for v in hex_data.values()}
    if len(widths) != 1:
        raise ValueError(
            f"all data values must have the same hex width; got {sorted(widths)}"
        )
    unit_width = widths.pop()
    if unit_width < 1:
        raise ValueError(f"invalid data width: {unit_width}")

    sorted_addrs = sorted(hex_data.keys())
    min_addr = sorted_addrs[0]
    max_addr = sorted_addrs[-1]

    # Align min_addr down to the nearest group boundary.
    first_base = min_addr - (min_addr % group_size)

    result: List[Tuple[int, str, int]] = []
    for base in range(first_base, max_addr + 1, group_size):
        units_in_group: List[Optional[str]] = []
        missing: List[int] = []
        for offset in range(group_size):
            a = base + offset
            if a in hex_data:
                units_in_group.append(hex_data[a])
            else:
                units_in_group.append(None)
                missing.append(offset)

        if all(u is None for u in units_in_group):
            continue  # completely empty group — skip silently

        if missing:
            msg = (
                f"Warning: group @0x{base:08X} has missing offset(s) "
                f"{missing}; filling with {'0' * unit_width}"
            )
            if strict:
                raise ValueError(msg)
            print(msg, file=err)
            units_in_group = [
                u if u is not None else "0" * unit_width
                for u in units_in_group
            ]

        # units_in_group is now a list of `group_size` hex strings,
        # in address-ascending order (offset 0, 1, ..., group_size-1).
        #
        # For little-endian: offset 0 is the LSB. The word value's hex
        #   string is units in REVERSE order.
        # For big-endian: offset 0 is the MSB. The word value's hex
        #   string is units in order.
        if endian == "little":
            ordered = list(reversed(units_in_group))
        else:
            ordered = list(units_in_group)
        word_hex = "".join(ordered).upper()
        decimal_value = int(word_hex, 16)

        result.append((base, word_hex, decimal_value))

    return result


# Backward compatibility: keep the old name as an alias.
def group_bytes_to_words(
    byte_data: Dict[int, str],
    group_size: int = 4,
    endian: str = "little",
    strict: bool = False,
    err: IO[str] = sys.stderr,
) -> List[Tuple[int, str, int]]:
    """Backward-compatible alias for :func:`group_hex_to_words`."""
    return group_hex_to_words(
        byte_data,
        group_size=group_size,
        endian=endian,
        strict=strict,
        err=err,
    )


def write_grouped_csv(
    grouped_data: List[Tuple[int, str, int]],
    output_file: str,
    address_width: int = 8,
) -> None:
    """Write grouped data to a CSV with columns ``address,word-data,decimal``.

    Args:
        grouped_data: List of ``(base_address, word_hex, decimal_value)``.
        output_file: Output path. Parent dirs are created if needed.
        address_width: Number of hex digits for the address column (default 8).
    """
    out_dir = os.path.dirname(output_file)
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    fmt = f"0x{{:0{address_width}X}}"
    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["address", "word-data", "decimal"]
        )
        writer.writeheader()
        for base, word_hex, decimal in grouped_data:
            writer.writerow(
                {
                    "address": fmt.format(base),
                    "word-data": word_hex,
                    "decimal": decimal,
                }
            )