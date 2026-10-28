"""Job-portal accounts: one login email, and a per-company password derived from a local secret.

password = HMAC-SHA256(secret, company), written out as 16 characters that satisfy common password
rules (upper, lower, digit, symbol). Nothing but the secret is stored: the same company always gets
the same password, and losing ``secret.env`` only means using each site's "forgot password" and
``jobfill account rotate``. Passwords are never printed except by ``account password --show`` in the
candidate's own terminal.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from pathlib import Path

from .text import company_key, normalize

SECRET_FILE = "secret.env"
TEMPLATE = """# jobfill secrets: never commit, share, or paste this file anywhere.
# JOBFILL_SECRET derives every job-portal password (HMAC-SHA256 of the company name). Back it up.
JOBFILL_SECRET={secret}

# Optional mail connector, used only by `jobfill login` to read verification codes/links.
# Gmail: turn on 2-step verification, create an app password (Google account > Security > App passwords).
# JOBFILL_IMAP_HOST=imap.gmail.com
# JOBFILL_IMAP_USER=you@gmail.com
# JOBFILL_IMAP_PASSWORD=your-16-character-app-password
"""

UPPER = "ABCDEFGHJKLMNPQRSTUVWXYZ"     # no I/O: easy to read back if typed by hand
LOWER = "abcdefghijkmnpqrstuvwxyz"     # no l
DIGITS = "23456789"                    # no 0/1
SYMBOLS = "!@#$%*?"                    # accepted by Workday, Greenhouse-hosted logins, most portals
ALPHABET = UPPER + LOWER + DIGITS


def load_env(path: Path) -> dict[str, str]:
    env = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def ensure_secret(data_dir: Path) -> Path:
    """Create ``secret.env`` with a fresh random secret if there is none. Never overwrites a secret."""
    path = Path(data_dir) / SECRET_FILE
    if load_env(path).get("JOBFILL_SECRET"):
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text(TEMPLATE.format(secret=secrets.token_hex(32)) + ("\n" + existing if existing else ""),
                    encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def secret(data_dir: Path) -> str:
    return load_env(ensure_secret(data_dir))["JOBFILL_SECRET"]


def account_name(company: str) -> str:
    """The company name the password is derived from: 'Stripe, Inc.' and 'Stripe' give the same password."""
    return company_key(company) or normalize(company)


def derive_password(secret_key: str, company: str, version: int = 1, length: int = 16) -> str:
    """HMAC-SHA256(secret, company), rendered to pass common password rules.

    ``version`` > 1 gives a new password for the same company (after a reset on the site).
    """
    msg = account_name(company) + ("" if version == 1 else f"#{version}")
    stream = b""
    block = 0
    while len(stream) < 2 * length:   # expand deterministically when more bytes are needed
        stream += hmac.new(secret_key.encode(), msg.encode() + (b"" if block == 0 else bytes([block])),
                           hashlib.sha256).digest()
        block += 1
    chars = [UPPER[stream[0] % len(UPPER)], LOWER[stream[1] % len(LOWER)], DIGITS[stream[2] % len(DIGITS)],
             SYMBOLS[stream[3] % len(SYMBOLS)]]
    chars += [ALPHABET[b % len(ALPHABET)] for b in stream[4:length]]
    for i in range(length - 1, 0, -1):   # deterministic shuffle so the classes are not always in front
        j = stream[length + i] % (i + 1)
        chars[i], chars[j] = chars[j], chars[i]
    return "".join(chars)


def login_email(store) -> str | None:
    """The address used for portal accounts: the candidate's choice, else their contact email."""
    return store.get_fact("account.login_email") or store.get_fact("contact.email")


def password_for(store, data_dir: Path, host: str, company: str) -> tuple[str, dict]:
    """Password for this portal's account, plus the account row (created as 'pending' if new)."""
    row = store.account(host) or store.upsert_account(host, account_name(company), login_email(store), "pending")
    return derive_password(secret(data_dir), row["company_key"], row["version"]), row
