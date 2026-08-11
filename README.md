# 📈 Institutional Quantitative Trading Terminal (v8.0)
**By Ravi Ray Purohit**

A robust, cloud-ready, and mobile-responsive web application designed for quantitative stock analysis. This terminal fetches institutional-grade fundamental data, advanced technical indicators, and real-time live charts for both Indian (NSE/BSE) and US markets—all presented in a beautiful, zero-lag web interface.

---

## ✨ Key Features

* **🔴 Real-Time Live Charts:** Fully integrated TradingView Advanced Chart widget. *Note: Automatically routes Indian `.NS` (NSE) stocks to `.BO` (BSE) to intelligently bypass NSE's widget-embedding restrictions.*
* **🛡️ Anti-Block Data Engine:** Features a custom "Crumb & Cookie Manager" that silently bypasses Yahoo Finance's recent 403 Forbidden security blocks to scrape deep fundamental data without API keys.
* **🧠 AI Verdict Engine:** Evaluates 15+ technical and fundamental parameters (EMAs, MACD, RSI, CMF, Revenue Growth, ROE) to output a directional probability score (0-100) and actionable verdicts (e.g., STRONG BUY, HOLD, AVOID).
* **📊 Deep Technical & Fundamental Audit:** Displays dynamic OHLCV tables, ATR-based trade setups (Entry, Stop Loss, Targets), Analyst Consensus targets, and Institutional/Insider shareholding percentages.
* **🌓 Seamless UI/UX:** Fully responsive on desktop and mobile. Features a sticky navigation bar with timeframe selection and a persistent Light/Dark Mode toggle.
* **⚡ Zero-Dependency Frontend:** The UI is rendered using pure HTML, CSS, and Vanilla JS, powered by Python's built-in `http.server`. No heavy frameworks like React, Django, or Flask required.

---

## 🛠️ Tech Stack

* **Backend:** Python 3.x, `http.server` (Standard Library)
* **Data Processing:** `pandas`, `numpy`
* **Data Ingestion:** `yfinance` (v0.2.37), `requests`
* **Mathematical Plotting:** `plotly`
* **Frontend:** HTML5, CSS3, JavaScript (Vanilla)

---

## 🚀 Deployment Guide (100% Free Cloud Hosting)

To run this application 24/7 on the internet for free, deploy it using GitHub and Render.

### 1. Repository Setup
Create a new GitHub repository and upload two files:
1. `main.py` (The main application code)
2. `requirements.txt` containing exactly:
```text
pandas
numpy
yfinance==0.2.37
plotly
requests
