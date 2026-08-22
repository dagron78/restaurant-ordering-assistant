# 👨‍🍳 Restaurant Ordering Assistant

A smart ordering application for restaurants that monitors vendor prices, tracks trends, and provides AI-powered recommendations for kitchen managers.

## Features

- **📧 Email Monitoring**: Automatically processes price list attachments from vendors (Sysco, US Foods)
- **🌐 Web Scraping**: Scrapes vendor websites for current pricing (with session persistence)
- **🤖 AI-Powered Parsing**: Uses Google Gemini to extract data from invoices and price sheets
- **📈 Trend Analysis**: Tracks historical prices and identifies deals/spikes
- **📋 Smart Recommendations**: Combines price data with your preferences to suggest best vendors
- **📱 Mobile-Friendly**: Simple Streamlit interface works on phones and tablets

## Screenshots

| Order Guide | Trends | Settings |
|-------------|--------|----------|
| View recommendations | Analyze history | Configure system |

## Quick Start

### Prerequisites

- Python 3.10+
- Google Gemini API key ([Get one here](https://makersuite.google.com/app/apikey))
- Email account for receiving vendor price lists
- Vendor login credentials (Sysco, US Foods)

### Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd restaurant-ordering-assistant
   ```

2. **Create virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   playwright install chromium
   ```

4. **Configure environment**
   ```bash
   cp .env.example .env
   # Edit .env with your API keys and credentials
   ```

5. **Initialize database**
   ```bash
   python scripts/init_db.py --sample-data
   ```

6. **Run the application**
   ```bash
   streamlit run app/main.py
   ```

7. **Open in browser**: http://localhost:8501

## Configuration

### Environment Variables

Copy `.env.example` to `.env` and configure:

```bash
# Required
GOOGLE_API_KEY=your_gemini_api_key

# Email monitoring
EMAIL_USER=orders@yourrestaurant.com
EMAIL_PASS=your_email_app_password
EMAIL_IMAP_SERVER=imap.gmail.com

# Optional: require a password to open the app (recommended!)
APP_PASSWORD=a-shared-secret

# Vendor logins are NOT stored here - sessions are created manually:
#   python workers/web_scraper.py --refresh sysco
#   python workers/web_scraper.py --refresh usfoods
```

### Preferences

Edit `data/preferences.txt` with your ordering rules in natural language:

```text
# Vendor Preferences
Prefer Sysco for all produce items unless US Foods is 15% cheaper.
Always buy dairy products from US Foods.

# Price Alerts
Alert me if Avocados exceed $55 per case.
Notify me when Heavy Cream increases more than 15%.

# Quality Rules
Quality over price for all beef products.
```

## Usage

### Adding Items

1. **Upload Invoice**: Go to Settings → Add Items, upload a photo of an invoice
2. **AI Extracts Data**: Gemini parses the document and extracts items/prices
3. **Review & Save**: Edit any corrections and save to database

### Viewing Recommendations

1. Go to **Order Guide** page
2. View AI recommendations with trend indicators:
   - 🟢 Price below average (deal!)
   - 🔴 Price above average (spike)
   - ⚪ Price stable
3. Enter quantities and generate order summary

### Analyzing Trends

1. Go to **Trends** page
2. Select an item to view price history
3. Compare vendor pricing over time
4. Download data as CSV

## Architecture

```
restaurant-ordering-assistant/
├── app/                    # Streamlit web interface
│   ├── main.py            # Home page
│   └── pages/             # Additional pages
├── core/                   # Core business logic
│   ├── ai_engine.py       # Gemini API wrapper
│   ├── database.py        # SQLite operations
│   ├── config.py          # Configuration management
│   └── recommendation.py  # Recommendation engine
├── workers/               # Background workers
│   ├── email_monitor.py   # Email processing
│   ├── web_scraper.py     # Vendor scraping
│   └── scheduler.py       # Task scheduling
├── scripts/               # Utility scripts
│   ├── schema.sql         # Database schema
│   └── init_db.py         # Initialization script
└── data/                  # Data storage
    ├── restaurant_data.db # SQLite database
    ├── preferences.txt    # User preferences
    └── sessions/          # Auth session files
```

## Docker Deployment

### Using Docker Compose (Recommended)

```bash
# Build and run
docker-compose up -d

# View logs
docker-compose logs -f

# Stop
docker-compose down
```

### Manual Docker

```bash
# Build image
docker build -t restaurant-ordering-assistant .

# Run container
docker run -d \
  -p 8501:8501 \
  -v $(pwd)/data:/app/data \
  --env-file .env \
  restaurant-ordering-assistant
```

## Background Workers

### Email Monitor
Checks email every 8 hours for price list attachments.

```bash
# Run manually
python workers/email_monitor.py

# Or via scheduler
python workers/scheduler.py
```

### Web Scraper

#### Refresh Login Sessions
```bash
# Sysco
python workers/web_scraper.py --refresh sysco

# US Foods
python workers/web_scraper.py --refresh usfoods
```

#### Run Scrape
```bash
python workers/web_scraper.py --scrape
```

## API Reference

### Database Operations

```python
from core.database import Database

db = Database()

# Add items
db.add_item("Heavy Cream", category="Dairy", default_unit="Case")

# Add prices
db.add_price("Heavy Cream", "Sysco", 24.50, "Case", source="manual")

# Get recommendations
items = db.get_all_items_with_prices()
```

### AI Engine

```python
from core.ai_engine import GeminiEngine

ai = GeminiEngine()

# Parse document
items = ai.parse_document("invoice.jpg", vendor_hint="Sysco")

# Parse preferences
rules = ai.parse_preferences("Prefer Sysco for produce")
```

### Recommendation Engine

```python
from core.recommendation import RecommendationEngine

engine = RecommendationEngine()
engine.load_preferences()

# Get all recommendations
recommendations = engine.generate_order_guide()

# Compare vendors for specific item
comparison = engine.compare_vendors("Heavy Cream")
```

## Troubleshooting

### "Gemini API key not configured"
- Ensure `GOOGLE_API_KEY` is set in `.env`
- Get a key from [Google AI Studio](https://makersuite.google.com/app/apikey)

### "No valid session for Sysco"
- Run `python workers/web_scraper.py --refresh sysco`
- Log in manually when browser opens
- Session is saved for future runs

### Email not processing
- Check IMAP settings in `.env`
- For Gmail, enable "Less secure apps" or use App Passwords
- Verify email domain filters in `config.py`

### Prices not extracting correctly
- Use clear, high-resolution images
- Try different file formats (PDF, PNG, JPG)
- Check document isn't password-protected

## Development

### Running Tests
```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest tests/
```

Tests run automatically in CI (`.github/workflows/ci.yml`) on every push to
`master` and every pull request: ruff lint, a test matrix on Python 3.10/3.11
with coverage, and a Docker image build.

### Linting
```bash
ruff check .
```

### Code Structure
- `core/` - Pure Python, no dependencies on Streamlit
- `app/` - Streamlit-specific UI code
- `workers/` - Background task workers
- `tests/` - pytest suite; no network or API key required

## Security Notes

- **App access**: set `APP_PASSWORD` to require a password on every page.
  This is a single shared password with unlimited attempts - there is no
  lockout or rate limiting. That's a deliberate trade-off for a homelab
  deployment; put the app behind a VPN or reverse proxy with real auth if
  that isn't acceptable for your network.
- **Vendor email trust**: price-list ingestion trusts the sender's *domain*
  only (`sysco.com`, `usfoods.com`, exact/subdomain match). There is no
  DKIM/SPF verification - anyone who can spoof the sender address can have
  a PDF ingested as vendor pricing. Prefer a dedicated mailbox and review
  the processing log (Settings page).
- **Vendor credentials are not stored anywhere.** Vendor site sessions are
  created by manual browser login only.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make changes
4. Run tests
5. Submit pull request

## License

MIT License - See LICENSE file for details.

## Support

For issues and feature requests, please create a GitHub issue.

---

Built with ❤️ using Python, Streamlit, and Google Gemini AI
