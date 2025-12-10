# Quick Start

## Running the Application in 3 Steps

1. **Activate the virtual environment:**

```bash
source venv/bin/activate  # Linux/Mac
# or
venv\Scripts\activate  # Windows
```

2. **Install dependencies:**

```bash
pip install -r requirements.txt
```

3. **Start the application:**

```bash
python app.py
```

4. **Open in your browser:**

```
http://localhost:8080
```

## Usage Examples

Enter a stock ticker in the search field, for example:

* `SBER` — Sberbank
* `GAZP` — Gazprom
* `YNDX` — Yandex
* `LKOH` — Lukoil

## Important Notes

* On first run, a SQLite database `moex_data.db` will be created.
* Neural network predictions require at least 60 historical candles for accurate results.
* If TA-Lib is not installed, technical indicators will be calculated in a simplified form.

## Troubleshooting

**TA-Lib Import Error:**

* Ensure the system library is installed (see README.md for instructions).
* The application will still function with simplified indicators if TA-Lib is unavailable.

**Connection Issues with MOEX API:**

* Check your internet connection.
* The MOEX API may be temporarily unavailable.

**No Data for a Stock:**

* Verify that the ticker symbol is correct.
* Some stocks may not be available through the API.


