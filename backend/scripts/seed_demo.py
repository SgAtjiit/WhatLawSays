"""Create the demo accounts and give each one finished reviews.

Run by ./demo.sh. Only ever against the Firebase Auth emulator: the demo
password is published in the frontend, so these accounts must not exist in a
real project.

    FIREBASE_AUTH_EMULATOR_HOST=127.0.0.1:9099 FIREBASE_PROJECT_ID=demo-whatlawsays \
        uv run python -m scripts.seed_demo --api http://127.0.0.1:8010 [--reset]

Each account keeps a fixed uid, so reviews saved in Postgres stay attached to it
when the emulator restarts empty. An account that already has reviews is left
alone unless --reset is given. Reviews go through the real API, the same path
an upload from the app takes.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import firebase_admin
import httpx
from firebase_admin import auth

from src.config import settings

REPO = Path(__file__).resolve().parents[2]
ACCOUNTS = REPO / "frontend" / "src" / "auth" / "demo-accounts.json"
SAMPLES = REPO / "backend" / "samples"


def fail(message: str) -> None:
    print(f"seed_demo: {message}", file=sys.stderr)
    sys.exit(1)


def ensure_account(app, account: dict, password: str) -> None:
    """The account exists, with this uid, confirmed, and with the demo password."""
    fields = dict(
        email=account["email"],
        password=password,
        display_name=account["name"],
        email_verified=True,
    )
    try:
        holder = auth.get_user_by_email(account["email"], app=app)
    except auth.UserNotFoundError:
        holder = None
    if holder and holder.uid != account["uid"]:
        # The address was taken by an account made by hand; the uid matters more.
        auth.delete_user(holder.uid, app=app)
        holder = None
    if holder:
        auth.update_user(account["uid"], app=app, **fields)
    else:
        auth.create_user(uid=account["uid"], app=app, **fields)


def id_token(emulator: str, email: str, password: str) -> str:
    response = httpx.post(
        f"http://{emulator}/identitytoolkit.googleapis.com/v1/accounts:signInWithPassword",
        params={"key": "demo"},
        json={"email": email, "password": password, "returnSecureToken": True},
    )
    response.raise_for_status()
    return response.json()["idToken"]


def wait_for(api: str, seconds: int = 300) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{api}/health", timeout=5).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(2)
    fail(f"the backend at {api} did not answer /health within {seconds} s")


def seed(client: httpx.Client, account: dict, reset: bool) -> None:
    existing = client.get("/api/v1/contracts", params={"limit": 100}).raise_for_status().json()["items"]
    if existing and not reset:
        print(f"  {account['name']}: {len(existing)} reviews already there")
        return
    for item in existing:
        client.delete(f"/api/v1/contracts/{item['contract_id']}").raise_for_status()

    # Oldest first, so the first review listed is the newest one in the app.
    for review in reversed(account["reviews"]):
        path = SAMPLES / review["file"]
        started = time.monotonic()
        with path.open("rb") as handle:
            response = client.post(
                "/api/v1/contracts",
                files={"file": (path.name, handle)},
                data={"contract_type": review["contract_type"], "position": review["position"]},
            )
        if response.status_code != 200:
            fail(f"{path.name} for {account['name']}: {response.status_code} {response.text[:300]}")
        body = response.json()
        print(
            f"  {account['name']}: {path.name} -> {body['overall_risk']}, "
            f"{len(body['findings'])} findings ({time.monotonic() - started:.0f} s)"
        )


def seed_conversation(client: httpx.Client, account: dict, reset: bool) -> None:
    """Replay the account's demo conversation into Talk it through, once."""
    messages = account.get("conversation")
    if not messages:
        return
    if not settings.GROQ_API_KEY:
        print(f"  {account['name']}: no demo conversation (it needs GROQ_API_KEY in backend/.env)")
        return
    existing = client.get("/api/v1/conversations", params={"limit": 100}).raise_for_status().json()["items"]
    if existing and not reset:
        print(f"  {account['name']}: {len(existing)} conversation(s) already there")
        return
    for item in existing:
        client.delete(f"/api/v1/conversations/{item['conversation_id']}").raise_for_status()

    conversation_id = client.post("/api/v1/conversations", json={}).raise_for_status().json()["conversation_id"]
    for message in messages:
        with client.stream(
            "POST", f"/api/v1/conversations/{conversation_id}/messages", json={"content": message}
        ) as response:
            response.raise_for_status()
            events = [line[7:] for line in response.iter_lines() if line.startswith("event: ")]
        if not events or events[-1] != "done":
            fail(f"the demo conversation for {account['name']} did not finish: {events[-1:]}")
    print(f"  {account['name']}: demo conversation with {len(messages)} questions")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", default="http://127.0.0.1:8010")
    parser.add_argument("--reset", action="store_true", help="delete and redo every demo review")
    args = parser.parse_args()

    emulator = os.environ.get("FIREBASE_AUTH_EMULATOR_HOST")
    project = os.environ.get("FIREBASE_PROJECT_ID")
    if not emulator:
        fail("FIREBASE_AUTH_EMULATOR_HOST is not set. Demo accounts are created only in the Auth emulator.")
    if not project:
        fail("FIREBASE_PROJECT_ID is not set.")

    spec = json.loads(ACCOUNTS.read_text())
    app = firebase_admin.initialize_app(options={"projectId": project}, name="seed-demo")
    wait_for(args.api)

    for account in spec["accounts"]:
        ensure_account(app, account, spec["password"])
        token = id_token(emulator, account["email"], spec["password"])
        with httpx.Client(
            base_url=args.api,
            headers={"Authorization": f"Bearer {token}"},
            timeout=httpx.Timeout(610, connect=10),
        ) as client:
            seed(client, account, args.reset)
            seed_conversation(client, account, args.reset)


if __name__ == "__main__":
    main()
