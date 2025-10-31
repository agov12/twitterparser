import os
import requests
from typing import Dict, Optional
from dotenv import load_dotenv
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.proxies import WebshareProxyConfig

# Load environment variables from .env file
load_dotenv()


def get_youtube_channel_videos(handle: str, keyword: str = None, max_results: int = 10) -> Optional[Dict]:
    """
    Fetch recent videos from a YouTube channel using the YouTube Data API v3.
    Optionally filter videos by searching for a keyword in their transcripts.

    Args:
        handle: The YouTube channel handle (e.g., '@MrBeast' or 'MrBeast')
        keyword: Optional keyword to search for in video transcripts
        max_results: Maximum number of videos to fetch (default: 10, max: 50)

    Returns:
        Dictionary containing channel info and list of recent videos (filtered by keyword if provided), or None if error
    """

    # Get API key from environment variable
    api_key = os.getenv('YOUTUBE_API_KEY')
    if not api_key:
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
        'key': api_key
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
            'key': api_key
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
        uploads_playlist_id = channel_info['contentDetails']['relatedPlaylists']['uploads']

        print(f"Found channel: {channel_title} (ID: {channel_id})")
        print(f"Uploads playlist ID: {uploads_playlist_id}")

        # Step 2: Get videos from uploads playlist
        playlist_url = "https://www.googleapis.com/youtube/v3/playlistItems"
        playlist_params = {
            'part': 'snippet,contentDetails',
            'playlistId': uploads_playlist_id,
            'maxResults': min(max_results, 50),  # API max is 50
            'key': api_key
        }

        response = requests.get(playlist_url, params=playlist_params)
        response.raise_for_status()
        playlist_data = response.json()

        videos = []
        for item in playlist_data.get('items', []):
            video_id = item['contentDetails']['videoId']
            video_info = {
                'video_id': video_id,
                'title': item['snippet']['title'],
                'description': item['snippet']['description'][:200] + '...' if len(item['snippet']['description']) > 200 else item['snippet']['description'],
                'published_at': item['snippet']['publishedAt'],
                'thumbnail_url': item['snippet']['thumbnails'].get('default', {}).get('url'),
                'video_url': f"https://www.youtube.com/watch?v={video_id}"
            }

            # If keyword is provided, check transcript for the keyword
            if keyword:
                try:
                    # Fetch transcript using youtube-transcript-api
                    # This is the correct static method usage
                    ytt_api = YouTubeTranscriptApi(
                        proxy_config=WebshareProxyConfig(
                            proxy_username=os.getenv('WEBSHARE_PROXY_USERNAME'),
                            proxy_password=os.getenv('WEBSHARE_PROXY_PASSWORD'),
                        )
                    )
                    transcript_list = ytt_api.fetch(video_id)
                    transcript_list = transcript_list.to_raw_data()

                    # Check each snippet for keyword
                    keyword_found = False
                    for entry in transcript_list:
                        if keyword.lower() in entry['text'].lower():
                            keyword_found = True
                            break  # Found keyword, no need to check more snippets

                    if keyword_found:
                        videos.append(video_info)
                        print(f"✅ Found keyword '{keyword}' in video: {video_info['title']}")
                    else:
                        print(f"❌ Keyword '{keyword}' not found in video: {video_info['title']}")

                except Exception as e:
                    # If transcript is not available or error occurs, skip the video when filtering by keyword
                    print(f"Error: {e}")
                    print(f"⚠️  Could not get transcript for video '{video_info['title']}': {str(e)[:100]}")
            else:
                # No keyword filter, include all videos
                videos.append(video_info)

        result = {
            'channel': {
                'id': channel_id,
                'title': channel_title,
                'uploads_playlist_id': uploads_playlist_id
            },
            'videos': videos,
            'total_videos_fetched': len(videos),
            'keyword_filter': keyword if keyword else None
        }

        return result

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


# Example usage (uncomment to test)
if __name__ == "__main__":
    # Test with a channel handle
    # Set YOUTUBE_API_KEY environment variable in .env file
    # Example: YOUTUBE_API_KEY="your_api_key_here"

    handle = input("Enter YouTube channel handle (e.g., '@MrBeast' or 'MrBeast'): ")
    keyword = input("Enter keyword to search in transcripts (or press Enter to skip): ")

    # Use keyword if provided, otherwise None
    result = get_youtube_channel_videos(handle, keyword if keyword else None, max_results=5)

    if result:
        if result['keyword_filter']:
            print(f"\n✅ Found {result['total_videos_fetched']} videos with keyword '{result['keyword_filter']}' from {result['channel']['title']}")
        else:
            print(f"\n✅ Successfully fetched {result['total_videos_fetched']} videos from {result['channel']['title']}")

        print("\nRecent videos:")
        for i, video in enumerate(result['videos'], 1):
            print(f"\n{i}. {video['title']}")
            print(f"   Published: {video['published_at']}")
            print(f"   URL: {video['video_url']}")