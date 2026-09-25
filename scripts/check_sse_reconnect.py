#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import time

import httpx


async def read_one(
    client: httpx.AsyncClient,
    url: str,
    last_event_id: str | None = None,
) -> dict:
    headers = {"Last-Event-ID": last_event_id} if last_event_id else {}
    async with client.stream("GET", url, headers=headers) as response:
        response.raise_for_status()
        event_id = None
        async for line in response.aiter_lines():
            if line.startswith("id:"):
                event_id = line[3:].strip()
            elif line.startswith("data:"):
                event = json.loads(line[5:].strip())
                event["sse_id"] = event_id
                return event
    raise RuntimeError("SSE connection ended without an event")


async def run(args: argparse.Namespace) -> dict:
    session_id = f"reconnect-{str(int(time.time() * 1000))[-8:]}"
    events_url = f"{args.base_url}/api/sessions/{session_id}/events"
    async with httpx.AsyncClient(timeout=args.timeout) as client:
        async def publish(sequence: int) -> dict:
            response = await client.post(
                f"{args.base_url}/api/sessions/{session_id}/captions",
                json={
                    "original": f"Original caption {sequence}",
                    "translation": f"Subtítulo traducido {sequence}",
                    "source_language": "en",
                    "target_language": "es",
                    "sequence": sequence,
                    "final": True,
                },
            )
            response.raise_for_status()
            return response.json()

        first_published = await publish(1)
        first_received = await read_one(client, events_url)
        second_published = await publish(2)
        second_received = await read_one(client, events_url, first_received["event_id"])
        stop_response = await client.post(f"{args.base_url}/api/sessions/{session_id}/stop")
        stop_response.raise_for_status()
        try:
            await asyncio.wait_for(read_one(client, events_url), timeout=1)
            stale_event_replayed = True
        except TimeoutError:
            stale_event_replayed = False
        await client.delete(f"{args.base_url}/api/sessions/{session_id}")

    passed = (
        first_received.get("event_id") == first_published.get("event_id")
        and first_received.get("sse_id") == first_published.get("event_id")
        and second_received.get("event_id") == second_published.get("event_id")
        and second_received.get("sse_id") == second_published.get("event_id")
        and second_received.get("sequence") == 2
        and not stale_event_replayed
    )
    return {
        "session_id": session_id,
        "first_event_id": first_received.get("event_id"),
        "replayed_event_id": second_received.get("event_id"),
        "replayed_sequence": second_received.get("sequence"),
        "stale_event_replayed_after_stop": stale_event_replayed,
        "passed": passed,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--timeout", type=float, default=10)
    args = parser.parse_args()
    result = asyncio.run(run(args))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
