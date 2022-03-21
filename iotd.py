#! /usr/bin/env python3
import argparse
import datetime
import logging
import types
from pathlib import Path

import pytz
import toml
from pluginbase import PluginBase, PluginSource
from telegram import (InlineKeyboardButton, InlineKeyboardMarkup, ParseMode,
                      Update)
from telegram.ext import (CallbackContext, CallbackQueryHandler,
                          CommandHandler, Dispatcher, JobQueue, Updater)

MAIN_DIR = Path(__file__).parent
SECRETS_FILE = MAIN_DIR / "secrets.toml"
SUBSCRIPTIONS_CONFIG = MAIN_DIR / "subscriptions.toml"
PLUGIN_DIR = MAIN_DIR / "plugins"


def verify_secrets() -> None:
    """Verify the secrets file is configured correctly for telegram.

    Raises:
        ValueError: If the secrets file is not configured correctly.
    """
    if (
        not SECRETS_FILE.exists()
        or "telegram" not in (secrets := toml.loads(SECRETS_FILE.read_text()))
        or "bot_id" not in secrets["telegram"]
    ):
        raise ValueError(
            "There must be a toml file 'secrets.toml' "
            "with a section '[telegram]' containing the key 'bot_id = '."
        )


def get_telegram_token() -> str:
    """Determine the telegram token from the secrets file.

    Returns:
        str: The telegram token
    """
    return toml.loads(SECRETS_FILE.read_text())["telegram"]["bot_id"]


def subscriptions(user: int) -> list[str]:
    """Get the subscriptions for a user."""
    user = str(user)
    if not SUBSCRIPTIONS_CONFIG.exists():
        return []
    config = toml.loads(SUBSCRIPTIONS_CONFIG.read_text())
    if not user in config:
        return []
    return config[user].get("subscriptions", [])


def subscribe(user: int, plugin_name: str, name: str | None = None) -> None:
    """Subscrie a user to a plugin."""
    user = str(user)
    data: dict[int, [list[str]]] = {}
    if SUBSCRIPTIONS_CONFIG.exists():
        data = toml.loads(SUBSCRIPTIONS_CONFIG.read_text())
    if not user in data:
        data[user] = {}
    data[user]["subscriptions"] = list(
        set(data[user].get("subscriptions", []) + [plugin_name])
    )
    if name is not None:
        data[user]["name"] = name
    SUBSCRIPTIONS_CONFIG.write_text(toml.dumps(data))


def unsubscribe(user: int, plugin_name: str) -> None:
    """Unsubscribe a user from a plugin."""
    user = str(user)
    data: dict[int, [list[str]]] = {}
    if SUBSCRIPTIONS_CONFIG.exists():
        data = toml.loads(SUBSCRIPTIONS_CONFIG.read_text())
    if not user in data:
        data[user] = []
    if plugin_name in data[user].get("subscriptions", []):
        data[user]["subscriptions"].remove(plugin_name)
    if not data[user].get("subscriptions", []):
        del data[user]
    SUBSCRIPTIONS_CONFIG.write_text(toml.dumps(data))


def subscriber(plugin_name: str | None = None) -> list[int]:
    """Get the subscribers of a plugin. No name = all subscribers to anything."""
    if not SUBSCRIPTIONS_CONFIG.exists():
        return []
    users = toml.loads(SUBSCRIPTIONS_CONFIG.read_text())
    return [
        int(user)
        for user, userdata in users.items()
        if plugin_name is None or plugin_name in userdata.get("subscriptions", [])
    ]


class Bot:
    updater: Updater
    dispatcher: Dispatcher
    job_queue: JobQueue

    plugin_base: PluginBase
    plugin_source: PluginSource

    plugins: dict[str, types.ModuleType]

    def __init__(self, token: str) -> None:
        self.updater = Updater(token=token)
        self.dispatcher = self.updater.dispatcher
        self.job_queue = self.updater.job_queue

        self.plugins = self.load_plugins()

        self.dispatcher.add_handler(CommandHandler("start", self.start))
        self.dispatcher.add_handler(CommandHandler("stop", self.stop))
        self.dispatcher.add_handler(CommandHandler("subscriptions", self.subscriptions))
        self.dispatcher.add_handler(CallbackQueryHandler(self.callback))

    def run(self) -> None:
        """Run the main loop."""
        self.schedule_plugin_messages()
        self.updater.start_polling()
        self.updater.idle()

    def load_plugins(self) -> dict[str, types.ModuleType]:
        """Load all plugins that meet the requirements."""
        self.plugin_base = PluginBase(package="iotd.plugins")
        self.plugin_source = self.plugin_base.make_plugin_source(
            searchpath=[str(PLUGIN_DIR.resolve())]
        )
        plugin_names = self.plugin_source.list_plugins()
        plugins: dict[str, types.ModuleType] = {}
        plugins = {
            plugin_name: plugin
            for plugin_name in plugin_names
            if hasattr(plugin := self.plugin_source.load_plugin(plugin_name), "HOUR")
            and hasattr(plugin, "MINUTE")
            and hasattr(plugin, "run")
        }
        return plugins

    def schedule_plugin_messages(self) -> None:
        """Schedule the plugins to run at their desired times."""
        for plugin_name, plugin in self.plugins.items():
            self.job_queue.run_daily(
                self.run_plugin,
                time=datetime.time(
                    hour=self.plugin_hour(plugin),
                    minute=self.plugin_minute(plugin),
                    second=0,
                    tzinfo=pytz.timezone("Europe/Berlin"),
                ),
                name=plugin_name,
            )

    def run_plugin(self, context: CallbackContext) -> None:
        """Run a plugin. Plugin name equals job name. Used a scheduler callback."""
        self.run_plugin_named(context.job.name)

    def run_plugin_named(self, plugin_name: str) -> None:
        """Run a plugin."""
        if plugin_name in self.plugins:
            subscribers = subscriber(plugin_name)
            logging.info(f"Running: {plugin_name} for {len(subscribers)} subscriber[s]")
            self.plugins[plugin_name].run(
                self.updater.bot,
                subscribers,
                toml.loads(SECRETS_FILE.read_text()),
            )
        else:
            logging.error(f"Running (not found): {plugin_name}")

    def plugin_long_name(self, plugin: types.ModuleType, plugin_name: str) -> str:
        """Get the long name (description) of a plugin."""
        return getattr(plugin, "NAME", plugin_name)

    def plugin_long_name_from_short_name(self, plugin_name: str) -> str | None:
        """Get the long name (description) of a plugin from its short name."""
        if plugin_name in self.plugins:
            return self.plugin_long_name(self.plugins[plugin_name], plugin_name)
        return None

    def plugin_hour(self, plugin: types.ModuleType) -> int:
        """Get the hour a plugin wants to run at."""
        return getattr(plugin, "HOUR", 0)

    def plugin_minute(self, plugin: types.ModuleType) -> int:
        """Get the minute a plugin wants to run at."""
        return getattr(plugin, "MINUTE", 0)

    def psa(self, message: str) -> None:
        """Send a PSA to all users."""
        chat_ids = subscriber()
        logging.info(f"PSAing {len(chat_ids)} people.")
        for chat_id in chat_ids:
            try:
                self.updater.bot.send_message(
                    chat_id=chat_id, text=message, parse_mode=ParseMode.MARKDOWN_V2
                )
            except Exception as e:
                logging.error(f"'{e}' for {chat_id}")

    ################
    # Bot Commands #
    ################

    def start(self, update: Update, context: CallbackContext) -> None:
        """Subscribe to a new plugin."""
        message = (
            "I am a telegram bot created by Hans that can send you daily images for a "
            "bunch of topics. What do you want to subscribe to?"
        )
        user_subscriptions = subscriptions(update.effective_chat.id)
        subscribeable_plugins = {
            plugin_name: plugin
            for plugin_name, plugin in self.plugins.items()
            if plugin_name not in user_subscriptions
        }
        if not subscribeable_plugins:
            update.message.reply_text(
                r"You already subscribe to <b>everything</b>. :)",
                parse_mode=ParseMode.HTML,
            )
            return
        reply_markup = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        self.plugin_long_name(plugin, plugin_name),
                        callback_data=f"subscribe {plugin_name}",
                    )
                ]
                for plugin_name, plugin in subscribeable_plugins.items()
            ]
        )
        update.message.reply_text(message, reply_markup=reply_markup)

    def stop(self, update: Update, context: CallbackContext) -> None:
        """Unsubscribe from a plugin."""
        message = "What do you want to unsubscribe from?"
        user_subscriptions = subscriptions(update.effective_chat.id)
        unsubscribeable_plugins = {
            plugin_name: plugin
            for plugin_name, plugin in self.plugins.items()
            if plugin_name in user_subscriptions
        }
        if not unsubscribeable_plugins:
            update.message.reply_text("You don't subscribe to anything yet.")
            return
        reply_markup = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        self.plugin_long_name(plugin, plugin_name),
                        callback_data=f"unsubscribe {plugin_name}",
                    )
                ]
                for plugin_name, plugin in unsubscribeable_plugins.items()
            ]
        )
        update.message.reply_text(message, reply_markup=reply_markup)

    def subscriptions(self, update: Update, context: CallbackContext) -> None:
        """List subscriptions."""
        user_subscriptions = subscriptions(update.effective_chat.id)
        message = (
            "\n".join(
                ("✅ " if plugin_name in user_subscriptions else "❌ ")
                + self.plugin_long_name(plugin, plugin_name)
                for plugin_name, plugin in self.plugins.items()
            )
            + "\n\nSubscribe with /start and unsubscribe with /stop"
        )
        update.message.reply_text(message)

    def callback(self, update: Update, context: CallbackContext) -> None:
        """Handle callback for subscribe or unsubscribe action."""
        reply = update.callback_query.data
        chat = update.callback_query.message.chat
        action, plugin = reply.split(" ")
        if action == "subscribe":
            subscribe(
                update.effective_chat.id,
                plugin,
                name=f"{chat.first_name} {chat.last_name}",
            )
            context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Successfully subscribed to "
                + (self.plugin_long_name_from_short_name(plugin) or "???"),
            )
            logging.info(
                f"Subscribe: {chat.first_name} {chat.last_name} ({chat.id}) "
                f"to {plugin}"
            )
        elif action == "unsubscribe":
            unsubscribe(update.effective_chat.id, plugin)
            context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Successfully unsubscribed from "
                + (self.plugin_long_name_from_short_name(plugin) or "???"),
            )
            logging.info(
                f"Unsubscribe: {chat.first_name} {chat.last_name} ({chat.id}) "
                f"from {plugin}"
            )


def main() -> None:
    # Setup
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    verify_secrets()
    bot = Bot(get_telegram_token())

    # Parse Command Line Arguments
    parser = argparse.ArgumentParser(
        description=(
            "\033[1mImage of the Day\033[0m: "
            "Send automated telegram messages to subscribed users."
        ),
        epilog="If no arguments are set the bot will run its main loop.",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--psa",
        help="Send a message to each user and exit. "
        "Markdown with *bold* and _italic_.",
    )
    group.add_argument(
        "--run",
        help="Run a specific plugin now (for testing).",
        choices=bot.plugins.keys(),
    )
    arguments = parser.parse_args()

    # Execute desired action
    if (psa := arguments.psa) is not None:
        bot.psa(psa)
        return
    if (plugin_name := arguments.run) is not None:
        bot.run_plugin_named(plugin_name)
        return
    bot.run()


if __name__ == "__main__":
    main()
