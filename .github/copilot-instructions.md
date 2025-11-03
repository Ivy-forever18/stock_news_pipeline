# Copilot Instructions for Stock News Pipeline

## Project Overview

This is a stock news data pipeline project that collects and organizes stock-related news and economic events. The project is written in Python and includes modules for scraping financial data, processing news, and managing trading day bundles.

## Project Structure

```
stock_news_pipeline/
├── src/
│   ├── config/           # Configuration and settings
│   ├── data_sources/     # Data scrapers and collectors
│   │   ├── fomc_scraper.py       # Federal Reserve FOMC meeting scraper
│   │   ├── economic_events.py    # Economic events collector
│   │   └── stockbench_news.py    # Stock news loader
│   ├── pipelines/        # Data processing pipelines
│   │   └── news_pipeline.py      # Main and simplified pipeline implementations
│   └── utils/           # Utility functions and models
│       ├── trading_calendar.py   # Trading day calculations
│       └── data_models.py        # Data models (NewsItem, EconomicEvent, etc.)
├── data/
│   ├── raw/             # Raw data storage
│   ├── processed/       # Processed data
│   └── outputs/         # Pipeline outputs (databases and JSON files)
├── run.py              # Main entry point
└── requirements.txt    # Python dependencies
```

## Environment Requirements

- **Python Version**: Python 3.11 (required for ecocal dependency)
- **Environment Setup**:
  ```bash
  conda create -n ecocal_py311 python=3.11
  conda activate ecocal_py311
  pip install -r requirements.txt
  ```

## Key Dependencies

- `requests` - HTTP requests for web scraping
- `beautifulsoup4` - HTML parsing
- `pandas` - Data manipulation
- `ecocal` - Economic calendar data (requires Python 3.11)
- `lxml` - XML/HTML parsing
- `pytest` - Testing framework

## Coding Standards

### Language and Comments
- The codebase uses **Chinese comments** (中文注释) for documentation
- Variable names and function names are in English
- Log messages can be in Chinese or English
- README and documentation are in Chinese

### Python Style
- Follow PEP 8 conventions
- Use type hints where appropriate
- Use descriptive variable names
- Keep functions focused and single-purpose
- Use logging instead of print statements

### Error Handling
- Always use try-except blocks for external API calls and file operations
- Log errors with appropriate context using the logging module
- Use `self.logger.error()` for errors and `self.logger.info()` for status updates
- Handle database connection failures gracefully

### Database Operations
- Use SQLite3 for data storage
- Always close database connections in finally blocks or use context managers
- Use parameterized queries to prevent SQL injection
- Tables:
  - `raw_news`: Stores all raw news and events
  - `trading_days`: Stores organized trading day bundles

## Pipeline Architecture

### Two Pipeline Versions

1. **NewsDataPipeline** (Full version):
   - Fetches FOMC meetings, economic events, and company news
   - Stores data in SQLite databases
   - Groups data by trading days
   - Use with `--no-simple` flag

2. **SimpleNewsDataPipeline** (Simplified version):
   - Minimal functionality for testing
   - Generates sample JSON output
   - Use with `--use-simple` flag (default)

### Data Flow

1. **Data Collection**:
   - FOMC meetings from Federal Reserve website
   - Economic events from ecocal library
   - Company news from StockBench data files

2. **Processing**:
   - Filter events by importance threshold
   - Adjust dates to trading days
   - Group by company and date

3. **Storage**:
   - Raw data → `raw_news.db`
   - Trading day bundles → `trading_day_collection.db`

## Running the Project

```bash
# Run with simplified pipeline (default)
python run.py

# Run with full pipeline
python run.py --no-simple

# Process specific number of days
python run.py --days 7

# Combination
python run.py --no-simple --days 30
```

## Testing

- Test framework: pytest
- Run tests with: `pytest`
- Tests should be added to a `tests/` directory when created
- Mock external API calls in tests

## Common Tasks

### Adding a New Data Source

1. Create a new scraper in `src/data_sources/`
2. Implement fetch methods that return NewsItem or EconomicEvent objects
3. Add initialization in NewsDataPipeline.__init__()
4. Integrate into the fetch methods
5. Update logging to track the new source

### Modifying Database Schema

1. Update table creation in `NewsDataPipeline.init_db()`
2. Update insert/query methods accordingly
3. Consider data migration for existing databases

### Adding Configuration

1. Add settings to `src/config/settings.py`
2. Use uppercase for constants
3. Group related settings together
4. Provide sensible defaults

## Important Notes

- **Trading Calendar**: The project uses a trading calendar to adjust dates to valid trading days
- **Data Deduplication**: News items use content hashes to prevent duplicates
- **Output Directory**: All outputs go to `data/outputs/`
- **Error Resilience**: Pipeline continues on individual component failures, logging errors

## File Operations

- Always use `pathlib.Path` for file paths (as shown in settings.py)
- Use `os.makedirs(directory, exist_ok=True)` to ensure directories exist
- Use UTF-8 encoding for JSON files: `json.dump(..., ensure_ascii=False)`

## When Making Changes

1. **Minimal Changes**: Make the smallest possible changes to achieve the goal
2. **Preserve Working Code**: Don't remove or modify working code unless necessary
3. **Test Changes**: Run the pipeline after making changes to verify functionality
4. **Chinese Comments**: Maintain Chinese comments when editing existing code
5. **Logging**: Add appropriate logging for new functionality
6. **Error Handling**: Always add try-except blocks for new external operations
