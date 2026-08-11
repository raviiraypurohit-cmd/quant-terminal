# ==============================================================================
# 🇮🇳 INSTITUTIONAL QUANTITATIVE TRADING TERMINAL v8.0 (Cloud Edition)
# Features: Mobile Responsive, Cloud-Ready (0.0.0.0 Bind), Theme Toggle
# ==============================================================================

import sys
import time
import math
import traceback
import os
import http.server
import socketserver
from urllib.parse import urlparse, parse_qs
from datetime import datetime
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests

# ==============================================================================
# CONFIG & UTILS
# ==============================================================================
class Config:
    CACHE_EXPIRY = 300
    TF_MAPPING = {"1mo": 22, "3mo": 65, "6mo": 130, "1y": 252, "2y": 504, "5y": 1260, "max": 5000}

class Utils:
    @staticmethod
    def safe_div(numerator, denominator, fallback=0.0):
        try:
            result = numerator / denominator
            if isinstance(result, pd.Series):
                result = result.copy()
                result[(result == np.inf) | (result == -np.inf)] = np.nan
                return result.fillna(fallback)
            if pd.isna(result) or result == float('inf') or result == float('-inf'): return fallback
            return result
        except: return fallback

    @staticmethod
    def fmt(val, is_curr=True, is_pct=False, crores=False):
        if val is None or pd.isna(val) or val == float('inf') or val == float('-inf') or val == 0 or val == "N/A": return "N/A"
        try:
            val = float(val)
            if is_pct: return f"{val*100:+.2f}%" if abs(val) < 1.5 else f"{val:+.2f}%"
            if crores: return f"₹{val/10000000:,.2f} Cr"
            if is_curr: return f"₹{val:,.2f}" if val > 1 else f"${val:,.2f}"
            return f"{val:,.2f}"
        except: return str(val)

# ==============================================================================
# DATA ENGINE (WITH CRUMB MANAGER)
# ==============================================================================
class DataEngine:
    _cache = {}

    @classmethod
    def get_session_and_crumb(cls, symbol):
        session = requests.Session()
        session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
        crumb = ""
        try:
            try: session.get("https://fc.yahoo.com", timeout=3)
            except: session.get(f"https://finance.yahoo.com/quote/{symbol}", timeout=3)
            res = session.get("https://query1.finance.yahoo.com/v1/test/getcrumb", timeout=3)
            if res.status_code == 200: crumb = res.text.strip()
        except: pass
        return session, crumb

    @classmethod
    def direct_api_fallback(cls, symbol, period):
        session, crumb = cls.get_session_and_crumb(symbol)
        
        chart_url = f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}?range={period}&interval=1d"
        if crumb: chart_url += f"&crumb={crumb}"
        res = session.get(chart_url)
        
        if res.status_code != 200 or not res.json().get('chart', {}).get('result'):
            if not symbol.endswith('.NS'):
                symbol = f"{symbol}.NS"
                chart_url = f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}?range={period}&interval=1d"
                if crumb: chart_url += f"&crumb={crumb}"
                res = session.get(chart_url)
                if res.status_code != 200: return pd.DataFrame(), {}, symbol
            else: return pd.DataFrame(), {}, symbol
                
        data = res.json()
        result = data['chart']['result'][0]
        quote = result['indicators']['quote'][0]
        
        df = pd.DataFrame({
            'Open': quote.get('open', []), 'High': quote.get('high', []),
            'Low': quote.get('low', []), 'Close': quote.get('close', []),
            'Volume': quote.get('volume', [])
        })
        df.index = pd.to_datetime(result['timestamp'], unit='s')
        df.dropna(inplace=True)
        
        info = {'longName': symbol}
        try:
            quote_url = f"https://query2.finance.yahoo.com/v7/finance/quote?symbols={symbol}"
            if crumb: quote_url += f"&crumb={crumb}"
            q_res = session.get(quote_url).json()['quoteResponse']['result'][0]
            info.update({
                'longName': q_res.get('longName', symbol), 'exchange': q_res.get('fullExchangeName', 'N/A'),
                'marketCap': q_res.get('marketCap', 0), 'fiftyTwoWeekHigh': q_res.get('fiftyTwoWeekHigh', 0),
                'fiftyTwoWeekLow': q_res.get('fiftyTwoWeekLow', 0), 'trailingPE': q_res.get('trailingPE', 0),
                'dividendYield': q_res.get('trailingAnnualDividendYield', 0), 'currentPrice': q_res.get('regularMarketPrice', df['Close'].iloc[-1])
            })
        except: pass
            
        try:
            summary_url = f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol}?modules=financialData,defaultKeyStatistics,majorHoldersBreakdown"
            if crumb: summary_url += f"&crumb={crumb}"
            sum_res = session.get(summary_url).json()['quoteSummary']['result'][0]
            
            fd = sum_res.get('financialData', {})
            info.update({
                'revenueGrowth': fd.get('revenueGrowth', {}).get('raw', None),
                'earningsGrowth': fd.get('earningsGrowth', {}).get('raw', None),
                'returnOnEquity': fd.get('returnOnEquity', {}).get('raw', None),
                'debtToEquity': fd.get('debtToEquity', {}).get('raw', None),
                'targetMeanPrice': fd.get('targetMeanPrice', {}).get('raw', None),
                'recommendationKey': fd.get('recommendationKey', 'N/A')
            })
            
            mhb = sum_res.get('majorHoldersBreakdown', {})
            info['heldPercentInsiders'] = mhb.get('insidersPercentHeld', {}).get('raw', None)
            info['heldPercentInstitutions'] = mhb.get('institutionsPercentHeld', {}).get('raw', None)
        except: pass
            
        return df, info, symbol

    @classmethod
    def fetch_data(cls, symbol: str, display_period: str = "1y"):
        symbol_clean = symbol.strip().upper()
        fetch_period = "5y" if display_period in ["2y", "5y", "max"] else "2y"
        cache_key = f"{symbol_clean}_{fetch_period}"

        if cache_key in cls._cache:
            data, timestamp = cls._cache[cache_key]
            if time.time() - timestamp < Config.CACHE_EXPIRY: return cls._slice_and_package(data, display_period)

        df = pd.DataFrame()
        info = {}

        try:
            session = requests.Session()
            session.headers.update({"User-Agent": "Mozilla/5.0"})
            stock = yf.Ticker(symbol_clean, session=session)
            df = stock.history(period=fetch_period)
            
            if df.empty and not symbol_clean.endswith('.NS'):
                symbol_clean = f"{symbol_clean}.NS"
                stock = yf.Ticker(symbol_clean, session=session)
                df = stock.history(period=fetch_period)

            if not df.empty:
                fast = getattr(stock, 'fast_info', {})
                try: info = stock.info or {}
                except: info = {}
                info['currentPrice'] = getattr(fast, 'lastPrice', info.get('currentPrice', df['Close'].iloc[-1]))
                info['marketCap'] = getattr(fast, 'marketCap', info.get('marketCap', 0))
        except: pass 

        if df is None or df.empty:
            df, info, symbol_clean = cls.direct_api_fallback(symbol_clean, fetch_period)

        if df.empty: raise ValueError(f"Ticker '{symbol}' not found. Check spelling.")

        df.index = pd.to_datetime(df.index)
        if df.index.tz is not None: df.index = df.index.tz_localize(None)

        latest_row = df.iloc[-1]
        if pd.isna(latest_row['Close']) or pd.isna(latest_row['High']) or pd.isna(latest_row['Low']) or latest_row['Volume'] == 0:
            df = df.iloc[:-1]

        df = df.ffill().bfill()
        if 'currentPrice' not in info or not info['currentPrice']: info['currentPrice'] = df['Close'].iloc[-1]

        raw_data = {"symbol": symbol_clean, "df": df, "info": info, "fast": {}}
        cls._cache[cache_key] = (raw_data, time.time())
        return cls._slice_and_package(raw_data, display_period)

    @classmethod
    def _slice_and_package(cls, raw_data, display_period):
        data = raw_data.copy()
        df = IndicatorEngine.compute_indicators(data['df'])
        data['info'] = FundamentalEngine.enrich_fundamentals(data['info'], data['fast'], df)
        limit = Config.TF_MAPPING.get(display_period, len(df))
        data['df'] = df.tail(limit)
        return data

class FundamentalEngine:
    @staticmethod
    def enrich_fundamentals(info: dict, fast, df: pd.DataFrame) -> dict:
        info = info.copy()
        fast_year_high = fast.get('yearHigh') if isinstance(fast, dict) else getattr(fast, 'yearHigh', None)
        fast_year_low = fast.get('yearLow') if isinstance(fast, dict) else getattr(fast, 'yearLow', None)

        if not info.get('fiftyTwoWeekHigh'): info['fiftyTwoWeekHigh'] = fast_year_high or df['High'].tail(252).max()
        if not info.get('fiftyTwoWeekLow'): info['fiftyTwoWeekLow'] = fast_year_low or df['Low'].tail(252).min()
        if not info.get('averageVolume'): info['averageVolume'] = int(df['Volume'].tail(20).mean())
        if not info.get('trailingPE') and info.get('trailingEps'):
            info['trailingPE'] = Utils.safe_div(info.get('currentPrice', 0), info['trailingEps'])
        return info

# ==============================================================================
# INDICATOR & VERDICT ENGINE
# ==============================================================================
class IndicatorEngine:
    @staticmethod
    def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        c, h, l, v = df['Close'], df['High'], df['Low'], df['Volume'].replace(0, 1)

        df['EMA9'] = c.ewm(span=9, adjust=False).mean()
        df['EMA21'] = c.ewm(span=21, adjust=False).mean()
        df['EMA50'] = c.ewm(span=50, adjust=False).mean()
        df['EMA200'] = c.ewm(span=200, adjust=False).mean()
        df['SMA20'] = c.rolling(20, min_periods=1).mean()
        df['Vol_20SMA'] = v.rolling(20, min_periods=1).mean()

        tp = (h + l + c) / 3.0
        df['VWAP'] = (tp * v).cumsum() / v.cumsum()

        std20 = c.rolling(20, min_periods=1).std().bfill()
        df['BB_Upper'] = df['SMA20'] + (std20 * 2)
        df['BB_Lower'] = df['SMA20'] - (std20 * 2)

        df['Swing_High'] = h.where(h == h.rolling(11, center=True).max(), np.nan)
        df['Swing_Low'] = l.where(l == l.rolling(11, center=True).min(), np.nan)
        df['Swing_Low_Val'] = df['Swing_Low'].ffill()

        delta = c.diff()
        gain = delta.where(delta > 0, 0.0).rolling(14, min_periods=1).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(14, min_periods=1).mean()
        rs = Utils.safe_div(gain, loss)
        df['RSI'] = 100 - (100 / (1 + rs))

        ema12 = c.ewm(span=12, adjust=False).mean()
        ema26 = c.ewm(span=26, adjust=False).mean()
        df['MACD'] = ema12 - ema26
        df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
        df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']

        rsi_min = df['RSI'].rolling(14, min_periods=1).min()
        rsi_max = df['RSI'].rolling(14, min_periods=1).max()
        stoch_rsi = Utils.safe_div(df['RSI'] - rsi_min, rsi_max - rsi_min)
        df['Stoch_RSI_K'] = stoch_rsi.rolling(3, min_periods=1).mean() * 100

        tr1, tr2, tr3 = h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df['ATR'] = tr.rolling(14, min_periods=1).mean()

        up_move, down_move = h - h.shift(1), l.shift(1) - l
        plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
        minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
        tr_smooth = tr.ewm(alpha=1/14, adjust=False).mean()
        plus_di = 100 * Utils.safe_div(plus_dm.ewm(alpha=1/14, adjust=False).mean(), tr_smooth)
        minus_di = 100 * Utils.safe_div(minus_dm.ewm(alpha=1/14, adjust=False).mean(), tr_smooth)
        dx = 100 * Utils.safe_div((plus_di - minus_di).abs(), (plus_di + minus_di))
        df['ADX'] = dx.ewm(alpha=1/14, adjust=False).mean()

        df['OBV'] = (np.sign(delta) * v).fillna(0).cumsum()
        mf_mult = Utils.safe_div((c - l) - (h - c), h - l)
        df['CMF'] = Utils.safe_div((mf_mult * v).rolling(20, min_periods=1).sum(), v.rolling(20, min_periods=1).sum())

        return df.ffill().bfill()

class VerdictEngine:
    @staticmethod
    def evaluate(df: pd.DataFrame, info: dict) -> dict:
        latest, prev = df.iloc[-1], df.iloc[-2]
        score = 0.0

        if latest['EMA9'] > latest['EMA21']: score += 7
        if latest['EMA21'] > latest['EMA50']: score += 7
        if latest['EMA50'] > latest['EMA200']: score += 6
        if latest['Close'] > latest['VWAP']: score += 5
        if 40 <= latest['RSI'] <= 65: score += 10
        if latest['MACD'] > latest['MACD_Signal']: score += 8
        if latest['MACD_Hist'] > prev['MACD_Hist']: score += 7
        if Utils.safe_div(latest['Volume'], latest['Vol_20SMA']) > 1.2: score += 8
        if latest['CMF'] > 0: score += 7
        if latest['Close'] > prev['High']: score += 8
        if latest['Low'] > prev['Low']: score += 7
        if (info.get('revenueGrowth') or 0) > 0: score += 5
        if (info.get('returnOnEquity') or 0) > 0.10: score += 5
        if 'buy' in str(info.get('recommendationKey', '')).lower(): score += 10

        score = min(100.0, max(0.0, score))
        prob_val = 30 + (score * 0.58)

        if score >= 85: verdict, stars, color = "STRONG BUY", "★★★★★", "#00c853"
        elif score >= 70: verdict, stars, color = "BUY", "★★★★☆", "#00e676"
        elif score >= 55: verdict, stars, color = "HOLD", "★★★☆☆", "#ffb300"
        elif score >= 40: verdict, stars, color = "WEAK", "★★☆☆☆", "#ff7043"
        else: verdict, stars, color = "AVOID", "★☆☆☆☆", "#ff5252"

        close, atr, swing_l = latest['Close'], latest['ATR'], latest['Swing_Low_Val']
        if pd.isna(swing_l) or swing_l > close or (close - swing_l) > (3 * atr): swing_l = close - (1.5 * atr)

        stop_loss = swing_l - (0.2 * atr)
        risk = close - stop_loss

        return {
            "score": int(score), "verdict": verdict, "stars": stars, "probability": f"{int(prob_val)}%", "color": color,
            "tech_score": int(score * 0.8), "fund_score": int(score * 1.1) if score < 90 else 98,
            "entry": close, "stop_loss": stop_loss, "target1": close + (1.5 * risk), "target2": close + (2.5 * risk)
        }

# ==============================================================================
# UI HTML ENGINE (MOBILE RESPONSIVE CSS INJECTED)
# ==============================================================================
class UIEngine:
    CSS = """
    <style>
        :root {
            --bg-body: #0b0e14; --bg-card: #151924; --bg-nav: #0b0e14; --bg-metric: #1c2130;
            --text-main: #e1e4ea; --text-muted: #848e9c; --border: #232733; --accent: #00f2fe;
            --brand-text: #ffffff; --brand-bg: linear-gradient(90deg, #00f2fe 0%, #4facfe 100%);
        }
        [data-theme="light"] {
            --bg-body: #f0f2f5; --bg-card: #ffffff; --bg-nav: #ffffff; --bg-metric: #f8f9fa;
            --text-main: #1a1d20; --text-muted: #5c6bc0; --border: #e0e4eb; --accent: #0056b3;
            --brand-text: #ffffff; --brand-bg: linear-gradient(90deg, #0056b3 0%, #00f2fe 100%);
        }
        * { box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: var(--bg-body); color: var(--text-main); margin: 0; padding: 0; transition: background-color 0.3s, color 0.3s; }
        .container { padding: 15px; max-width: 1400px; margin: 0 auto; }
        
        .brand-header { background: var(--brand-bg); color: var(--brand-text); text-align: center; padding: 12px; font-size: 16px; font-weight: 800; letter-spacing: 1.5px; box-shadow: 0 2px 10px rgba(0,0,0,0.2); }
        .nav-bar { background: var(--bg-nav); padding: 15px; border-bottom: 2px solid var(--border); display: flex; gap: 10px; justify-content: center; align-items: center; position: sticky; top: 0; z-index: 1000; flex-wrap: wrap;}
        .nav-bar input, .nav-bar select { padding: 10px; border-radius: 6px; border: 1px solid var(--border); background: var(--bg-metric); color: var(--text-main); font-size: 14px; outline: none; }
        .nav-bar input { flex: 1; max-width: 250px; min-width: 150px; }
        .nav-bar button.action-btn { padding: 10px 20px; border-radius: 6px; border: none; background: #00f2fe; color: #0b0e14; font-size: 14px; font-weight: bold; cursor: pointer; }
        .nav-bar button.theme-btn { padding: 10px 15px; border-radius: 6px; border: 1px solid var(--border); background: var(--bg-metric); color: var(--text-main); font-size: 16px; cursor: pointer; }
        
        .flex-container { display: flex; flex-wrap: wrap; gap: 15px; margin-bottom: 15px; }
        .flex-item { flex: 1 1 300px; }
        .flex-large { flex: 2 1 600px; }
        .card { background: var(--bg-card); border: 1px solid var(--border); border-radius: 8px; padding: 16px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); margin-bottom:15px; }
        .header-bar { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; border-bottom: 2px solid var(--border); padding-bottom: 12px; margin-bottom: 15px; gap: 10px; }
        .ticker-title { font-size: 24px; font-weight: 700; color: var(--accent); margin: 0; }
        .badge-pos { background: rgba(0,200,83,0.15); color: #00c853; padding: 4px 8px; border-radius: 4px; font-weight: 600; display: inline-block;}
        .badge-neg { background: rgba(255,82,82,0.15); color: #ff5252; padding: 4px 8px; border-radius: 4px; font-weight: 600; display: inline-block;}
        
        .metric-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 10px; }
        .metric-item { background: var(--bg-metric); padding: 10px; border-radius: 6px; }
        .metric-label { font-size: 11px; color: var(--text-muted); text-transform: uppercase; font-weight: 600; }
        .metric-value { font-size: 14px; font-weight: 600; color: var(--text-main); margin-top: 4px; }
        .section-title { font-size: 13px; text-transform: uppercase; color: var(--accent); border-left: 3px solid var(--accent); padding-left: 8px; margin-bottom: 12px; font-weight: 700; }
        
        .table-responsive { overflow-x: auto; width: 100%; }
        .quant-table { width: 100%; border-collapse: collapse; font-size: 12px; min-width: 600px; }
        .quant-table th { background: var(--bg-metric); color: var(--text-muted); text-align: left; padding: 10px; border-bottom: 1px solid var(--border);}
        .quant-table td { padding: 10px; border-bottom: 1px solid var(--border); }
        
        /* Mobile Specific Overrides */
        @media (max-width: 600px) {
            .header-bar { flex-direction: column; align-items: flex-start; }
            .header-bar > div { width: 100%; }
            .nav-bar { padding: 10px; }
            .nav-bar input { max-width: 100%; }
            .metric-grid { grid-template-columns: 1fr 1fr; }
        }
    </style>
    <script>
        function toggleTheme() {
            const body = document.documentElement;
            const currentTheme = body.getAttribute('data-theme') || 'dark';
            const newTheme = currentTheme === 'light' ? 'dark' : 'light';
            body.setAttribute('data-theme', newTheme);
            localStorage.setItem('theme', newTheme);
            window.dispatchEvent(new Event('themeChanged')); 
        }
        document.addEventListener('DOMContentLoaded', () => {
            const savedTheme = localStorage.getItem('theme') || 'dark';
            document.documentElement.setAttribute('data-theme', savedTheme);
        });
    </script>
    """

    @classmethod
    def build_nav_bar(cls, current_ticker="", current_tf="1y"):
        tfs = ["1mo", "3mo", "6mo", "1y", "2y", "5y", "max"]
        options = "".join([f'<option value="{tf}" {"selected" if tf == current_tf else ""}>{tf}</option>' for tf in tfs])
        return f"""
        <div class="brand-header">BY RAVI RAY PUROHIT</div>
        <form class="nav-bar" method="GET" action="/">
            <input type="text" name="ticker" placeholder="Ticker (e.g. RELIANCE)" value="{current_ticker}" required>
            <select name="tf">{options}</select>
            <button type="submit" class="action-btn">Analyze</button>
            <button type="button" class="theme-btn" onclick="toggleTheme()" title="Toggle Theme">🌓</button>
        </form>
        """

    @classmethod
    def build_landing_page(cls):
        return f"""
        <!DOCTYPE html><html lang="en" data-theme="dark"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Quant Dashboard by Ravi Ray Purohit</title>{cls.CSS}</head>
        <body>{cls.build_nav_bar()}
        <div class="container"><div style="text-align:center; padding: 50px; color:var(--text-muted);"><h2>📈 Terminal Ready</h2><p>Enter a ticker symbol above to pull live market data.</p></div></div>
        </body></html>
        """

    @classmethod
    def build_error_page(cls, error_text, current_ticker):
        return f"""
        <!DOCTYPE html><html lang="en" data-theme="dark"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Error</title>{cls.CSS}</head>
        <body>{cls.build_nav_bar(current_ticker)}
        <div class="container"><div style="background: rgba(255,82,82,0.15); color: #ff5252; padding: 20px; border-radius: 8px; text-align: center; border: 1px solid #ff5252;"><h2>❌ Processing Error</h2><p>{error_text}</p></div></div>
        </body></html>
        """

    @classmethod
    def build_live_chart(cls, symbol):
        tv_sym = symbol
        if symbol.endswith(".NS") or symbol.endswith(".BO"):
            tv_sym = f"BSE:{symbol.replace('.NS', '').replace('.BO', '')}"
            
        return f"""
        <div class="card">
            <div class="section-title">🔴 LIVE REAL-TIME CHART</div>
            <div class="tradingview-widget-container" style="height: 450px; width: 100%;">
              <div id="tv_chart" style="height: 100%; width: 100%;"></div>
              <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
              <script type="text/javascript">
                function renderTVChart() {{
                    let theme = document.documentElement.getAttribute('data-theme') || 'dark';
                    document.getElementById('tv_chart').innerHTML = ""; 
                    new TradingView.widget({{"autosize": true,"symbol": "{tv_sym}","interval": "5","timezone": "Asia/Kolkata","theme": theme,"style": "1","locale": "en","enable_publishing": false,"backgroundColor": theme === 'light' ? "#ffffff" : "#151924","gridColor": theme === 'light' ? "#e0e4eb" : "#232733","hide_top_toolbar": false,"save_image": false,"container_id": "tv_chart"}});
                }}
                document.addEventListener('DOMContentLoaded', renderTVChart);
                window.addEventListener('themeChanged', renderTVChart);
              </script>
            </div>
        </div>
        """

    @classmethod
    def build_header(cls, info, latest, prev, symbol):
        curr_price, prev_close = latest['Close'], prev['Close']
        change_pct = Utils.safe_div(curr_price - prev_close, prev_close) * 100
        return f"""
        <div class="card">
            <div class="header-bar">
                <div>
                    <h1 class="ticker-title">{info.get('longName', symbol)} ({symbol})</h1>
                    <span style="color:var(--text-muted); font-size:12px;">{info.get('exchange', 'NSE')} | {info.get('sector', 'N/A')}</span>
                </div>
                <div style="text-align: right;">
                    <div style="font-size: 28px; font-weight: 700;">{Utils.fmt(curr_price)}</div>
                    <span class="{ 'badge-pos' if change_pct >= 0 else 'badge-neg' }">{change_pct:+.2f}% ({curr_price - prev_close:+.2f})</span>
                </div>
            </div>
            <div class="metric-grid">
                <div class="metric-item"><div class="metric-label">Prev Close</div><div class="metric-value">{Utils.fmt(prev_close)}</div></div>
                <div class="metric-item"><div class="metric-label">Day Range</div><div class="metric-value">{Utils.fmt(latest['Low'])} - {Utils.fmt(latest['High'])}</div></div>
                <div class="metric-item"><div class="metric-label">52W High</div><div class="metric-value">{Utils.fmt(info.get('fiftyTwoWeekHigh'))}</div></div>
                <div class="metric-item"><div class="metric-label">Market Cap</div><div class="metric-value">{Utils.fmt(info.get('marketCap'), crores=True)}</div></div>
                <div class="metric-item"><div class="metric-label">Trailing P/E</div><div class="metric-value">{Utils.fmt(info.get('trailingPE'), False)}</div></div>
                <div class="metric-item"><div class="metric-label">Div Yield</div><div class="metric-value">{Utils.fmt(info.get('dividendYield', 0)*100, False)}%</div></div>
                <div class="metric-item"><div class="metric-label">Avg Volume</div><div class="metric-value">{info.get('averageVolume', 0):,}</div></div>
            </div>
        </div>
        """

    @classmethod
    def build_verdict(cls, verdict):
        return f"""
        <div class="card flex-item" style="border-top: 4px solid {verdict['color']}; text-align:center;">
            <div class="section-title" style="text-align:left;">AI VERDICT ENGINE</div>
            <div style="font-size: 32px; font-weight: 800; color: {verdict['color']};">{verdict['stars']}</div>
            <div style="font-size: 22px; font-weight: 800; padding: 10px; border-radius: 6px; margin: 10px 0; background: {verdict['color']}22; color: {verdict['color']};">{verdict['verdict']}</div>
            <div style="font-size: 13px; color: var(--text-muted); margin-bottom: 12px;">Score: <strong>{verdict['score']}/100</strong> | Win Prob: <strong>{verdict['probability']}</strong></div>
            <div class="metric-grid" style="grid-template-columns: repeat(2, 1fr); margin-top: 10px;">
                <div class="metric-item"><div class="metric-label">Tech Score</div><div class="metric-value">{verdict['tech_score']}</div></div>
                <div class="metric-item"><div class="metric-label">Fund Score</div><div class="metric-value">{verdict['fund_score']}</div></div>
            </div>
            <div style="text-align: left; margin-top: 15px; border-top: 1px solid var(--border); padding-top: 10px;">
                <div style="font-size:11px; color:var(--text-muted); margin-bottom:4px;">ATR TRADE SETUP</div>
                <div style="font-size:12px; display:flex; justify-content:space-between; margin-bottom:3px;"><span>Entry:</span> <strong>{Utils.fmt(verdict['entry'])}</strong></div>
                <div style="font-size:12px; display:flex; justify-content:space-between; margin-bottom:3px;"><span>Stop Loss:</span> <strong style="color:#ff5252;">{Utils.fmt(verdict['stop_loss'])}</strong></div>
                <div style="font-size:12px; display:flex; justify-content:space-between;"><span>Target:</span> <strong style="color:#00c853;">{Utils.fmt(verdict['target1'])}</strong></div>
            </div>
        </div>
        """

    @classmethod
    def build_tech_panel(cls, latest):
        return f"""
        <div class="card flex-large">
            <div class="section-title">TECHNICAL & MOMENTUM BREAKDOWN</div>
            <div class="metric-grid" style="grid-template-columns: repeat(auto-fit, minmax(110px, 1fr));">
                <div class="metric-item"><div class="metric-label">RSI (14)</div><div class="metric-value">{Utils.fmt(latest['RSI'], False)}</div></div>
                <div class="metric-item"><div class="metric-label">MACD</div><div class="metric-value">{Utils.fmt(latest['MACD'], False)}</div></div>
                <div class="metric-item"><div class="metric-label">Stoch %K</div><div class="metric-value">{Utils.fmt(latest['Stoch_RSI_K'], False)}</div></div>
                <div class="metric-item"><div class="metric-label">ADX</div><div class="metric-value">{Utils.fmt(latest['ADX'], False)}</div></div>
                <div class="metric-item"><div class="metric-label">ATR (14)</div><div class="metric-value">{Utils.fmt(latest['ATR'])}</div></div>
                <div class="metric-item"><div class="metric-label">CMF</div><div class="metric-value">{Utils.fmt(latest['CMF'], False)}</div></div>
                <div class="metric-item"><div class="metric-label">Volume</div><div class="metric-value">{latest['Volume']:,}</div></div>
                <div class="metric-item"><div class="metric-label">Vol Ratio</div><div class="metric-value">{Utils.safe_div(latest['Volume'], latest['Vol_20SMA']):.2f}x</div></div>
            </div>
        </div>
        """

    @classmethod
    def build_funds(cls, info):
        return f"""
        <div class="flex-container">
            <div class="card flex-item">
                <div class="section-title">FUNDAMENTAL AUDIT</div>
                <div class="table-responsive">
                    <table class="quant-table">
                        <tr><td>Revenue Growth (YoY)</td><td><strong>{Utils.fmt(info.get('revenueGrowth'), is_pct=True)}</strong></td></tr>
                        <tr><td>Earnings Growth (YoY)</td><td><strong>{Utils.fmt(info.get('earningsGrowth'), is_pct=True)}</strong></td></tr>
                        <tr><td>Return on Equity (ROE)</td><td><strong>{Utils.fmt(info.get('returnOnEquity'), is_pct=True)}</strong></td></tr>
                        <tr><td>Debt to Equity Ratio</td><td><strong>{Utils.fmt(info.get('debtToEquity'), False)}</strong></td></tr>
                    </table>
                </div>
            </div>
            <div class="card flex-item">
                <div class="section-title">ANALYST CONSENSUS & SHAREHOLDING</div>
                <div class="table-responsive">
                    <table class="quant-table">
                        <tr><td>Consensus Rec</td><td><strong style="color:var(--accent);">{str(info.get('recommendationKey', 'N/A')).upper()}</strong></td></tr>
                        <tr><td>Mean Target</td><td><strong>{Utils.fmt(info.get('targetMeanPrice'))}</strong></td></tr>
                        <tr><td>Insiders Holding</td><td><strong>{Utils.fmt(info.get('heldPercentInsiders'), is_pct=True)}</strong></td></tr>
                        <tr><td>Institutions Holding</td><td><strong>{Utils.fmt(info.get('heldPercentInstitutions'), is_pct=True)}</strong></td></tr>
                    </table>
                </div>
            </div>
        </div>
        """

    @classmethod
    def render_plot_html(cls, df, symbol):
        fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.60, 0.20, 0.20])
        fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], increasing_line_color='#00c853', decreasing_line_color='#ff5252', showlegend=False), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['EMA9'], line=dict(color='#00f2fe', width=1), name='EMA 9'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['EMA50'], line=dict(color='#e040fb', width=1.2), name='EMA 50'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['EMA200'], line=dict(color='#ffffff', width=1.5), name='EMA 200'), row=1, col=1)

        colors = ['#00c853' if c >= o else '#ff5252' for c, o in zip(df['Close'], df['Open'])]
        fig.add_trace(go.Bar(x=df.index, y=df['Volume'], marker_color=colors, showlegend=False), row=2, col=1)

        fig.add_trace(go.Scatter(x=df.index, y=df['MACD'], line=dict(color='#00f2fe', width=1.2), name='MACD'), row=3, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['MACD_Signal'], line=dict(color='#ffab00', width=1.2), name='Signal'), row=3, col=1)

        fig.update_layout(template='plotly_dark', paper_bgcolor='#151924', plot_bgcolor='#151924', margin=dict(l=10, r=10, t=10, b=10), height=550, xaxis_rangeslider_visible=False)
        fig.update_xaxes(gridcolor='#232733', showgrid=True)
        fig.update_yaxes(gridcolor='#232733', showgrid=True)
        return fig.to_html(full_html=False, include_plotlyjs='cdn')

# ==============================================================================
# CLOUD-READY HTTP WEB SERVER
# ==============================================================================
class DashboardHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed_url = urlparse(self.path)
        
        if parsed_url.path == "/" or parsed_url.path == "/index.html":
            query_params = parse_qs(parsed_url.query)
            ticker = query_params.get('ticker', [''])[0].strip().upper()
            tf = query_params.get('tf', ['1y'])[0]

            if not ticker: html = UIEngine.build_landing_page()
            else:
                try:
                    data = DataEngine.fetch_data(ticker, tf)
                    df, info = data['df'], data['info']
                    latest, prev = df.iloc[-1], df.iloc[-2]
                    verdict = VerdictEngine.evaluate(df, info)

                    header_html = UIEngine.build_header(info, latest, prev, data['symbol'])
                    live_chart_html = UIEngine.build_live_chart(data['symbol'])
                    verdict_html = UIEngine.build_verdict(verdict)
                    tech_html = UIEngine.build_tech_panel(latest)
                    plot_html = UIEngine.render_plot_html(df, data['symbol'])
                    funds_html = UIEngine.build_funds(info)

                    recent_df = df.dropna(subset=['Close', 'Volume']).tail(5).iloc[::-1]
                    table_rows = "".join([f"<tr><td>{idx.strftime('%Y-%m-%d')}</td><td>{Utils.fmt(r['Open'])}</td><td>{Utils.fmt(r['High'])}</td><td>{Utils.fmt(r['Low'])}</td><td>{Utils.fmt(r['Close'])}</td><td>{int(r['Volume']):,}</td><td>{Utils.fmt(r['RSI'], False)}</td><td>{Utils.fmt(r['MACD'], False)}</td></tr>" for idx, r in recent_df.iterrows()])
                    
                    ohlcv_html = f"""
                    <div class="card">
                        <div class="section-title">RECENT OHLCV SNAPSHOT</div>
                        <div class="table-responsive">
                            <table class="quant-table">
                                <thead><tr><th>Date</th><th>Open</th><th>High</th><th>Low</th><th>Close</th><th>Volume</th><th>RSI</th><th>MACD</th></tr></thead>
                                <tbody>{table_rows}</tbody>
                            </table>
                        </div>
                    </div>
                    """

                    html = f"""
                    <!DOCTYPE html><html lang="en" data-theme="dark"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>{data['symbol']} Quant Dashboard</title>{UIEngine.CSS}</head>
                    <body>{UIEngine.build_nav_bar(ticker, tf)}
                        <div class="container">
                            {header_html}{live_chart_html} 
                            <div class="flex-container">{verdict_html}{tech_html}</div>
                            <div class="card" style="background:#151924; border-color:#232733;"><div class="section-title">ADVANCED TECHNICAL CHART</div>{plot_html}</div>
                            {funds_html}{ohlcv_html}
                        </div>
                    </body></html>
                    """
                except Exception as e:
                    error_trace = traceback.format_exc()
                    html = UIEngine.build_error_page(f"{str(e)}<br><pre style='color:var(--text-muted); font-size:10px; margin-top:10px;'>{error_trace}</pre>", ticker)

            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))
            return
        else:
            self.send_response(404)
            self.end_headers()

class ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True

if __name__ == "__main__":
    # DYNAMIC PORT: Render will inject its own port here.
    PORT = int(os.environ.get("PORT", 8050))
    print(f"Starting server on port {PORT}...")
    try:
        # BIND TO 0.0.0.0: Allows the cloud service to expose your app to the public internet.
        with ReusableTCPServer(("0.0.0.0", PORT), DashboardHandler) as httpd:
            httpd.serve_forever()
    except Exception as e:
        print(f"Failed to start server: {e}")
