"""Motorola S-Record parsing.

This module knows how to read S-Record text and turn it into a flat
``{address: byte_hex}`` dict. It supports S0/S1/S2/S3 data records and
S7/S8/S9 termination records; S4/S5/S6 are silently skipped.

The parser is strict about:
    * line length (must match the byte-count field)
    * hex validity
    * Motorola checksum rule: ``low_byte(count + address + data + checksum) == 0xFF``
"""

from __future__ import annotations

import sys
from typing import Dict, IO, Optional, Tuple, Union


# Type alias for a parsed data record: (address, data_hex).
ParsedRecord = Tuple[int, str]


def parse_srecord_line(line: str, line_no: int) -> Optional[Union[str, ParsedRecord]]:
    """Parse one S-Record line.

    Returns:
        ``None``           -> skip (header / count / unknown type)
        ``"EOF"``          -> termination record (S7/S8/S9)
        ``(address, data_hex)`` -> data record (S1/S2/S3)

    Raises:
        ValueError: on any malformed line.
    """
    line = line.strip().upper()

    if not line or not line.startswith("S"):
        return None

    if len(line) < 4:
        raise ValueError(f"Line {line_no}: record too short")

    record_type = line[1]

    # Header / count records are ignored.
    if record_type in ("0", "4", "5", "6"):
        return None

    # Termination records.
    if record_type in ("7", "8", "9"):
        return "EOF"

    # Only data records remain.
    if record_type not in ("1", "2", "3"):
        return None

    try:
        byte_count = int(line[2:4], 16)
    except ValueError as exc:
        raise ValueError(f"Line {line_no}: invalid byte count") from exc

    address_hex_len = {"1": 4, "2": 6, "3": 8}[record_type]
    address_byte_len = address_hex_len // 2
    data_byte_len = byte_count - address_byte_len - 1

    if data_byte_len < 0:
        raise ValueError(f"Line {line_no}: invalid byte count")

    expected_line_len = 4 + byte_count * 2
    if len(line) != expected_line_len:
        raise ValueError(
            f"Line {line_no}: invalid length, "
            f"expected {expected_line_len}, got {len(line)}"
        )

    address_start = 4
    address_end = address_start + address_hex_len
    data_start = address_end
    data_end = data_start + data_byte_len * 2
    checksum_start = data_end
    checksum_end = checksum_start + 2

    if checksum_end != len(line):
        raise ValueError(f"Line {line_no}: invalid checksum field")

    try:
        address = int(line[address_start:address_end], 16)
        data_hex = line[data_start:data_end]
        checksum = int(line[checksum_start:checksum_end], 16)
        # Bytes included in checksum: count + address + data
        record_bytes = bytes.fromhex(line[2:checksum_start])
    except ValueError as exc:
        raise ValueError(f"Line {line_no}: invalid hex data") from exc

    # Motorola S-Record checksum rule:
    # low byte of (count + address + data + checksum) must be 0xFF.
    if ((sum(record_bytes) + checksum) & 0xFF) != 0xFF:
        raise ValueError(f"Line {line_no}: checksum mismatch")

    return address, data_hex


def convert_srecord_stream(
    file_handle: IO[str],
    warn_on_overlap: bool = True,
    err: IO[str] = sys.stderr,
) -> Dict[int, str]:
    """Parse S-Record content from a file object (line-by-line).

    Args:
        file_handle: An iterable of lines (e.g. an open text file).
        warn_on_overlap: If True, print a warning when an address is
            written more than once.
        err: Stream for warnings (default: stderr).

    Returns:
        Dict mapping ``address -> 2-char hex byte string``.
    """
    memory_data: Dict[int, str] = {}

    for line_no, line in enumerate(file_handle, start=1):
        parsed = parse_srecord_line(line, line_no)

        if parsed is None:
            continue

        if parsed == "EOF":
            break

        address, data_hex = parsed

        for i in range(0, len(data_hex), 2):
            byte_value = data_hex[i:i + 2]

            if warn_on_overlap and address in memory_data:
                print(
                    f"Warning: Line {line_no}: address 0x{address:08X} overwritten",
                    file=err,
                )

            memory_data[address] = byte_value
            address += 1

    return memory_data


def convert_srecord_string(
    text: str,
    warn_on_overlap: bool = True,
    err: IO[str] = sys.stderr,
) -> Dict[int, str]:
    """Convenience wrapper around :func:`convert_srecord_stream` for strings."""
    return convert_srecord_stream(
        text.splitlines(),
        warn_on_overlap=warn_on_overlap,
        err=err,
    )