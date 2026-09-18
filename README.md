# news-updater

A single-execution app that gathers AI model-release news and market prices, filters
them through a free LLM, speaks a short briefing with StyleTTS2, then exits. It is
meant to be triggered at Windows logon by Task Scheduler.

## Setup

1. Create the environment and install dependencies:

   ```powershell
   uv venv --python 3.12
   uv pip install -r requirements.txt
   ```

   The CPU build of PyTorch is pulled from the CPU index so StyleTTS2 does not
   download the multi-GB CUDA version.

2. Create your config file and fill in your OpenRouter key and models:

   ```powershell
   Copy-Item .env.example .env
   ```

3. Warm up the TTS model once (downloads the voice checkpoints, cached afterwards):

   ```powershell
   uv run main.py --tts "test"
   ```

4. Register the app to run at logon. Run this once from an elevated prompt:

   ```powershell
   .\setup_task.bat
   ```

That's it. A dry run you can watch any time:

```powershell
uv run main.py --no-play
```

Logs are written to `logs\news-updater.log` if something looks wrong.
