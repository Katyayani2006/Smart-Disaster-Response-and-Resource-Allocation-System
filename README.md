# Smart Disaster Response & Resource Allocation System

A Flask web application that helps a control room prioritise disaster incidents and send the nearest available resources to them, with instant SMS/WhatsApp alerts for on-call officers.

## Features
- **ML priority prediction**: a Random Forest classifier (scikit-learn) predicts incident priority (LOW / MEDIUM / HIGH / CRITICAL) from severity, people affected, damage, accessibility and previous incidents.
- **Urgency scoring**: priority, severity and people affected combine into a transparent 0-100 score with a visible breakdown.
- **Resource allocation engine**: open incidents are sorted by urgency and matched greedily to the nearest available resource using haversine distance; stock levels update automatically.
- **Live map dashboard**: Leaflet map of incidents and resources, allocation history, and a printable command report.
- **Citizen SOS page**: the public can report an emergency, and officers are alerted straight away.
- **Role-based access**: admin, officer and viewer accounts with hashed passwords.
- **Alerts (Twilio)**: SMS and WhatsApp alerts to on-call officers. Without Twilio keys the app runs in simulation mode and logs alerts instead.

## Tech Stack
Python, Flask, scikit-learn, pandas, joblib, Leaflet, Twilio, OpenStreetMap Nominatim (geocoding)

## Getting Started
```bash
git clone https://github.com/Katyayani2006/Smart-Disaster-Response-and-Resource-Allocation-System.git
cd Smart-Disaster-Response-and-Resource-Allocation-System
python -m venv venv
venv\Scripts\activate           # Mac/Linux: source venv/bin/activate
pip install -r requirements.txt

copy .env.example .env          # Mac/Linux: cp .env.example .env
# then set ADMIN_API_KEY and FLASK_SECRET_KEY in .env

python train_model.py           # optional: retrain the model
python app.py
```
Open http://127.0.0.1:5000

Demo accounts are created on first run (`admin`, `officer1`, `viewer1`). Change these passwords before any real use.

## Project Structure
```
app.py                    Flask routes, urgency score, allocation engine
notifications.py          Twilio SMS / WhatsApp alerts (with simulation mode)
train_model.py            Trains the Random Forest priority model
disaster_dataset.csv      Training data
models/                   Saved model (disaster_model.pkl)
templates/  static/       Frontend pages, CSS, JS
data/                     Incident, resource and officer data (JSON)
test_system_integrity.py  Integration checks
```

## Author
Katyayani Sathua - [LinkedIn](https://www.linkedin.com/in/katyayani-sathua-2a2b73337)
