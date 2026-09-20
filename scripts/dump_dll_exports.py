"""Print export names from a PE DLL (Timeslips TSDBAP32)."""
from __future__ import annotations

import struct
import sys
from pathlib import Path


def export_names(path: Path) -> list[str]:
    data = path.read_bytes()
    if data[:2] != b"MZ":
        raise SystemExit(f"{path} is not a PE file")
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    if data[e_lfanew : e_lfanew + 4] != b"PE\x00\x00":
        raise SystemExit("missing PE header")
    coff = e_lfanew + 4
    machine, n_sections, _, _, _, opt_size, _ = struct.unpack_from("<HHIIIHH", data, coff)
    opt = coff + 20
    magic = struct.unpack_from("<H", data, opt)[0]
    pe32plus = magic == 0x20B
    export_rva, export_size = struct.unpack_from(
        "<II", data, opt + (112 if pe32plus else 96)
    )
    if export_rva == 0:
        return []
    sections = []
    sec_off = opt + opt_size
    for i in range(n_sections):
        off = sec_off + i * 40
        name = data[off : off + 8].split(b"\x00", 1)[0].decode("ascii", "replace")
        vsize, va, raw_size, raw_ptr = struct.unpack_from("<IIII", data, off + 8)
        sections.append((name, va, vsize, raw_ptr, raw_size))

    def rva_to_off(rva: int) -> int:
        for _, va, vsize, raw_ptr, raw_size in sections:
            size = max(vsize, raw_size)
            if va <= rva < va + size:
                return raw_ptr + (rva - va)
        raise SystemExit(f"RVA {rva:#x} not in a section")

    export_off = rva_to_off(export_rva)
    fields = struct.unpack_from("<IIHHIIIIIII", data, export_off)
    n_names = fields[7]
    addr_names = fields[9]
    names = []
    names_off = rva_to_off(addr_names)
    for i in range(n_names):
        name_rva = struct.unpack_from("<I", data, names_off + i * 4)[0]
        noff = rva_to_off(name_rva)
        end = data.index(b"\x00", noff)
        names.append(data[noff:end].decode("ascii", "replace"))
    return names


def main() -> None:
    default = Path(r"C:\Program Files (x86)\Timeslips\TSDBAP32.DLL")
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else default
    names = export_names(path)
    print(f"{path} ({len(names)} exports)")
    for name in names:
        print(name)
    if path.name.upper() == "TSDBAP32.DLL":
        out = Path(__file__).resolve().parents[1] / "docs" / "tsdbap32-exports.txt"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(f"{path} ({len(names)} exports)\n" + "\n".join(names) + "\n", encoding="utf-8")
        print(f"wrote {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
