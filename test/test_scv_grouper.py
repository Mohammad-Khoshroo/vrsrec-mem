"""Tests for src.csv_grouper."""

from __future__ import annotations

import csv
import io
import os
import tempfile
import unittest

from src.csv_grouper import (
    group_bytes_to_words,  # backward-compat alias
    group_hex_to_words,
    read_byte_csv,
    write_grouped_csv,
)


class TestGroupBytesToWordsLittleEndian(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(group_hex_to_words({}, err=io.StringIO()), [])

    def test_basic_little_endian(self):
        # bytes [DE, AD, BE, EF] at addresses [0,1,2,3]
        # little-endian word value = 0xEFBEADDE
        byte_data = {0: "DE", 1: "AD", 2: "BE", 3: "EF"}
        result = group_hex_to_words(byte_data, group_size=4,
                                    endian="little", err=io.StringIO())
        self.assertEqual(len(result), 1)
        base, word_hex, decimal = result[0]
        self.assertEqual(base, 0)
        self.assertEqual(word_hex, "EFBEADDE")
        self.assertEqual(decimal, 0xEFBEADDE)
        self.assertEqual(int(word_hex, 16), decimal)  # invariant

    def test_multiple_groups_little_endian(self):
        byte_data = {
            0: "11", 1: "22", 2: "33", 3: "44",
            4: "55", 5: "66", 6: "77", 7: "88",
        }
        result = group_hex_to_words(byte_data, group_size=4,
                                    endian="little", err=io.StringIO())
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], (0, "44332211", 0x44332211))
        self.assertEqual(result[1], (4, "88776655", 0x88776655))

    def test_non_aligned_start(self):
        # If bytes start at addr 4, base should be 4 (already aligned).
        byte_data = {4: "11", 5: "22", 6: "33", 7: "44"}
        result = group_hex_to_words(byte_data, group_size=4,
                                    endian="little", err=io.StringIO())
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0], 4)

    def test_start_unaligned_to_group(self):
        # If bytes start at addr 1, the base is still 0 (rounded down),
        # but offset 0 is missing -> warning + fill 00.
        byte_data = {1: "AA", 2: "BB", 3: "CC"}
        err_buf = io.StringIO()
        result = group_hex_to_words(byte_data, group_size=4,
                                    endian="little", err=err_buf)
        self.assertEqual(len(result), 1)
        base, word_hex, decimal = result[0]
        self.assertEqual(base, 0)
        # bytes [00, AA, BB, CC] little-endian -> word 0xCCBBAA00
        self.assertEqual(word_hex, "CCBBAA00")
        self.assertIn("missing", err_buf.getvalue())

    def test_strict_mode_raises(self):
        byte_data = {1: "AA", 2: "BB", 3: "CC"}  # missing offset 0
        with self.assertRaises(ValueError) as ctx:
            group_hex_to_words(byte_data, group_size=4,
                               endian="little", strict=True,
                               err=io.StringIO())
        self.assertIn("missing", str(ctx.exception))


class TestGroupBytesToWordsBigEndian(unittest.TestCase):
    def test_basic_big_endian(self):
        # bytes [DE, AD, BE, EF] at addresses [0,1,2,3]
        # big-endian word value = 0xDEADBEEF
        byte_data = {0: "DE", 1: "AD", 2: "BE", 3: "EF"}
        result = group_hex_to_words(byte_data, group_size=4,
                                    endian="big", err=io.StringIO())
        self.assertEqual(len(result), 1)
        base, word_hex, decimal = result[0]
        self.assertEqual(base, 0)
        self.assertEqual(word_hex, "DEADBEEF")
        self.assertEqual(decimal, 0xDEADBEEF)

    def test_invariant_word_hex_equals_decimal(self):
        # For both endians, int(word_hex, 16) must equal decimal.
        byte_data = {0: "11", 1: "22", 2: "33", 3: "44"}
        for endian in ("little", "big"):
            result = group_hex_to_words(byte_data, group_size=4,
                                        endian=endian, err=io.StringIO())
            _, word_hex, decimal = result[0]
            self.assertEqual(int(word_hex, 16), decimal,
                             f"failed for endian={endian}")


class TestGroupBytesToWordsValidation(unittest.TestCase):
    def test_invalid_group_size(self):
        with self.assertRaises(ValueError):
            group_hex_to_words({0: "AA"}, group_size=0, err=io.StringIO())

    def test_invalid_endian(self):
        with self.assertRaises(ValueError):
            group_hex_to_words({0: "AA"}, endian="middle", err=io.StringIO())


class TestGroupBytesToWordsGaps(unittest.TestCase):
    def test_gap_between_groups(self):
        # Two complete groups with a gap in between — both should be reported.
        byte_data = {
            0: "11", 1: "22", 2: "33", 3: "44",
            16: "55", 17: "66", 18: "77", 19: "88",
        }
        err_buf = io.StringIO()
        result = group_hex_to_words(byte_data, group_size=4,
                                    endian="little", err=err_buf)
        # The empty group @8 should be skipped silently.
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0][0], 0)
        self.assertEqual(result[1][0], 16)
        self.assertEqual(err_buf.getvalue(), "")  # no warnings

    def test_group_with_partial_missing(self):
        # Only addresses 0,1 present (offsets 2,3 missing)
        byte_data = {0: "11", 1: "22"}
        err_buf = io.StringIO()
        result = group_hex_to_words(byte_data, group_size=4,
                                    endian="little", err=err_buf)
        self.assertEqual(len(result), 1)
        base, word_hex, decimal = result[0]
        self.assertEqual(base, 0)
        # bytes [11, 22, 00, 00] little-endian -> 0x00002211
        self.assertEqual(word_hex, "00002211")
        self.assertIn("missing", err_buf.getvalue())


class TestGroupSize2(unittest.TestCase):
    def test_halfword_grouping_little(self):
        byte_data = {0: "DE", 1: "AD"}
        result = group_hex_to_words(byte_data, group_size=2,
                                    endian="little", err=io.StringIO())
        self.assertEqual(result, [(0, "ADDE", 0xADDE)])

    def test_halfword_grouping_big(self):
        byte_data = {0: "DE", 1: "AD"}
        result = group_hex_to_words(byte_data, group_size=2,
                                    endian="big", err=io.StringIO())
        self.assertEqual(result, [(0, "DEAD", 0xDEAD)])


class TestReadWriteCsv(unittest.TestCase):
    def test_roundtrip(self):
        grouped = [
            (0, "EFBEADDE", 0xEFBEADDE),
            (4, "88776655", 0x88776655),
        ]
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "grouped.csv")
            write_grouped_csv(grouped, path)

            with open(path) as f:
                reader = csv.DictReader(f)
                self.assertEqual(reader.fieldnames,
                                 ["address", "word-data", "decimal"])
                rows = list(reader)
            self.assertEqual(rows[0]["address"], "0x00000000")
            self.assertEqual(rows[0]["word-data"], "EFBEADDE")
            self.assertEqual(rows[0]["decimal"], str(0xEFBEADDE))

    def test_read_byte_csv(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "in.csv")
            with open(path, "w") as f:
                f.write("address,data\n")
                f.write("0x0000,DE\n")
                f.write("0x0001,AD\n")
                f.write("0x0002,BE\n")
                f.write("0x0003,EF\n")
            data = read_byte_csv(path)
            self.assertEqual(data, {0: "DE", 1: "AD", 2: "BE", 3: "EF"})

    def test_read_byte_csv_missing_columns(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "bad.csv")
            with open(path, "w") as f:
                f.write("addr,byte\n")
                f.write("0x0000,DE\n")
            with self.assertRaises(ValueError):
                read_byte_csv(path)

    def test_write_creates_parent_dir(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "sub", "out.csv")
            write_grouped_csv([(0, "DEADBEEF", 0xDEADBEEF)], path)
            self.assertTrue(os.path.exists(path))


# --------------------------------------------------------------------------- #
# v1.2.0 additions: variable-width input (word-level CSVs)
# --------------------------------------------------------------------------- #

class TestGroupHexWordsVariableWidth(unittest.TestCase):
    """Test that group_hex_to_words works with any hex string width, not
    just 2-char byte strings."""

    def test_word_level_input_4char(self):
        # Input: 16-bit halfwords at 0,1,2,3 -> 64-bit word groups.
        # halfwords: 0x1111, 0x2222, 0x3333, 0x4444
        # little-endian word: 0x4444333322221111
        hex_data = {0: "1111", 1: "2222", 2: "3333", 3: "4444"}
        result = group_hex_to_words(hex_data, group_size=4,
                                    endian="little", err=io.StringIO())
        self.assertEqual(len(result), 1)
        base, word_hex, decimal = result[0]
        self.assertEqual(base, 0)
        self.assertEqual(word_hex, "4444333322221111")
        self.assertEqual(decimal, 0x4444333322221111)

    def test_word_level_input_8char(self):
        # Input: 32-bit words at 0,1 -> 64-bit word group.
        # words: 0xDEADBEEF, 0xCAFEBABE
        # little-endian combined: 0xCAFEBABEDEADBEEF
        hex_data = {0: "DEADBEEF", 1: "CAFEBABE"}
        result = group_hex_to_words(hex_data, group_size=2,
                                    endian="little", err=io.StringIO())
        self.assertEqual(len(result), 1)
        base, word_hex, decimal = result[0]
        self.assertEqual(word_hex, "CAFEBABEDEADBEEF")
        self.assertEqual(decimal, 0xCAFEBABEDEADBEEF)

    def test_word_level_big_endian(self):
        # Same input, big-endian: 0xDEADBEEFCAFEBABE
        hex_data = {0: "DEADBEEF", 1: "CAFEBABE"}
        result = group_hex_to_words(hex_data, group_size=2,
                                    endian="big", err=io.StringIO())
        self.assertEqual(result[0][1], "DEADBEEFCAFEBABE")
        self.assertEqual(result[0][2], 0xDEADBEEFCAFEBABE)

    def test_mixed_widths_rejected(self):
        # If rows have differing hex widths, that's an error.
        hex_data = {0: "DE", 1: "AD", 2: "BEEF", 3: "CAFE"}  # mixed widths
        with self.assertRaises(ValueError) as ctx:
            group_hex_to_words(hex_data, group_size=4, err=io.StringIO())
        self.assertIn("same hex width", str(ctx.exception))

    def test_group_size_2_with_word_input(self):
        # 8-char words, group_size=2 -> 16-char output.
        hex_data = {0: "11223344", 1: "55667788"}
        result = group_hex_to_words(hex_data, group_size=2,
                                    endian="little", err=io.StringIO())
        self.assertEqual(result, [(0, "5566778811223344",
                                    0x5566778811223344)])


class TestReadByteCsvWithWidth(unittest.TestCase):
    """Test that read_byte_csv accepts an explicit input_width."""

    def test_auto_detect_byte_width(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "in.csv")
            with open(path, "w") as f:
                f.write("address,data\n")
                f.write("0x0,DE\n")
                f.write("0x1,AD\n")
            data = read_byte_csv(path)  # auto-detect: width=2
            self.assertEqual(data, {0: "DE", 1: "AD"})

    def test_auto_detect_word_width(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "in.csv")
            with open(path, "w") as f:
                f.write("address,data\n")
                f.write("0x0,DEADBEEF\n")
                f.write("0x1,CAFEBABE\n")
            data = read_byte_csv(path)  # auto-detect: width=8
            self.assertEqual(data, {0: "DEADBEEF", 1: "CAFEBABE"})

    def test_explicit_width_match(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "in.csv")
            with open(path, "w") as f:
                f.write("address,data\n")
                f.write("0x0,DEADBEEF\n")
            data = read_byte_csv(path, input_width=8)
            self.assertEqual(data, {0: "DEADBEEF"})

    def test_explicit_width_mismatch_raises(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "in.csv")
            with open(path, "w") as f:
                f.write("address,data\n")
                f.write("0x0,DE\n")        # 2 chars
                f.write("0x1,DEADBEEF\n")  # 8 chars, mismatch
            with self.assertRaises(ValueError):
                read_byte_csv(path, input_width=2)

    def test_skip_empty_data_rows(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "in.csv")
            with open(path, "w") as f:
                f.write("address,data\n")
                f.write("0x0,DE\n")
                f.write("0x1,\n")  # empty
                f.write("0x2,AD\n")
            data = read_byte_csv(path)
            self.assertEqual(data, {0: "DE", 2: "AD"})


# --------------------------------------------------------------------------- #
# v1.2.0 additions: backward-compat alias
# --------------------------------------------------------------------------- #

class TestBackwardCompatAlias(unittest.TestCase):
    def test_group_bytes_to_words_is_alias(self):
        # The old name should produce the same result as the new name.
        byte_data = {0: "DE", 1: "AD", 2: "BE", 3: "EF"}
        result_old = group_bytes_to_words(byte_data, group_size=4,
                                          endian="little", err=io.StringIO())
        result_new = group_hex_to_words(byte_data, group_size=4,
                                        endian="little", err=io.StringIO())
        self.assertEqual(result_old, result_new)


if __name__ == "__main__":
    unittest.main()