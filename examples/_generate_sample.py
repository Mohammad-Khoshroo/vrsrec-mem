#!/usr/bin/env python3
"""Generate a valid sample.srec for the examples/ directory."""

import os


def s_record(record_type: str, addr: int, addr_bytes: int, data: bytes) -> str:
    """Build a valid S-record line."""
    addr_hex = f"{addr:0{2 * addr_bytes}X}"
    body = bytes([len(data) + addr_bytes + 1]) + bytes.fromhex(addr_hex) + data
    chk = (~sum(body)) & 0xFF
    return f"S{record_type}" + body.hex().upper() + f"{chk:02X}"


def main():
    out_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "sample.srec"
    )

    # S0 header: just a comment string "srec-sample"
    header_text = b"srec-sample"
    s0 = s_record("0", 0x0000, 2, header_text)

    # S1 data: 3 chunks of 16 bytes each at 0x0000, 0x0010, 0x0020.
    data0 = bytes.fromhex("DEADBEEFCAFEBABE0123456789ABCDEF")
    data1 = bytes.fromhex("112233445566778899AABBCCDDEEFF00")
    data2 = bytes.fromhex("FFEEBBDDCCBBAA998877665544332211")
    s1a = s_record("1", 0x0000, 2, data0)
    s1b = s_record("1", 0x0010, 2, data1)
    s1c = s_record("1", 0x0020, 2, data2)

    # S9 termination.
    s9 = s_record("9", 0x0000, 2, b"")

    lines = [s0, s1a, s1b, s1c, s9]
    with open(out_path, "w") as f:
        f.write("\n".join(lines) + "\n")

    print(f"Wrote {out_path}")
    for line in lines:
        print(line)


if __name__ == "__main__":
    main()