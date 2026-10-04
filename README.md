# Echo — multilingual Telegram relay bot

Echo is a **private, invite-only Telegram relay**. Members never sit in a shared group. Each approved person talks to the bot in a private chat; Echo translates the message into every other member's configured language and sends a new message under the admin-assigned display name.

## What this version implements

- Python 3.12
- aiogram 3.31
- Docker Compose / long polling — no domain, SSL or public port
- SQLite in one persistent Docker volume
- Admin-only onboarding: the user has **zero setup**
- One-time invite links with preset custom name + language
- Optional add-by-Telegram-ID flow; the user still has to press Start once
- Owner authorization is locked to the numeric Telegram ID after the first `/start`
- Text relay with one translation request per distinct target language
- Translation cache
- Gemini + optional DeepL + generic OpenAI-compatible fallback providers
- Admin can choose the primary provider; configured providers remain fallback chain
- Admin-only **Original view**: owner receives translation plus the original in an expandable quote
- Photo/video/animation/audio/document relayed by Telegram `file_id`, with no download, re-encode or metadata-removal pipeline
- Voice is passed through in the original language and is not translated
- Stickers/video notes get the custom name immediately before the media because Telegram does not support captions for those types
- Per-user rate limit and global Telegram send throttle
- Translation failure is reported to the sender instead of silently dropping the message
- No message body is written to SQLite
- Admin statistics: messages, media, translation errors and provider calls
- Owner broadcast, translated per member
- No message deletion and no edit synchronization

## Message format

### Text

```text
Alex
<translated text>
```

The real Telegram name, @username and forwarding metadata are not sent to other members.

### Photo / video / audio / document / animation

Echo reuses the Telegram `file_id` and sends the media with a caption:

```text
[media]

Alex
<translated caption>
```

If there is no source caption, the caption is simply the custom display name.

If the caption is too long for Telegram's caption limit, the remaining translated text is sent as a normal message immediately after the media.

### Voice

Voice is **never translated**. It is sent as the original Telegram voice message, with the custom display name as its caption (and the original voice-caption text unchanged if one exists).

### Sticker / video note

Telegram does not support captions on these types, so Echo sends:

```text
Alex
[sticker/video note]
```

## Media quality and metadata

Echo does **not** download, convert, resize, recompress, strip EXIF, run Pillow or ffmpeg, or otherwise modify media.

It passes the received Telegram `file_id` back to Telegram. This avoids a second upload/encoding step by the bot.

Important Telegram limitation: a normal Telegram **photo** has already gone through Telegram's photo processing before the bot receives it. The bot cannot recover the camera-original bytes. If exact original bytes matter, the sender should use Telegram's **Send as file/document** flow. Documents are then resent as the same Telegram-stored file.

This project deliberately does **not** implement metadata removal.

## Privacy model

Recipients receive newly sent messages from the bot, never Telegram forwards. Therefore the recipient does not see `Forwarded from <real account>`.

The bot itself necessarily sees Telegram user IDs. Those IDs and the admin's configured custom names/languages are stored in SQLite for routing.

Message bodies are not stored in the database.

If a cloud translator is enabled, message text is sent to that provider. For sensitive deployments, use a provider you trust or a self-hosted translation service later.

## Admin workflow

1. Create the bot in **@BotFather**.
2. Put the owner Telegram `@username` in `OWNER_USERNAME`.
3. Start the bot from the owner's account once.
4. Open `/admin`.
5. Choose **New invite**.
6. Enter the custom display name.
7. Choose the member's language.
8. Send the one-time invite link.
9. The member opens it and presses Start.
10. The member immediately becomes active; they do not choose any settings.

The owner can also add a numeric Telegram ID. That user still needs to press Start once because Telegram bots cannot initiate a private conversation with a user.

## Admin panel

- **Users** — view connected/pending/disabled members and enable/disable them.
- **Invites** — view pending one-time links and revoke them.
- **Original view** — owner-only toggle. When ON, the owner sees the translated version plus the original in an expandable quote. Other members never get the original automatically.
- **Translator** — see configured providers and select the primary provider.
- **Test** — send a phrase and test translation into the owner's configured language.
- **Stats** — today's relay/media/error/provider-call counters.
- **Broadcast** — owner-only announcement, translated per member.

The bot never deletes or edits chat messages.

## Translation providers

Configure the order in `.env`:

```env
PROVIDERS=gemini,deepl
```

The first provider is primary. If it fails, Echo tries the next provider.

### Gemini

Default model:

```env
GEMINI_MODEL=gemini-3.5-flash-lite
```

This is a current stable Flash-Lite model intended for high-volume, cost-sensitive workloads. Change it in `.env` if you prefer another currently available Gemini model.

### DeepL

Set:

```env
DEEPL_API_KEY=...
```

and include `deepl` in `PROVIDERS`.

### OpenAI-compatible

The adapter uses the standard `/chat/completions` shape, so it can point at OpenAI-compatible gateways:

```env
OPENAI_COMPAT_API_KEY=...
OPENAI_COMPAT_BASE_URL=https://api.openai.com/v1
OPENAI_COMPAT_MODEL=...
```

Then:

```env
PROVIDERS=gemini,openai_compat,deepl
```

A local OpenAI-compatible gateway can also be used by changing `OPENAI_COMPAT_BASE_URL`.

## Translation optimization

For one source message:

1. Echo collects all active recipients.
2. It removes the sender.
3. It skips translation for recipients whose configured language is the same as the sender's.
4. It builds a set of **distinct target languages**.
5. One provider request handles all those target languages where the provider supports it.
6. The result is cached by `(source language, target language, text)`.
7. The translated result is fanned out to every member using that language.

This avoids paying for 20 identical translations when 20 members all use Russian.

The translation prompt treats user text as untrusted data and explicitly tells the model not to follow instructions inside the message.

## Reliability

- Per-user rate limit: 20 messages/minute by default.
- Global send throttle: 20 Telegram messages/sec by default.
- Telegram 429 responses are retried.
- Temporary Telegram API errors are retried.
- If a recipient blocks the bot, that recipient is automatically paused (`started=0`) and the owner is notified.
- Messages from the same sender are serialized so rapid messages cannot overtake one another.
- SQLite uses WAL mode and a persistent Docker volume.

## Start

```bash
cp .env.example .env
# edit .env

docker compose up -d --build
docker compose logs -f bot
```

Update:

```bash
docker compose up -d --build
```

Stop:

```bash
docker compose down
```

The database remains in the Docker volume.

### Backup

```bash
docker compose cp bot:/data/bot.db ./bot-backup.db
```

### Local run without Docker

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m bot
```

## Project structure

```text
Echo/
├── bot/
│   ├── main.py
│   ├── config.py
│   ├── db.py
│   ├── languages.py
│   ├── textutil.py
│   ├── handlers/
│   │   ├── start.py
│   │   ├── admin.py
│   │   └── relay.py
│   ├── services/
│   │   ├── media.py
│   │   ├── relay.py
│   │   ├── rate_limit.py
│   │   ├── serial.py
│   │   └── tgio.py
│   └── translators/
│       ├── base.py
│       ├── http.py
│       ├── gemini.py
│       ├── deepl.py
│       ├── openai_compat.py
│       └── router.py
├── tests/
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── requirements.txt
└── README.md
```

## Deliberately excluded

- shared Telegram group mode
- forwarding messages
- message deletion
- edit synchronization
- voice-to-text
- voice translation
- EXIF stripping
- Pillow / ffmpeg
- media downloading for relay
- web admin panel
- Postgres
- webhook deployment
- MTProto/userbots
- user self-service language/name commands

The goal is a small, easy-to-deploy relay, not a large platform.
