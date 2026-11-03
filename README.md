<img src="logo.png" alt="KolaVid" width="96" height="96">

# KolaVid: whiteboard explainer videos from your chat, your code or your agent

[KolaVid](https://kolavid.com) turns a topic, a text or a web page into a narrated whiteboard explainer video
(1 to 5 minutes, 16:9, 9:16 or 1:1, narrated in many languages). This repository holds the public pieces for
developers and AI agents:

- the **remote MCP server** at `https://kolavid.com/mcp` (listed in the official MCP Registry as `com.kolavid/kolavid`)
- the **Python** and **JavaScript/TypeScript** clients for the REST API v1 (`python/`, `js/`)
- a shell **example** for the REST API (`examples/make-video.sh`)

Full API documentation: <https://kolavid.com/developers>.

## MCP server

| | |
|---|---|
| URL | `https://kolavid.com/mcp` |
| Transport | Streamable HTTP |
| Sign-in | OAuth 2.1 with dynamic client registration (your client opens KolaVid's sign-in page; you click Allow) |
| Tools | `make_whiteboard_video`, `get_video`, `list_recent_videos`, `get_my_account` |

Videos use the credits of the KolaVid account you sign in with; a free account can make a short video.

**Claude (claude.ai and desktop):** Customize > Connectors > Add custom connector, URL `https://kolavid.com/mcp`.
Step-by-step guide: <https://kolavid.com/claude>.

**Claude Code:**

```bash
claude mcp add --transport http kolavid https://kolavid.com/mcp
```

**Cursor, VS Code and other clients** that read `.mcp.json` / `mcp.json`:

```json
{ "mcpServers": { "kolavid": { "type": "http", "url": "https://kolavid.com/mcp" } } }
```

Then ask, for example: *"Make a 2-minute whiteboard video explaining photosynthesis for 10-year-olds."*

## REST API

Create a key in your KolaVid account (Account > API keys), then:

```bash
curl https://kolavid.com/api/v1/videos \
  -H "Authorization: Bearer $KOLAVID_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "How vaccines work, for 12-year-olds", "length_minutes": 2}'
```

Poll `GET /api/v1/videos/{id}` until `status` is `completed`, then download `video_url`. See
[`examples/make-video.sh`](examples/make-video.sh).

## SDKs

| | Python | JavaScript / TypeScript |
|---|---|---|
| Folder | [`python/`](python) | [`js/`](js) |
| Runtime | Python 3.9+, no dependencies | Node 18+, browsers, Deno, Bun |
| Install | `pip install kolavid` ([PyPI](https://pypi.org/project/kolavid/)) | `npm install kolavid` ([npm](https://www.npmjs.com/package/kolavid)) |

```python
from kolavid import KolaVid

client = KolaVid()  # reads KOLAVID_API_KEY
video = client.videos.create(prompt="How vaccines work, for 12-year-olds", length_minutes=2)
video = client.videos.wait(video.id)
client.videos.download(video.id, "vaccines.mp4")
```

## Other ways to use KolaVid

Chrome extension, Google Docs and Slides add-on, Slack, Discord, Telegram, Zapier and Make:
<https://kolavid.com/blog/kolavid-integrations>.

## Support

support@kolavid.com, or <https://kolavid.com/support>. Licence: MIT (this repository; the KolaVid service has its
own [terms](https://kolavid.com/terms)).
