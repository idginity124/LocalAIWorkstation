# Contributing

Use Linux, Python 3.12–3.14 and Node.js 22+. Run `bash setup.sh`, then `bash start.sh --dev`. Configuration and optional engine setup are described in [Installation](docs/INSTALLATION.md).

Before opening a pull request:

```bash
PYTHONDONTWRITEBYTECODE=1 backend/.venv/bin/python -m unittest discover -s backend/tests -q
backend/.venv/bin/python -m unittest discover -s scripts/tests -q
npm --prefix frontend run build
npm --prefix frontend run test:i18n
python3 scripts/check_source_release.py
```

Keep changes focused. Describe the problem, resulting behavior and validation. For GPU-specific changes, report the GPU, runtime and model used; mock tests cannot establish hardware compatibility.

Do not commit model weights, generated media, voice profiles, conversations, local configuration, logs or credentials. Keep model download sources and licensing separate from this project's code license. Never include private recordings or project files in bug reports.
