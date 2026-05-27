"""Quick test of the _validate_codigo logic."""
import re

CODIGO_RE = re.compile(r"^[OS]H?-?\d{2,6}$")


def validate(c):
    if c is None:
        return None
    n = c.strip().upper().replace(" ", "")
    bad_chars = ("/", "\\", "..", "\x00")
    if not n or any(b in n for b in bad_chars):
        return None
    if not CODIGO_RE.match(n):
        return None
    return n


bads = ["../etc/passwd", "O-../bad", "O-1234/..", "foo", "O-", "SH-12", "O 1234abc", "O-1234\x00", "O-1234\\bad"]
goods = ["O-1234", "SH-2345", "o-1234", "  O-1234  ", "O-2687", "O-12"]

print("== Malicious / invalid ==")
for c in bads:
    r = validate(c)
    status = "BLOCKED" if r is None else f"ACCEPTED as {r!r} (BUG)"
    print(f"  {c!r:30s} -> {status}")

print()
print("== Valid ==")
for c in goods:
    r = validate(c)
    status = repr(r) if r else "REJECTED (BUG)"
    print(f"  {c!r:30s} -> {status}")
