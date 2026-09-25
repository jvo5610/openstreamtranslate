#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import time

import httpx


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


async def run(args: argparse.Namespace) -> dict:
    session_id = f"sse-scale-{args.viewers}"
    ready = asyncio.Event()
    ready_count = 0
    ready_lock = asyncio.Lock()
    limits = httpx.Limits(max_connections=args.viewers + 20, max_keepalive_connections=20)
    timeout = httpx.Timeout(args.timeout, connect=args.timeout, pool=args.timeout)

    async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
        async def watch(index: int) -> dict:
            nonlocal ready_count
            result = {"viewer": index, "delivery_ms": None, "event_id": None, "error": None}
            try:
                async with client.stream("GET", f"{args.base_url}/api/sessions/{session_id}/events") as response:
                    response.raise_for_status()
                    async with ready_lock:
                        ready_count += 1
                        if ready_count == args.viewers:
                            ready.set()
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        event = json.loads(line[5:].strip())
                        if event.get("sequence") != 1:
                            continue
                        result["delivery_ms"] = round(
                            max(0, time.time() - float(event["published_at"])) * 1000,
                            2,
                        )
                        result["event_id"] = event.get("event_id")
                        return result
            except Exception as exc:
                result["error"] = f"{type(exc).__name__}: {exc}"
            return result

        tasks = [asyncio.create_task(watch(index + 1)) for index in range(args.viewers)]
        await asyncio.wait_for(ready.wait(), timeout=args.timeout)
        publish_started = time.perf_counter()
        response = await client.post(
            f"{args.base_url}/api/sessions/{session_id}/captions",
            json={
                "original": "This is one caption generated once for every connected viewer.",
                "translation": "Este subtítulo se generó una vez para todos los espectadores conectados.",
                "source_language": "en",
                "target_language": "es",
                "sequence": 1,
                "final": True,
                "latency": {"asr": 0.3, "translation": 0.2, "total": 0.5},
            },
        )
        response.raise_for_status()
        publish_request_ms = round((time.perf_counter() - publish_started) * 1000, 2)
        results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=args.timeout)
        await client.delete(f"{args.base_url}/api/sessions/{session_id}")

    successful = [item for item in results if item["delivery_ms"] is not None]
    delivery = [item["delivery_ms"] for item in successful]
    event_ids = {item["event_id"] for item in successful}
    delivery_p95_ms = round(percentile(delivery, 0.95), 2) if delivery else None
    passed = (
        len(successful) == args.viewers
        and len(event_ids) == 1
        and delivery_p95_ms is not None
        and delivery_p95_ms <= args.max_p95_ms
    )
    return {
        "viewers": args.viewers,
        "successful_viewers": len(successful),
        "publish_request_ms": publish_request_ms,
        "delivery_p50_ms": round(statistics.median(delivery), 2) if delivery else None,
        "delivery_p95_ms": delivery_p95_ms,
        "delivery_p99_ms": round(percentile(delivery, 0.99), 2) if delivery else None,
        "delivery_max_ms": round(max(delivery), 2) if delivery else None,
        "one_event_id": len(event_ids) == 1,
        "max_p95_ms": args.max_p95_ms,
        "passed": passed,
        "errors": [item for item in results if item["error"]][:10],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--viewers", type=int, default=1000)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--max-p95-ms", type=float, default=250)
    args = parser.parse_args()
    result = asyncio.run(run(args))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
