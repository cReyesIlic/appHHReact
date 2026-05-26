"""Monitor de uso del File Share `shimin-data` en Azure.

Mide cuánto espacio está ocupando el File Share vs su cuota y manda email
si pasa de un umbral configurable (default: 70% de la cuota).

Uso:
    python -m scripts.monitor_share_usage                  # solo reporta
    python -m scripts.monitor_share_usage --email          # también manda email si supera umbral
    python -m scripts.monitor_share_usage --threshold 0.8  # umbral 80%
    python -m scripts.monitor_share_usage --top 10         # incluye top 10 carpetas por tamaño

Config via env vars:
    AZURE_STORAGE_ACCOUNT      = apphhdrive (default)
    AZURE_FILE_SHARE_NAME      = shimin-data (default)
    AZURE_STORAGE_KEY          = key del storage account (o AZURE_CONNECTION_STRING)
    AZURE_CONNECTION_STRING    = connection string completa (alternativa a key)
    SHARE_USAGE_THRESHOLD      = 0.70 (default — 70%)
    ACS_*                      = ver email_client.py para notificación

Exit codes:
    0  → todo OK (uso < umbral)
    1  → error de configuración / API
    2  → uso supera el umbral (útil para cron / CI alert)
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime


def human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.2f} {unit}"
        n /= 1024
    return f"{n:.2f} PB"


def get_share_stats(account: str, share: str, key: str | None, conn_str: str | None) -> dict:
    """Devuelve {used_bytes, quota_gb, top_dirs?} para el File Share."""
    try:
        from azure.storage.fileshare import ShareServiceClient
    except ImportError:
        raise RuntimeError("Falta dependencia: pip install azure-storage-file-share")

    if conn_str:
        client = ShareServiceClient.from_connection_string(conn_str)
    elif key:
        url = f"https://{account}.file.core.windows.net"
        client = ShareServiceClient(account_url=url, credential=key)
    else:
        raise RuntimeError("Falta AZURE_CONNECTION_STRING o AZURE_STORAGE_KEY")

    share_client = client.get_share_client(share)
    props = share_client.get_share_properties()
    quota_gb = props.quota
    stats = share_client.get_share_stats()
    used_bytes = stats  # API devuelve int (bytes) en versiones nuevas, o dict {'share_usage_bytes': ...}
    if isinstance(stats, dict):
        used_bytes = stats.get("share_usage_bytes", 0)

    return {
        "account": account,
        "share": share,
        "used_bytes": int(used_bytes),
        "quota_bytes": int(quota_gb) * 1024 ** 3,
        "quota_gb": int(quota_gb),
        "utilization": int(used_bytes) / max(1, int(quota_gb) * 1024 ** 3),
    }


def top_directories(account: str, share: str, key: str | None, conn_str: str | None, top: int) -> list[dict]:
    """Lista las top N carpetas raíz por tamaño (1 nivel — el File Share API no expone du recursivo barato)."""
    try:
        from azure.storage.fileshare import ShareDirectoryClient
    except ImportError:
        return []

    if conn_str:
        root = ShareDirectoryClient.from_connection_string(conn_str, share_name=share, directory_path="")
    elif key:
        url = f"https://{account}.file.core.windows.net"
        root = ShareDirectoryClient(account_url=url, share_name=share, directory_path="", credential=key)
    else:
        return []

    dirs: list[dict] = []
    for item in root.list_directories_and_files():
        if not getattr(item, "is_directory", False):
            continue
        name = item["name"]
        size = _dir_size(account, share, key, conn_str, name, max_depth=2)
        dirs.append({"name": name, "bytes": size})
    dirs.sort(key=lambda d: d["bytes"], reverse=True)
    return dirs[:top]


def _dir_size(account: str, share: str, key: str | None, conn_str: str | None, path: str, max_depth: int) -> int:
    """Suma recursiva (acotada) de tamaños de archivos."""
    from azure.storage.fileshare import ShareDirectoryClient

    if conn_str:
        client = ShareDirectoryClient.from_connection_string(conn_str, share_name=share, directory_path=path)
    else:
        url = f"https://{account}.file.core.windows.net"
        client = ShareDirectoryClient(account_url=url, share_name=share, directory_path=path, credential=key)

    total = 0
    for item in client.list_directories_and_files():
        if getattr(item, "is_directory", False):
            if max_depth > 0:
                total += _dir_size(account, share, key, conn_str, f"{path}/{item['name']}", max_depth - 1)
        else:
            total += item.get("size") or 0
    return total


def render_report(stats: dict, top_dirs: list[dict], threshold: float) -> tuple[str, str, str]:
    pct = stats["utilization"] * 100
    over = stats["utilization"] >= threshold
    status_text = "⚠️  ATENCIÓN" if over else "✅ OK"

    lines = [
        f"{status_text} — File Share `{stats['share']}` en `{stats['account']}`",
        f"Uso: {human_bytes(stats['used_bytes'])} / {stats['quota_gb']} GB ({pct:.1f}%)",
        f"Umbral configurado: {threshold * 100:.0f}%",
        f"Generado: {datetime.now().isoformat(timespec='seconds')}",
    ]
    if top_dirs:
        lines.append("")
        lines.append("Top carpetas por tamaño:")
        for d in top_dirs:
            lines.append(f"  {human_bytes(d['bytes']):>10}  {d['name']}")
    plain = "\n".join(lines)

    subject = f"[storage-monitor] {stats['share']} {pct:.0f}% ({'over' if over else 'ok'})"
    html = "<pre style='font-family:Consolas,monospace'>" + plain + "</pre>"
    return subject, plain, html


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--threshold", type=float, default=float(os.getenv("SHARE_USAGE_THRESHOLD", "0.70")))
    parser.add_argument("--top", type=int, default=0, help="Si > 0, incluye top N carpetas por tamaño (lento)")
    parser.add_argument("--email", action="store_true", help="Mandar email si se supera el umbral")
    parser.add_argument("--always-email", action="store_true", help="Mandar email siempre (no solo si over)")
    args = parser.parse_args()

    account = os.getenv("AZURE_STORAGE_ACCOUNT", "apphhdrive")
    share = os.getenv("AZURE_FILE_SHARE_NAME", "shimin-data")
    key = os.getenv("AZURE_STORAGE_KEY")
    conn_str = os.getenv("AZURE_CONNECTION_STRING")

    try:
        stats = get_share_stats(account, share, key, conn_str)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    top_dirs = []
    if args.top > 0:
        try:
            top_dirs = top_directories(account, share, key, conn_str, args.top)
        except Exception as exc:
            print(f"WARN: no se pudo listar top dirs: {exc}", file=sys.stderr)

    subject, plain, html = render_report(stats, top_dirs, args.threshold)
    print(plain)

    over = stats["utilization"] >= args.threshold
    if args.always_email or (args.email and over):
        try:
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
            from app.services.email_client import EmailClient
        except ImportError as exc:
            print(f"WARN: no se pudo cargar EmailClient: {exc}", file=sys.stderr)
        else:
            result = EmailClient().send(subject, plain, html)
            print(f"\nEmail: {result}")

    return 2 if over else 0


if __name__ == "__main__":
    sys.exit(main())
