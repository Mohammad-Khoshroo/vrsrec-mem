"""Tests for src.formatter."""

from __future__ import annotations

import io
import unittest

from src.formatter import (
    WIDTH_MAP,
    detect_gaps,
    format_output,
    get_output_extension,
    make_value,
)


def make_memory():
    """Return {0:11, 1:22, 2:33, 3:44, 4:55, 5:66, 6:77, 7:88}."""
    return {
        0: "11", 1: "22", 2: "33", 3: "44",
        4: "55", 5: "66", 6: "77", 7: "88",
    }


class TestMakeValue(unittest.TestCase):
    def test_little_endian(self):
        self.assertEqual(make_value(["11", "22", "33", "44"], "little"), "44332211")

    def test_big_endian(self):
        self.assertEqual(make_value(["11", "22", "33", "44"], "big"), "11223344")


class TestDetectGaps(unittest.TestCase):
    def test_no_gaps(self):
        self.assertFalse(detect_gaps([0, 1, 2, 3]))
        self.assertFalse(detect_gaps([5]))
        self.assertFalse(detect_gaps([]))

    def test_with_gaps(self):
        self.assertTrue(detect_gaps([0, 1, 2, 4]))
        self.assertTrue(detect_gaps([0, 4]))


class TestFormatOutput(unittest.TestCase):
    def test_empty_memory(self):
        self.assertEqual(format_output({}, err=io.StringIO()), "")

    def test_invalid_width(self):
        with self.assertRaises(ValueError):
            format_output({0: "11"}, data_width="dword", err=io.StringIO())

    def test_invalid_format(self):
        with self.assertRaises(ValueError):
            format_output({0: "11"}, out_format="json", err=io.StringIO())

    def test_invalid_endian(self):
        with self.assertRaises(ValueError):
            format_output({0: "11"}, endian="middle", err=io.StringIO())

    # --- byte width -----------------------------------------------
    def test_byte_mem_no_address_contiguous(self):
        out = format_output(make_memory(), err=io.StringIO())
        self.assertEqual(out.splitlines(), ["11", "22", "33", "44", "55", "66", "77", "88"])

    def test_byte_mem_with_address(self):
        out = format_output(make_memory(), with_address=True, err=io.StringIO())
        self.assertIn("@00000000", out)
        self.assertIn("@00000004", out)

    def test_byte_txt_with_address(self):
        out = format_output(make_memory(), out_format="txt", with_address=True, err=io.StringIO())
        self.assertIn("00000000: 11", out)
        self.assertIn("00000007: 88", out)

    def test_byte_csv_with_address(self):
        out = format_output(make_memory(), out_format="csv", with_address=True, err=io.StringIO())
        lines = out.splitlines()
        self.assertEqual(lines[0], "address,data")
        self.assertEqual(lines[1], "0x00000000,11")
        self.assertEqual(lines[-1], "0x00000007,88")

    def test_byte_csv_no_address(self):
        out = format_output(make_memory(), out_format="csv", with_address=False, err=io.StringIO())
        lines = out.splitlines()
        self.assertEqual(lines[0], "data")
        self.assertEqual(lines[1], "11")
        self.assertEqual(lines[-1], "88")

    # --- word width -----------------------------------------------
    def test_word_mem_little_endian(self):
        out = format_output(make_memory(), data_width="word", endian="little", err=io.StringIO())
        # little-endian: 0x44332211, 0x88776655
        self.assertEqual(out.splitlines(), ["44332211", "88776655"])

    def test_word_mem_big_endian(self):
        out = format_output(make_memory(), data_width="word", endian="big", err=io.StringIO())
        self.assertEqual(out.splitlines(), ["11223344", "55667788"])

    def test_word_mem_with_address(self):
        out = format_output(
            make_memory(), data_width="word", with_address=True, err=io.StringIO()
        )
        lines = out.splitlines()
        self.assertEqual(lines[0], "@00000000")
        self.assertEqual(lines[1], "44332211")
        self.assertEqual(lines[2], "@00000001")
        self.assertEqual(lines[3], "88776655")

    # --- halfword width -------------------------------------------
    def test_halfword_little(self):
        out = format_output(make_memory(), data_width="halfword", endian="little", err=io.StringIO())
        self.assertEqual(out.splitlines(), ["2211", "4433", "6655", "8877"])

    def test_halfword_big(self):
        out = format_output(make_memory(), data_width="halfword", endian="big", err=io.StringIO())
        self.assertEqual(out.splitlines(), ["1122", "3344", "5566", "7788"])

    # --- gaps -----------------------------------------------------
    def test_gap_mem_auto_switch_to_address(self):
        """When .mem output has gaps and no --with-address, auto-switch."""
        memory = {
            0: "11", 1: "22", 2: "33", 3: "44",
            16: "55", 17: "66", 18: "77", 19: "88",
        }
        err_buf = io.StringIO()
        out = format_output(memory, out_format="mem", with_address=False, err=err_buf)
        # Warning emitted
        self.assertIn("gaps", err_buf.getvalue())
        # Output uses @addr lines (byte mode -> @addr == address itself).
        lines = out.splitlines()
        self.assertIn("@00000000", lines)
        self.assertIn("@00000010", lines)  # 16 = 0x10 in byte mode
        self.assertIn("11", lines)
        self.assertIn("88", lines)

    def test_gap_mem_with_address_no_warning(self):
        """When --with-address is given, no auto-switch warning."""
        memory = {0: "11", 16: "22"}
        err_buf = io.StringIO()
        out = format_output(memory, out_format="mem", with_address=True, err=err_buf)
        self.assertNotIn("gaps", err_buf.getvalue())
        self.assertIn("@00000000", out)
        self.assertIn("@00000010", out)  # 16 = 0x10 in byte mode

    # --- missing bytes in chunk -----------------------------------
    def test_missing_byte_padded_with_warning(self):
        """If only byte 1 of a 4-byte chunk is present, warn and pad with 00."""
        memory = {1: "AA"}  # only offset 1 of word at address 0
        err_buf = io.StringIO()
        out = format_output(memory, data_width="word", with_address=True, err=err_buf)
        self.assertIn("filled with 0x00", err_buf.getvalue())
        # Little-endian: bytes are [00, AA, 00, 00] -> reversed -> 0000AA00
        self.assertIn("0000AA00", out)


class TestGetOutputExtension(unittest.TestCase):
    def test_extensions(self):
        self.assertEqual(get_output_extension("mem"), ".mem")
        self.assertEqual(get_output_extension("txt"), ".txt")
        self.assertEqual(get_output_extension("csv"), ".csv")


class TestWidthMap(unittest.TestCase):
    def test_values(self):
        self.assertEqual(WIDTH_MAP, {"byte": 1, "halfword": 2, "word": 4})


if __name__ == "__main__":
    unittest.main()