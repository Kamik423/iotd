# Image of the Day

Run Telegram bots at specified time.
The users can manage subscriptions to various plugins.

Create a `secrets.toml` file looking like this:

```toml
[telegram]
bot_id = "123:xxx"

[reddit]
client_id = "xxx"
client_secret = "xxx"
password = "xxx"
user_agent = "SRIOTD"
username = "xxx"
```

`[telegram]` is required for the telegram bot, `[reddit]` for the red panda of the day.
If you do not use this plugin you can just remove it.

To create new plugins just put them in the plugins folder. 
They must have two variables named `HOUR` and `MINUTE` to define their daily run time.
Additionally a function `run` is required:

```python
from telegram import Bot
def run(bot: Bot, chat_ids: list[int], secrets: dict[str, dict[str, str]]) -> None:
    ...
```

It uses the telegram-python-api.
The `chat_ids` passed are the clients to send to.
The `secrets` is the deserialized content of the secrets file.

You can also provide a better name than just the plugin's file name in a `NAME` variable.