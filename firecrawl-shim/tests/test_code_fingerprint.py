"""Dấu vân tay mã trong /health (SDO-210) — để kiểm sau deploy container chạy đúng code vừa merge."""
import hashlib
import pathlib

from fastapi.testclient import TestClient

from app import main


def _tree(tmp_path, files):
    for name, body in files.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    return tmp_path


def test_cung_noi_dung_thi_cung_dau(tmp_path):
    a = _tree(tmp_path / "a", {"x.py": "print(1)\n", "sub/y.py": "y = 2\n"})
    b = _tree(tmp_path / "b", {"sub/y.py": "y = 2\n", "x.py": "print(1)\n"})
    assert main.code_fingerprint(a) == main.code_fingerprint(b)


def test_sua_mot_dong_thi_doi_dau(tmp_path):
    # Chính ca SDO-210: code mới mà dấu không đổi thì phép kiểm sau deploy vô dụng.
    root = _tree(tmp_path, {"x.py": "print(1)\n"})
    before = main.code_fingerprint(root)
    (root / "x.py").write_text("print(2)\n")
    assert main.code_fingerprint(root) != before


def test_doi_ten_file_thi_doi_dau(tmp_path):
    a = _tree(tmp_path / "a", {"x.py": "v = 1\n"})
    b = _tree(tmp_path / "b", {"z.py": "v = 1\n"})
    assert main.code_fingerprint(a) != main.code_fingerprint(b)


def test_bo_qua_file_khong_phai_py(tmp_path):
    root = _tree(tmp_path, {"x.py": "v = 1\n"})
    before = main.code_fingerprint(root)
    (root / "note.pyc").write_bytes(b"\x00")
    assert main.code_fingerprint(root) == before


def test_lenh_kiem_tay_trong_docstring_ra_cung_ket_qua():
    # Người vận hành so /health với lệnh một dòng trên bản checkout; hai cách phải khớp.
    r = pathlib.Path(main.__file__).parent
    h = hashlib.sha256()
    [h.update(str(p.relative_to(r)).encode() + p.read_bytes()) for p in sorted(r.rglob("*.py"))]
    assert h.hexdigest()[:12] == main.CODE_FINGERPRINT


def test_health_tra_dau_van_tay():
    body = TestClient(main.app).get("/health").json()
    assert body == {"status": "ok", "code": main.CODE_FINGERPRINT}
