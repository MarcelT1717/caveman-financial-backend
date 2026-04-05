from fastapi import APIRouter, HTTPException
from typing import List, Optional
import yfinance as yf
import requests
from pydantic import BaseModel
import logging
import time

router = APIRouter()
logger = logging.getLogger(__name__)

# Simple in-memory cache: { cache_key: (timestamp, data) }
_cache = {}
CACHE_TTL = 60  # seconds

def _cache_get(key):
    entry = _cache.get(key)
    if entry and (time.time() - entry[0]) < CACHE_TTL:
        return entry[1]
    return None

def _cache_set(key, data):
    _cache[key] = (time.time(), data)

class StockData(BaseModel):
    ticker: str
    name: str
    price: float
    change_percent: float
    volume: Optional[int] = 0
    market_cap: Optional[str] = "N/A"

class StockQuote(BaseModel):
    ticker: str
    price: float
    change_percent: float

def format_market_cap(value):
    """Format market cap to B or M"""
    if value is None or value == 0:
        return "N/A"
    if value >= 1e9:
        return f"${value/1e9:.1f}B"
    elif value >= 1e6:
        return f"${value/1e6:.1f}M"
    else:
        return f"${value:.0f}"

def format_volume(value):
    """Format volume to M or K"""
    if value is None or value == 0:
        return "N/A"
    if value >= 1e6:
        return f"{value/1e6:.1f}M"
    elif value >= 1e3:
        return f"{value/1e3:.1f}K"
    else:
        return f"{value}"

@router.get("/stocks/quote/{ticker}", response_model=StockQuote)
async def get_stock_quote(ticker: str):
    """Get real-time stock quote for a single ticker"""
    cache_key = f"quote:{ticker.upper()}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    try:
        url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}"

        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, headers=headers)

        data = response.json()

        result = data["chart"]["result"][0]["meta"]

        price = result["regularMarketPrice"]
        previous = result["chartPreviousClose"]

        change_percent = ((price - previous) / previous) * 100

        quote = StockQuote(
            ticker=ticker.upper(),
            price=round(price, 2),
            change_percent=round(change_percent, 2)
        )
        _cache_set(cache_key, quote)
        return quote

    except Exception as e:
        logger.error(f"Error fetching quote for {ticker}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch data for {ticker}")

@router.get("/stocks/details/{ticker}", response_model=StockData)
async def get_stock_details(ticker: str):
    """Get detailed stock information including volume and market cap"""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        
        current_price = info.get('currentPrice') or info.get('regularMarketPrice', 0)
        previous_close = info.get('previousClose', current_price)
        
        if previous_close and previous_close != 0:
            change_percent = ((current_price - previous_close) / previous_close) * 100
        else:
            change_percent = 0
        
        volume = info.get('volume', 0)
        market_cap = info.get('marketCap', 0)
        
        return StockData(
            ticker=ticker.upper(),
            name=info.get('longName', ticker.upper()),
            price=round(current_price, 2),
            change_percent=round(change_percent, 2),
            volume=volume,
            market_cap=format_market_cap(market_cap)
        )
    except Exception as e:
        logger.error(f"Error fetching details for {ticker}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch data for {ticker}")

@router.post("/stocks/batch", response_model=List[StockQuote])
async def get_batch_quotes(tickers: List[str]):
    """Get real-time quotes for multiple tickers"""
    tickers = [t.upper() for t in tickers]
    cache_key = f"batch:{','.join(sorted(tickers))}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    results = []

    # Primary: yf.download — single HTTP call for all tickers, most reliable
    try:
        raw = yf.download(
            tickers=" ".join(tickers),
            period="5d",
            interval="1d",
            progress=False,
            auto_adjust=True,
        )

        # Normalise columns: single ticker returns a flat Series, multi returns a DataFrame
        if len(tickers) == 1:
            closes = raw["Close"].dropna()
            if len(closes) >= 2:
                price = float(closes.iloc[-1])
                prev  = float(closes.iloc[-2])
                results.append(StockQuote(
                    ticker=tickers[0],
                    price=round(price, 2),
                    change_percent=round((price - prev) / prev * 100, 2)
                ))
        else:
            close_df = raw["Close"]
            for ticker in tickers:
                try:
                    col = close_df[ticker].dropna()
                    if len(col) >= 2:
                        price = float(col.iloc[-1])
                        prev  = float(col.iloc[-2])
                        results.append(StockQuote(
                            ticker=ticker,
                            price=round(price, 2),
                            change_percent=round((price - prev) / prev * 100, 2)
                        ))
                except Exception as e:
                    logger.warning(f"download skip {ticker}: {e}")

        if results:
            _cache_set(cache_key, results)
            return results
    except Exception as e:
        logger.warning(f"yf.download failed: {e}")

    # Fallback: individual history calls (slower but reliable)
    for ticker in tickers:
        try:
            hist = yf.Ticker(ticker).history(period="5d")
            if len(hist) >= 2:
                price = float(hist["Close"].iloc[-1])
                prev  = float(hist["Close"].iloc[-2])
                results.append(StockQuote(
                    ticker=ticker,
                    price=round(price, 2),
                    change_percent=round((price - prev) / prev * 100, 2)
                ))
        except Exception as e:
            logger.warning(f"history fallback skip {ticker}: {e}")

    if results:
        _cache_set(cache_key, results)
        return results

    # Last resort: Yahoo Finance API with session cookie
    try:
        symbols = ",".join(tickers)
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json",
        })
        session.get("https://finance.yahoo.com/", timeout=10)
        url = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={symbols}"
        response = session.get(url, timeout=15)
        data = response.json()
        for stock in data["quoteResponse"]["result"]:
            results.append(StockQuote(
                ticker=stock["symbol"],
                price=round(stock["regularMarketPrice"], 2),
                change_percent=round(stock["regularMarketChangePercent"], 2)
            ))
        _cache_set(cache_key, results)
        return results
    except Exception as e:
        logger.error(f"Batch fallback also failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch batch quotes")
    