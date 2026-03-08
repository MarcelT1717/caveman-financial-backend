from fastapi import APIRouter, HTTPException
from typing import List, Optional
import yfinance as yf
import requests
from pydantic import BaseModel
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

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
    try:
        url = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={ticker}"
        
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, headers=headers)

        data = response.json()

        result = data["quoteResponse"]["result"][0]

        return StockQuote(
            ticker=ticker.upper(),
            price=round(result["regularMarketPrice"], 2),
            change_percent=round(result["regularMarketChangePercent"], 2)
        )

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
    try:
        symbols = ",".join(tickers)

        url = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={symbols}"
        response = requests.get(url)
        data = response.json()

        results = []

        for stock in data["quoteResponse"]["result"]:
            results.append(
                StockQuote(
                    ticker=stock["symbol"],
                    price=round(stock["regularMarketPrice"], 2),
                    change_percent=round(stock["regularMarketChangePercent"], 2)
                )
            )

        return results

    except Exception as e:
        logger.error(f"Batch fetch error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch batch quotes")
    