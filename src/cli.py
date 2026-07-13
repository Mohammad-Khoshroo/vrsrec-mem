"""Command-line interface for the S-Record converter toolkit.

Three subcommands:
    convert   Convert a Motorola S-Record file to mem/txt/csv.
    gen       Generate a fully-populated memory dump CSV.
    group     Group a byte-addressed CSV into multi-byte words.

For backward compatibility with v1.0.x, if no subcommand is given the
first positional argument is treated as an input file for ``convert``:

    vrsrec-mem file.srec            # equivalent to `convert file.srec`
    vrsrec-mem convert file.srec
    vrsrec-mem gen -c 256 -w 8
    vrsrec-mem group input.csv
"""

from __future__ import annotations

import argparse
import io
import os
import random
import sys
from typing import List, Optional

from .formatter import format_output, get_output_extension
from .parser import convert_srecord_stream
from .memory_generator import (
    DEFAULT_MAX_CAPACITY,
    generate_memory_dump,
    read_sparse_csv,
    write_memory_csv,
)
from .csv_grouper import (
    group_hex_to_words,
    read_byte_csv,
    write_grouped_csv,
)

# Avoid circular import: read __version__ lazily.
def _get_version() -> str:
    from . import __version__
    return __version__


KNOWN_SUBCOMMANDS = {"convert", "gen", "group"}


# --------------------------------------------------------------------------- #
# Subparser builders
# --------------------------------------------------------------------------- #

def _add_convert_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("filename", help="Input S-Record file")
    parser.add_argument(
        "--with-address", action="store_true", help="Include address in output"
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Suppress overlap and padding warnings",
    )
    parser.add_argument(
        "-o", "--output",
        help="Write to this file instead of <basename>.<ext>",
    )

    width_group = parser.add_mutually_exclusive_group()
    width_group.add_argument(
        "--byte-format", action="store_const", dest="data_width",
        const="byte", help="Output 8-bit bytes, default",
    )
    width_group.add_argument(
        "--halfword-format", action="store_const", dest="data_width",
        const="halfword", help="Output 16-bit halfwords",
    )
    width_group.add_argument(
        "--word-format", action="store_const", dest="data_width",
        const="word", help="Output 32-bit words",
    )

    format_group = parser.add_mutually_exclusive_group()
    format_group.add_argument(
        "--mem", action="store_const", dest="out_format", const="mem",
        help="Output .mem format, default",
    )
    format_group.add_argument(
        "--txt", action="store_const", dest="out_format", const="txt",
        help="Output .txt format",
    )
    format_group.add_argument(
        "--csv", action="store_const", dest="out_format", const="csv",
        help="Output .csv format",
    )

    endian_group = parser.add_mutually_exclusive_group()
    endian_group.add_argument(
        "--little-endian", action="store_const", dest="endian", const="little",
        help="Output little-endian values, default",
    )
    endian_group.add_argument(
        "--big-endian", action="store_const", dest="endian", const="big",
        help="Output big-endian values",
    )

    parser.set_defaults(
        data_width="byte", out_format="mem", endian="little",
    )


def _add_gen_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-i", "--input", type=str, default=None,
        help="Optional sparse CSV (address,data) to merge into the dump.",
    )
    parser.add_argument(
        "-o", "--output", type=str, default="output.csv",
        help="Output CSV file (default: output.csv).",
    )
    parser.add_argument(
        "-c", "--capacity", type=int, required=True,
        help="Total memory capacity (number of addresses).",
    )
    parser.add_argument(
        "-w", "--width", type=int, default=8,
        help="Data width in bits (default: 8).",
    )
    parser.add_argument(
        "-f", "--fill",
        choices=["x", "0", "1", "random", "random_with_x"],
        default="x",
        help="Fill pattern for empty addresses (default: x).",
    )
    parser.add_argument(
        "--seed", type=int, default=None,
        help="Random seed for reproducible random fills.",
    )
    parser.add_argument(
        "--base-address", type=lambda s: int(s, 0),
        default=0,
        help="First address in the dump (default: 0). Accepts decimal or "
             "0x-prefixed hex (e.g. 0x1000).",
    )
    parser.add_argument(
        "--hex-output", action="store_const", dest="output_format",
        const="hex", default="bin",
        help="Write data column as hex string (for $readmemh). Default: "
             "binary string (for $readmemb).",
    )
    parser.add_argument(
        "--input-format", choices=["auto", "bin", "hex"], default="auto",
        help="Format of the optional --input CSV's data column (default: auto).",
    )
    parser.add_argument(
        "--max-capacity", type=int, default=DEFAULT_MAX_CAPACITY,
        help=f"Soft safeguard against huge allocations "
             f"(default: {DEFAULT_MAX_CAPACITY}). Set to 0 to disable.",
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true",
        help="Suppress status messages.",
    )


def _add_group_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "input",
        help="Input CSV file with columns: address,data (hex string per row).",
    )
    parser.add_argument(
        "-o", "--output", type=str, default="output_grouped.csv",
        help="Output CSV file (default: output_grouped.csv).",
    )
    parser.add_argument(
        "-s", "--group-size", type=int, default=4,
        help="Number of input elements per group (default: 4).",
    )
    parser.add_argument(
        "--input-width", type=int, default=None,
        help="Force input hex width in characters (default: auto-detect "
             "from first non-empty row). Example: 2 for bytes, 8 for 32-bit "
             "words.",
    )
    endian_group = parser.add_mutually_exclusive_group()
    endian_group.add_argument(
        "--little-endian", action="store_const", dest="endian", const="little",
        help="Treat element at offset 0 as LSB (default).",
    )
    endian_group.add_argument(
        "--big-endian", action="store_const", dest="endian", const="big",
        help="Treat element at offset 0 as MSB.",
    )
    parser.set_defaults(endian="little")
    parser.add_argument(
        "--strict", action="store_true",
        help="Error instead of warn on incomplete/misaligned groups.",
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true",
        help="Suppress warnings and status messages.",
    )


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the top-level parser with subcommands."""
    parser = argparse.ArgumentParser(
        prog="vrsrec-mem",
        description=(
            "Motorola S-Record converter + memory utilities for "
            "hardware simulation workflows."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--version", action="version",
        version=f"vrsrec-mem {_get_version()}",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p_conv = sub.add_parser(
        "convert",
        help="Convert S-Record file to mem/txt/csv",
        description=(
            "Convert a Motorola S-Record file to Verilog .mem, .txt, or .csv "
            "format."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    _add_convert_arguments(p_conv)

    p_gen = sub.add_parser(
        "gen",
        help="Generate a fully-populated memory dump CSV",
        description=(
            "Generate a memory dump CSV with all addresses from 0 to "
            "capacity-1, optionally merging in a sparse CSV. Useful for "
            "creating $readmemb-compatible inputs."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    _add_gen_arguments(p_gen)

    p_group = sub.add_parser(
        "group",
        help="Group a byte-addressed CSV into multi-byte words",
        description=(
            "Group a CSV with columns (address,data) where data is a hex "
            "byte into a CSV with columns (address,word-data,decimal). "
            "Useful as a post-processing step after `convert --csv`."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    _add_group_arguments(p_group)

    return parser


# --------------------------------------------------------------------------- #
# Subcommand handlers
# --------------------------------------------------------------------------- #

def cmd_convert(args) -> int:
    """Execute the `convert` subcommand (originally the only command)."""
    try:
        file_handle = open(args.filename, "r", encoding="ascii")
    except FileNotFoundError:
        print(f"Error: File '{args.filename}' not found.", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"Error: Cannot open '{args.filename}': {exc}", file=sys.stderr)
        return 1

    warn_err = sys.stderr if not args.quiet else io.StringIO()

    try:
        with file_handle:
            memory_data = convert_srecord_stream(
                file_handle,
                warn_on_overlap=not args.quiet,
                err=warn_err,
            )
    except UnicodeDecodeError:
        print(
            f"Error: File '{args.filename}' is not valid ASCII text.",
            file=sys.stderr,
        )
        return 1
    except ValueError as exc:
        print(f"Conversion Error: {exc}", file=sys.stderr)
        return 1

    if not memory_data:
        print(
            f"Warning: No data records found in '{args.filename}'. "
            "No output file written.",
            file=sys.stderr,
        )
        return 0

    try:
        formatted = format_output(
            memory_data=memory_data,
            data_width=args.data_width,
            with_address=args.with_address,
            out_format=args.out_format,
            endian=args.endian,
            err=warn_err,
        )
    except ValueError as exc:
        print(f"Format Error: {exc}", file=sys.stderr)
        return 1

    if args.output:
        out_filename = args.output
    else:
        base_name = os.path.splitext(args.filename)[0]
        out_ext = get_output_extension(args.out_format)
        out_filename = base_name + out_ext

    try:
        with open(out_filename, "w", encoding="ascii") as out_file:
            out_file.write(formatted)
            if not formatted.endswith("\n"):
                out_file.write("\n")
    except OSError as exc:
        print(f"Error: Cannot write '{out_filename}': {exc}", file=sys.stderr)
        return 1

    print(f"Successfully converted '{args.filename}' to '{out_filename}'.")
    return 0


def cmd_gen(args) -> int:
    """Execute the `gen` subcommand."""
    rng = random.Random(args.seed) if args.seed is not None else random.Random()

    # Resolve max_capacity safeguard. 0 means "disabled".
    max_cap = args.max_capacity if args.max_capacity and args.max_capacity > 0 else None

    existing_data = None
    if args.input:
        if not os.path.exists(args.input):
            print(
                f"Error: Input file '{args.input}' not found.", file=sys.stderr
            )
            return 1
        try:
            existing_data = read_sparse_csv(
                args.input,
                data_bits=args.width,
                input_format=args.input_format,
            )
            if not args.quiet:
                print(
                    f"Read {len(existing_data)} entries from {args.input}",
                    file=sys.stderr,
                )
        except Exception as exc:
            print(f"Error reading input file: {exc}", file=sys.stderr)
            return 1

    try:
        memory = generate_memory_dump(
            capacity=args.capacity,
            data_bits=args.width,
            fill_mode=args.fill,
            existing_data=existing_data,
            rng=rng,
            base_address=args.base_address,
            max_capacity=max_cap,
        )
        write_memory_csv(
            memory,
            args.output,
            data_bits=args.width,
            output_format=args.output_format,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if not args.quiet:
        print(
            f"Successfully generated memory with capacity {args.capacity} "
            f"to {args.output}",
            file=sys.stderr,
        )
    return 0


def cmd_group(args) -> int:
    """Execute the `group` subcommand."""
    err = sys.stderr if not args.quiet else io.StringIO()
    try:
        byte_data = read_byte_csv(
            args.input,
            input_width=args.input_width,
        )
    except FileNotFoundError:
        print(f"Error: File '{args.input}' not found!", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error reading input CSV: {exc}", file=sys.stderr)
        return 1

    try:
        grouped = group_hex_to_words(
            byte_data,
            group_size=args.group_size,
            endian=args.endian,
            strict=args.strict,
            err=err,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    try:
        write_grouped_csv(grouped, args.output)
    except Exception as exc:
        print(f"Error writing output file: {exc}", file=sys.stderr)
        return 1

    if not args.quiet:
        print(
            f"Success! Created {len(grouped)} {args.group_size}-byte groups.",
            file=sys.stderr,
        )
        print(f"Output file: {args.output}", file=sys.stderr)
    return 0


# --------------------------------------------------------------------------- #
# Top-level dispatch
# --------------------------------------------------------------------------- #

def main(argv: Optional[List[str]] = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    # Backward-compat shim: if the first arg is not a known subcommand
    # and not a flag, treat the whole invocation as `convert <args>`.
    # This keeps `vrsrec-mem file.srec` working as before.
    if argv and argv[0] not in KNOWN_SUBCOMMANDS and not argv[0].startswith("-"):
        argv = ["convert"] + argv

    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 1

    dispatch = {
        "convert": cmd_convert,
        "gen": cmd_gen,
        "group": cmd_group,
    }
    return dispatch[args.command](args)


if __name__ == "__main__":
    sys.exit(main())