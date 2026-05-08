import os
import smtplib
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
from dotenv import load_dotenv

load_dotenv()

REDASH_API_KEY_923 = os.environ["REDASH_API_KEY_923"]
REDASH_API_KEY_924 = os.environ["REDASH_API_KEY_924"]
GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
ALERT_EMAIL = os.environ["ALERT_EMAIL"]

TODAY_STR = date.today().strftime("%Y-%m-%d")


def fetch_row_count(query_id: int, api_key: str) -> int:
    url = f"https://omniview.mytrudoc.com/api/queries/{query_id}/results.json?api_key={api_key}"
    response = requests.get(url, timeout=60)
    if response.status_code != 200:
        return 0
    rows = response.json()["query_result"]["data"]["rows"]
    return len(rows)


def send_alert(missing_queries: list[int]) -> None:
    names = " and ".join(f"Query {q}" for q in missing_queries)
    body = (
        f"Health check failed on {TODAY_STR}.\n\n"
        f"{names} returned no data. "
        "The prescription SLA report may be incomplete or missing today."
    )

    msg = MIMEMultipart()
    msg["From"] = GMAIL_USER
    msg["To"] = ALERT_EMAIL
    msg["Subject"] = f"⚠️ Prescription SLA data missing – {TODAY_STR}"
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.ehlo()
        server.starttls()
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, [ALERT_EMAIL], msg.as_string())


def main() -> None:
    missing = []

    if fetch_row_count(923, REDASH_API_KEY_923) == 0:
        missing.append(923)

    if fetch_row_count(924, REDASH_API_KEY_924) == 0:
        missing.append(924)

    if missing:
        print(f"Data missing for queries: {missing}. Sending alert to {ALERT_EMAIL}.")
        send_alert(missing)
    else:
        print("Both queries have data. No alert needed.")


if __name__ == "__main__":
    main()
