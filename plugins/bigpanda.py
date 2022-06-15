import datetime
import itertools
import logging
import random
from pathlib import Path

import praw
import requests
from telegram import Bot, ParseMode

NAME = "STD Panda of the Day"
HOUR = 8
MINUTE = 51

SCIRPT_DIR = Path(__file__).parent

POST_CACHE_COUNT = 32
CACHE = SCIRPT_DIR / "std_panda_cache.txt"


def get_cache() -> list[str]:
    """Get the cache of the latest image URLs for duplicate detection."""
    if not CACHE.exists():
        return []
    return [entry for entry in CACHE.read_text().split("\n") if entry]


def cache(entry: str) -> None:
    """Cache a new image URL for duplicate detection."""
    CACHE.write_text("\n".join((get_cache() + [entry])[-POST_CACHE_COUNT:]))


def post_of_the_day(reddit: praw.Reddit, subreddit="panda") -> tuple[str, str]:
    """Returns image URL and post URL"""
    subreddit = reddit.subreddit(subreddit)
    top_posts = subreddit.top("day", limit=10)
    fallback_posts = list(subreddit.top(limit=100))
    random.shuffle(fallback_posts)
    for post in itertools.chain(top_posts, fallback_posts):
        try:
            image_url = post.preview["images"][0]["source"]["url"]
            post_url = "https://reddit.com" + post.permalink
            if image_url in get_cache():
                logging.warning("Image already known, skipping")
            else:
                return (image_url, post_url)
        except (KeyError, IndexError, AttributeError):
            logging.warning("Imageless post, skipping")
    logging.info("no image found. obi wan.")
    return (
        "https://i.redd.it/f46azqiqcg411.jpg",
        "https://www.youtube.com/watch?v=rEq1Z0bjdwc",
    )


def run(bot: Bot, chat_ids: list[int], secrets: dict[str, dict[str, str]]) -> None:
    reddit = praw.Reddit(
        client_id=secrets["reddit"]["client_id"],
        client_secret=secrets["reddit"]["client_secret"],
        password=secrets["reddit"]["password"],
        user_agent=secrets["reddit"]["user_agent"],
        username=secrets["reddit"]["username"],
    )
    image_url, post_url = post_of_the_day(reddit)
    cache(image_url)
    today = datetime.date.today().isoformat()
    image = requests.get(image_url).content
    for chat_id in chat_ids:
        try:
            bot.send_photo(
                chat_id=chat_id,
                photo=image,
                caption=f"Good Morning Panda of the day 🤗 ({today}) "
                f'<a href="{post_url}">🐼🌐</a>',
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            logging.error(f"'{e}' for {chat_id}")
