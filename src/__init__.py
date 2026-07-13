"""
src — Motorola S-Record to mem/txt/csv converter + memory
utilities for hardware simulation workflows.

Public API:
    # S-Record parsing
    parse_srecord_line(line, line_no)
    convert_srecord_stream(file_handle, warn_on_overlap, err)
    convert_srecord_string(text, warn_on_overlap, err)

    # Output formatting
    WIDTH_MAP
    make_value(bytes_collected, endian)
    detect_gaps(sorted_addresses)
    format_output(memory_data, data_width, with_address, out_format, endian, err)
    get_output_extension(out_format)

    # Memory dump generator (new in v1.1.0; extended in v1.2.0)
    DEFAULT_MAX_CAPACITY
    generate_random_data(data_bits, include_x, rng)
    fill_value(fill_mode, data_bits, rng)
    binary_to_hex(bin_str, data_bits)
    hex_to_binary(hex_str, data_bits)
    read_sparse_csv(input_file, data_bits, input_format)
    generate_memory_dump(capacity, data_bits, fill_mode, existing_data, rng,
                         normalize_x, base_address, max_capacity)
    format_data_value(bin_str, data_bits, output_format)
    write_memory_csv(memory_data, output_file, address_width, data_bits,
                     output_format)

    # CSV hex->word grouper (new in v1.1.0; extended in v1.2.0)
    read_byte_csv(input_file, input_width)
    group_hex_to_words(hex_data, group_size, endian, strict, err)
    group_bytes_to_words  # backward-compat alias for group_hex_to_words
    write_grouped_csv(grouped_data, output_file, address_width)

CLI entry point:
    python -m src <command> [options]

    Commands:
        convert   Convert S-Record file to mem/txt/csv
        gen       Generate a fully-populated memory dump CSV
        group     Group a byte-addressed CSV into multi-byte words

    Backward compat: `python -m src file.srec` is equivalent
    to `python -m src convert file.srec`.
"""

from .parser import (
    parse_srecord_line,
    convert_srecord_stream,
    convert_srecord_string,
)
from .formatter import (
    WIDTH_MAP,
    make_value,
    detect_gaps,
    format_output,
    get_output_extension,
)
from .memory_generator import (
    DEFAULT_MAX_CAPACITY,
    generate_random_data,
    fill_value,
    binary_to_hex,
    hex_to_binary,
    read_sparse_csv,
    generate_memory_dump,
    format_data_value,
    write_memory_csv,
)
from .csv_grouper import (
    read_byte_csv,
    group_hex_to_words,
    group_bytes_to_words,
    write_grouped_csv,
)
from .cli import build_arg_parser, main

__version__ = "1.2.0"
__all__ = [
    # Parser
    "parse_srecord_line",
    "convert_srecord_stream",
    "convert_srecord_string",
    # Formatter
    "WIDTH_MAP",
    "make_value",
    "detect_gaps",
    "format_output",
    "get_output_extension",
    # Memory generator
    "DEFAULT_MAX_CAPACITY",
    "generate_random_data",
    "fill_value",
    "binary_to_hex",
    "hex_to_binary",
    "read_sparse_csv",
    "generate_memory_dump",
    "format_data_value",
    "write_memory_csv",
    # CSV grouper
    "read_byte_csv",
    "group_hex_to_words",
    "group_bytes_to_words",
    "write_grouped_csv",
    # CLI
    "build_arg_parser",
    "main",
    "__version__",
]
