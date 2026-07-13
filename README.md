# vrsrec-mem

A small, dependency-free Python toolkit for working with **Motorola S-Record** files and **memory images** for hardware simulation. Three utilities in one package:

| Command   | What it does                                                                                                                       |
| --------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| `convert` | Convert `.srec` / `.s19` / `.s28` / `.s37` files to Verilog `.mem`, `.txt`, or `.csv`                                              |
| `gen`     | Generate a fully-populated memory dump CSV with fill patterns (`x`/`0`/`1`/`random`) — binary or hex output, optional base address |
| `group`   | Group any fixed-width hex CSV into multi-element word groups (bytes → 32-bit words, words → 64-bit words, etc.)                    |

All three support both CLI use and a clean Python library API. **129 unit tests**, no runtime dependencies beyond Python 3.8+.

---

## ✨ Features

### `convert` — S-Record → mem/txt/csv
- ✅ Strict S-Record parsing with checksum verification (S0–S9, S1/S2/S3 data)
- ✅ Output widths: byte (8-bit), halfword (16-bit), word (32-bit)
- ✅ Endianness: little (default) / big
- ✅ Formats: `.mem` (default, `$readmemh`-compatible), `.txt`, `.csv`
- ✅ Gap-aware `.mem` output — auto-switches to `@addr` lines when the data has gaps
- ✅ Warnings for address overlaps and 0x00-padded missing bytes
- ✅ Streaming line-by-line parser (low memory usage on large files)

### `gen` — memory dump generator
- ✅ Fill modes: `x`, `0`, `1`, `random`, `random_with_x` (10% don't-care)
- ✅ Optional merge with an existing sparse CSV (binary or hex input)
- ✅ `--seed` for reproducible random fills
- ✅ Accepts input addresses with or without `0x` prefix
- ✅ Auto-width address column based on capacity
- ✅ **`--hex-output`** for `$readmemh` (default: binary for `$readmemb`)
- ✅ **`--base-address 0x1000`** to start at a non-zero address
- ✅ **`--input-format {auto,bin,hex}`** to disambiguate sparse input
- ✅ **`--max-capacity`** safeguard against accidental huge allocations

### `group` — hex CSV → word CSV
- ✅ **Accepts any fixed-width hex input** (bytes, halfwords, words, …)
- ✅ Configurable group size (default: 4 input elements per group)
- ✅ Little-endian and big-endian support
- ✅ `--input-width N` to force/validate the input hex-character width
- ✅ `--strict` mode to error on incomplete/misaligned groups
- ✅ Reports missing elements inside a group (warns or errors)
- ✅ Output columns: `address,word-data,decimal`

---

## 📦 Installation

### From source (development)

```bash
git clone https://github.com/your-username/vrsrec-mem.git
cd vrsrec-mem
pip install -e .
```

### Without installing — run as a module

```bash
python -m src convert firmware.srec
python -m src gen -c 256 -w 8 -f random
python -m src group bytes.csv
```

---

## 🚀 Usage

### 1. `convert` — S-Record → mem/txt/csv

```bash
# Default: byte-width, little-endian, .mem output, no addresses
vrsrec-mem convert firmware.srec
# -> writes firmware.mem

# With addresses
vrsrec-mem convert firmware.srec --with-address

# 32-bit words, big-endian, CSV
vrsrec-mem convert firmware.srec --word-format --big-endian --csv --with-address
```

**Backward compatibility**: `vrsrec-mem firmware.srec` (without the `convert` keyword) still works.

### 2. `gen` — memory dump generator

```bash
# Generate 1024 addresses, 8-bit data, fill with 'x' (don't-care), binary output
vrsrec-mem gen -c 1024 -w 8 -f x -o mem.csv

# Hex output (for $readmemh), random data, reproducible with seed
vrsrec-mem gen -c 256 -w 8 -f random --seed 42 --hex-output -o mem.csv

# Start at non-zero base address
vrsrec-mem gen -c 256 -w 32 -f 0 --base-address 0x1000 -o mem.csv

# Merge existing sparse data (hex format), fill the rest with random bits
vrsrec-mem gen -c 256 -w 8 -f random_with_x -i sparse.csv \
    --input-format hex --hex-output -o mem.csv

# Disable the max-capacity safeguard (be careful!)
vrsrec-mem gen -c 20000000 -w 8 --max-capacity 0 -o big.csv
```

### 3. `group` — hex CSV → word CSV

```bash
# Default: group 4 byte-level entries into little-endian 32-bit words
vrsrec-mem group bytes.csv -o words.csv

# Group 2 word-level entries into 64-bit words (auto-detects 8-char hex input)
vrsrec-mem group words.csv -s 2 -o qwords.csv

# Big-endian grouping, with explicit input width validation
vrsrec-mem group bytes.csv --big-endian --input-width 2 -o words_be.csv

# 2-element groups (halfwords), strict mode
vrsrec-mem group bytes.csv -s 2 --strict -o halfwords.csv
```

### End-to-end pipeline

```bash
# Step 1: S-Record -> byte-level CSV
vrsrec-mem convert firmware.srec --csv --with-address -o bytes.csv

# Step 2: bytes -> 32-bit little-endian words
vrsrec-mem group bytes.csv -o words.csv
```

`words.csv` will have columns `address,word-data,decimal`, e.g.:

```csv
address,word-data,decimal
0x00000000,EFBEADDE,4022250974
0x00000004,BEBAFECA,3199925962
```

---

## 🧰 CLI reference

```
usage: vrsrec-mem [-h] [--version] <command> ...

Commands:
  convert   Convert S-Record file to mem/txt/csv
  gen       Generate a fully-populated memory dump CSV
  group     Group a byte-addressed CSV into multi-byte words
```

### `convert`

| Option              | Description                                      |
| ------------------- | ------------------------------------------------ |
| `filename`          | Input S-Record file                              |
| `--with-address`    | Include address in output                        |
| `--quiet`           | Suppress overlap / padding warnings              |
| `-o, --output FILE` | Write to this file instead of `<basename>.<ext>` |
| `--byte-format`     | 8-bit bytes (default)                            |
| `--halfword-format` | 16-bit halfwords                                 |
| `--word-format`     | 32-bit words                                     |
| `--mem`             | `.mem` output (default)                          |
| `--txt`             | `.txt` output                                    |
| `--csv`             | `.csv` output                                    |
| `--little-endian`   | Little-endian (default)                          |
| `--big-endian`      | Big-endian                                       |

### `gen`

| Option                | Description                                                    |
| --------------------- | -------------------------------------------------------------- |
| `-i, --input FILE`    | Optional sparse CSV to merge                                   |
| `-o, --output FILE`   | Output CSV file (default: `output.csv`)                        |
| `-c, --capacity N`    | Total memory capacity (required)                               |
| `-w, --width BITS`    | Data width in bits (default: 8)                                |
| `-f, --fill MODE`     | `x` / `0` / `1` / `random` / `random_with_x` (default: `x`)    |
| `--seed N`            | Random seed for reproducibility                                |
| `--base-address ADDR` | First address (default: 0). Accepts `0x` hex.                  |
| `--hex-output`        | Hex string output (`$readmemh`). Default: binary (`$readmemb`) |
| `--input-format FMT`  | `auto` / `bin` / `hex` for `--input` CSV (default: `auto`)     |
| `--max-capacity N`    | Soft safeguard (default: 16777216). `0` disables.              |
| `-q, --quiet`         | Suppress status messages                                       |

### `group`

| Option               | Description                                            |
| -------------------- | ------------------------------------------------------ |
| `input`              | Input CSV file with `address,data` columns             |
| `-o, --output FILE`  | Output CSV file (default: `output_grouped.csv`)        |
| `-s, --group-size N` | Input elements per group (default: 4)                  |
| `--input-width N`    | Force input hex-character width (default: auto-detect) |
| `--little-endian`    | Element at offset 0 is LSB (default)                   |
| `--big-endian`       | Element at offset 0 is MSB                             |
| `--strict`           | Error instead of warn on incomplete/misaligned groups  |
| `-q, --quiet`        | Suppress warnings and status messages                  |

---

## 📚 As a Python library

```python
from src import (
    convert_srecord_string, format_output,        # convert
    generate_memory_dump, write_memory_csv,       # gen
    group_bytes_to_words, write_grouped_csv,      # group
)

# --- convert ---
srec_text = open("firmware.srec").read()
memory = convert_srecord_string(srec_text, warn_on_overlap=False)
out = format_output(memory, data_width="word", with_address=True,
                    out_format="mem", endian="little")

# --- gen ---
import random
mem = generate_memory_dump(capacity=256, data_bits=8,
                           fill_mode="random", rng=random.Random(42))
write_memory_csv(mem, "mem.csv")

# --- group ---
from src import read_byte_csv
bytes_ = read_byte_csv("bytes.csv")
grouped = group_bytes_to_words(bytes_, group_size=4, endian="little")
write_grouped_csv(grouped, "words.csv")
```

---

## 📤 Output format examples

### `convert` → `.mem` (default, byte width)

```
@00000000
DE
AD
BE
EF
@00000010
11
22
```

Because the data has a gap, the converter auto-switches to `@addr` lines (and prints a warning). Use `--with-address` explicitly to silence the warning.

### `convert` → `.mem` with `--word-format --little-endian`

```
@00000000
EFBEADDE
@00000004
88776655
```

### `gen` → CSV

```csv
address,data
0x000,xxxxxxxx
0x001,10101100
0x002,00001111
```

### `group` → CSV

```csv
address,word-data,decimal
0x00000000,EFBEADDE,4022250974
0x00000004,BEBAFECA,3199925962
```

---

## 🧪 Tests

```bash
python -m pytest tests/ -v
```

Or without `pytest`:

```bash
python -m unittest discover -s tests -v
```

81 tests covering parsing, formatting, memory generation, and CSV grouping.

> _Update: as of v1.2.0 the test suite has grown to **129 tests** including
> the new hex/base-address/max-capacity/variable-width-input coverage._

---

## 📁 Project layout

```
vrsrec-mem/
├── src/
│   ├── __init__.py            # public API
│   ├── __main__.py            # python -m src
│   ├── parser.py              # S-Record parsing
│   ├── formatter.py           # output formatting (mem/txt/csv)
│   ├── memory_generator.py    # gen subcommand: memory dump generator
│   ├── csv_grouper.py         # group subcommand: byte→word CSV grouper
│   └── cli.py                 # argparse CLI with subcommands
├── tests/
│   ├── __init__.py
│   ├── test_parser.py         # 18 tests
│   ├── test_formatter.py      # 23 tests
│   ├── test_memory_generator.py  # 21 tests
│   └── test_csv_grouper.py       # 19 tests
├── examples/
│   ├── sample.srec
│   └── _generate_sample.py
├── pyproject.toml
├── README.md
├── CHANGELOG.md
├── LICENSE
└── .gitignore
```

---

## 📝 License

MIT — see [LICENSE](LICENSE).

---
