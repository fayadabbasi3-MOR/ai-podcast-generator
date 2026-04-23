# AI Industry Weekly — Podcast Generator

Automated pipeline that scrapes news from Anthropic, OpenAI, and Google Gemini, generates a two-speaker podcast script via Claude, converts it to audio with Google Cloud TTS, and publishes it as an RSS feed on GitHub Pages.

## Pipeline

```
Ingest (18 sources) → Summarize (Claude API) → Script (Claude API) → TTS (Google Cloud) → Audio (ffmpeg) → Publish (RSS + GitHub Pages)
```

Runs weekly via GitHub Actions (Wednesday 8 PM ET). ~$0.08/day.

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt
brew install ffmpeg  # macOS

# Set up env vars
cp .env.example .env
# Edit .env with your API keys

# Run full pipeline locally
python -m src.pipeline

# Or run individual stages
python scripts/run_local.py --stage ingest --source anthropic_blog
python scripts/run_local.py --stage all --dry-run
```

## Project Structure

```
src/
  config.py      # Constants, 18-source list, voice configs
  ingest.py      # RSS/Atom/scrape/sitemap/API fetchers
  diff.py        # Snapshot loading, saving, comparison
  summarize.py   # Claude API — deduplicate + cluster into themes
  scriptgen.py   # Claude API — two-speaker script generation
  tts.py         # Google Cloud TTS with chunking
  audio.py       # ffmpeg stitching with silence gaps
  publish.py     # RSS XML manipulation
  pipeline.py    # Orchestrator wiring all stages
```

## Setup

1. **API Keys**: Anthropic API key + Google Cloud TTS service account
2. **GitHub Secrets**: `ANTHROPIC_API_KEY`, `GOOGLE_TTS_CREDENTIALS` (base64-encoded)
3. **GitHub Pages**: Enable from `main` branch, `/site` folder
4. **Cover Art**: Replace `site/cover.jpg` with 3000x3000 podcast artwork

## Tests

```bash
pytest tests/ -v
```
