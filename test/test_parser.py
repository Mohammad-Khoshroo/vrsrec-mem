"""Tests for src.parser."""

from __future__ import annotations

import io
import unittest

from src.parser import (
    parse_srecord_line,
    convert_srecord_string,
    convert_srecord_stream,
)


def make_s1(addr: int, data: bytes) -> str:
    """Build a valid S1 record line for testing."""
    addr_hex = f"{addr:04X}"
    body = bytes([len(data) + 2 + 1]) + bytes.fromhex(addr_hex) + data
    chk = (~sum(body)) & 0xFF
    return "S1" + body.hex().upper() + f"{chk:02X}"


def make_s2(addr: int, data: bytes) -> str:
    """Build a valid S2 record line for testing (3-byte address)."""
    addr_hex = f"{addr:06X}"
    body = bytes([len(data) + 3 + 1]) + bytes.fromhex(addr_hex) + data
    chk = (~sum(body)) & 0xFF
    return "S2" + body.hex().upper() + f"{chk:02X}"


def make_s3(addr: int, data: bytes) -> str:
    """Build a valid S3 record line for testing (4-byte address)."""
    addr_hex = f"{addr:08X}"
    body = bytes([len(data) + 4 + 1]) + bytes.fromhex(addr_hex) + data
    chk = (~sum(body)) & 0xFF
    return "S3" + body.hex().upper() + f"{chk:02X}"


class TestParseSRecordLine(unittest.TestCase):
    def test_blank_line(self):
        self.assertIsNone(parse_srecord_line("", 1))
        self.assertIsNone(parse_srecord_line("   ", 1))

    def test_non_srecord(self):
        self.assertIsNone(parse_srecord_line("hello", 1))

    def test_header_s0_ignored(self):
        # S0030000FC
        self.assertIsNone(parse_srecord_line("S0030000FC", 1))

    def test_count_records_s5_s6_ignored(self):
        self.assertIsNone(parse_srecord_line("S5030001FB", 1))
        self.assertIsNone(parse_srecord_line("S6030001FA", 1))

    def test_termination_records(self):
        self.assertEqual(parse_srecord_line("S9030000FC", 1), "EOF")
        self.assertEqual(parse_srecord_line("S804000000FA", 1), "EOF")
        self.assertEqual(parse_srecord_line("S70500000000FB", 1), "EOF")

    def test_s1_data_record(self):
        line = make_s1(0x1234, b"\xDE\xAD\xBE\xEF")
        result = parse_srecord_line(line, 1)
        self.assertEqual(result, (0x1234, "DEADBEEF"))

    def test_s2_data_record(self):
        line = make_s2(0x123456, b"\x01\x02")
        result = parse_srecord_line(line, 1)
        self.assertEqual(result, (0x123456, "0102"))

    def test_s3_data_record(self):
        line = make_s3(0x12345678, b"\xAA\xBB")
        result = parse_srecord_line(line, 1)
        self.assertEqual(result, (0x12345678, "AABB"))

    def test_too_short(self):
        with self.assertRaises(ValueError):
            parse_srecord_line("S1", 1)

    def test_invalid_byte_count(self):
        with self.assertRaises(ValueError):
            parse_srecord_line("S1ZZ0000DEADBEEF", 1)

    def test_invalid_hex_data(self):
        with self.assertRaises(ValueError):
            parse_srecord_line("S1070000DEADBEEZ00", 1)  # bad hex char

    def test_invalid_length(self):
        # Claim 7 bytes but provide fewer
        line = "S1030000DEAD"  # body claims 3 bytes total but record is wrong
        with self.assertRaises(ValueError):
            parse_srecord_line(line, 1)

    def test_checksum_mismatch(self):
        # Take a valid S1 line and corrupt the checksum byte.
        good = make_s1(0x0000, b"\x11\x22\x33\x44")
        bad = good[:-2] + "00"  # replace checksum with 00
        with self.assertRaises(ValueError) as ctx:
            parse_srecord_line(bad, 1)
        self.assertIn("checksum mismatch", str(ctx.exception))


class TestConvertSRecordString(unittest.TestCase):
    def test_basic_conversion(self):
        text = "\n".join([
            "S0030000FC",
            make_s1(0x0000, b"\x11\x22\x33\x44"),
            make_s1(0x0004, b"\x55\x66\x77\x88"),
            "S9030000FC",
        ])
        memory = convert_srecord_string(text, warn_on_overlap=False, err=io.StringIO())
        self.assertEqual(memory, {
            0x0000: "11", 0x0001: "22", 0x0002: "33", 0x0003: "44",
            0x0004: "55", 0x0005: "66", 0x0006: "77", 0x0007: "88",
        })

    def test_eof_stops_parsing(self):
        text = "\n".join([
            make_s1(0x0000, b"\xAA"),
            "S9030000FC",
            make_s1(0x0010, b"\xBB"),  # should be ignored
        ])
        memory = convert_srecord_string(text, warn_on_overlap=False, err=io.StringIO())
        self.assertEqual(memory, {0x0000: "AA"})

    def test_overlap_warning(self):
        text = "\n".join([
            make_s1(0x0000, b"\xAA"),
            make_s1(0x0000, b"\xBB"),  # overwrite
        ])
        err_buf = io.StringIO()
        memory = convert_srecord_string(text, warn_on_overlap=True, err=err_buf)
        self.assertEqual(memory[0x0000], "BB")
        self.assertIn("overwritten", err_buf.getvalue())

    def test_overlap_silenced(self):
        text = "\n".join([
            make_s1(0x0000, b"\xAA"),
            make_s1(0x0000, b"\xBB"),
        ])
        err_buf = io.StringIO()
        memory = convert_srecord_string(text, warn_on_overlap=False, err=err_buf)
        self.assertEqual(memory[0x0000], "BB")
        self.assertEqual(err_buf.getvalue(), "")

    def test_stream_vs_string_match(self):
        text = "\n".join([
            make_s1(0x0000, b"\x11\x22"),
            make_s1(0x0004, b"\x33\x44"),
            "S9030000FC",
        ])
        via_string = convert_srecord_string(text, warn_on_overlap=False, err=io.StringIO())
        via_stream = convert_srecord_stream(
            io.StringIO(text), warn_on_overlap=False, err=io.StringIO()
        )
        self.assertEqual(via_string, via_stream)


if __name__ == "__main__":
    unittest.main()