import os
import json
import requests
import xml.etree.ElementTree as ET
from flask import Flask, request, Response
from typing import Dict, Optional
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Flask app for receiving webhook callbacks
app = Flask(__name__)

# Persistence for active subscriptions across processes
SUBS_FILE = "active_subscriptions.json"

def load_subscriptions() -> dict:
    try:
        with open(SUBS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_subscriptions(data: dict) -> None:
    try:
        with open(SUBS_FILE, "w") as f:
            json.dump(data, f)
    except Exception:
        pass

# Store active subscriptions (loaded from disk)
active_subscriptions = load_subscriptions()


def get_channel_id_from_handle(handle: str) -> Optional[str]:
    """
    Get YouTube channel ID from a channel handle.

    Args:
        handle: The YouTube channel handle (e.g., '@MrBeast' or 'MrBeast')

    Returns:
        Channel ID string or None if not found
    """

    # Get API key from environment variable
    youtube_api_key = os.getenv('YOUTUBE_API_KEY')

    if not youtube_api_key:
        print("Error: YOUTUBE_API_KEY environment variable not set")
        return None

    # Add @ if not present in handle
    if not handle.startswith('@'):
        handle = f'@{handle}'

    # Step 1: Search for channel using handle
    search_url = "https://www.googleapis.com/youtube/v3/search"
    search_params = {
        'part': 'snippet',
        'q': handle,
        'type': 'channel',
        'maxResults': 1,
        'key': youtube_api_key
    }

    try:
        response = requests.get(search_url, params=search_params)
        response.raise_for_status()
        search_data = response.json()

        if not search_data.get('items'):
            print(f"Channel '{handle}' not found")
            return None

        # Get the channel ID from search results
        channel_id = search_data['items'][0]['id']['channelId']

        # Get full channel info with the channel ID
        channel_url = "https://www.googleapis.com/youtube/v3/channels"
        channel_params = {
            'part': 'contentDetails,snippet',
            'id': channel_id,
            'key': youtube_api_key
        }

        response = requests.get(channel_url, params=channel_params)
        response.raise_for_status()
        channel_data = response.json()

        if not channel_data.get('items'):
            print(f"Channel '{handle}' not found")
            return None

        channel_info = channel_data['items'][0]
        channel_id = channel_info['id']
        channel_title = channel_info['snippet']['title']

        print(f"Found channel: {channel_title} (ID: {channel_id})")

        return channel_id

    except requests.exceptions.RequestException as e:
        print(f"Error making API request: {e}")
        if hasattr(e, 'response') and e.response is not None:
            try:
                error_data = e.response.json()
                print(f"API Error: {error_data}")
            except:
                print(f"HTTP Status Code: {e.response.status_code}")
        return None
    except Exception as e:
        print(f"Unexpected error: {e}")
        return None


def check_video_for_keyword(video_id: str, keyword: str, video_title: str = "") -> bool:
    """
    Check if a video's transcript contains a keyword using RapidAPI.
    """
    rapidapi_key = os.getenv('RAPIDAPI_KEY')
    if not rapidapi_key:
        print("Error: RAPIDAPI_KEY environment variable not set")
        return False

    try:
        rapidapi_url = f"https://youtube-transcript3.p.rapidapi.com/api/transcript"
        rapidapi_params = {'videoId': video_id}
        rapidapi_headers = {
            'x-rapidapi-host': 'youtube-transcript3.p.rapidapi.com',
            'x-rapidapi-key': rapidapi_key
        }

        response = requests.get(rapidapi_url, params=rapidapi_params, headers=rapidapi_headers, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data.get('success') and 'transcript' in data:
            for segment in data['transcript']:
                if 'text' in segment and keyword.lower() in segment['text'].lower():
                    print(f"✅ Found keyword '{keyword}' in video: {video_title or video_id}")
                    return True
            print(f"❌ Keyword '{keyword}' not found in video: {video_title or video_id}")
        else:
            print(f"⚠️  No transcript available for video '{video_title or video_id}'")

        return False

    except Exception as e:
        print(f"⚠️  Could not get transcript for video '{video_title or video_id}': {str(e)[:100]}")
        return False


def unsubscribe_from_youtube_channel(channel_identifier: str, callback_url: str):
    """
    Unsubscribe from a YouTube channel using either a channel ID or handle.
    """
    hub_url = "https://pubsubhubbub.appspot.com/"

    # Determine if identifier is already a channel ID (typically starts with "UC")
    channel_id = channel_identifier
    if not channel_identifier.startswith("UC"):
        resolved_channel_id = get_channel_id_from_handle(channel_identifier)
        if not resolved_channel_id:
            print(f"❌ Failed to resolve channel handle '{channel_identifier}' to an ID")
            return False
        channel_id = resolved_channel_id

    topic_url = f"https://www.youtube.com/xml/feeds/videos.xml?channel_id={channel_id}"

    data = {
        'hub.mode': 'unsubscribe',
        'hub.topic': topic_url,
        'hub.callback': callback_url,
        'hub.verify': 'sync'
    }

    try:
        response = requests.post(hub_url, data=data)
        response.raise_for_status()
        if channel_id in active_subscriptions:
            del active_subscriptions[channel_id]
            save_subscriptions(active_subscriptions)
        print(f"✅ Successfully unsubscribed from channel {channel_id}")
        return True
    except Exception as e:
        print(f"❌ Failed to unsubscribe: {e}")
        return False


def subscribe_to_youtube_channel(handle: str, callback_url: str, keyword: str = None):
    """
    Subscribe to a YouTube channel for new video notifications with optional keyword filtering.
    """
    # Get channel ID from handle
    channel_id = get_channel_id_from_handle(handle)
    if not channel_id:
        return {'success': False, 'error': 'Could not find channel'}

    # Store subscription info for keyword filtering
    active_subscriptions[channel_id] = {'keyword': keyword, 'callback_url': callback_url}
    save_subscriptions(active_subscriptions)

    # Subscribe via PubSubHubbub
    hub_url = "https://pubsubhubbub.appspot.com/"
    topic_url = f"https://www.youtube.com/xml/feeds/videos.xml?channel_id={channel_id}"

    data = {
        'hub.mode': 'subscribe',
        'hub.topic': topic_url,
        'hub.callback': callback_url,
        'hub.verify': 'sync',
        'hub.lease_seconds': 432000  # 5 days
    }

    try:
        response = requests.post(hub_url, data=data)
        response.raise_for_status()
        print(f"✅ Successfully subscribed to channel {channel_id}")
        return {
            'success': True,
            'channel_id': channel_id,
            'callback_url': callback_url,
            'keyword': keyword
        }
    except requests.exceptions.RequestException as e:
        print(f"❌ Failed to subscribe: {e}")
        return {'success': False, 'error': str(e)}


@app.route('/youtube-webhook', methods=['GET', 'POST'])
def youtube_webhook():
    """
    Webhook endpoint to receive YouTube feed notifications.
    """
    if request.method == 'GET':
        # Hub verification challenge
        challenge = request.args.get('hub.challenge')
        if challenge:
            return Response(challenge, mimetype='text/plain')
        return Response('Invalid request', status=400)

    elif request.method == 'POST':
        # New video notification
        try:
            root = ET.fromstring(request.data)
            ns = {'atom': 'http://www.w3.org/2005/Atom', 'yt': 'http://www.youtube.com/xml/schemas/2015'}

            entry = root.find('atom:entry', ns)
            if entry:
                video_id = entry.find('yt:videoId', ns).text
                video_title = entry.find('atom:title', ns).text
                channel_id = entry.find('yt:channelId', ns).text

                print(f"\n🔔 New video: {video_title}")
                print(f"   URL: https://www.youtube.com/watch?v={video_id}")

                # Check keyword if configured (reload from disk to pick up external changes)
                subs = load_subscriptions()
                if channel_id in subs:
                    keyword = subs[channel_id].get('keyword')
                    if keyword and check_video_for_keyword(video_id, keyword, video_title):
                        print(f"🎯 MATCH! Contains keyword '{keyword}'")
                        # Trigger notification here

            return Response('OK', status=200)
        except Exception as e:
            print(f"Error processing webhook: {e}")
            return Response('Error', status=500)


# Example usage (uncomment to test)
if __name__ == "__main__":
    # Test subscription
    # Set environment variables in .env file:

    print("YouTube Channel Subscription Setup")
    print("1. Subscribe to channel")
    print("2. Run webhook server")
    print("3. Unsubscribe from channel")

    choice = input("Enter choice (1, 2, or 3): ")

    if choice == "1":
        handle = input("Enter YouTube channel handle (e.g., '@MrBeast' or 'MrBeast'): ")
        callback_url = "https://uncarted-bev-nonpathologically.ngrok-free.dev/youtube-webhook"
        keyword = input("Enter keyword to filter videos (or press Enter to skip): ")

        print(f"\n⚠️  Make sure the webhook server is running (option 2) before subscribing!")
        print(f"Callback URL: {callback_url}")

        result = subscribe_to_youtube_channel(handle, callback_url, keyword if keyword else None)

        if result['success']:
            print(f"\n✅ Successfully subscribed!")
            print(f"   Channel ID: {result['channel_id']}")
            print(f"   Callback URL: {result['callback_url']}")
            if result['keyword']:
                print(f"   Filtering for keyword: {result['keyword']}")
        else:
            print(f"\n❌ Failed to subscribe: {result['error']}")

    elif choice == "2":
        print("\nStarting webhook server on port 5000...")
        print("Make sure your callback URL points to this server!")
        app.run(port=5000, debug=True, use_reloader=False)

    elif choice == "3":
        channel_identifier = input("Enter YouTube channel handle or ID to unsubscribe: ")
        callback_url = "https://uncarted-bev-nonpathologically.ngrok-free.dev/youtube-webhook"
        print(f"Unsubscribing from channel {channel_identifier}...")
        unsubscribe_from_youtube_channel(channel_identifier, callback_url)