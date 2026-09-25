# Contributing

Issues and pull requests are welcome. Keep changes focused and include evidence
for behavior that affects quality, latency or concurrency.

## Local checks

```bash
python3 -m py_compile app/*.py remote/*.py scripts/*.py docs/diagrams/*.py
node --check app/static/*.js
for file in scripts/*.sh remote/*.sh; do bash -n "$file"; done
docker compose config -q
make smoke
```

Run `make acceptance` before changing the streaming scheduler, Redis fan-out,
language handling or inference prompts. Do not lower a quality/latency threshold
without documenting the measured reason in the pull request.

Never commit credentials, private SSH hostnames, model weights or media without
clear redistribution rights.
