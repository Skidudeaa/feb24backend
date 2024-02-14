import aiohttp
import aiofiles
import os
from urllib.parse import urljoin
import re
import asyncio
from m3u8 import M3U8

import aiohttp
import aiofiles
import os
from urllib.parse import urljoin
import re
import asyncio
from m3u8 import M3U8




this should be close to being able to be called from the main app to get video and image



# Consolidated Fetch Function
async def fetch_content(url, session, allow_redirects=True, max_redirects=4):
    redirect_count = 0
    while True:
        async with session.get(url, allow_redirects=False) as response:
            if response.status in [200, 201]:
                return await response.text()
            elif response.status in [301, 302, 303, 307, 308] and redirect_count < max_redirects:
                url = response.headers['Location']
                print(f"Redirecting to {url}")
                redirect_count += 1
                continue
            response.raise_for_status()

# Utility function to generate filenames
def generate_filename(base_filename, suffix):
    # Replace non-alphanumeric characters with underscore
    safe_filename = re.sub(r"\W+", "_", base_filename)
    return f"{safe_filename}_{suffix}"

# Functions for Apple Music interactions
async def fetch_variant_playlist_url(playlist_url, session):
    content = await fetch_content(playlist_url, session)
    if content:
        playlists = M3U8(content).playlists
        if playlists:
            playlists.sort(key=lambda p: abs(p.stream_info.resolution[0] - 720))
            return urljoin(playlist_url, playlists[0].uri)
    return None

async def fetch_playlist_url(url, session):
    return await fetch_content(url, session, allow_redirects=False)

async def fetch_segment_urls(variant_playlist_url, session):
    content = await fetch_content(variant_playlist_url, session)
    if content:
        return [urljoin(variant_playlist_url, segment.uri) for segment in M3U8(content).segments]
    return None

async def download_content(url, path, session):
    async with session.get(url) as response:
        if response.status == 200:
            async with aiofiles.open(path, "wb") as file:
                while True:
                    chunk = await response.content.read(1024)
                    if not chunk:
                        break
                    await file.write(chunk)
            print(f"Content downloaded: {path}")
        else:
            print(f"Failed to download content. Status code: {response.status}")

async def download_media(song_title, artist_name, media_type="both", session=None):
    if not session:
        async with aiohttp.ClientSession() as session:
            await _download_media(song_title, artist_name, media_type, session)
    else:
        await _download_media(song_title, artist_name, media_type, session)

async def _download_media(song_title, artist_name, media_type, session):
    headers = {"Authorization": "Bearer " + DEVELOPER_TOKEN}
    params = {"term": song_title + " " + artist_name, "limit": "5", "types": "songs"}
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

    tasks = []
    if media_type in ["video", "both"]:
        for song in song_data:
            song_url = song["attributes"]["url"]
            playlist_url = await fetch_playlist_url(song_url, session)
            if playlist_url:
                variant_playlist_url = await fetch_variant_playlist_url(playlist_url, session)
                if variant_playlist_url:
                    segment_urls = await fetch_segment_urls(variant_playlist_url, session)
                    if segment_urls:
                        # Assuming you want to download the first segment only for demonstration
                        video_dir = os.path.join(os.getcwd(), "finalOutput")
                        os.makedirs(video_dir, exist_ok=True)
                        base_filename = f"{artist_name.lower()}_{song_title.lower()}"
                        mp4_filename = generate_filename(base_filename, "mp4")
                        video_path = os.path.join(video_dir, mp4_filename)
                        tasks.append(download_content(segment_urls[0], video_path, session))
                        break

    if media_type in ["image", "both"]:
        artwork_url = (
            song_data[0]["attributes"]["artwork"]["url"]
            .replace("{w}", "3000")
            .replace("{h}", "3000")
        )
        image_dir = os.path.join(os.getcwd(), "finalOutput")
        os.makedirs(image_dir, exist_ok=True)
        jpg_filename = generate_filename(
            f"{artist_name.lower()}_{song_title.lower()}", "jpg"
        )
        image_path = os.path.join(image_dir, jpg_filename)
        tasks.append(download_content(artwork_url, image_path, session))

    if tasks:
        await asyncio.gather(*tasks)


# Main function to run the script
async def main():
    song_title = "paranoid"
    artist_name = "post malone"
    async with aiohttp.ClientSession() as session:
        await download_media(
            song_title, artist_name, media_type="both", session=session
        )


if __name__ == "__main__":
    # Replace DEVELOPER_TOKEN with your actual Apple Music developer token
    DEVELOPER_TOKEN = "eyJhbGciOiJFUzI1NiIsImtpZCI6IjYyMlcyTVVVV1EiLCJ0eXAiOiJKV1QifQ.eyJpc3MiOiJVNEdMUUdGTlQzIiwiaWF0IjoxNjk3MjQ4NDQ4LCJleHAiOjE3MTAyMDg0NDh9.XMe-WEuuAJS_LOirXG6yU8CZW1RL6Lw4cwxhc405rvZm_LesEsaLoqNnZ9l_n3SQ0eOqUQEsWXEPNZYJ5wdZXw" 
    
    asyncio.run(main())

