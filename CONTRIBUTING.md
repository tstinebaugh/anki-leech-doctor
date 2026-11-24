# Contributing to Anki Leech Doctor & Mnemonic Studio

Thank you for your interest in improving Anki Leech Doctor! We welcome contributions from developers and Japanese language learners of all skill levels.

---

## 🛠️ Local Development Setup

### 1. Prerequisites
- Python 3.12+ (CI tests 3.12, 3.13, 3.14 and 3.15)
- [Anki](https://apps.ankiweb.net/) desktop app running with the [AnkiConnect](https://ankiweb.net/shared/info/2055492153) add-on (code: `2055492153`).
- A Gemini API Key from [Google AI Studio](https://aistudio.google.com/).

### 2. Installation
```bash
# Clone the repository
git clone https://github.com/<your-username>/anki-leech-doctor.git
cd anki-leech-doctor

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies (app + test/lint tools)
pip install -r requirements-dev.txt

# Create your local config (or configure it in the web UI)
cp config.example.json config.json
```

### 3. Running the Development Server
```bash
python3 app.py
# Or with auto-reload:
uvicorn app:app --host 127.0.0.1 --port 8766 --reload
```
Open [http://127.0.0.1:8766](http://127.0.0.1:8766) in your browser.

### 4. Running Tests & Lint
```bash
pytest                    # unit tests (no Anki or API key needed)
ruff check .              # lint
pytest -m integration     # optional: needs Anki running and a real Gemini key; spends API quota
```
Unit tests run against a temporary config and database (see `conftest.py`), so they never modify your `config.json` or `leech_doctor.db`. CI runs `ruff check .` and `pytest` on every pull request.

### 5. Database migrations

`leech_doctor.db` is SQLite, mapped with SQLAlchemy 2.0 in [`db.py`](db.py); [Alembic](https://alembic.sqlalchemy.org/) owns the schema in [`migrations/`](migrations/). The app runs `alembic upgrade head` itself on startup. To change the schema:

```bash
# 1. Edit the models in db.py, then generate a migration and read it before committing
alembic revision --autogenerate -m "add something"
# 2. Apply it to your local database
alembic upgrade head
# 3. Confirm models and migrations agree (the test suite checks this too)
alembic check
```

Migrations must not import app code (use plain `sa.DateTime()` and friends), and SQLite changes go through `op.batch_alter_table`.

---

## 💡 How You Can Contribute

1. **New Deck Presets & Field Mappings**: Add out-of-the-box support for popular Japanese Anki decks (Kaishi, Core 2k/6k, Nayr, Tango, RTK, Wanikani).
2. **AI Mnemonic Strategies**: Improve prompt engineering for specific kanji learning methods (Radical breakdown, Hanzi/Kanji crossovers, etymology).
3. **UI / UX Improvements**: Help refine responsive design, dark mode themes, accessibility, and hotkeys.
4. **Bug Fixes & Test Cases**: Add automated test cases for edge cases in Japanese parsing and Anki field synchronization.

---

## 📋 Pull Request Guidelines

- Create a feature branch (`git checkout -b feature/amazing-idea`).
- Ensure `pytest` and `ruff check .` pass.
- Keep code clean, well-documented, and avoid hardcoding user-specific paths or decks. New defaults belong in `config_defaults.py`.
- Text that isn't Anki field HTML must go through `escapeHtml()` before it reaches `innerHTML`; rendered markdown goes through `renderMarkdown()`.
- Submit your pull request with a descriptive title and summary of changes!
