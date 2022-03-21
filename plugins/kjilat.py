from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml
from telegram import Bot

NAME = "Kim Jong-Il Looking at Things"
HOUR = 14
MINUTE = 47

IMAGE_CONFIG = Path(__file__).parent / "kjilat_shuffled.yaml"


def day() -> int:
    """Day since 1970."""
    return (datetime.utcnow() - datetime(1970, 1, 1)).days


@dataclass
class Image:
    """A wrapper for image data."""

    index: int
    title: str
    url: str

    @classmethod
    def for_index(cls, index: int, images: list[dict[str, str]]) -> Image:
        index %= len(images)
        image = images[index]
        return Image(index=index, title=image["img"], url=image["src"])

    @classmethod
    def daily(cls) -> Image:
        return Image.for_index(
            day(), yaml.load(IMAGE_CONFIG.read_text(), Loader=yaml.FullLoader)
        )


def run(bot: Bot, chat_ids: list[int], secrets: dict[str, dict[str, str]]) -> None:
    image = Image.daily()
    for chat_id in chat_ids:
        try:
            bot.send_photo(chat_id=chat_id, photo=image.url, caption=image.title)
        except Exception as e:
            logging.error(f"'{e}' for {chat_id}")
