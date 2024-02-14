"""
 technical flowchart incorporating the five points from our previous discussion:

1. Start
User sends a POST request to /process_song with song_title and artist_name.

2. Check MongoDB for JSON File
If JSON exists: Go to Step 3.
If JSON does not exist: Process all files (JSON, MP4, JPG), upload to MongoDB, and serve files. Go to Step 7.

3. Check for MP4 and JPG in MongoDB
If both MP4 and JPG exist: Serve all files (JSON, MP4, JPG) from MongoDB. Go to Step 7.
If MP4 does not exist: Search for MP4. Go to Step 4.
If JPG does not exist: Fetch JPG from Apple Music. Go to Step 5.
If neither MP4 nor JPG exists: Process both MP4 and JPG. Go to Steps 4 and 5 accordingly.

4. Process MP4
If found: Upload MP4 to MongoDB.
If not found: Log error or serve a placeholder.

5. Process JPG
If found: Upload JPG to MongoDB.
If not found: Log error or serve a placeholder.

6. Update MongoDB and Serve Files
Update MongoDB with any newly processed files.
Serve the latest versions of JSON, MP4, and JPG files from MongoDB.

7. Error Handling
Catch and log any exceptions during processing.
Modify error handling in serve_files_from_mongodb to continue processing other files if one is not found, instead of returning an error immediately.
Return an error response for any failures or exceptions.

8. End
"""

import importlib
# applemedia2 almost ready to use
# import appleMedia2
# importlib.reload(appleMedia2)
# from appleMedia2 import download_media
# Standard library imports
import asyncio
import json
import logging
import mimetypes
import os
import re
import tempfile
import time
import uuid
import warnings
import mimetypes
import aiofiles
import aiohttp

# Third-party package imports (alphabetically)
import backoff
from bertopic import BERTopic
from bs4 import BeautifulSoup
from gensim.models.doc2vec import Doc2Vec, TaggedDocument
from gensim.models.word2vec import Word2Vec
from m3u8 import M3U8
from syncedlyrics import search
import syncedlyrics
from motor.motor_asyncio import AsyncIOMotorClient
from urllib3.util import Retry
from urllib.parse import urljoin
from bson.binary import Binary

from difflib import SequenceMatcher
from bisect import bisect_left, bisect_right
from sentence_transformers import SentenceTransformer
from umap import UMAP
from hdbscan import HDBSCAN
from typing import List, Tuple, Dict, Any
from itertools import product

# from sklearn.model_selection import ParameterGrid
# from sklearn.feature_extraction.text import CountVectorizer
# from concurrent.futures import ProcessPoolExecutor
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import ProcessPoolExecutor
from transformers import pipeline
from nltk import word_tokenize, WordNetLemmatizer, ngrams
from nltk.corpus import stopwords
import nltk
# nltk.download("vader_lexicon")
# nltk.download("punkt")
# nltk.download("stopwords")
# nltk.download('wordnet')

import numpy as np
from pymongo import MongoClient
from quart import (
    Quart,
    request,
    redirect,
    url_for,
    render_template,
    flash,
    jsonify,
    Response,
)
from sentence_transformers import SentenceTransformer
import spacy
from transformers import (
    BartTokenizer,
    BartForConditionalGeneration,
    AutoTokenizer,
    AutoModelForSeq2SeqLM,
    FlaxAutoModelForSeq2SeqLM,
)


from appleMedia import download_media, download_image, download_video_segments
from LRC import Musixmatch


# Initialization
GENIUS_API_KEY = "6IJtS4Xta8IPcEPwmC-8YVOXf5Eoc4RHwbhWINDbzomMcFVXQVxbVQapsFxzKewr"
APPLE_MUSIC_API_KEY = "eyJhbGciOiJFUzI1NiIsImtpZCI6IjYyMlcyTVVVV1EiLCJ0eXAiOiJKV1QifQ.eyJpc3MiOiJVNEdMUUdGTlQzIiwiaWF0IjoxNjk3MjQ4NDQ4LCJleHAiOjE3MTAyMDg0NDh9.XMe-WEuuAJS_LOirXG6yU8CZW1RL6Lw4cwxhc405rvZm_LesEsaLoqNnZ9l_n3SQ0eOqUQEsWXEPNZYJ5wdZXw"
headers = {"Authorization": "Bearer " + APPLE_MUSIC_API_KEY}
warnings.filterwarnings("ignore", category=FutureWarning)
# Create the executor at the module level
executor = ThreadPoolExecutor(max_workers=4)
# Load the spaCy model
nlp = spacy.load("en_core_web_sm")
# Ensure that NLTK's list of stopwords is downloaded
# nltk.download("stopwords")
stop_words = set(stopwords.words("english"))
# python -m spacy download en_core_web_sm


app = Quart(__name__)

FINAL_OUTPUT_DIR = "finalOutput"


@app.route("/process_song", methods=["POST"])
async def process_song():
    try:
        start_time = time.time()
        
        data = await request.get_json()
        song_title = data.get("song_title").lower()
        artist_name = data.get("artist_name").lower()
        logging.info(f"Processing: {song_title}, by {artist_name}")
        print(f"Processing: {song_title} by {artist_name}")

        # Generate unique file names
        base_filename = f"{artist_name}_{song_title}"
        file_extensions = {
            "json": "Final_1.json",
            "mp4": "AnimatedArt.mp4",
            "jpg": "artwork.jpg",
        }
        file_names = {
            file_type: generate_filename(base_filename, file_name)
            for file_type, file_name in file_extensions.items()
        }

        # Preliminary check for files in MongoDB before starting processing
        files_existence = await check_files_existence_in_mongodb(
            app, *file_names.values()
        )

        # If all files exist in MongoDB, serve them directly without processing
        if all(files_existence.values()):
            logging.info("All files found in MongoDB, serving from database.")
            return await serve_files_from_mongodb(app, *file_names.values())

        # Determine which files need to be processed based on their existence in MongoDB
        files_to_process = {
            file_type: not exists for file_type, exists in files_existence.items()
        }

        # Process all files if JSON is missing, as it's the primary file
        if files_to_process["json"]:
            await process_all_files(
                song_title,
                artist_name,
                FINAL_OUTPUT_DIR,
                file_names['json'],  # json_filename
                file_names['mp4'],  # mp4_filename
                file_names['jpg']   # jpg_filename
            )
            files_to_process["mp4"] = False
            files_to_process["jpg"] = False

        # Process MP4 and/or JPG if they are missing
        if files_to_process["mp4"] or files_to_process["jpg"]:
            await process_mp4_and_jpg_files(
                song_title,
                artist_name,
                FINAL_OUTPUT_DIR,
                file_names['json'],  # json_filename
                file_names['mp4'],  # mp4_filename
                file_names['jpg'],  # jpg_filename
                process_mp4=files_to_process["mp4"],
                process_jpg=files_to_process["jpg"],
            )
        print(f"Files to process: {files_to_process}")

        # Serve what's available, regardless of whether all files are present
        return await serve_available_files(app, *file_names.values())

    except Exception as e:
        logging.error(f"An error occurred during processing: {e}", exc_info=e)
        return {"error": "An internal server error occurred."},  500


async def check_files_existence_in_mongodb(
    app, json_filename, mp4_filename, jpg_filename
):
    files_existence = {"json": False, "mp4": False, "jpg": False}
    for filename in [json_filename, mp4_filename, jpg_filename]:
        if filename and await app.collection.find_one({"filename": filename}):
            file_type = filename.split(".")[-1]
            if file_type == "json":
                files_existence["json"] = True
            elif file_type == "mp4":
                files_existence["mp4"] = True
            elif file_type == "jpg":
                files_existence["jpg"] = True
    return files_existence


async def save_files_to_mongodb_and_local(
    app,
    output_dir,
    json_filename,
    mp4_filename,
    jpg_filename,
    json_processed,
    mp4_processed,
    jpg_processed,
):
    # Save the processed json file to MongoDB only if it was processed
    if json_processed:
        await save_file_to_mongodb(app, output_dir, json_filename)
    # Save the processed mp4 file to MongoDB only if it was processed
    if mp4_processed:
        await save_file_to_mongodb(app, output_dir, mp4_filename)
    # Save the processed jpg file to MongoDB only if it was processed
    if jpg_processed:
        await save_file_to_mongodb(app, output_dir, jpg_filename)


async def save_file_to_mongodb(app, output_dir, filename):
    file_path = os.path.join(output_dir, filename)
    if os.path.exists(file_path):
        async with aiofiles.open(file_path, "rb") as file:
            contents = await file.read()
            try:
                if not await app.collection.find_one({"filename": filename}):
                    await app.collection.insert_one(
                        {"filename": filename, "file_data": Binary(contents)}
                    )
                    print(f"{filename} written to MongoDB.")
            except Exception as e:
                print(f"Error writing {filename} to MongoDB: {e}")


async def serve_files_from_mongodb(app, json_filename, mp4_filename, jpg_filename):
    files = {}
    for file_name in [json_filename, mp4_filename, jpg_filename]:
        if file_name is None:
            continue  # Skip to the next file if the filename is None
        try:
            file_document = await app.collection.find_one({"filename": file_name})
            if not file_document:
                print(f"File {file_name} not found in MongoDB.")
                continue  # Skip this file if not found
            file_data = file_document["file_data"]
            files[file_name] = file_data
        except Exception as e:
            print(f"Error retrieving {file_name} from MongoDB: {e}")
            continue  # Continue processing other files even if one fails
    if not files:
        return {"error": "No files found in MongoDB."}, 404
    return create_multipart_response(files)


async def serve_files_from_local(json_filename, mp4_filename, jpg_filename):
    output_dir = "finalOutput"
    files = {}
    for file_name in [json_filename, mp4_filename, jpg_filename]:
        file_path = os.path.join(output_dir, file_name)
        if not os.path.exists(file_path):
            print(f"File not found at path: {file_path}")
            continue  # Skip to the next file if this one is not found
        async with aiofiles.open(file_path, "rb") as file:
            files[file_name] = await file.read()
    if not files:
        return {"error": "No files found locally."}, 404
    return create_multipart_response(files)


async def serve_available_files(app, json_filename, mp4_filename, jpg_filename):
    output_dir = "finalOutput"
    files = {}
    # Define a mapping of file types to their filenames
    filenames = {
        "json": json_filename,
        "mp4": mp4_filename,
        "jpg": jpg_filename,
    }
    # Check MongoDB for the existence of each file type
    files_existence = await check_files_existence_in_mongodb(
        app, json_filename, mp4_filename, jpg_filename
    )
    # Attempt to serve files from MongoDB or locally based on their existence
    for file_type, exists in files_existence.items():
        filename = filenames[file_type]
        if exists:
            # Serve from MongoDB if the file exists
            file_document = await app.collection.find_one({"filename": filename})
            if file_document:
                files[filename] = file_document["file_data"]
            else:
                print(f"File {filename} expected in MongoDB but not found.")
        else:
            # Fallback to serving from local storage
            file_path = os.path.join(output_dir, filename)
            if os.path.exists(file_path):
                async with aiofiles.open(file_path, "rb") as file:
                    files[filename] = await file.read()
            else:
                print(f"File {filename} not found locally.")
    if not files:
        return {"error": "No files available to serve."}, 404
    # Create and return a multipart response with the available files
    return create_multipart_response(files)


def create_multipart_response(files):
    boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
    response_data = b""
    for filename, filedata in files.items():
        mimetype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        response_data += f"--{boundary}\r\n".encode()
        response_data += f'Content-Disposition: form-data; name="{filename}"; filename="{filename}"\r\n'.encode()
        response_data += f"Content-Type: {mimetype}\r\n\r\n".encode()
        response_data += filedata
        response_data += b"\r\n"
    response_data += f"--{boundary}--\r\n".encode()
    return Response(response_data, mimetype=f"multipart/form-data; boundary={boundary}")


async def process_all_files(
    song_title, artist_name, output_dir, json_filename, mp4_filename, jpg_filename
):
    # All the code that processes the song and generates the JSON, MP4, and JPG files goes here
    ...
    # After processing the files, set the processed flags as True
    json_processed = True
    mp4_processed = True
    jpg_processed = True

    bg_color, text_colors, song_duration = await search_song(
        song_title, artist_name, APPLE_MUSIC_API_KEY
    )
    # Convert song_duration from milliseconds to seconds and round to one decimal place
    song_duration = round(song_duration / 1000, 1)
    # print(f"song_duration: {song_duration}")
    # Get the song ID from Genius API
    song_id = await get_song_id(song_title, artist_name, GENIUS_API_KEY)
    if song_id is None:
        print("Error: Could not find the song ID")
        return {"error": "Could not find the song ID."}, 400
    # Get the song details from Genius API
    song_details = await get_song_details(song_id, GENIUS_API_KEY)
    
    # Fetch lyrics and process annotations
    lyrics_data = await fetch_lyrics_with_syncedlyrics(artist_name, song_title)
    if lyrics_data is None:
        print("Error: Could not fetch the lyrics")
        return {"error": "Could not fetch the lyrics."}, 400
    
    
    '''
    #this method works but strange connectiviet sessions still open, only 1 LRC provider
    # Initialize Musixmatch with your user token
    musixmatch = Musixmatch("190523f77464fba06fa5f82a9bfab0aa9dc201244ecf5124a06d95")
    # Ensure the Musixmatch session is created
    await musixmatch.create_session()
    # Replace fetch_lyrics_with_syncedlyrics with Musixmatch.get_lrc_by_search
    lyrics_data = await musixmatch.get_lrc_by_search(song_title, artist_name)
    if lyrics_data is None:
        print("Error: Could not fetch the lyrics")
        return {"error": "Could not fetch the lyrics."}, 400
    '''
    
    

    # Process annotations
    (
        topic_model,
        grouped_annotations,
        topic_summaries,
        topic_names,
    ) = await process_annotations(song_id, GENIUS_API_KEY, lyrics_data, song_duration)
    logging.info("process_annotations function completed.")
    # Check if topic_names is not None before iterating
    if topic_names is not None:
        for topic in topic_names:
            if topic != -1:
                print(f"Topic {topic}: {topic_names[topic]}")
    # Flatten the lyrics_with_timestamps
    flattened_lyrics_with_timestamps = lyrics_data["lyrics_with_timestamps"]
    # Handling the possibility of 'song_details' or 'album' being None
    album_name = ""
    if song_details is not None:
        album = song_details.get("album")
        if album:
            album_name = album.get("name", "")
    # print(f"album_name: {album_name}")
    # Convert song_duration from seconds to milliseconds and round to the nearest integer
    song_duration = round(song_duration * 1000)
    # Generate final JSON
    final_1 = {
        "title": song_details.get("title", "") if song_details else "",
        "artist": song_details.get("primary_artist", {}).get("name", "")
        if song_details
        else "",
        "album": album_name,
        "release_date": song_details.get("release_date", "") if song_details else "",
        "description": song_details.get("description", "") if song_details else "",
        "bgColor": bg_color,
        "textColors": text_colors,
        "songDuration": song_duration,
        "lyrics_with_timestamps": flattened_lyrics_with_timestamps,
        "annotations_with_timestamps": topic_summaries,
    }
    # Ensure that final_1 does not contain any coroutines
    final_1 = {
        key: await value if asyncio.iscoroutine(value) else value
        for key, value in final_1.items()
    }
    # Serialize and write to file
    json_file_path = os.path.join(output_dir, json_filename)
    async with aiofiles.open(json_file_path, "w") as json_file:
        await json_file.write(json.dumps(final_1))
    # Check if other files exist and read them into memory asynchronously
    files = {}
    for filename in [json_filename, mp4_filename, jpg_filename]:
        file_path = os.path.join(output_dir, filename)
        if os.path.exists(file_path):
            async with aiofiles.open(file_path, "rb") as file:
                files[filename] = await file.read()
        else:
            logging.debug(f"Warning: File {filename} not found in {output_dir}")
    # After processing the files
    json_processed = True  # Set to True if the JSON file was processed
    mp4_processed = True  # Set to True if the MP4 file was processed
    jpg_processed = True  # Set to True if the JPG file was processed
    # Save files to MongoDB and local storage
    await save_files_to_mongodb_and_local(
        app,
        output_dir,
        json_filename,
        mp4_filename,
        jpg_filename,
        json_processed,
        mp4_processed,
        jpg_processed,
    )


async def process_mp4_and_jpg_files(
    song_title,
    artist_name,
    output_dir,
    json_filename,
    mp4_filename,
    jpg_filename,
    process_mp4,
    process_jpg,
):
    # Assume the implementation of processing MP4 and JPG files is here
    ...
    await download_media(song_title, artist_name)


def generate_filename(base_filename, suffix):
    # Replace non-alphanumeric characters with underscore
    safe_filename = re.sub(r"\W+", "_", base_filename)
    return f"{safe_filename}_{suffix}"


@app.before_serving
async def before_serving():
    global http_session
    # Initialize the session before the app starts serving
    http_session = aiohttp.ClientSession()
    await setup_mongodb()


@app.after_serving
async def after_serving():
    global http_session
    # Close the session after the app stops serving
    await http_session.close()
    app.db.client.close()  # Properly close the MongoDB connection


async def setup_mongodb():
    uri = "mongodb+srv://namosson:lfWSEOTZyunhQ0Ih@mdb1.ib6ljqe.mongodb.net/?retryWrites=true&w=majority"
    client = AsyncIOMotorClient(uri)
    db = client["songs2_db"]
    app.db = db  # Attach the database object to the app
    app.collection = db["songs2"]  # Directly attach the collection for easier access


@app.route("/")
async def index():
    return "Welcome to the Quart Server!"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)


# PROCESS ALL FILES
def name_topics(topic_model, topics, n_top_words=10):
    topic_names = {}
    for topic in set(topics):
        # Get the top words for this topic
        top_words = topic_model.get_topic(topic)
        # Filter out stop words from the top words
        filtered_top_words = [
            (word, weight)
            for word, weight in top_words
            if word.lower() not in stop_words
        ]
        # Use spaCy for NER
        doc = nlp(" ".join(word for word, _ in filtered_top_words[:n_top_words]))
        named_entities = [ent.text for ent in doc.ents]
        # If we have any named entities, use them as the topic name
        if named_entities:
            topic_names[topic] = " ".join(named_entities[:2]) + f" {topic}"
        else:
            # Otherwise, use the top non-stop words
            topic_names[topic] = (
                " ".join(word for word, _ in filtered_top_words[:3]) + f" {topic}"
            )
    return topic_names


# Specify the model for embeddings and tokenization
tokenizer = AutoTokenizer.from_pretrained("sshleifer/distilbart-cnn-12-6")
model = AutoModelForSeq2SeqLM.from_pretrained("sshleifer/distilbart-cnn-12-6")


def preprocess_text(
    text, use_stopwords=False, use_ngrams=False, ngram_range=(1, 2), keep_pos_tags=None
):
    # Initialize stopwords and lemmatizer
    stop_words = set(stopwords.words("english")) if use_stopwords else set()
    lemmatizer = WordNetLemmatizer()
    # Remove stopwords
    words = [
        word
        for word in word_tokenize(text.lower())
        if word.isalpha() and word not in stop_words
    ]
    # Tokenize and lemmatize text
    tokens = [lemmatizer.lemmatize(word) for word in words]
    # Optionally filter by POS tags
    if keep_pos_tags:
        tagged_tokens = nltk.pos_tag(tokens)
        tokens = [word for word, tag in tagged_tokens if tag in keep_pos_tags]
    return tokens


def fit_and_update_topics(docs):
    # Preprocess the documents
    preprocessed_docs = [preprocess_text(doc) for doc in docs]
    # Prepare training data for Doc2Vec
    tagged_data = [
        TaggedDocument(words=doc, tags=[i]) for i, doc in enumerate(preprocessed_docs)
    ]
    # Train a Doc2Vec model
    model = Doc2Vec(
        tagged_data, vector_size=100, window=5, min_count=1, workers=4, epochs=100
    )
    # Use the trained model to get the vector of each document
    vectorized_docs = [model.infer_vector(doc) for doc in preprocessed_docs]
    # Convert vectorized_docs to a numpy array
    vectorized_docs = np.array(vectorized_docs)
    # Define UMAP and HDBSCAN parameters
    umap_params = {
        "n_neighbors": 7,
        "n_components": 2,
        "min_dist": 0.01,
        "metric": "cosine",
    }
    hdbscan_params = {
        "min_cluster_size": 2,
        "metric": "euclidean",
        "cluster_selection_method": "leaf",
        "min_samples": 1,
    }
    # Create a BERTopic model with the specified parameters
    umap_model = UMAP(**umap_params)
    hdbscan_model = HDBSCAN(**hdbscan_params)
    topic_model = BERTopic(
        embedding_model=None, umap_model=umap_model, hdbscan_model=hdbscan_model
    )
    # Train the BERTopic model
    topics, _ = topic_model.fit_transform(docs, embeddings=vectorized_docs)
    # Get the current number of topics
    current_nr_topics = len(
        set(topics)
    )  # No subtraction to exclude the outlier topic (-1)
    # If the number of topics is more than 6, reduce it
    if current_nr_topics > 7:
        topic_model.update_topics(docs, topics, top_n_words=10)
    # If the number of topics is less than 4, retrain the model with a smaller min_topic_size
    elif current_nr_topics < 3:
        topic_model = BERTopic(min_topic_size=2)
        topics, _ = topic_model.fit_transform(docs, embeddings=vectorized_docs)
    return topic_model, topics


async def summarize_and_process_topic(
    combined_text,
    topic,
    annotations,
    minimum_length,
    maximum_length,
    penalty_factor,
    beam_count,
    batch_size,
    used_timestamps,
    grace_period,
    song_duration,
):
    try:
        start_time_5 = time.time()
        summaries = await summarize_text(
            [combined_text],
            minimum_length,
            maximum_length,
            penalty_factor,
            beam_count,
            batch_size,
        )
        logging.info(f"Summaries for topic {topic} completed successfully.")
    except Exception as e:
        logging.error(f"Error during summarization of topic {topic}: {e}")
        return None
    annotations.sort(
        key=lambda x: x["timestamp"] if x["timestamp"] is not None else float("-inf")
    )
    timestamp = find_next_available_timestamp(
        annotations, used_timestamps, grace_period, song_duration
    )
    topic_summary = {
        "id": str(uuid.uuid4()),
        "annotation": " ".join(summaries),
        "lyric": f"Topic {topic}",
        "timestamp": timestamp,
    }
    logging.info(
        f"Time for a batch of summaries {time.time() - start_time_5 :.2f} seconds."
    )
    return topic_summary


import asyncio
import logging
import uuid
import time
from typing import Any, Dict, List, Tuple

# Ensure necessary imports and helper functions like `summarize_text`,
# `get_annotations_by_song_id`, `process_referent_annotations`, etc., are defined.


async def process_annotations(
    song_id: str,
    api_key: str,
    lyrics_data: str,
    song_duration: int,
    grace_period: int = 20,
) -> Tuple[Any, Dict, List[Dict], Dict]:
    logging.info("Starting to process annotations for song_id: %s", song_id)
    song_duration = round(song_duration, 2)
    try:
        referents = await get_annotations_by_song_id(song_id, api_key)
        logging.info("Referents data retrieved successfully.")
    except Exception as e:
        logging.error(f"Failed to get referents: {e}")
        return None, None, None, None

    used_timestamps = [0, song_duration]
    annotations_data = []
    for referent in referents:
        processed_annotations = await process_referent_annotations(
            referent, lyrics_data, used_timestamps
        )
        annotations_data.extend(processed_annotations)

    if len(annotations_data) >= 6:
        annotation_texts = [
            " ".join(preprocess_text(annotation["annotation"]))
            for annotation in annotations_data
        ]
        topic_model, topics = fit_and_update_topics(annotation_texts)
        topic_names = name_topics(topic_model, topics) if topic_model else {}
        logging.info("Starting batched summarizations")
        grouped_annotations = {}
        for annotation, topic in zip(annotations_data, topics):
            grouped_annotations.setdefault(topic, []).append(annotation)
        topic_summaries = []
        summarization_tasks = []
        for topic, annotations in grouped_annotations.items():
            combined_text = " ".join(
                [annotation["annotation"] for annotation in annotations]
            )
            summarization_tasks.append(
                summarize_and_process_topic(
                    combined_text,
                    topic,
                    annotations,
                    75,  # minimum_length
                    250,  # maximum_length
                    2,  # penalty_factor
                    4,  # beam_count
                    11,  # batch_size
                    used_timestamps,
                    grace_period,
                    song_duration,
                )
            )
        all_summaries = await asyncio.gather(*summarization_tasks)
        topic_summaries = [summary for summary in all_summaries if summary is not None]
        topic_summaries = sorted(topic_summaries, key=lambda x: x["timestamp"])
        return topic_model, grouped_annotations, topic_summaries, topic_names
    else:
        logging.info(
            "Proceeding with batch summarization due to insufficient data or errors."
        )
        # Prepare data for batch summarization
        annotations_texts = [
            annotation["annotation"] for annotation in annotations_data
        ]
        batch_summaries = await summarize_text(
            annotations_texts,
            75,  # minimum_length
            250,  # maximum_length
            2,  # penalty_factor
            4,  # beam_count
            len(annotations_data),  # Adjust batch size to the number of annotations
        )
        annotations_with_summaries = []
        for i, summary in enumerate(batch_summaries):
            annotation = annotations_data[i]
            summarized_annotation = {
                "id": str(uuid.uuid4()),
                "annotation": summary,
                "lyric": annotation.get("lyric", ""),
                "timestamp": find_next_available_timestamp(
                    [annotation], used_timestamps, grace_period, song_duration
                ),
            }
            annotations_with_summaries.append(summarized_annotation)
            used_timestamps.append(
                summarized_annotation["timestamp"]
            )  # Update used timestamps
        annotations_with_summaries = sorted(
            annotations_with_summaries, key=lambda x: x["timestamp"]
        )
        return None, annotations_data, annotations_with_summaries, None


def find_next_available_timestamp(
    annotations: List[Dict],
    used_timestamps: List[int],
    grace_period: int,
    song_duration: int,
) -> int:
    """
    Find the next available timestamp that is not within the grace period of any used timestamp.
    Parameters:
    annotations (List[Dict]): The list of annotations.
    used_timestamps (List[int]): The list of used timestamps.
    grace_period (int): The grace period in seconds.
    song_duration (int): The duration of the song in seconds.
    Returns:
    int: The next available timestamp.
    """
    song_start = 0  # The start of the song in seconds
    song_end = song_duration  # The end of the song in seconds
    timestamp = annotations[0]["timestamp"] if annotations else None
    if timestamp is not None:
        # Check if the timestamp is within the grace period of any used timestamp
        if any(
            abs(timestamp - other_timestamp) < grace_period
            for other_timestamp in used_timestamps
        ):
            # Look for the next available timestamp outside the grace period
            for next_annotation in annotations[1:]:
                next_timestamp = next_annotation["timestamp"]
                if next_timestamp is not None and all(
                    abs(next_timestamp - other_timestamp) >= grace_period
                    for other_timestamp in used_timestamps
                ):
                    timestamp = next_timestamp
                    break
            else:
                # No available timestamp found, find the midpoint of the largest gap
                timestamp = find_midpoint_of_largest_gap(
                    used_timestamps, song_start, song_end
                )
    else:
        # No initial timestamp, find the midpoint of the largest gap
        timestamp = find_midpoint_of_largest_gap(used_timestamps, song_start, song_end)
    # Add the new timestamp to the list of used timestamps
    used_timestamps.append(timestamp)
    used_timestamps.sort()  # Keep the list sorted for future calls
    return timestamp


def find_midpoint_of_largest_gap(
    used_timestamps: List[int], song_start: int, song_end: int
) -> int:
    """
    Find the midpoint of the largest gap in the list of used timestamps, including the start and end of the song.
    Parameters:
    used_timestamps (List[int]): The list of used timestamps in seconds.
    song_start (int): The start of the song in seconds.
    song_end (int): The end of the song in seconds.
    Returns:
    int: The midpoint of the largest gap in seconds.
    Raises:
    ValueError: If song_start is negative, song_end is less than song_start, or any timestamp is out of bounds.
    """
    if song_start < 0:
        raise ValueError("Song start time cannot be negative.")
    if song_end < song_start:
        raise ValueError("Song end time cannot be before the song start time.")
    if any(ts < song_start or ts > song_end for ts in used_timestamps):
        raise ValueError("Used timestamps must be within the song duration.")
    # Include the start and end of the song in the list of timestamps
    extended_timestamps = [song_start] + sorted(used_timestamps) + [song_end]
    # Find the largest gap
    largest_gap_start, largest_gap_size = max(
        (
            (start, end - start)
            for start, end in zip(extended_timestamps, extended_timestamps[1:])
        ),
        key=lambda x: x[1],
    )
    # Return the midpoint of the largest gap
    return largest_gap_start + largest_gap_size // 2


async def summarize_text(
    input_texts: List[str],
    minimum_length: int = 75,
    maximum_length: int = 250,
    penalty_factor: float = 2,
    beam_count: int = 4,
    batch_size: int = 11,
) -> List[str]:
    """
    Summarize a list of input texts using the BART CNN summarization model, in batches.
    """

    # Ensure batch_size is at least 1 to avoid ValueError in range()
    batch_size = max(1, batch_size)

    # Process texts in batches
    batches = [
        input_texts[i : i + batch_size] for i in range(0, len(input_texts), batch_size)
    ]
    summaries = []
    for batch in batches:
        tokenized_texts = tokenizer(
            batch, truncation=True, padding=True, return_tensors="pt"
        )
        try:
            summary_ids = await asyncio.to_thread(
                model.generate,
                tokenized_texts["input_ids"],
                num_beams=beam_count,
                no_repeat_ngram_size=3,
                length_penalty=penalty_factor,
                min_length=minimum_length,
                max_length=maximum_length,
                early_stopping=True,
            )
            summaries.extend(
                [tokenizer.decode(g, skip_special_tokens=True) for g in summary_ids]
            )
        except Exception as e:
            print(f"Error in batch summarization: {e}")
    return summaries


# Genius API Interactions for Song ID
async def get_song_id(search_term, artist_name, api_key):
    url = "https://api.genius.com/search"
    headers = {"Authorization": f"Bearer {api_key}"}
    params = {"q": f"{search_term} {artist_name}"}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, params=params) as response:
            # Check if the request was successful
            if response.status != 200:
                print(f"Failed to get song ID. HTTP status code: {response.status}")
                return None
            response_json = await response.json()
            # Check if the response contains the expected keys
            if (
                "response" not in response_json
                or "hits" not in response_json["response"]
                or not response_json["response"]["hits"]
            ):
                print(
                    f"No results found for '{search_term} by {artist_name}'. Please try again with a different search term."
                )
                return None
            # Return the first song's ID
            song_id = response_json["response"]["hits"][0]["result"]["id"]
            return song_id


# Compile regex pattern for reuse
punctuation_pattern = re.compile(r'\s([?.!",](?:\s|$))')
def parse_description(description):
    readable_description = []

    def parse_element(element):
        if isinstance(element, str):
            readable_description.append(element.strip())
        elif isinstance(element, dict):
            if "children" in element:
                for child in element["children"]:
                    parse_element(child)
            elif "tag" in element and element["tag"] == "a":
                if "children" in element:
                    for child in element["children"]:
                        parse_element(child)
                else:
                    readable_description.append(element.get("text", "").strip())

    for item in description:
        parse_element(item)
    full_description = " ".join(filter(None, readable_description))
    full_description = punctuation_pattern.sub(r"\1", full_description)
    return full_description


async def get_song_details(song_id, api_key):
    url = f"https://api.genius.com/songs/{song_id}"
    headers = {"Authorization": f"Bearer {api_key}"}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            if response.status != 200:
                print(
                    f"Failed to get song details. HTTP status code: {response.status}"
                )
                return None
            response_json = await response.json()
            if (
                "response" not in response_json
                or "song" not in response_json["response"]
            ):
                print("Unexpected response format from Genius API.")
                return None
            song_details = response_json["response"]["song"]
            if (
                "description" not in song_details
                or "dom" not in song_details["description"]
                or "children" not in song_details["description"]["dom"]
            ):
                print("Unexpected song details format from Genius API.")
                return None
            # Parse the description
            song_description_dom = song_details["description"]["dom"]["children"]
            song_description = parse_description(song_description_dom)
            # Summarize the description
            summarized_descriptions = await summarize_text(
                [song_description],  # Wrap the description in a list
                minimum_length=75,  # Adjust these parameters as needed
                maximum_length=250,
                penalty_factor=2,
                beam_count=4,
                batch_size=1,  # Since we're summarizing a single description
            )
            if summarized_descriptions:
                song_details["description"] = summarized_descriptions[
                    0
                ]  # Use the first (and only) summary
            else:
                song_details["description"] = (
                    song_description  # Fallback to the original description if summarization fails
                )
            return song_details
'''

async def get_song_details(song_id, api_key):
    url = f"https://api.genius.com/songs/{song_id}"
    headers = {"Authorization": f"Bearer {api_key}"}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            if response.status != 200:
                print(
                    f"Failed to get song details. HTTP status code: {response.status}"
                )
                return None
            response_json = await response.json()
            if (
                "response" not in response_json
                or "song" not in response_json["response"]
            ):
                print("Unexpected response format from Genius API.")
                return None
            song_details = response_json["response"]["song"]
            if (
                "description" not in song_details
                or "dom" not in song_details["description"]
                or "children" not in song_details["description"]["dom"]
            ):
                print("Unexpected song details format from Genius API.")
                return None
            # Parse the description
            song_description_dom = song_details["description"]["dom"]["children"]
            full_description = parse_description(song_description_dom)
            # Summarize the full description
            summary = await summarize_song_description(full_description)
            if summary:
                song_details["description"] = summary
            return song_details


# Summarize the song description, trying to avoid tokanizer errors prior to the fork
async def summarize_song_description(
    full_description,
    minimum_length=75,
    maximum_length=250,
    penalty_factor=2,
    beam_count=6,
    batch_size=11,
):
    # Tokenize and summarize the full description
    tokenized_description = tokenizer(
        full_description, truncation=True, padding=True, return_tensors="pt"
    )
    try:
        summary_ids = await asyncio.to_thread(
            model.generate,
            tokenized_description["input_ids"],
            num_beams=beam_count,
            no_repeat_ngram_size=3,
            length_penalty=penalty_factor,
            min_length=minimum_length,
            max_length=maximum_length,
            early_stopping=True,
        )
        summary = tokenizer.decode(summary_ids[0], skip_special_tokens=True)
        return summary
    except Exception as e:
        print(f"Error in summarizing song description: {e}")
        return None
'''

import backoff


# Backoff strategy for rate limiting
# Modified backoff strategy to reuse an aiohttp.ClientSession
@backoff.on_exception(backoff.expo, aiohttp.ClientError, max_tries=5)
async def make_api_request(url, headers, session):
    async with session.get(url, headers=headers) as response:
        response.raise_for_status()
        return await response.json()


# Function to get the first two paginations of referents and annotations by song ID from Genius API
async def get_annotations_by_song_id(
    song_id, api_key, max_pages=2, results_per_page=20
):
    base_url = "https://api.genius.com"
    referents_url = (
        base_url
        + f"/referents?song_id={song_id}&text_format=plain&per_page={results_per_page}"
    )
    headers = {"Authorization": "Bearer " + api_key}
    all_referents = []
    pages_fetched = 0
    async with aiohttp.ClientSession() as session:
        while referents_url and pages_fetched < max_pages:
            async with session.get(referents_url, headers=headers) as response:
                if response.status != 200:
                    print(
                        f"Failed to get referents. HTTP status code: {response.status}"
                    )
                    break
                json = await response.json()
                referents = json["response"]["referents"]
                all_referents.extend(referents)
                pages_fetched += 1
                # Check for the next page
                next_page = json["response"].get(
                    "next_page"
                )  # Use .get() to avoid KeyError
                if next_page and pages_fetched < max_pages:
                    referents_url = (
                        base_url
                        + f"/referents?song_id={song_id}&text_format=plain&page={next_page}&per_page={results_per_page}"
                    )
                else:
                    referents_url = None  # No more pages left or max pages fetched
    print(f"Total number of referent-annotation pairs: {len(all_referents)}")
    return all_referents[
        : min(len(all_referents), 20)
    ]  # Ensure that no more than 20 results are returned


async def process_referent_annotations(referent, lyrics_data, used_timestamps):
    fragment = referent["fragment"]
    annotations = referent["annotations"]
    processed_annotations = []
    last_index = 0  # Initialize the last index
    for annotation in annotations:
        if "body" in annotation and "plain" in annotation["body"]:
            annotation_text = annotation["body"]["plain"]
        else:
            continue  # Skip if plain text is not available
        match_index, timestamp = await asyncio.to_thread(
            find_matching_lyric_timestamp,
            fragment,
            lyrics_data,
            used_timestamps,
            0.4,
            last_index,
        )
        if timestamp is None:
            continue  # Skip if no timestamp is found
        processed_annotation = {
            "id": str(uuid.uuid4()),
            "annotation": annotation_text,
            "lyric": fragment,
            "timestamp": timestamp,
        }
        processed_annotations.append(processed_annotation)
        # Add the timestamp to the list of used timestamps
        used_timestamps.append(timestamp)
        # Update the last_index to the index after the matched timestamp
        last_index = match_index + 1 if match_index is not None else last_index
    return processed_annotations


def find_matching_lyric_timestamp(
    fragment, lyrics_data, used_timestamps, threshold=0.3, start_index=0
):
    lyrics_list = lyrics_data.get("lyrics_with_timestamps", [])
    matcher = SequenceMatcher(None, fragment)

    for i, lyric_entry in enumerate(lyrics_list[start_index:], start=start_index):
        matcher.set_seq2(lyric_entry["lyric"])
        similarity_ratio = matcher.ratio()
        if (
            similarity_ratio >= threshold
            and lyric_entry["timestamp"] not in used_timestamps
        ):
            return i, lyric_entry["timestamp"]  # Return the index and timestamp

    return None, None  # Return None if no suitable match is found


@backoff.on_exception(backoff.expo, Exception, max_tries=5)
async def fetch_lyrics_with_syncedlyrics(artist_name, song_title):
    try:
        # Attempt to search for the synced lyrics with retry functionality
        lrc = await asyncio.to_thread(
            syncedlyrics.search, f"{song_title} {artist_name}"
        )
        if not lrc:
            logging.error(f"No lyrics found for '{song_title} by {artist_name}'.")
            return None

        # Process the lyrics if successfully fetched
        parsed_lyrics = [
            {
                "id": str(uuid.uuid4()),  # Add an "id" key with a unique UUID
                "lyric": lyric,  # 'lyric' comes after 'id'
                "timestamp": round(
                    float(timestamp[1:].split(":")[0]) * 60
                    + float(timestamp[1:].split(":")[1]),
                    1,
                ),  # 'timestamp' comes after 'lyric'
            }
            for line in lrc.split("\n")
            if line and "] " in line and len(line.split("] ")) == 2
            for timestamp, lyric in [line.split("] ")]
        ]
        return {"lyrics_with_timestamps": parsed_lyrics}
    except Exception as e:
        logging.error(
            f"An error occurred while fetching synced lyrics for '{song_title} by {artist_name}': {e}"
        )
        return None


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
    # print("No variant playlist found.")
    return None


async def fetch_playlist_url(url):
    async with aiohttp.ClientSession() as session:
        while True:  # Loop to handle redirects manually if necessary
            async with session.get(url, allow_redirects=False) as response:
                if response.status in [200, 201]:  # Check for successful response
                    content = await response.text()
                    match = re.search(r'src="h([^"]*)', content)
                    if match:
                        return "h" + match.group(
                            1
                        )  # Return the matched and reconstructed URL
                elif response.status in [
                    301,
                    302,
                    303,
                    307,
                    308,
                ]:  # Redirect status codes
                    url = response.headers[
                        "Location"
                    ]  # Update URL to the redirect location
                    continue  # Continue the loop with the new URL
                break  # Break the loop if not successful or a redirect
    #print("No playlist URL found.")
    return None


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
    # Use the generate_filename function to create a consistent filename
    base_filename = f"{artist_name.lower()}_{song_title.lower()}"
    jpg_filename = generate_filename(base_filename, "artwork.jpg")
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


async def search_song(song_title, artist_name, developer_token):
    headers = {"Authorization": "Bearer " + developer_token}
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
        return None, None, None
    song_data = json_response["results"]["songs"]["data"]
    for i, song in enumerate(song_data, start=1):
        song_name = song["attributes"]["name"]
        artist = song["attributes"]["artistName"]
        album_name = song["attributes"].get("albumName", "Single")
    bg_color, text_colors, song_duration = None, None, None
    video_downloaded = False
    for index, song in enumerate(song_data):
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
    if not video_downloaded:
        print("No animated cover art found.")
    artwork_url = (
        song_data[0]["attributes"]["artwork"]["url"]
        .replace("{w}", "3000")
        .replace("{h}", "3000")
    )
    await download_image(artwork_url, song_title, artist_name)
    bg_color = song_data[0]["attributes"]["artwork"]["bgColor"]
    text_colors = {
        "textColor1": song_data[0]["attributes"]["artwork"]["textColor1"],
        "textColor2": song_data[0]["attributes"]["artwork"]["textColor2"],
        "textColor3": song_data[0]["attributes"]["artwork"]["textColor3"],
        "textColor4": song_data[0]["attributes"]["artwork"]["textColor4"],
    }
    song_duration = song_data[0]["attributes"]["durationInMillis"]
    return bg_color, text_colors, song_duration


async def download_video_segments(segment_urls, video_dir, song_title, artist_name):
    output_dir = os.path.join(os.getcwd(), video_dir)
    os.makedirs(output_dir, exist_ok=True)
    segment_url = segment_urls[0]  # Get the first segment URL
    # Use the generate_filename function to create a consistent filename
    base_filename = f"{artist_name.lower()}_{song_title.lower()}"
    mp4_filename = generate_filename(base_filename, "AnimatedArt.mp4")
    async with aiohttp.ClientSession() as session:
        async with session.get(segment_url) as response:
            if response.status == 200:
                try:
                    content = await response.read()
                    async with aiofiles.open(
                        os.path.join(output_dir, mp4_filename), "wb"
                    ) as file:
                        await file.write(content)
                    print(f"{mp4_filename} downloaded.")
                except aiohttp.client_exceptions.ClientPayloadError:
                    print("The response payload was not fully received.")
            else:
                print(f"No AnimatedArt. Status code: {response.status}")
