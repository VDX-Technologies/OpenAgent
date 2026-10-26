# Privacy

VDX OpenAgent runs locally. Your chats, memory, settings and tokens are stored in
`data/` and `.env` on your Mac. They are never uploaded.

## Optional anonymous telemetry

Telemetry is **off until you allow it** in the in-app prompt. You can turn it
off again at any time (Telemetry → Anonymous sharing). Turning it off also
deletes anything still queued for upload.

**What is sent**

- **Once per app start: an install record.** This contains:
  - a random install ID, generated locally
  - the app version
  - your Mac model (for example `Mac16,1`) and chip
  - CPU core count and RAM size
  - macOS, Python and Ollama versions
- **For each request**, the request numbers:
  - model name, family, parameter size and quantization
  - model size and VRAM used
  - prompt and completion token counts
  - total, load and prefill time
  - GPU time (Ollama prefill + generation)
  - CPU time used by the app process
  - tokens per second, number of tool calls, and whether the request succeeded

**What is never sent:** your prompts, replies, memory, files, tool arguments,
calendar or mail content, account names, hostname, username or IP address.
The ingest service does not store the caller's address.

Data goes to the VDX Core ingest endpoint (`https://dash.vdxtechnologies.com/api/agent/telemetry`,
overridable with `VDX_TELEMETRY_URL`; if that is empty, nothing is sent). No token or account is used. Implementation:
[`core/telemetry_share.py`](core/telemetry_share.py).
