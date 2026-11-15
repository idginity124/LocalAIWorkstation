<p align="center"><a href="README.md">English</a> &nbsp; / &nbsp; <a href="README.tr.md">Türkçe</a></p>

# Local AI Workstation

A local Linux workspace for chat, code assistance, image generation and optional audio tools. Built with React, TypeScript, FastAPI and SQLite.

[Installation](docs/INSTALLATION.md) · [Usage](docs/USER_GUIDE.md) · [Tests](docs/TESTING.md) · [Contributing](CONTRIBUTING.md)

**Status: experimental desktop prototype.** Originally exercised on CachyOS with an AMD RX 6800 XT. Hardware-specific engines require separate setup and validation. Model weights and inference engines are not included.

## Features

- Streaming local chat, saved conversations, cancellation and continuation of truncated replies.
- Code workspace with project-scoped file access, diff preview and explicit approval before writing.
- ComfyUI image generation and FLUX.2 Klein editing, a gallery and persistent image jobs.
- Shared GPU ownership between managed services to avoid simultaneous heavy workloads.
- Optional voice profiles, text-to-speech and speech/singing conversion after runtime verification.
- Experimental Krita-backed editing and masked AI corrections.
- Dark/light themes and 11 interface languages.

## Quick start

Requires Linux, Python 3.12–3.14 and Node.js 22+. From the cloned repository:

```bash
bash setup.sh
cp .env.example .env
# Edit .env if your models or ComfyUI live elsewhere.
bash start.sh
```

Open **http://127.0.0.1:8000**. Stop with `Ctrl+C`. Development mode: `bash start.sh --dev`.

Setup installs application dependencies only. The UI opens without model weights; inference stays unavailable until you install the relevant engine and files. Chat uses a local `llama-server` executable on `PATH`; this release does not connect to an LM Studio or Ollama server. See [Installation](docs/INSTALLATION.md) for exact model filenames and engine requirements.

## Configuration

| Variable | Default |
| --- | --- |
| `AI_WORKSTATION_MODEL_DIR` | `~/AI/models` |
| `AI_WORKSTATION_COMFYUI_DIR` | `~/AI/ComfyUI` |
| `AI_WORKSTATION_DATA` | `~/.local/share/ai-workstation` |

`start.sh` reads an optional local `.env` as Bash configuration. Only use a configuration file you trust. Direct Python commands and engine utility scripts use exported environment variables; they do not automatically read `.env`.

## Scope and limits

- Linux desktop use only; AMD-oriented GPU monitoring and conservative resource checks. NVIDIA, macOS and Windows are not validated targets.
- Chat is restricted to the included Gemma, Qwen and gpt-oss catalog. Arbitrary model import and automatic model downloads are not implemented in the UI.
- ComfyUI is managed through `systemd --user`, with a 10 GiB available-RAM startup threshold and memory limits. Image model compatibility, especially INT8/FP8 on older AMD GPUs, needs local validation.
- Audio inference is optional and remains disabled until successful engine probes. The integrated TTS readiness check currently requires ROCm.
- Krita editing is experimental; export your work before closing. See [Krita integration](docs/KRITA_INTEGRATION.md).
- Video generation, image understanding in chat and a document workspace are not available in this release.
- The API is for a single local user. Do not expose it publicly; see [Security](SECURITY.md).

## Data and licensing

Conversations, jobs and settings live in the configured data directory. Saved voice profiles live in browser IndexedDB and need a separate export/backup; completed audio outputs live in the data directory. Image outputs live under `ComfyUI/output/LocalAIWorkstation/`. These, model weights, caches and local runtime reports are excluded from Git. Back up personal data separately before changing engines or moving installations.

Code is licensed under [MIT](LICENSE). Models, dependencies and downloaded third-party engines retain their own licenses; this repository does not redistribute them.

<br>
<p align="center"><img src="assets/training-arc.en.svg" width="840" alt="The Training Arc — Ekrem Bulgan"></p>
<p align="center"><a href="https://www.ekrembulgan.com">Ekrem Bulgan</a> &nbsp; / &nbsp; <a href="https://linkedin.com/in/ekrembulgan">LinkedIn</a> &nbsp; / &nbsp; <a href="https://buymeacoffee.com/ekrembulgan">Support development</a></p>
<p align="center"><sub>© 2026 Ekrem Bulgan · <a href="LICENSE">MIT licensed</a></sub></p>
