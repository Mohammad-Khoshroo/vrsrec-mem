"""Tests for vrsrec_mem.memory_generator."""

from __future__ import annotations

import csv
import io
import os
import random
import tempfile
import unittest

from vrsrec_mem.memory_generator import (
    DEFAULT_MAX_CAPACITY,
    binary_to_hex,
    fill_value,
    format_data_value,
    generate_memory_dump,
    generate_random_data,
    hex_to_binary,
    read_sparse_csv,
    write_memory_csv,
)


class TestGenerateRandomData(unittest.TestCase):
    def test_no_x_when_include_x_false(self):
        rng = random.Random(42)
        for _ in range(100):
            d = generate_random_data(8, include_x=False, rng=rng)
            self.assertEqual(len(d), 8)
            self.assertNotIn("x", d)
            self.assertTrue(set(d) <= {"0", "1"})

    def test_x_possible_when_include_x_true(self):
        # With many draws and include_x=True, we should see at least one
        # all-'x' result eventually (probability ~10% per draw).
        rng = random.Random(0)
        seen_x = False
        for _ in range(500):
            d = generate_random_data(8, include_x=True, rng=rng)
            self.assertEqual(len(d), 8)
            if d == "xxxxxxxx":
                seen_x = True
                break
        self.assertTrue(seen_x, "expected at least one all-x result")

    def test_invalid_bits(self):
        with self.assertRaises(ValueError):
            generate_random_data(0)

    def test_widths(self):
        for bits in (1, 4, 8, 16, 32):
            d = generate_random_data(bits, include_x=False, rng=random.Random(1))
            self.assertEqual(len(d), bits)


class TestFillValue(unittest.TestCase):
    def test_x_mode(self):
        self.assertEqual(fill_value("x", 8), "xxxxxxxx")

    def test_zero_mode(self):
        self.assertEqual(fill_value("0", 4), "0000")

    def test_one_mode(self):
        self.assertEqual(fill_value("1", 4), "1111")

    def test_random_mode_no_x(self):
        d = fill_value("random", 16, rng=random.Random(7))
        self.assertEqual(len(d), 16)
        self.assertNotIn("x", d)

    def test_random_with_x_mode(self):
        # Just check it produces the right length; whether it's x or bits
        # depends on the rng.
        d = fill_value("random_with_x", 8, rng=random.Random(7))
        self.assertEqual(len(d), 8)

    def test_invalid_mode(self):
        with self.assertRaises(ValueError):
            fill_value("invalid", 8)


class TestGenerateMemoryDump(unittest.TestCase):
    def test_capacity_zero(self):
        self.assertEqual(generate_memory_dump(0, 8), {})

    def test_negative_capacity(self):
        with self.assertRaises(ValueError):
            generate_memory_dump(-1, 8)

    def test_invalid_data_bits(self):
        with self.assertRaises(ValueError):
            generate_memory_dump(10, 0)

    def test_default_fill_x(self):
        mem = generate_memory_dump(4, 8, fill_mode="x")
        self.assertEqual(
            mem, {0: "xxxxxxxx", 1: "xxxxxxxx", 2: "xxxxxxxx", 3: "xxxxxxxx"}
        )

    def test_fill_zero(self):
        mem = generate_memory_dump(3, 4, fill_mode="0")
        self.assertEqual(mem, {0: "0000", 1: "0000", 2: "0000"})

    def test_merge_existing(self):
        existing = {1: "10101010", 2: "xxxxxxxx"}
        mem = generate_memory_dump(4, 8, fill_mode="0", existing_data=existing)
        # addr 0: not in existing -> fill 0
        self.assertEqual(mem[0], "00000000")
        # addr 1: from existing
        self.assertEqual(mem[1], "10101010")
        # addr 2: from existing, contains 'x' -> normalized to all 'x'
        self.assertEqual(mem[2], "xxxxxxxx")
        # addr 3: fill 0
        self.assertEqual(mem[3], "00000000")

    def test_merge_existing_no_normalize(self):
        existing = {1: "10x0"}
        mem = generate_memory_dump(
            2, 4, fill_mode="0", existing_data=existing, normalize_x=False
        )
        self.assertEqual(mem[1], "10x0")  # preserved as-is

    def test_seed_reproducibility(self):
        rng1 = random.Random(123)
        rng2 = random.Random(123)
        m1 = generate_memory_dump(50, 8, fill_mode="random", rng=rng1)
        m2 = generate_memory_dump(50, 8, fill_mode="random", rng=rng2)
        self.assertEqual(m1, m2)


class TestReadWriteCsv(unittest.TestCase):
    def test_roundtrip(self):
        mem = {0: "00000000", 1: "11111111", 2: "xxxxxxxx", 3: "10101010"}
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "mem.csv")
            write_memory_csv(mem, path)

            # Verify file contents
            with open(path) as f:
                reader = csv.reader(f)
                header = next(reader)
                self.assertEqual(header, ["address", "data"])
                rows = list(reader)
            self.assertEqual(rows[0][1], "00000000")
            self.assertEqual(rows[2][1], "xxxxxxxx")

            # Round-trip via read_sparse_csv
            read_back = read_sparse_csv(path)
            self.assertEqual(read_back, mem)

    def test_read_accepts_0x_prefix(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "mem.csv")
            with open(path, "w") as f:
                f.write("address,data\n")
                f.write("0x000,00000000\n")
                f.write("0x001,11111111\n")
            read_back = read_sparse_csv(path)
            self.assertEqual(read_back, {0: "00000000", 1: "11111111"})

    def test_write_creates_parent_dir(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "subdir", "nested", "mem.csv")
            write_memory_csv({0: "00000000"}, path)
            self.assertTrue(os.path.exists(path))

    def test_address_width_auto(self):
        # capacity 0x10000 should produce 4-digit hex addresses
        mem = {0: "00000000", 0xFFFF: "11111111"}
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "mem.csv")
            write_memory_csv(mem, path)
            with open(path) as f:
                lines = f.read().splitlines()
            self.assertEqual(lines[1].split(",")[0], "0x0000")
            self.assertEqual(lines[2].split(",")[0], "0xFFFF")


# --------------------------------------------------------------------------- #
# v1.2.0 additions: binary <-> hex conversion
# --------------------------------------------------------------------------- #


class TestBinaryToHex(unittest.TestCase):
    def test_basic_8bit(self):
        self.assertEqual(binary_to_hex("11111111", 8), "FF")
        self.assertEqual(binary_to_hex("00000000", 8), "00")
        self.assertEqual(binary_to_hex("10101010", 8), "AA")
        self.assertEqual(binary_to_hex("01010101", 8), "55")

    def test_4bit(self):
        # 4 bits = 1 hex digit
        self.assertEqual(binary_to_hex("1010", 4), "A")
        self.assertEqual(binary_to_hex("1111", 4), "F")

    def test_12bit(self):
        # 12 bits = 3 hex digits
        self.assertEqual(binary_to_hex("111111111111", 12), "FFF")
        self.assertEqual(binary_to_hex("000000000000", 12), "000")
        self.assertEqual(binary_to_hex("101010101010", 12), "AAA")

    def test_x_propagation(self):
        # Any nibble containing an 'x' becomes 'x'.
        self.assertEqual(binary_to_hex("xxxx1111", 8), "XF")
        self.assertEqual(binary_to_hex("xxxxxxxx", 8), "XX")
        self.assertEqual(binary_to_hex("0000xxxx", 8), "0X")

    def test_width_mismatch_raises(self):
        with self.assertRaises(ValueError):
            binary_to_hex("1010", 8)


class TestHexToBinary(unittest.TestCase):
    def test_basic_8bit(self):
        self.assertEqual(hex_to_binary("FF", 8), "11111111")
        self.assertEqual(hex_to_binary("00", 8), "00000000")
        self.assertEqual(hex_to_binary("AA", 8), "10101010")

    def test_4bit(self):
        self.assertEqual(hex_to_binary("A", 4), "1010")
        self.assertEqual(hex_to_binary("F", 4), "1111")

    def test_12bit(self):
        self.assertEqual(hex_to_binary("FFF", 12), "111111111111")
        self.assertEqual(hex_to_binary("AAA", 12), "101010101010")

    def test_x_expansion(self):
        # X -> 4 x's
        self.assertEqual(hex_to_binary("XF", 8), "xxxx1111")
        self.assertEqual(hex_to_binary("XX", 8), "xxxxxxxx")

    def test_padding(self):
        # Hex string shorter than expected -> left-pad with 0
        self.assertEqual(hex_to_binary("F", 8), "00001111")

    def test_truncation(self):
        # Hex string longer than expected -> take least-significant digits
        self.assertEqual(hex_to_binary("FFF", 8), "11111111")

    def test_invalid_char(self):
        with self.assertRaises(ValueError):
            hex_to_binary("GH", 8)


class TestBinaryHexRoundtrip(unittest.TestCase):
    def test_roundtrip_8bit(self):
        for i in range(256):
            b = f"{i:08b}"
            h = binary_to_hex(b, 8)
            self.assertEqual(hex_to_binary(h, 8), b)

    def test_roundtrip_12bit(self):
        for i in [0, 1, 0xFFF, 0xAAA, 0x555, 0x123]:
            b = f"{i:012b}"
            h = binary_to_hex(b, 12)
            self.assertEqual(hex_to_binary(h, 12), b)


# --------------------------------------------------------------------------- #
# v1.2.0 additions: base_address
# --------------------------------------------------------------------------- #


class TestBaseAddress(unittest.TestCase):
    def test_base_address_zero_default(self):
        mem = generate_memory_dump(4, 8, fill_mode="0")
        self.assertEqual(set(mem.keys()), {0, 1, 2, 3})

    def test_base_address_nonzero(self):
        mem = generate_memory_dump(4, 8, fill_mode="0", base_address=0x1000)
        self.assertEqual(set(mem.keys()), {0x1000, 0x1001, 0x1002, 0x1003})
        self.assertEqual(mem[0x1000], "00000000")

    def test_base_address_with_existing_data(self):
        existing = {0x1001: "11111111"}
        mem = generate_memory_dump(
            4,
            8,
            fill_mode="0",
            base_address=0x1000,
            existing_data=existing,
        )
        self.assertEqual(mem[0x1000], "00000000")
        self.assertEqual(mem[0x1001], "11111111")
        self.assertEqual(mem[0x1002], "00000000")
        self.assertEqual(mem[0x1003], "00000000")

    def test_base_address_outside_existing_ignored(self):
        # Existing data outside [base, base+capacity) should not appear.
        existing = {0x0000: "00000000", 0x1000: "11111111", 0x2000: "10101010"}
        mem = generate_memory_dump(
            4,
            8,
            fill_mode="0",
            base_address=0x1000,
            existing_data=existing,
        )
        # Only addresses in [0x1000, 0x1004) should be present.
        self.assertEqual(set(mem.keys()), {0x1000, 0x1001, 0x1002, 0x1003})
        # 0x0000 and 0x2000 should be ignored
        self.assertNotIn(0x0000, mem)
        self.assertNotIn(0x2000, mem)

    def test_negative_base_address(self):
        with self.assertRaises(ValueError):
            generate_memory_dump(4, 8, base_address=-1)


# --------------------------------------------------------------------------- #
# v1.2.0 additions: max_capacity safeguard
# --------------------------------------------------------------------------- #


class TestMaxCapacity(unittest.TestCase):
    def test_default_max_capacity_constant(self):
        self.assertEqual(DEFAULT_MAX_CAPACITY, 1 << 24)

    def test_capacity_under_max_ok(self):
        mem = generate_memory_dump(10, 8, fill_mode="0", max_capacity=100)
        self.assertEqual(len(mem), 10)

    def test_capacity_over_max_raises(self):
        with self.assertRaises(ValueError) as ctx:
            generate_memory_dump(1000, 8, fill_mode="0", max_capacity=100)
        self.assertIn("exceeds max_capacity", str(ctx.exception))

    def test_max_capacity_disabled(self):
        # max_capacity=None should allow any (reasonable) capacity.
        mem = generate_memory_dump(10, 8, fill_mode="0", max_capacity=None)
        self.assertEqual(len(mem), 10)

    def test_default_max_capacity_in_effect(self):
        # Capacity > DEFAULT_MAX_CAPACITY should raise by default.
        with self.assertRaises(ValueError):
            generate_memory_dump(DEFAULT_MAX_CAPACITY + 1, 8, fill_mode="0")


# --------------------------------------------------------------------------- #
# v1.2.0 additions: hex output format
# --------------------------------------------------------------------------- #


class TestFormatDataValue(unittest.TestCase):
    def test_bin_format(self):
        self.assertEqual(format_data_value("10101010", 8, "bin"), "10101010")

    def test_hex_format(self):
        self.assertEqual(format_data_value("10101010", 8, "hex"), "AA")
        self.assertEqual(format_data_value("11111111", 8, "hex"), "FF")
        self.assertEqual(format_data_value("xxxxxxxx", 8, "hex"), "XX")

    def test_invalid_format(self):
        with self.assertRaises(ValueError):
            format_data_value("10101010", 8, "decimal")


class TestWriteMemoryCsvHex(unittest.TestCase):
    def test_hex_output(self):
        mem = {0: "10101010", 1: "11111111", 2: "xxxxxxxx"}
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "mem.csv")
            write_memory_csv(mem, path, data_bits=8, output_format="hex")
            with open(path) as f:
                lines = f.read().splitlines()
            self.assertEqual(lines[0], "address,data")
            self.assertEqual(lines[1], "0x000,AA")
            self.assertEqual(lines[2], "0x001,FF")
            self.assertEqual(lines[3], "0x002,XX")

    def test_hex_output_requires_data_bits(self):
        with self.assertRaises(ValueError):
            write_memory_csv(
                {0: "10101010"}, "/dev/null", output_format="hex"
            )  # data_bits=None

    def test_bin_output_default(self):
        mem = {0: "10101010"}
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "mem.csv")
            write_memory_csv(mem, path, data_bits=8)
            with open(path) as f:
                lines = f.read().splitlines()
            self.assertEqual(lines[1], "0x000,10101010")


# --------------------------------------------------------------------------- #
# v1.2.0 additions: read_sparse_csv with input_format
# --------------------------------------------------------------------------- #


class TestReadSparseCsvFormats(unittest.TestCase):
    def test_auto_detect_binary(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "in.csv")
            with open(path, "w") as f:
                f.write("address,data\n")
                f.write("0x0,10101010\n")
                f.write("0x1,11111111\n")
            data = read_sparse_csv(path, data_bits=8, input_format="auto")
            self.assertEqual(data, {0: "10101010", 1: "11111111"})

    def test_auto_detect_hex(self):
        # Hex string "AA" contains 'A' which is not in {0,1,x} -> treated as hex.
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "in.csv")
            with open(path, "w") as f:
                f.write("address,data\n")
                f.write("0x0,AA\n")
                f.write("0x1,FF\n")
            data = read_sparse_csv(path, data_bits=8, input_format="auto")
            self.assertEqual(data, {0: "10101010", 1: "11111111"})

    def test_explicit_hex_format(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "in.csv")
            with open(path, "w") as f:
                f.write("address,data\n")
                f.write("0x0,FF\n")
            data = read_sparse_csv(path, data_bits=8, input_format="hex")
            self.assertEqual(data, {0: "11111111"})

    def test_explicit_bin_format(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "in.csv")
            with open(path, "w") as f:
                f.write("address,data\n")
                f.write("0x0,10101010\n")
            data = read_sparse_csv(path, data_bits=8, input_format="bin")
            self.assertEqual(data, {0: "10101010"})

    def test_hex_format_requires_data_bits(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "in.csv")
            with open(path, "w") as f:
                f.write("address,data\n")
                f.write("0x0,FF\n")
            with self.assertRaises(ValueError):
                read_sparse_csv(path, data_bits=None, input_format="hex")

    def test_bin_format_validates_width(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "in.csv")
            with open(path, "w") as f:
                f.write("address,data\n")
                f.write("0x0,10101010\n")  # 8 chars
                f.write("0x1,1010\n")  # 4 chars, mismatch
            with self.assertRaises(ValueError):
                read_sparse_csv(path, data_bits=8, input_format="bin")

    def test_invalid_input_format(self):
        with self.assertRaises(ValueError):
            read_sparse_csv("/dev/null", input_format="decimal")


if __name__ == "__main__":
    unittest.main()
