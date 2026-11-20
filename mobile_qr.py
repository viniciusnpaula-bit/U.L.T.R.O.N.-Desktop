"""Gerador puro-Python de QR Code (ISO/IEC 18004, modo Byte, ECC M) para SVG/Data URI.

Zero dependências externas (funciona também no Python Embedded sem pacotes extras).
"""
from __future__ import annotations

import base64

# (versao, total_data_bytes, ec_bytes_per_block, [(num_blocks, data_bytes_per_block), ...])
_ECC_M_SPEC = (
    (1, 16, 10, ((1, 16),)),
    (2, 28, 16, ((1, 28),)),
    (3, 44, 26, ((1, 44),)),
    (4, 64, 18, ((2, 32),)),
    (5, 86, 24, ((2, 43),)),
    (6, 108, 16, ((4, 27),)),
    (7, 124, 18, ((4, 31),)),
    (8, 154, 22, ((2, 38), (2, 39))),
    (9, 182, 22, ((3, 36), (2, 37))),
    (10, 216, 26, ((4, 43), (1, 44))),
    (11, 254, 30, ((1, 50), (4, 51))),
    (12, 290, 22, ((6, 36), (2, 37))),
)

_ALIGNMENT = {
    1: (),
    2: (6, 18),
    3: (6, 22),
    4: (6, 26),
    5: (6, 30),
    6: (6, 34),
    7: (6, 22, 38),
    8: (6, 24, 42),
    9: (6, 26, 46),
    10: (6, 28, 50),
    11: (6, 30, 54),
    12: (6, 32, 58),
}

# Galois Field GF(256) com polinômio primitivo 0x11D
_GF_EXP = [0] * 512
_GF_LOG = [0] * 256
_x = 1
for _i in range(255):
    _GF_EXP[_i] = _x
    _GF_LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _GF_EXP[_i] = _GF_EXP[_i - 255]


def _gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _GF_EXP[_GF_LOG[a] + _GF_LOG[b]]


def _rs_generator(degree: int) -> list[int]:
    poly = [1]
    for i in range(degree):
        root = _GF_EXP[i]
        nxt = [0] * (len(poly) + 1)
        for j, coef in enumerate(poly):
            nxt[j] ^= coef
            nxt[j + 1] ^= _gf_mul(coef, root)
        poly = nxt
    return poly


def _rs_encode(data: bytes, ec_len: int) -> bytes:
    gen = _rs_generator(ec_len)
    buf = list(data) + [0] * ec_len
    for i in range(len(data)):
        coef = buf[i]
        if coef != 0:
            for j in range(1, len(gen)):
                buf[i + j] ^= _gf_mul(gen[j], coef)
    return bytes(buf[len(data):])


def _choose_version(byte_len: int):
    for spec in _ECC_M_SPEC:
        ver, total_data, _, _ = spec
        count_bits = 8 if ver <= 9 else 16
        header_bits = 4 + count_bits
        if header_bits + byte_len * 8 <= total_data * 8:
            return spec
    raise ValueError("Conteúdo longo demais para QR Code (máx ~287 bytes).")


def _encode_codewords(payload: bytes) -> tuple[int, list[int]]:
    ver, total_data, ec_per_block, groups = _choose_version(len(payload))
    bits: list[int] = []

    def push(val: int, width: int) -> None:
        for shift in range(width - 1, -1, -1):
            bits.append((val >> shift) & 1)

    push(0b0100, 4)  # Byte mode
    push(len(payload), 8 if ver <= 9 else 16)
    for b in payload:
        push(b, 8)

    cap_bits = total_data * 8
    term = min(4, cap_bits - len(bits))
    push(0, term)
    while len(bits) % 8 != 0:
        bits.append(0)

    data_bytes = bytearray()
    for i in range(0, len(bits), 8):
        val = 0
        for bit in bits[i:i + 8]:
            val = (val << 1) | bit
        data_bytes.append(val)

    pad_cycle = (0xEC, 0x11)
    idx = 0
    while len(data_bytes) < total_data:
        data_bytes.append(pad_cycle[idx & 1])
        idx += 1

    data_blocks: list[bytes] = []
    ec_blocks: list[bytes] = []
    pos = 0
    for count, size in groups:
        for _ in range(count):
            blk = bytes(data_bytes[pos:pos + size])
            pos += size
            data_blocks.append(blk)
            ec_blocks.append(_rs_encode(blk, ec_per_block))

    interleaved: list[int] = []
    max_data = max(len(b) for b in data_blocks)
    for i in range(max_data):
        for blk in data_blocks:
            if i < len(blk):
                interleaved.append(blk[i])
    for i in range(ec_per_block):
        for blk in ec_blocks:
            interleaved.append(blk[i])

    return ver, interleaved


def _make_base_matrix(ver: int) -> tuple[list[list[bool | None]], list[list[bool]]]:
    size = ver * 4 + 17
    mat: list[list[bool | None]] = [[None] * size for _ in range(size)]
    func = [[False] * size for _ in range(size)]

    def set_func(r: int, c: int, val: bool) -> None:
        if 0 <= r < size and 0 <= c < size:
            mat[r][c] = val
            func[r][c] = True

    def draw_finder(r0: int, c0: int) -> None:
        for dr in range(-1, 8):
            for dc in range(-1, 8):
                r, c = r0 + dr, c0 + dc
                if not (0 <= r < size and 0 <= c < size):
                    continue
                if dr in (-1, 7) or dc in (-1, 7):
                    set_func(r, c, False)
                else:
                    on = (
                        dr in (0, 6)
                        or dc in (0, 6)
                        or (2 <= dr <= 4 and 2 <= dc <= 4)
                    )
                    set_func(r, c, on)

    draw_finder(0, 0)
    draw_finder(0, size - 7)
    draw_finder(size - 7, 0)

    # Timing patterns
    for i in range(8, size - 8):
        val = (i % 2 == 0)
        set_func(6, i, val)
        set_func(i, 6, val)

    # Alignment patterns (pula apenas os 3 cantos que sobrepõem os finder patterns)
    coords = _ALIGNMENT[ver]
    for r in coords:
        for c in coords:
            if (r == coords[0] and c in (coords[0], coords[-1])) or (r == coords[-1] and c == coords[0]):
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    on = max(abs(dr), abs(dc)) != 1
                    set_func(r + dr, c + dc, on)

    # Dark module
    set_func(size - 8, 8, True)

    # Reserve format info cells
    for i in range(9):
        if i != 6:
            func[8][i] = True
            func[i][8] = True
    for i in range(8):
        func[8][size - 1 - i] = True
        func[size - 1 - i][8] = True

    # Version info (ver >= 7)
    if ver >= 7:
        rem = ver
        for _ in range(12):
            rem = (rem << 1) ^ (0x1F25 if (rem >> 11) & 1 else 0)
        bits = (ver << 12) | rem
        for i in range(18):
            bit = bool((bits >> i) & 1)
            a = size - 11 + (i % 3)
            b = i // 3
            set_func(a, b, bit)
            set_func(b, a, bit)

    return mat, func


def _place_codewords(mat: list[list[bool | None]], func: list[list[bool]], codewords: list[int]) -> None:
    size = len(mat)
    bits: list[bool] = []
    for cw in codewords:
        for shift in range(7, -1, -1):
            bits.append(bool((cw >> shift) & 1))

    idx = 0
    col = size - 1
    upward = True
    while col >= 1:
        if col == 6:
            col -= 1
        rows = range(size - 1, -1, -1) if upward else range(size)
        for r in rows:
            for c in (col, col - 1):
                if not func[r][c]:
                    mat[r][c] = bits[idx] if idx < len(bits) else False
                    idx += 1
        col -= 2
        upward = not upward


def _mask_bit(mask: int, r: int, c: int) -> bool:
    if mask == 0:
        return (r + c) % 2 == 0
    if mask == 1:
        return r % 2 == 0
    if mask == 2:
        return c % 3 == 0
    if mask == 3:
        return (r + c) % 3 == 0
    if mask == 4:
        return ((r // 2) + (c // 3)) % 2 == 0
    if mask == 5:
        return (r * c) % 2 + (r * c) % 3 == 0
    if mask == 6:
        return ((r * c) % 2 + (r * c) % 3) % 2 == 0
    return ((r + c) % 2 + (r * c) % 3) % 2 == 0


def _apply_format_info(mat: list[list[bool]], mask: int) -> None:
    size = len(mat)
    data = (0b00 << 3) | mask  # ECC M = 00
    rem = data
    for _ in range(10):
        rem = (rem << 1) ^ (0x537 if (rem >> 9) & 1 else 0)
    bits = ((data << 10) | rem) ^ 0x5412

    for i in range(15):
        bit = bool((bits >> i) & 1)
        if i < 6:
            mat[i][8] = bit
        elif i < 8:
            mat[i + 1][8] = bit
        else:
            mat[size - 15 + i][8] = bit

        if i < 8:
            mat[8][size - 1 - i] = bit
        elif i < 9:
            mat[8][15 - i] = bit
        else:
            mat[8][14 - i] = bit


def _penalty(mat: list[list[bool]]) -> int:
    size = len(mat)
    score = 0

    for line_is_row in (True, False):
        for i in range(size):
            run_color = None
            run_len = 0
            for j in range(size):
                val = mat[i][j] if line_is_row else mat[j][i]
                if val == run_color:
                    run_len += 1
                else:
                    if run_len >= 5:
                        score += 3 + (run_len - 5)
                    run_color = val
                    run_len = 1
            if run_len >= 5:
                score += 3 + (run_len - 5)

    for r in range(size - 1):
        for c in range(size - 1):
            v = mat[r][c]
            if v == mat[r][c + 1] == mat[r + 1][c] == mat[r + 1][c + 1]:
                score += 3

    p1 = (True, False, True, True, True, False, True, False, False, False, False)
    p2 = (False, False, False, False, True, False, True, True, True, False, True)
    for i in range(size):
        row = mat[i]
        col = [mat[r][i] for r in range(size)]
        for seq in (row, col):
            for j in range(size - 10):
                sl = tuple(seq[j:j + 11])
                if sl == p1 or sl == p2:
                    score += 40

    dark = sum(1 for r in mat for cell in r if cell)
    pct = (dark * 100) // (size * size)
    k = min(abs(pct - 50) // 5, abs((pct + 4) - 50) // 5)
    score += k * 10
    return score


def encode_matrix(text: str) -> list[list[bool]]:
    """Codifica texto UTF-8 em uma matriz booleana QR Code (True = módulo escuro)."""
    payload = text.encode("utf-8")
    ver, codewords = _encode_codewords(payload)
    base, func = _make_base_matrix(ver)
    _place_codewords(base, func, codewords)
    size = len(base)

    best_mat = None
    best_score = None
    for mask in range(8):
        cand: list[list[bool]] = [[False] * size for _ in range(size)]
        for r in range(size):
            for c in range(size):
                val = bool(base[r][c])
                if not func[r][c] and _mask_bit(mask, r, c):
                    val = not val
                cand[r][c] = val
        _apply_format_info(cand, mask)
        sc = _penalty(cand)
        if best_score is None or sc < best_score:
            best_score = sc
            best_mat = cand

    assert best_mat is not None
    return best_mat


def render_svg(text: str, *, quiet: int = 4, module_px: int = 6) -> str:
    """Renderiza o QR Code como SVG nítido com fundo branco e quiet zone."""
    mat = encode_matrix(text)
    n = len(mat)
    total = (n + quiet * 2) * module_px
    rects: list[str] = []
    for r, row in enumerate(mat):
        y = (r + quiet) * module_px
        c = 0
        while c < n:
            if row[c]:
                start = c
                while c < n and row[c]:
                    c += 1
                x = (start + quiet) * module_px
                w = (c - start) * module_px
                rects.append(f'<rect x="{x}" y="{y}" width="{w}" height="{module_px}"/>')
            else:
                c += 1
    body = "".join(rects)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total} {total}" '
        f'width="{total}" height="{total}" shape-rendering="crispEdges">'
        f'<rect width="100%" height="100%" fill="#ffffff"/>'
        f'<g fill="#0b0d13">{body}</g></svg>'
    )


def render_svg_data_uri(text: str, *, quiet: int = 4, module_px: int = 6) -> str:
    """Devolve Data URI image/svg+xml pronta para <img src="..."> sob CSP estrita."""
    svg = render_svg(text, quiet=quiet, module_px=module_px).encode("utf-8")
    return "data:image/svg+xml;base64," + base64.b64encode(svg).decode("ascii")
