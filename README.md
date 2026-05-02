# AI Industry Weekly

> A fully automated podcast pipeline — scrapes 18 AI news sources, generates a two-speaker script with Claude, converts to audio, and publishes an RSS feed. Runs every Wednesday for ~$0.08/episode.

[![AI Industry Weekly](https://github.com/fayad-abbasi/ai-podcast-generator/actions/workflows/ai-industry-weekly.yml/badge.svg)](https://github.com/fayad-abbasi/ai-podcast-generator/actions/workflows/ai-industry-weekly.yml)
[![Substack PM Weekly](https://github.com/fayad-abbasi/ai-podcast-generator/actions/workflows/substack-pm-weekly.yml/badge.svg)](https://github.com/fayad-abbasi/ai-podcast-generator/actions/workflows/substack-pm-weekly.yml)

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat&logo=python&logoColor=white)](https://python.org)
[![Claude API](https://img.shields.io/badge/Claude-Script%20Generation-CC785C?style=flat)](https://anthropic.com)
[![Google TTS](https://img.shields.io/badge/Google%20Cloud-Text--to--Speech-4285F4?style=flat&logo=google-cloud&logoColor=white)](https://cloud.google.com/text-to-speech)
[![GitHub Actions](https://img.shields.io/badge/GitHub%20Actions-Automated-2088FF?style=flat&logo=github-actions&logoColor=white)](https://github.com/features/actions)
[![RSS](https://img.shields.io/badge/RSS-GitHub%20Pages-FFA500?style=flat&logo=rss&logoColor=white)]()

> The repo also runs **Substack PM Weekly** — a private weekly digest of the maintainer's paid Substack PM newsletters (Friday cron, Gmail-sourced, email-only delivery). The pipeline modules and `Source` plugin protocol are shared across both podcasts; only the ingestion stage and the final audience differ.

---

## What It Does

Every Wednesday at 8 PM ET, a GitHub Actions workflow runs a 6-stage pipeline with no human involvement:

1. **Ingests** fresh content from 18 AI news sources (RSS, Atom, sitemaps, APIs)
2. **Diffs** against last week's snapshot — only new content moves forward
3. **Summarizes** with Claude — deduplicates stories and clusters them into themes
4. **Generates a script** with Claude — two distinct speaker voices, natural dialogue, ~20 minute runtime
5. **Converts to audio** via Google Cloud TTS with ffmpeg stitching
6. **Publishes** an updated RSS feed on GitHub Pages — subscribable in any podcast app

Total cost: **~$0.08 per episode** (Claude API + Google TTS).

---

## Pipeline Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    GitHub Actions (Weekly Cron)             │
└─────────────────────────┬───────────────────────────────────┘
                          │
          ┌───────────────▼───────────────┐
          │         ingest.py             │
          │  18 sources: RSS · Atom ·     │
          │  Sitemaps · APIs · Scrapers   │
          └───────────────┬───────────────┘
                          │
          ┌───────────────▼───────────────┐
          │          diff.py              │
          │  Snapshot comparison —        │
          │  only new stories proceed     │
          └───────────────┬───────────────┘
                          │
          ┌───────────────▼───────────────┐
          │        summarize.py           │
          │  Claude API — deduplicate,    │
          │  cluster stories into themes  │
          └───────────────┬───────────────┘
                          │
          ┌───────────────▼───────────────┐
          │        scriptgen.py           │
          │  Claude API — two-speaker     │
          │  dialogue, ~20 min runtime    │
          └───────────────┬───────────────┘
                          │
          ┌───────────────▼───────────────┐
          │          tts.py               │
          │  Google Cloud TTS with        │
          │  chunking for long text       │
          └───────────────┬───────────────┘
                          │
          ┌───────────────▼───────────────┐
          │       audio.py + publish.py   │
          │  ffmpeg stitching → RSS XML   │
          │  → GitHub Pages deployment    │
          └───────────────────────────────┘
```

**Sources tracked:** Anthropic Blog · OpenAI · Google DeepMind · Gemini · Hugging Face · plus 13 more AI/ML publications

---

## Key Design Decisions

**Diff-based ingestion** — Rather than reprocessing everything weekly, `diff.py` snapshots the previous run and only forwards new content. This keeps Claude API costs minimal and prevents the same stories from appearing across episodes.

**Two-stage Claude prompting** — Summarization and script generation are separated intentionally. The summarize stage produces structured theme clusters; the script stage consumes those clusters to write natural dialogue. Combining them in one prompt produced worse scripts.

**Chunked TTS** — Google Cloud TTS has character limits per request. `tts.py` handles chunking transparently, then `audio.py` stitches the segments with calibrated silence gaps for natural pacing.

**GitHub Pages as podcast host** — The RSS feed and MP3s live in `/site`, published via GitHub Pages. Zero hosting cost, subscribable in Apple Podcasts, Spotify, Overcast, or any RSS reader.

---

## Quick Start

### Prerequisites

- Python 3.11+
- ffmpeg (`brew install ffmpeg` on macOS)
- Anthropic API key
- Google Cloud project with Text-to-Speech API enabled

### Setup

```bash
git clone https://github.com/fayad-abbasi/ai-podcast-generator.git
cd ai-podcast-generator
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your API keys
```

### Run Locally

```bash
# Full pipeline
python -m src.pipeline

# Individual stages (useful for debugging)
python scripts/run_local.py --stage ingest --source anthropic_blog
python scripts/run_local.py --stage summarize
python scripts/run_local.py --stage all --dry-run   # No TTS/publish
```

### Deploy to GitHub Actions

1. Fork this repo
2. Add secrets in **Settings → Secrets → Actions**:

| Secret | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Your Anthropic API key |
| `GOOGLE_TTS_CREDENTIALS` | Base64-encoded GCP service account JSON |

3. Enable GitHub Pages from `main` branch, `/site` folder
4. Replace `site/cover.jpg` with 3000×3000 podcast artwork
5. The workflow runs every Wednesday at 8 PM ET — or trigger it manually from the Actions tab

---

## Project Structure

```
src/
├── config.py       # 18-source list, voice configs, constants
├── ingest.py       # RSS/Atom/scrape/sitemap/API fetchers
├── diff.py         # Snapshot loading, saving, comparison
├── summarize.py    # Claude — deduplicate + cluster into themes
├── scriptgen.py    # Claude — two-speaker script generation
├── tts.py          # Google Cloud TTS with chunking
├── audio.py        # ffmpeg stitching with silence gaps
├── publish.py      # RSS XML manipulation
└── pipeline.py     # Orchestrator wiring all stages
tests/
scripts/
  run_local.py      # Stage-by-stage local runner
site/               # GitHub Pages output (RSS + MP3s)
```

---

## Cost Breakdown

| Stage | Service | Cost/episode |
|---|---|---|
| Summarization | Claude API | ~$0.03 |
| Script generation | Claude API | ~$0.03 |
| Audio conversion | Google Cloud TTS | ~$0.02 |
| Hosting | GitHub Pages | Free |
| **Total** | | **~$0.08** |

---

## Tests

```bash
pytest tests/ -v
```

---

## Why I Built This

I wanted to understand what a production-grade, multi-stage AI pipeline actually looks like end to end — not a demo with a single API call, but something with real ingestion, diffing, multi-prompt chaining, audio processing, and automated deployment. This is that project.

The prompt engineering for `scriptgen.py` was the most interesting problem: getting Claude to write dialogue that sounds like two distinct people talking, not a formatted article read aloud.

---

## Roadmap

- [ ] Per-source relevance scoring to filter low-signal content
- [ ] Listener-style feedback loop — track which topics get engagement
- [ ] Dynamic episode length based on news volume that week
- [ ] Chapter markers in the RSS feed for navigation
- [ ] Web player embedded in GitHub Pages

---

## Related Projects

- [codeguard-ai](https://github.com/fayad-abbasi/codeguard-ai) — AI-powered PR review bot using Claude + GitHub webhooks
- [OpenClaw (Privacy-First)](https://github.com/fayad-abbasi/My-privacy-first-OpenClaw-Implementation) — Self-hosted AI assistant on Raspberry Pi

---

## License

MIT — fork it, extend it, point it at different sources.

---

<div align="center">
  <sub>Built by <a href="https://linkedin.com/in/fayad-abbasi">Fayad Abbasi</a> · DevEx PM exploring production AI pipelines</sub>
</div>
