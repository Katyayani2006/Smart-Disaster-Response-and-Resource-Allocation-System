from pathlib import Path
import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

Path("models").mkdir(parents=True, exist_ok=True)

csv_path = Path("disaster_dataset.csv")
if csv_path.exists() and csv_path.stat().st_size > 0:
    df = pd.read_csv(csv_path)
    required_columns = {"severity", "people", "damage", "accessibility", "previous", "priority"}
    if not required_columns.issubset(df.columns):
        print("Dataset file missing required columns. Falling back to built-in sample data.")
        df = None
else:
    df = None

if df is None:
    data = {
        "severity": [2, 3, 4, 5, 6, 7, 8, 9, 10, 5, 8, 9],
        "people": [100, 300, 500, 800, 1200, 2000, 3000, 4500, 6000, 1000, 3500, 5000],
        "damage": [1, 2, 3, 4, 6, 7, 8, 9, 10, 5, 8, 9],
        "accessibility": [9, 8, 7, 6, 5, 4, 3, 2, 1, 6, 3, 2],
        "previous": [0, 0, 1, 1, 2, 2, 3, 3, 4, 2, 3, 4],
        "priority": [
            "LOW",
            "LOW",
            "MEDIUM",
            "MEDIUM",
            "HIGH",
            "HIGH",
            "HIGH",
            "CRITICAL",
            "CRITICAL",
            "MEDIUM",
            "HIGH",
            "CRITICAL",
        ],
    }
    df = pd.DataFrame(data)

X = df[["severity", "people", "damage", "accessibility", "previous"]]
y = df["priority"]

model = RandomForestClassifier(n_estimators=150, random_state=42)
model.fit(X, y)

model_path = Path("models") / "disaster_model.pkl"
joblib.dump(model, model_path)
print("===================================")
print(f"Model trained successfully and saved to: {model_path}")
print("===================================")
