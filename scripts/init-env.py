#!/usr/bin/env python3
"""Create .env and fill in the secrets docker compose refuses to start without.

`cp .env.example .env` on its own is not enough: the example leaves SECRET_KEY
and POSTGRES_PASSWORD deliberately blank, and compose treats an empty required
variable exactly like a missing one, so the stack fails to start with

    required variable SECRET_KEY is missing a value

This fills only the values that are still blank, so running it twice does not
rotate a key that is already in use - which would sign out every user and
leave the database password out of step with the volume that was created with
it.

    python3 scripts/init-env.py
"""
from __future__ import annotations

import re
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Length in bytes of entropy; token_urlsafe returns roughly 4/3 that in characters.
REQUIRED = {"SECRET_KEY": 48, "POSTGRES_PASSWORD": 24}


def main() -> int:
    env, example = ROOT / ".env", ROOT / ".env.example"

    if not env.exists():
        if not example.exists():
            print(f"error: neither {env} nor {example} exists", file=sys.stderr)
            return 1
        env.write_text(example.read_text())
        print(f"created {env.name} from {example.name}")

    text = env.read_text()
    for key, length in REQUIRED.items():
        if re.search(rf"^{key}=.+$", text, re.M):
            print(f"  {key}: already set, left unchanged")
            continue
        value = secrets.token_urlsafe(length)
        if re.search(rf"^{key}=", text, re.M):
            text = re.sub(rf"^{key}=.*$", f"{key}={value}", text, count=1, flags=re.M)
        else:
            text = text.rstrip("\n") + f"\n{key}={value}\n"
        print(f"  {key}: generated")

    env.write_text(text)
    env.chmod(0o600)          # it holds the signing key and the database password
    print(f"\n{env.name} is ready. Next: docker compose up --build")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
