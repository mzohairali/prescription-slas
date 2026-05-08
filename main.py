import os
import smtplib
import sys
from datetime import date, timedelta
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from io import BytesIO

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()

REDASH_API_KEY_923 = os.environ["REDASH_API_KEY_923"]
REDASH_API_KEY_924 = os.environ["REDASH_API_KEY_924"]
GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
EMAIL_TO = [addr.strip() for addr in os.environ["EMAIL_TO"].split(",")]

YESTERDAY = date.today() - timedelta(days=1)
YESTERDAY_STR = YESTERDAY.strftime("%Y-%m-%d")


def fetch_query(query_id: int, api_key: str) -> list[dict]:
    url = f"https://omniview.mytrudoc.com/api/queries/{query_id}/results.json?api_key={api_key}"
    response = requests.get(url, timeout=60)
    if response.status_code != 200:
        raise RuntimeError(
            f"Query {query_id} returned HTTP {response.status_code}: {response.text[:200]}"
        )
    rows = response.json()["query_result"]["data"]["rows"]
    if not rows:
        raise RuntimeError(f"Query {query_id} returned zero rows — aborting.")
    return rows


def compute_stats(series: pd.Series) -> dict:
    quantiles = series.quantile([0.25, 0.5, 0.75, 0.9])
    return {
        "P25": round(quantiles[0.25], 1),
        "P50": round(quantiles[0.50], 1),
        "P75": round(quantiles[0.75], 1),
        "P90": round(quantiles[0.90], 1),
        "Mean": round(series.mean(), 1),
    }


def build_excel(stats_creation: dict, stats_attempt: dict) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        workbook = writer.book
        worksheet = workbook.create_sheet("Prescription SLAs")
        # Remove default sheet created by openpyxl
        if "Sheet" in workbook.sheetnames:
            del workbook["Sheet"]

        ws = worksheet

        # Row 1: title
        ws.cell(row=1, column=1, value=f"Prescription SLAs – {YESTERDAY_STR}")

        # Row 2: blank
        # Row 3: section header
        ws.cell(row=3, column=1, value="Prescription Creation Time (minutes)")

        # Row 4: column headers
        headers = ["Metric", "P25", "P50", "P75", "P90", "Mean"]
        for col, header in enumerate(headers, start=1):
            ws.cell(row=4, column=col, value=header)

        # Row 5: data
        ws.cell(row=5, column=1, value="Prescription Creation Time")
        for col, key in enumerate(["P25", "P50", "P75", "P90", "Mean"], start=2):
            ws.cell(row=5, column=col, value=stats_creation[key])

        # Row 6: blank
        # Row 7: section header
        ws.cell(row=7, column=1, value="Prescription First Attempt Time (minutes)")

        # Row 8: column headers
        for col, header in enumerate(headers, start=1):
            ws.cell(row=8, column=col, value=header)

        # Row 9: data
        ws.cell(row=9, column=1, value="Prescription First Attempt Time")
        for col, key in enumerate(["P25", "P50", "P75", "P90", "Mean"], start=2):
            ws.cell(row=9, column=col, value=stats_attempt[key])

    return output.getvalue()


def send_email(excel_bytes: bytes, filename: str) -> None:
    msg = MIMEMultipart()
    msg["From"] = GMAIL_USER
    msg["To"] = ", ".join(EMAIL_TO)
    msg["Subject"] = f"Prescription SLAs – {YESTERDAY_STR}"

    body = f"Please find attached the prescription SLA data for {YESTERDAY_STR}."
    msg.attach(MIMEText(body, "plain"))

    part = MIMEBase("application", "octet-stream")
    part.set_payload(excel_bytes)
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f'attachment; filename="{filename}"')
    msg.attach(part)

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.ehlo()
        server.starttls()
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, EMAIL_TO, msg.as_string())


def main() -> None:
    print(f"Fetching Redash data for {YESTERDAY_STR}...")

    try:
        rows_923 = fetch_query(923, REDASH_API_KEY_923)
        rows_924 = fetch_query(924, REDASH_API_KEY_924)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    df_923 = pd.DataFrame(rows_923)[["encounter_id", "prescription_send_attempted_at"]]
    df_924 = pd.DataFrame(rows_924)[
        [
            "prescription_id",
            "encounter_id",
            "prescription_creation_time_duration",
            "prescription_creation_start_time",
            "prescription_created_at",
        ]
    ]

    # Left join: 924 is left, 923 is right
    df = df_924.merge(df_923, on="encounter_id", how="left")

    # Column 1: creation duration in minutes
    df["prescription_creation_time_duration"] = (
        pd.to_numeric(df["prescription_creation_time_duration"], errors="coerce") / 60
    ).round(1)

    # Column 2: first attempt duration in minutes
    df["prescription_creation_start_time"] = pd.to_datetime(
        df["prescription_creation_start_time"], errors="coerce"
    )
    df["prescription_send_attempted_at"] = pd.to_datetime(
        df["prescription_send_attempted_at"], errors="coerce"
    )
    df["prescription_first_attempt_time_duration"] = (
        (
            df["prescription_send_attempted_at"] - df["prescription_creation_start_time"]
        ).dt.total_seconds()
        / 60
    ).round(1)

    creation_col = df["prescription_creation_time_duration"].dropna()
    attempt_col = df["prescription_first_attempt_time_duration"].dropna()

    if creation_col.empty:
        print("ERROR: No valid prescription_creation_time_duration values.", file=sys.stderr)
        sys.exit(1)
    if attempt_col.empty:
        print("ERROR: No valid prescription_first_attempt_time_duration values.", file=sys.stderr)
        sys.exit(1)

    stats_creation = compute_stats(creation_col)
    stats_attempt = compute_stats(attempt_col)

    filename = f"prescription_slas_{YESTERDAY_STR}.xlsx"
    excel_bytes = build_excel(stats_creation, stats_attempt)

    print(f"Sending email to {EMAIL_TO}...")
    send_email(excel_bytes, filename)
    print("Done.")


if __name__ == "__main__":
    main()
