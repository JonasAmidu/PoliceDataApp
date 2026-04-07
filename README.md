# PoliceDataApp

> Python data pipeline & web interface for the UK Police Data API — automated extraction, transformation, and RESTful delivery.

A Flask-based web application that consumes the [UK Police Data API](https://data.police.uk/docs/) and presents it through a clean, user-friendly interface. Built with Python, Flask, Pandas, and REST API best practices.

## 🎯 Project Overview

- **Data source**: UK Police Data API (data.police.uk)
- **Purpose**: Make UK police data more accessible and easier to query
- **Stack**: Python · Flask · Pandas · REST API · HTML/CSS/JavaScript
- **Pipeline**: Data extraction → transformation → serving via API endpoints

## 📡 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/forces` | List all police forces |
| GET | `/api/forces/<force_id>` | Get force details |
| GET | `/api/forces/<force_id>/people` | Get force personnel |
| GET | `/api/crime-categories` | List crime categories |
| GET | `/api/crimes/street?lat=&lng=` | Crimes near location |
| GET | `/api/stop-search/street` | Stop-and-search records |

## 🔧 Technical Features

- **Flask REST API** — structured endpoint routing with error handling
- **Pandas** — data transformation and cleaning
- **Police Data API integration** — external API consumption with request handling
- **Jinja2 templates** — server-side rendered frontend
- **Modular architecture** — `utils/police_api.py`, `config.py`, `feature_manager.py`

## 📂 Key Files

```
PoliceDataApp/
├── app.py              # Flask application entry point
├── config.py           # Configuration management
├── utils/
│   └── police_api.py   # Police Data API client
├── templates/          # Jinja2 HTML templates
├── static/             # CSS & JS assets
└── requirements.txt    # Python dependencies
```

## 🚀 Local Setup

```bash
git clone https://github.com/JonasAmidu/PoliceDataApp.git
cd PoliceDataApp
pip install -r requirements.txt
python app.py
# App runs at http://localhost:5000
```

## 🛠️ Tech Stack

<div>

| Component | Technology |
|-----------|------------|
| Backend | Python 3, Flask |
| Data processing | Pandas, Requests |
| API | RESTful Flask routes |
| Frontend | HTML, CSS, JavaScript |
| Templates | Jinja2 |
| Server | Flask dev server (prod: gunicorn) |

</div>

## 👤 Author

**Jonas Amidu** — [github.com/JonasAmidu](https://github.com/JonasAmidu) · jonasamidu@gmail.com

MIT License
