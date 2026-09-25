# Devpost submission draft

## Project name

OpenStreamTranslate

## Tagline

One GPU inference per stage. Accessible bilingual captions for every viewer.

## Demo video

https://youtu.be/1ihxp3AwdfM

## Public repository

https://github.com/jvo5610/openstreamtranslate

## Inspiration

Nerdearla already invests in accessibility, but more than 30 English sessions
and several simultaneous stages make commercial caption tools expensive and
operationally difficult. The same problem affects open source conferences
everywhere. We wanted the caption pipeline to scale with active stages, not
with audience size.

## What it does

OpenStreamTranslate accepts live English or Spanish audio and publishes
original plus translated captions in near real time. Viewers choose the stage
and language from a familiar video player. Producers get a separate Studio for
microphone/video input, per-talk technical glossaries and SRT/VTT/TXT export.
OBS and vMix can consume a transparent overlay.

Every stage is inferred once. Redis Streams and Pub/Sub distribute the same
caption event to reconnectable SSE gateways, so adding viewers does not add GPU
work.

## How we built it

- faster-whisper `large-v3-turbo` for bilingual ASR;
- TranslateGemma 4B IT Q8_0 on llama.cpp for local translation;
- FastAPI WebSockets for audio ingress and SSE for audience delivery;
- Redis Streams for short history/replay and Pub/Sub across replicas;
- FFmpeg `-re` to turn real conference videos into deterministic live tests;
- a dependency-free web player, operator Studio and OBS overlay;
- Prometheus metrics and structured JSON logs;
- an acceptance suite covering WER, latency, 2/5/10 concurrent sessions,
  bilingual isolation, reconnect replay and up to 5,000 SSE clients.

## Challenges

The hardest part was not raw inference speed. Partial hypotheses changed while
people were reading them, short fragments disappeared too quickly, and naive
fan-out made one source look expensive for every viewer. We anchored captions
to the video clock, stabilized partials, limited them to two readable lines and
made one Redis subscription feed all local SSE clients for a session.

## Accomplishments

- 3.70% English WER on a real technical video with a human reference;
- ten simultaneous sources with a 3.51 s maximum first-caption delay;
- 1,000 viewers on one replica with 173.07 ms fan-out p95 and one shared event;
- English↔Spanish streams running simultaneously without cross-talk;
- technical hotwords and exact translation mappings per talk;
- no commercial inference API or per-viewer model cost.

## What we learned

Caption UX is a scheduling problem as much as an ML problem. A marginally more
accurate model can still feel worse if it rewrites text too often or lets delay
accumulate. We also learned to separate stage capacity from delivery capacity:
GPU workers scale by concurrent talks, while inexpensive CPU gateways scale by
viewers.

## What's next

- word-level alignment and speaker labels;
- Portuguese after evaluating it with human references;
- authentication, rate limits and production ingress hardening;
- multi-GPU scheduling with Ray Serve/KubeRay;
- a second-pass high-accuracy transcript after each talk.

## Built with

Python, FastAPI, faster-whisper, TranslateGemma, llama.cpp, Redis, FFmpeg,
Docker, WebSocket, Server-Sent Events, Prometheus and vanilla JavaScript.
