import os
import requests
import smtplib
from email.mime.text import MIMEText
from flask import Flask, request
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# Global variables to store monitoring parameters for filtering
MONITOR_HANDLE = None
MONITOR_KEYWORD = None

API_BASE = "https://api.twitterapi.io/oapi/tweet_filter"
API_HEADERS = {'Content-Type': 'application/json'}

def get_rules(api_key):
    headers = {**API_HEADERS, 'X-API-Key': api_key}
    resp = requests.get(f"{API_BASE}/get_rules", headers=headers)
    if not resp.ok:
        print("Failed to fetch rules:", resp.status_code, resp.text)
        return []
    return resp.json().get('rules', []) or []

def find_rule_by_tag_or_value(api_key, tag=None, value=None):
    rules = get_rules(api_key)
    for r in rules:
        # adjust key names depending on API response (common names: rule_id, tag, value)
        if tag and r.get('tag') == tag:
            return r
        if value and r.get('value') == value:
            return r
    return None

def create_rule(api_key, tag, value, interval_seconds=100):
    headers = {**API_HEADERS, 'X-API-Key': api_key}
    payload = {'tag': tag, 'value': value, 'interval_seconds': interval_seconds}
    resp = requests.post(f"{API_BASE}/add_rule", headers=headers, json=payload)
    if not resp.ok:
        print("Failed to create rule:", resp.status_code, resp.text)
        return None
    return resp.json()

def update_rule(api_key, rule_id, tag, value, interval_seconds=100, is_effect=1):
    headers = {**API_HEADERS, 'X-API-Key': api_key}
    payload = {
        'rule_id': rule_id,
        'tag': tag,
        'value': value,
        'interval_seconds': interval_seconds,
        'is_effect': is_effect
    }
    resp = requests.post(f"{API_BASE}/update_rule", headers=headers, json=payload)
    if not resp.ok:
        print("Failed to update rule:", resp.status_code, resp.text)
        return None
    return resp.json()

def monitor_twitter(handle=None, keyword=None):
    """Create or reuse a monitoring rule (idempotent)"""
    global MONITOR_HANDLE, MONITOR_KEYWORD

    # Store monitoring parameters for webhook filtering
    MONITOR_HANDLE = handle.lstrip('@') if handle else None
    MONITOR_KEYWORD = keyword.lower() if keyword else None

    api_key = os.getenv('TWITTER_API_KEY')
    if not api_key:
        print("TWITTER_API_KEY missing")
        return

    rule_parts = []
    if handle:
        rule_parts.append(f'from:{handle.lstrip("@")}')
    if keyword:
        rule_parts.append(keyword)
    if not rule_parts:
        print("Error: Provide at least a handle or keyword")
        return
    rule_value = ' '.join(rule_parts)
    rule_tag = f'monitor_{handle or keyword}'

    # try to find existing rule by tag or exact value
    existing = find_rule_by_tag_or_value(api_key, tag=rule_tag, value=rule_value)
    if existing:
        rule_id = existing.get('rule_id') or existing.get('id') or existing.get('id_str')
        print(f"Found existing rule (tag={rule_tag}): ID={rule_id}. Updating/activating it.")
        update_rule(api_key, rule_id, rule_tag, rule_value, interval_seconds=100, is_effect=1)
        return

    # Otherwise create
    created = create_rule(api_key, rule_tag, rule_value, interval_seconds=100)
    if created:
        # returned payload might include rule_id under different key names
        rule_id = created.get('rule_id') or created.get('id') or created.get('id_str')
        print(f"Created rule: {rule_value} (ID: {rule_id})")
        # activate explicitly
        update_rule(api_key, rule_id, rule_tag, rule_value, interval_seconds=100, is_effect=1)
    else:
        print("Could not create rule.")

def send_email(subject, body):
    smtp_server = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
    smtp_port = int(os.getenv('SMTP_PORT', '587'))
    email_address = os.getenv('EMAIL_USERNAME')
    email_password = os.getenv('EMAIL_PASSWORD')
    recipient_email = os.getenv('RECIPIENT_EMAIL')

    if not all([email_address, email_password, recipient_email]):
        print("Email config missing in .env file")
        return

    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = email_address
    msg['To'] = recipient_email

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(email_address, email_password)
            server.send_message(msg)
        print(f"Email sent to {recipient_email}")
    except Exception as e:
        print(f"Failed to send email: {e}")

@app.route('/', methods=['POST'])
def webhook():
    """Receive tweet notifications and send clean emails with just URLs"""
    data = request.json
    print(f"Received webhook data")

    # Get tweets array from the webhook data
    tweets = data.get('tweets', [])
    if not tweets:
        print("No tweets in webhook data")
        return 'OK', 200

    matching_tweets = []

    for tweet in tweets:
        # Extract tweet data
        author_username = tweet.get('author', {}).get('userName', '').lower()
        tweet_text = tweet.get('text', '').lower()
        tweet_url = tweet.get('url', '')

        # Check if tweet matches our monitoring criteria
        matches = True

        # Filter by handle if specified
        if MONITOR_HANDLE and author_username != MONITOR_HANDLE.lower():
            matches = False

        # Filter by keyword if specified
        if MONITOR_KEYWORD and MONITOR_KEYWORD not in tweet_text:
            matches = False

        # Add matching tweet URL
        if matches and tweet_url:
            matching_tweets.append(tweet_url)
            print(f"Found matching tweet: {tweet_url}")

    # Send email if we have matching tweets
    if matching_tweets:
        email_body = '\n'.join(matching_tweets)
        send_email(
            "New Tweets Detected",
            email_body
        )

    return 'OK', 200

if __name__ == "__main__":
    # Option 1: avoid reloader creating duplicate rules
    # Only create rule when we're in the reloader child process (WERKZEUG_RUN_MAIN is set).
    # If you prefer, you can instead use app.run(..., use_reloader=False)
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true" or os.environ.get("FLASK_RUN_FROM_CLI") == "true":
        monitor_twitter(handle='a_gov12', keyword='test')
    else:
        # If not set, still create once (covers running without debug)
        if not app.debug:
            monitor_twitter(handle='a_gov12', keyword='test')

    print("\nStarting webhook server on http://localhost:5000")
    app.run(port=5000, debug=True)  # or use debug=True, use_reloader=False
