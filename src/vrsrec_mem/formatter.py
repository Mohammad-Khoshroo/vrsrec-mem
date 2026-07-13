"""Output formatting for the S-Record converter.

Turns a flat ``{address: byte_hex}`` dict into one of:
    * ``mem`` — Verilog ``$readmemh``-compatible text
    * ``txt`` — plain ``address: value`` or just ``value`` per line
    * ``csv`` — two-column ``address,data`` (or single-column ``data``)

Important behavior:
    * If the data has gaps and the user did not pass ``--with-address``
      for ``mem`` output, we **auto-switch** to ``@addr`` lines so the
      result stays correct for ``$readmemh``. A warning is emitted.
    * Missing bytes inside an aligned chunk are padded with ``0x00`` and
      a warning is printed listing the missing offsets.
"""

from __future__ import annotations

import csv
import io
import sys
from typing import Dict, IO, List, Tuple


WIDTH_MAP = {"byte": 1, "halfword": 2, "word": 4}


def make_value(bytes_collected: List[str], endian: str) -> str:
    """Convert collected bytes to an output value string."""
    if endian == "little":
        bytes_collected = list(reversed(bytes_collected))
    return "".join(bytes_collected)


def detect_gaps(sorted_addresses: List[int]) -> bool:
    """Return True if there is any address gap in the sorted list."""
    if len(sorted_addresses) < 2:
        return False
    prev = sorted_addresses[0]
    for a in sorted_addresses[1:]:
        if a != prev + 1:
            return True
        prev = a
    return False


def format_output(
    memory_data: Dict[int, str],
    data_width: str = "byte",
    with_address: bool = False,
    out_format: str = "mem",
    endian: str = "little",
    err: IO[str] = sys.stderr,
) -> str:
    """Format memory data into mem, txt, or csv output.

    See module docstring for the gap / padding behavior.
    """
    if not memory_data:
        return ""

    if data_width not in WIDTH_MAP:
        raise ValueError(f"Unsupported data width: {data_width}")
    if out_format not in ("mem", "txt", "csv"):
        raise ValueError(f"Unsupported output format: {out_format}")
    if endian not in ("little", "big"):
        raise ValueError(f"Unsupported endian: {endian}")

    size = WIDTH_MAP[data_width]
    sorted_addresses = sorted(memory_data.keys())

    # --- .mem without --with-address + gaps -> auto-switch ----------
    auto_address = False
    if out_format == "mem" and not with_address:
        if detect_gaps(sorted_addresses):
            print(
                "Warning: data has address gaps; .mem output without "
                "--with-address would be incorrect. "
                "Auto-switching to @addr value lines.",
                file=err,
            )
            auto_address = True

    output: List[Tuple[str, str]] = []  # (addr_tag_or_None, value)
    i = 0
    while i < len(sorted_addresses):
        addr = sorted_addresses[i]
        aligned_addr = addr - (addr % size)

        # Warn when padding missing bytes with 0x00.
        missing_offsets: List[int] = []
        bytes_collected: List[str] = []
        for offset in range(size):
            a = aligned_addr + offset
            if a in memory_data:
                bytes_collected.append(memory_data[a])
            else:
                bytes_collected.append("00")
                missing_offsets.append(offset)

        if missing_offsets:
            print(
                f"Warning: address 0x{aligned_addr:08X}: "
                f"byte offset(s) {missing_offsets} not present, "
                f"filled with 0x00",
                file=err,
            )

        value = make_value(bytes_collected, endian)

        if out_format == "mem":
            if with_address or auto_address:
                # Standard $readmemh layout: @addr on its own line, then value.
                output.append((f"@{aligned_addr // size:08X}", value))
            else:
                output.append((None, value))

        elif out_format == "txt":
            if with_address:
                output.append((f"{aligned_addr:08X}:", value))
            else:
                output.append((None, value))

        elif out_format == "csv":
            if with_address:
                output.append((f"0x{aligned_addr:08X}", value))
            else:
                output.append((None, value))

        next_addr = aligned_addr + size
        while i < len(sorted_addresses) and sorted_addresses[i] < next_addr:
            i += 1

    # --- Render ------------------------------------------------------
    if out_format == "csv":
        buf = io.StringIO(newline="")
        writer = csv.writer(buf)
        writer.writerow(["address", "data"] if with_address else ["data"])
        for row in output:
            writer.writerow([c for c in row if c is not None])
        return buf.getvalue().strip()

    if out_format == "mem":
        lines: List[str] = []
        for addr_tag, val in output:
            if addr_tag is not None:
                lines.append(addr_tag)
                lines.append(val)
            else:
                lines.append(val)
        return "\n".join(lines)

    # txt
    lines = []
    for addr_tag, val in output:
        if addr_tag is not None:
            lines.append(f"{addr_tag} {val}")
        else:
            lines.append(val)
    return "\n".join(lines)


def get_output_extension(out_format: str) -> str:
    """Return the conventional file extension for an output format."""
    if out_format == "csv":
        return ".csv"
    if out_format == "txt":
        return ".txt"
    return ".mem"