#!/usr/bin/env python3
"""Vân tay mã firecrawl-shim tính từ mã nguồn (SDO-302).

Cùng thuật toán với code_fingerprint() trong firecrawl-shim/app/main.py — thứ
container trả ở GET /health → "code" (SDO-210). CI so hai giá trị trong ảnh vừa
dựng, nên nếu hai bên lệch nhau thì PR đỏ ngay. Chỉ dùng thư viện chuẩn để chạy
được ở job không cài gói nào.
"""
import hashlib
import pathlib

root = pathlib.Path(__file__).resolve().parent.parent / "firecrawl-shim" / "app"
h = hashlib.sha256()
for p in sorted(root.rglob("*.py")):
    h.update(str(p.relative_to(root)).encode() + p.read_bytes())
print(h.hexdigest()[:12])
