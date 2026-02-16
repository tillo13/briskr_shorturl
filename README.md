# bris.kr - Privacy-First URL Shortener

> **🔗 [Try it now at bris.kr](https://bris.kr)** - Free URL shortener with no tracking and no ads.

[![Python](https://img.shields.io/badge/Python-3.11-blue.svg)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-3.0-green.svg)](https://flask.palletsprojects.com/)
[![GCP](https://img.shields.io/badge/GCP-App%20Engine-orange.svg)](https://cloud.google.com/appengine)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-blue.svg)](https://www.postgresql.org/)

## What is this?

Most URL shorteners charge for basic features or plaster your links with ads and tracking. I wanted something simple that just works, so I built **bris.kr**:

- ✅ **No tracking** - Clean redirects, no surveillance
- ✅ **No ads** - Just fast, simple links
- ✅ **Free to use** - Live at [bris.kr](https://bris.kr)
- ✅ **Open source** - Use mine or stand up your own

## Features

- 🚀 **Fast redirects** - Minimal latency
- 🎯 **Custom short codes** - Choose your own URL slug
- 📊 **Basic stats** - See how many clicks your links get
- 🌐 **Simple API** - Programmatic link creation

## How to Use

1. Visit **[bris.kr](https://bris.kr)**
2. Paste your long URL
3. Get a short link like `bris.kr/abc`
4. Share it!

## Tech Stack

Built to learn cloud infrastructure and web services:

- **Backend:** Python, Flask
- **Database:** PostgreSQL
- **Hosting:** Google Cloud Platform
- **Infrastructure:** Serverless auto-scaling

## Code

The full source code is here if you want to:
- See how it works
- Learn from the implementation
- Stand up your own instance

Key files:
- `app.py` - Main Flask application (~200 lines)
- `app.yaml` - Cloud deployment config
- `requirements.txt` - Python dependencies

## Use It

You're welcome to:
- **Use the live version** at [bris.kr](https://bris.kr) - it's free
- **Deploy your own** - all the code is here
- **Learn from it** - see how simple a URL shortener can be

I built this because I was tired of URL shorteners that charge for basic features or track every click. Sometimes you just need a simple tool that works.

---

**License:** Feel free to learn from this code. See individual files for implementation details.
