# Security policy

This hackathon prototype is intended for controlled conference infrastructure.

- Keep ASR and translation bound to loopback or a private cluster network.
- Terminate TLS and authenticate producer WebSockets at the ingress in
  production.
- Treat session creation and caption injection as privileged operations.
- Do not commit `.env`, SSH keys, access tokens or model credentials.
- Apply request/body limits at the reverse proxy before exposing the simulator.

For a private vulnerability report, contact the repository owner through the
address published in the final public repository profile. Do not include
credentials or personal attendee audio in a public issue.
