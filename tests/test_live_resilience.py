import asyncio
import unittest

import httpx

from app.main import BYTES_PER_SECOND, CONTEXT_CHARACTERS, LiveSessionProcessor, MAX_FINAL_SECONDS
from app.pipeline import CaptionPipeline


class FakePipeline:
    def __init__(self, failures: int = 0) -> None:
        self.failures = failures
        self.calls = 0

    async def process(self, _audio, _filename, _prompt, source, target, _glossary):
        self.calls += 1
        if self.calls <= self.failures:
            raise httpx.ConnectError("temporary model outage")
        text = f"Caption {self.calls} " + ("technical context " * 12) + "."
        return {
            "original": text,
            "translation": text,
            "language": source,
            "source_language": source,
            "target_language": target,
            "latency": {"asr": 0.01, "translation": 0.01, "total": 0.02},
        }


class LiveSessionProcessorTests(unittest.IsolatedAsyncioTestCase):
    async def test_long_stream_compacts_audio_and_bounds_context(self) -> None:
        captions = []
        async def collect(caption):
            captions.append(caption)

        processor = LiveSessionProcessor(FakePipeline(), collect)
        await processor.start()

        quarter_second = b"\0" * (BYTES_PER_SECOND // 4)
        for _ in range(400):  # 100 seconds without sleeping in real time.
            await processor.feed(quarter_second)
            await asyncio.sleep(0)
        await processor.finish()

        self.assertGreater(processor.buffer_start_bytes, 0)
        self.assertLessEqual(
            len(processor.buffer),
            int((MAX_FINAL_SECONDS + 1) * BYTES_PER_SECOND),
        )
        self.assertLessEqual(len(processor.context), CONTEXT_CHARACTERS)
        self.assertGreater(captions[-1]["audio_end_seconds"], 95)

    async def test_failed_chunks_do_not_kill_live_session(self) -> None:
        captions = []
        async def collect(caption):
            captions.append(caption)

        pipeline = FakePipeline(failures=2)
        processor = LiveSessionProcessor(pipeline, collect)
        await processor.start()
        for _ in range(3):
            await processor.feed(b"\0" * (5 * BYTES_PER_SECOND))
            await asyncio.sleep(0.01)
        await processor.finish()

        self.assertGreaterEqual(pipeline.calls, 3)
        self.assertTrue(captions)
        self.assertIsNone(processor.task.exception())


class CaptionPipelineRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_translation_retry_does_not_repeat_successful_asr(self) -> None:
        calls = {"asr": 0, "translation": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/transcribe"):
                calls["asr"] += 1
                return httpx.Response(200, json={"text": "Kubernetes scales.", "language": "en"})
            calls["translation"] += 1
            if calls["translation"] < 3:
                return httpx.Response(503, json={"error": "GPU busy"})
            return httpx.Response(200, json={"content": "Kubernetes escala.", "tokens_predicted": 3})

        pipeline = CaptionPipeline(max_attempts=3, retry_base_seconds=0, retry_max_seconds=0)
        await pipeline.client.aclose()
        pipeline.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            result = await pipeline.process(b"wav", "test.wav", source_language="en", target_language="es")
        finally:
            await pipeline.close()

        self.assertEqual(calls, {"asr": 1, "translation": 3})
        self.assertEqual(result["translation"], "Kubernetes escala.")

    async def test_non_retryable_client_error_fails_immediately(self) -> None:
        calls = 0

        def handler(_request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(422, json={"error": "invalid language"})

        pipeline = CaptionPipeline(max_attempts=3, retry_base_seconds=0, retry_max_seconds=0)
        await pipeline.client.aclose()
        pipeline.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            with self.assertRaises(httpx.HTTPStatusError):
                await pipeline.transcribe(b"wav", "test.wav")
        finally:
            await pipeline.close()

        self.assertEqual(calls, 1)


if __name__ == "__main__":
    unittest.main()
