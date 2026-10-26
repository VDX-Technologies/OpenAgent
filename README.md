# VDX OpenAgent

A local, open-source AI assistant for macOS. It runs models on your Mac with
[Ollama](https://ollama.com) and can work with Calendar, Reminders, Mail/Gmail,
GitHub, Discord and scheduled automations. Your conversations stay on your machine.

- **Backend:** Python 3.10+ / FastAPI on `http://127.0.0.1:8741`
- **UI:** SvelteKit (Svelte 5, TypeScript, Tailwind), built as static files and served by the API
- **App:** a native window (pywebview) installed as `~/Applications/VDX OpenAgent.app`

## Requirements

| | |
|---|---|
| macOS | 13+ (Apple Silicon recommended) |
| Python | 3.10 or newer (`python3 --version`) |
| Node + pnpm | Node 20+, then `npm i -g pnpm` |
| Ollama | [ollama.com/download](https://ollama.com/download) or `brew install ollama` |

## Install

```bash
git clone https://github.com/<your-org>/vdx-agent.git
cd vdx-agent
./scripts/install.sh            # add --autostart to launch at login
ollama pull qwen2.5:7b          # or pick a model in the welcome guide
```

Open **VDX OpenAgent** from `~/Applications` or Spotlight. The first launch opens a
short welcome guide that checks Ollama, picks a model and turns on connectors.

To uninstall, run `./scripts/uninstall.sh`.

## Run from source (development)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # optional: Gmail, Discord, GitHub tokens…
python3 main.py                 # API + built UI on http://127.0.0.1:8741

cd ui && pnpm install && pnpm dev   # hot-reload UI on http://localhost:5173
```

`pnpm build` writes `ui/build`, which the API serves.

## Project layout

```
api/          FastAPI routes (chat, status, settings, history, telemetry)
core/         agent loop, Ollama client, memory, automations, telemetry
tools/        Apple Calendar / Reminders (AppleScript), Gmail, …
interface/    Discord bot
ui/           SvelteKit app
scripts/      install.sh / uninstall.sh
main.py       entry point (port 8741)
```

## Configuration

All settings live in `.env` (see `.env.example`) and can be edited in
**Settings** in the app. `.env` is git-ignored and never leaves your Mac.

## Privacy and telemetry

The app asks once whether you want to share **anonymous performance data**.
Nothing is sent unless you choose **Allow**, and you can change this at any
time under **Telemetry → Anonymous sharing** or in **Settings**. That panel also
shows the exact record that would be sent. Details are in [PRIVACY.md](PRIVACY.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Bug reports and pull requests are welcome.

## License

[MIT](LICENSE)
