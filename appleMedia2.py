import aiohttp
import aiofiles
import os
from urllib.parse import urljoin
import re
import asyncio
from m3u8 import M3U8


async def download_media(song_title, artist_name, media_type="both"):
    headers = {"Authorization": "Bearer " + DEVELOPER_TOKEN}
    params = {"term": song_title + " " + artist_name, "limit": "5", "types": "songs"}
    async with aiohttp.ClientSession() as session:
        async with session.get(
            "https://api.music.apple.com/v1/catalog/us/search",
            headers=headers,
            params=params,
        ) as response:
            json_response = await response.json()
    if "songs" not in json_response["results"]:
        print("No songs found.")
        return
    song_data = json_response["results"]["songs"]["data"]

    if media_type in ["video", "both"]:
        video_downloaded = False
        for song in song_data:
            song_url = song["attributes"]["url"]
            playlist_url = await fetch_playlist_url(song_url)
            if playlist_url:
                variant_playlist_url = await fetch_variant_playlist_url(playlist_url)
                if variant_playlist_url:
                    segment_urls = await fetch_segment_urls(variant_playlist_url)
                    if segment_urls:
                        await download_video_segments(
                            segment_urls, "finalOutput", song_title, artist_name
                        )
                        video_downloaded = True
                        break
        if not video_downloaded and media_type == "video":
            print("No animated cover art found.")

    if media_type in ["image", "both"]:
        artwork_url = (
            song_data[0]["attributes"]["artwork"]["url"]
            .replace("{w}", "3000")
            .replace("{h}", "3000")
        )
        await download_image(artwork_url, song_title, artist_name)


# Utility function to generate filenames
def generate_filename(base_filename, suffix):
    # Replace non-alphanumeric characters with underscore
    safe_filename = re.sub(r"\W+", "_", base_filename)
    return f"{safe_filename}_{suffix}"


# Utility Functions
async def fetch_data(url):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            return await response.text()


async def get_webpage_content(url):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                response.raise_for_status()
                return await response.text()
    except aiohttp.ClientError as e:
        print(f"Error occurred while fetching page: {e}")
        return None


async def fetch_variant_playlist_url(playlist_url):
    content = await get_webpage_content(playlist_url)
    if content:
        playlists = M3U8(content).playlists
        if playlists:
            playlists.sort(key=lambda p: abs(p.stream_info.resolution[0] - 720))
            return urljoin(playlist_url, playlists[0].uri)
    print("No variant playlist found.")
    return None


async def fetch_playlist_url(url):
    max_redirects = 5  # Set a reasonable limit for redirects
    async with aiohttp.ClientSession() as session:
        for _ in range(max_redirects):
            async with session.get(url, allow_redirects=False) as response:
                if response.status in (
                    301,
                    302,
                    303,
                    307,
                    308,
                ):  # Redirect status codes
                    url = response.headers["Location"]
                    print(f"Redirecting to {url}")  # For debugging purposes
                else:
                    return url  # Final URL after following redirects
        print("Too many redirects or redirect loop detected")
        return None  # In case of too many redirects or a loop


async def fetch_segment_urls(variant_playlist_url):
    content = await get_webpage_content(variant_playlist_url)
    if content:
        return [
            urljoin(variant_playlist_url, segment.uri)
            for segment in M3U8(content).segments
        ]
    return None


# Functions for Apple Music interactions
async def download_image(image_url, song_title, artist_name):
    output_dir = os.path.join(os.getcwd(), "finalOutput")
    os.makedirs(output_dir, exist_ok=True)
    base_filename = f"{artist_name.lower()}_{song_title.lower()}"
    jpg_filename = generate_filename(base_filename, "jpg")
    async with aiohttp.ClientSession() as session:
        async with session.get(image_url) as response:
            if response.status == 200:
                async with aiofiles.open(
                    os.path.join(output_dir, jpg_filename), "wb"
                ) as out_file:
                    while True:
                        chunk = await response.content.read(1024)
                        if not chunk:
                            break
                        await out_file.write(chunk)
                print(f"Image downloaded: {jpg_filename}")


async def download_video_segments(segment_urls, video_dir, song_title, artist_name):
    output_dir = os.path.join(os.getcwd(), video_dir)
    os.makedirs(output_dir, exist_ok=True)
    base_filename = f"{artist_name.lower()}_{song_title.lower()}"
    mp4_filename = generate_filename(base_filename, "mp4")
    async with aiohttp.ClientSession() as session:
        async with session.get(
            segment_urls[0]
        ) as response:  # Assuming you want to download the first segment only
            if response.status == 200:
                content = await response.read()
                async with aiofiles.open(
                    os.path.join(output_dir, mp4_filename), "wb"
                ) as file:
                    await file.write(content)
                print(f"{mp4_filename} downloaded.")
            else:
                print(f"No AnimatedArt. Status code: {response.status}")


# Your developer token for the Apple Music API
DEVELOPER_TOKEN = "eyJhbGciOiJFUzI1NiIsImtpZCI6IjYyMlcyTVVVV1EiLCJ0eXAiOiJKV1QifQ.eyJpc3MiOiJVNEdMUUdGTlQzIiwiaWF0IjoxNjk3MjQ4NDQ4LCJleHAiOjE3MTAyMDg0NDh9.XMe-WEuuAJS_LOirXG6yU8CZW1RL6Lw4cwxhc405rvZm_LesEsaLoqNnZ9l_n3SQ0eOqUQEsWXEPNZYJ5wdZXw"


'''
# Assuming appleMedia.py is the name of your script and it's in your PYTHONPATH
# If it's not, you might need to adjust the import statement accordingly
from appleMedia import download_media, download_image, download_video_segments

# The song title and artist you're interested in
SONG_TITLE = "wishing well"
ARTIST_NAME = "juice wrld"


async def main():
    # Start by searching for the song and attempting to download the image and video
    await download_media(SONG_TITLE, ARTIST_NAME, DEVELOPER_TOKEN)


# Run the main function
if __name__ == "__main__":
    asyncio.run(main())
'''
