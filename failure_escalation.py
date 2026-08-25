#!/usr/bin/env python3

import argparse
import hashlib
import json
from pathlib import Path


def failure_key(version: str, reason: str) -> str:
    return hashlib.sha256(f"{version}\0{reason}".encode()).hexdigest()[:16]


def state_key(state: object) -> str:
    if not isinstance(state, dict):
        return ""
    version = state.get("version")
    reason = state.get("reason")
    if not isinstance(version, str) or not isinstance(reason, str):
        return ""
    return failure_key(version, reason)


def transition(
    previous: object,
    status: str,
    version: str,
    reason: str,
    log_url: str,
) -> dict[str, object]:
    old_key = state_key(previous)
    if status == "success":
        return {
            "state": {},
            "key": "",
            "close_key": old_key,
            "escalate": False,
            "body": "",
        }
    if status != "failure" or not version or not reason:
        raise ValueError("failure status requires a version and reason")

    key = failure_key(version, reason)
    same_failure = old_key == key
    count = previous.get("count", 0) + 1 if same_failure else 1
    if not isinstance(count, int):
        count = 1
    state = {"version": version, "reason": reason, "count": count}
    body = (
        f"<!-- amp-update-failure:{key} -->\n"
        f"Amp version: {version}\n\n"
        f"Failing step: {reason}\n\n"
        f"Consecutive failures: {count}\n\n"
        f"Latest workflow log: {log_url}\n\n"
        "Recommended next action: open the workflow log, fix the failing step, and rerun detection.\n"
    )
    return {
        "state": state,
        "key": key,
        "close_key": old_key if old_key and not same_failure else "",
        "escalate": count >= 2,
        "body": body,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Track consecutive Amp update failures")
    parser.add_argument("--previous-state", type=Path, required=True)
    parser.add_argument("--next-state", type=Path, required=True)
    parser.add_argument("--body", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--status", choices=("success", "failure"), required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--reason", default="")
    parser.add_argument("--log-url", required=True)
    arguments = parser.parse_args()

    try:
        previous = json.loads(arguments.previous_state.read_text())
    except (OSError, json.JSONDecodeError):
        previous = {}
    result = transition(
        previous,
        arguments.status,
        arguments.version,
        arguments.reason,
        arguments.log_url,
    )
    arguments.next_state.write_text(json.dumps(result["state"], sort_keys=True) + "\n")
    arguments.body.write_text(str(result["body"]))
    with arguments.output.open("a") as output:
        output.write(f"key={result['key']}\n")
        output.write(f"close_key={result['close_key']}\n")
        output.write(f"escalate={str(result['escalate']).lower()}\n")
        output.write(f"version={arguments.version}\n")
        output.write(f"reason={arguments.reason}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
