import aiohttp
from typing import Optional
import json
from fuzzywuzzy import process
import re
import uuid
import asyncio


class LRCProvider:
    def __init__(self, user_token: str) -> None:
        self.user_token = user_token
        self.session = None

    async def create_session(self):
        if not self.session:
            self.session = aiohttp.ClientSession(
                headers={
                    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36"
                }
            )

    async def __aenter__(self):
        await self.create_session()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.session.close()

    async def get_lrc_by_id(self, track_id: str) -> Optional[str]:
        raise NotImplementedError

    async def get_lrc(self) -> Optional[str]:
        raise NotImplementedError


class Musixmatch(LRCProvider):
    SEARCH_ENDPOINT = "https://apic-desktop.musixmatch.com/ws/1.1/track.search?format=json&q={q}&page_size=5&page=1&s_track_rating=desc&quorum_factor=1.0&app_id=web-desktop-app-v1.0&usertoken={token}"
    LRC_ENDPOINT = "https://apic-desktop.musixmatch.com/ws/1.1/track.subtitle.get?format=json&track_id={track_id}&subtitle_format=lrc&app_id=web-desktop-app-v1.0&usertoken={token}"

    async def get_lrc_by_id(self, track_id: str) -> Optional[dict]:
        url = self.LRC_ENDPOINT.format(track_id=track_id, token=self.user_token)
        async with self.session.get(url) as r:
            if not r.ok:
                return None
            if r.headers.get("Content-Type").startswith("application/json"):
                body = await r.json()
            else:
                text = await r.text()
                try:
                    body = json.loads(text)
                except json.JSONDecodeError:
                    print("Failed to decode response as JSON.")
                    return None
            subtitle_body = (
                body.get("message", {})
                .get("body", {})
                .get("subtitle", {})
                .get("subtitle_body")
            )
            if not subtitle_body:
                return None
            return self.parse_lrc(subtitle_body)

    def parse_lrc(self, lrc_content: str) -> dict:
        lyrics_with_timestamps = []
        for line in lrc_content.split("\n"):
            match = re.match(r"\[(\d+):(\d+\.\d+)\](.*)", line)
            if match:
                minutes, seconds, lyric = match.groups()
                timestamp = float(minutes) * 60 + float(seconds)
                lyrics_with_timestamps.append(
                    {"id": str(uuid.uuid4()), "lyric": lyric, "timestamp": timestamp}
                )
        return {"lyrics_with_timestamps": lyrics_with_timestamps}

    async def get_lrc(self) -> Optional[dict]:
        search_term = input("Enter the song title and/or artist: ")
        url = self.SEARCH_ENDPOINT.format(q=search_term, token=self.user_token)
        async with self.session.get(url) as r:
            if not r.ok:
                return None
            if r.headers.get("Content-Type") == "application/json":
                body = await r.json()
            else:
                text = await r.text()
                try:
                    body = json.loads(text)
                except json.JSONDecodeError:
                    print("Failed to decode response as JSON.")
                    return None
            tracks = body.get("message", {}).get("body", {}).get("track_list", [])
            if not tracks:
                return None
            search_term = search_term.lower()
            track_names = [
                f"{track['track']['track_name']} {track['track']['artist_name']}".lower()
                for track in tracks
            ]
            best_match = process.extractOne(search_term, track_names)
            if best_match:
                best_match_index = track_names.index(best_match[0])
                best_track_id = tracks[best_match_index]["track"]["track_id"]
                return await self.get_lrc_by_id(best_track_id)
            else:
                print("No suitable match found.")
                return None

    async def get_lrc_by_search(self, song_title: str, artist_name: str) -> Optional[dict]:
        search_term = f"{song_title} {artist_name}"
        url = self.SEARCH_ENDPOINT.format(q=search_term, token=self.user_token)
        async with self.session.get(url) as response:
            if not response.ok:
                print(f"Request failed with status: {response.status}")
                return None
            if not response.headers.get("Content-Type", "").startswith("application/json"):
                print("Invalid content type received.")
                return None
            response_text = await response.text()
            try:
                body = json.loads(response_text)
            except json.JSONDecodeError as e:
                print(f"Failed to decode JSON, exception: {e}")
                return None
            tracks = body.get("message", {}).get("body", {}).get("track_list", [])
            if not tracks:
                print("No tracks found in the response.")
                return None
            search_term = search_term.lower()
            track_names = [
                f"{track['track']['track_name']} {track['track']['artist_name']}".lower()
                for track in tracks
            ]
            best_match, score = process.extractOne(search_term, track_names, score_cutoff=70)
            if best_match and score >= 70:
                best_match_index = track_names.index(best_match)
                best_track_id = tracks[best_match_index]["track"]["track_id"]
                return await self.get_lrc_by_id(best_track_id)
            else:
                print("No suitable match found or match score is too low.")
                return None


async def main():
    async with Musixmatch(
        "190523f77464fba06fa5f82a9bfab0aa9dc201244ecf5124a06d95"
    ) as musixmatch:
        lyrics = await musixmatch.get_lrc()
        if lyrics:
            print(json.dumps(lyrics, indent=4))
        else:
            print("Lyrics not found.")


if __name__ == "__main__":
    asyncio.run(main())
