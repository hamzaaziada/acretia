"""Minimal dependency-free PDF writer for synthetic test corpora and gates.

Coordinates are PDF user space (origin bottom-left, points). Text is encoded as
WinAnsi (cp1252); characters outside it become '?'.
"""
import zlib

FONTS = {"Helvetica": "F1", "Helvetica-Bold": "F2"}


def _esc(s):
    b = s.encode("cp1252", errors="replace")
    return b.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _n(v):
    return ("%.3f" % v).rstrip("0").rstrip(".") or "0"


class _Page:
    def __init__(self):
        self.ops = []
        self.images = []   # (name, w, h, bytes)


class PDFWriter:
    def __init__(self, page_size=(612, 792)):
        self.page_size = page_size
        self.pages = []

    def page(self):
        self.pages.append(_Page())
        return self

    def _cur(self):
        if not self.pages:
            self.page()
        return self.pages[-1]

    def text(self, x, y, s, size=10, font="Helvetica"):
        if font not in FONTS:
            raise ValueError(f"unsupported font {font!r}")
        op = b"BT /%s %s Tf %s %s Td (" % (FONTS[font].encode(), _n(size).encode(), _n(x).encode(), _n(y).encode())
        self._cur().ops.append(op + _esc(s) + b") Tj ET")
        return self

    def line(self, x0, y0, x1, y1, width=0.5):
        self._cur().ops.append(("%s w %s %s m %s %s l S" % tuple(map(_n, (width, x0, y0, x1, y1)))).encode())
        return self

    def rect(self, x, y, w, h, fill=None, stroke=True):
        parts = ["q"]
        if fill is not None:
            parts.append("%s %s %s rg" % tuple(_n(c) for c in fill))
        parts.append("%s %s %s %s re" % tuple(map(_n, (x, y, w, h))))
        parts.append("B" if fill is not None and stroke else "f" if fill is not None else "S" if stroke else "n")
        parts.append("Q")
        self._cur().ops.append(" ".join(parts).encode())
        return self

    def image_gray(self, x, y, w, h, pixels, pw, ph):
        if len(pixels) != pw * ph:
            raise ValueError("pixels length must equal pw*ph")
        pg = self._cur()
        name = "Im%d" % (len(pg.images) + 1)
        pg.images.append((name, pw, ph, bytes(pixels)))
        pg.ops.append(("q %s 0 0 %s %s %s cm /%s Do Q" % (_n(w), _n(h), _n(x), _n(y), name)).encode())
        return self

    def to_bytes(self):
        if not self.pages:
            self.page()
        objs = {}  # num -> bytes
        nxt = [3]  # 1 catalog, 2 pages

        def alloc():
            nxt[0] += 1
            return nxt[0] - 1
        f1, f2 = alloc(), alloc()
        objs[f1] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
        objs[f2] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"
        kids = []
        W, H = self.page_size
        for pg in self.pages:
            content = zlib.compress(b"\n".join(pg.ops))
            cn = alloc()
            objs[cn] = b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(content) + content + b"\nendstream"
            xo = b""
            for name, pw, ph, data in pg.images:
                inum = alloc()
                comp = zlib.compress(data)
                objs[inum] = (b"<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceGray "
                              b"/BitsPerComponent 8 /Filter /FlateDecode /Length %d >>\nstream\n" % (pw, ph, len(comp))
                              + comp + b"\nendstream")
                xo += b"/%s %d 0 R " % (name.encode(), inum)
            res = b"<< /Font << /F1 %d 0 R /F2 %d 0 R >>" % (f1, f2)
            if xo:
                res += b" /XObject << " + xo + b">>"
            res += b" >>"
            pn = alloc()
            objs[pn] = (b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %s %s] /Resources %s /Contents %d 0 R >>"
                        % (_n(W).encode(), _n(H).encode(), res, cn))
            kids.append(pn)
        objs[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
        objs[2] = b"<< /Type /Pages /Kids [" + b" ".join(b"%d 0 R" % k for k in kids) + b"] /Count %d >>" % len(kids)
        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offs = {}
        for num in sorted(objs):
            offs[num] = len(out)
            out += b"%d 0 obj\n" % num + objs[num] + b"\nendobj\n"
        xref = len(out)
        total = max(objs) + 1
        out += b"xref\n0 %d\n" % total + b"0000000000 65535 f \n"
        for num in range(1, total):
            out += b"%010d 00000 n \n" % offs[num]
        out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (total, xref)
        return bytes(out)

    def save(self, path):
        with open(path, "wb") as fh:
            fh.write(self.to_bytes())
