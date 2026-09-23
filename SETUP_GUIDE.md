# Lead Intelligence Engine — Windows Setup

## 1. Create/activate the virtual environment

PowerShell:

```powershell
cd "C:\Users\ismail shah\Downloads\lead-intelligence-engine\lead-intelligence-engine"
python -m venv venv
.\venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\venv\Scripts\Activate.ps1
```

## 2. Install the project dependencies

Your error:

`ModuleNotFoundError: No module named 'yaml'`

means PyYAML is not installed in the active virtual environment. The project already lists `PyYAML` in `requirements.txt`.

Run:

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Then verify:

```powershell
python -c "import yaml; print('PyYAML OK:', yaml.__version__)"
```

Do not install a package named `yaml`; the Python package needed here is **PyYAML**.

## 3. Create `.env`

A `.env` template is included in this ZIP. Keep the file private and never commit real API keys to GitHub.

The important discovery key added by this version is:

```text
EXA_API_KEY=
```

Other optional keys already used by the project are:

```text
GOOGLE_PLACES_API_KEY=
GOOGLE_CUSTOM_SEARCH_API_KEY=
GOOGLE_CUSTOM_SEARCH_CX=
META_ACCESS_TOKEN=
FACEBOOK_PAGE_ACCESS_TOKEN=
XAI_API_KEY=
XAI_MODEL=grok-4.7
```

## 4. Initialize the database

After dependencies are installed:

```powershell
python -m app initdb
```

Then check connector status:

```powershell
python -m app sources
```

Exa should show as AVAILABLE only after `EXA_API_KEY` is filled.

## 5. Test Exa by itself

```powershell
python -m app discover --source exa --industry roofing --location "Austin, TX"
```

With a valid key, this calls Exa and stores normalized records in the existing pipeline database.

## 6. Run the full pipeline

```powershell
python -m app pipeline --industry roofing --location "Texas"
```

Or use the configured industries:

```powershell
python -m app pipeline --location "Texas"
```

## 7. Run tests

```powershell
python -m pytest -q
```

## API key setup — one by one

### Exa

1. Open https://dashboard.exa.ai/api-keys
2. Create/sign in to your Exa account.
3. Create an API key.
4. Copy it.
5. Put it in `.env`:

```text
EXA_API_KEY=your_real_key_here
```

6. Do not add quotes unless the key itself requires them.
7. Run:

```powershell
python -m app sources
```

### Google Places

1. Open https://console.cloud.google.com/
2. Create/select a Google Cloud project.
3. Enable **Places API (New)**.
4. Set up billing if Google requires it for the account/project.
5. Create an API key.
6. Put it in:

```text
GOOGLE_PLACES_API_KEY=your_real_key_here
```

### Google Custom Search

This connector is legacy/limited in the supplied project. Only configure it if you already have an active Custom Search JSON API setup.

Variables:

```text
GOOGLE_CUSTOM_SEARCH_API_KEY=
GOOGLE_CUSTOM_SEARCH_CX=
```

### Meta Ad Library

The supplied connector expects:

```text
META_ACCESS_TOKEN=
META_API_VERSION=v23.0
```

Use Meta's official developer/Ad Library documentation and account setup. The project's own README documents important limitations for US commercial-ad discovery.

### Facebook Pages

Only configure this if you have a permitted Page access token:

```text
FACEBOOK_PAGE_ACCESS_TOKEN=
```

This is not a general Facebook-page scraper.

### xAI / Grok

The project now uses xAI/Grok instead of Anthropic for the optional cold-call brief polishing step.

1. Open https://console.x.ai/
2. Create or sign in to your xAI developer account.
3. Open the API Keys section and create an API key.
4. Put it in `.env`:

```text
LLM_PROVIDER=xai
XAI_API_KEY=your_real_key_here
XAI_MODEL=grok-4.7
```

The integration uses xAI's OpenAI-compatible API at `https://api.x.ai/v1/chat/completions`. xAI's current documentation says the Responses API is recommended for new integrations, while Chat Completions remains available; this project uses the compatible chat endpoint for its one-shot polishing task.

Important: Grok chat access and the xAI developer API are separate. API access may require credits, so check the current xAI Console pricing/billing before using it at scale.

If you leave `LLM_PROVIDER=template`, no LLM API is required.

## Recommended first setup

You do NOT need every API before testing the application.

Start with:

1. Install `requirements.txt`
2. Fix/verify PyYAML
3. Add `EXA_API_KEY`
4. Run `python -m app initdb`
5. Run `python -m app sources`
6. Run the Exa-only discover command
7. Then add Google Places if you want Google Maps discovery

The project is designed so missing optional keys do not stop the entire pipeline.
