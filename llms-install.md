# Installing the KolaVid MCP server (for AI agents)

KolaVid is a **remote** MCP server. There is nothing to clone, build or run locally, and no API key to paste.

1. Add this server to the client's MCP settings:

   ```json
   {
     "mcpServers": {
       "kolavid": {
         "type": "streamableHttp",
         "url": "https://kolavid.com/mcp"
       }
     }
   }
   ```

   (Clients that use `"type": "http"` for streamable HTTP servers take the same URL.)

2. The first time a tool is used, the server answers 401 with an OAuth 2.1 challenge. The client registers itself
   (dynamic client registration) and opens KolaVid's sign-in page in the browser. The user signs in, or creates a
   free account, and clicks **Allow**. No secrets go in the config file.

3. Tools: `make_whiteboard_video` (topic, text or web page; 1-5 minutes; 16:9, 9:16 or 1:1; narration language),
   `get_video` (progress, then download and share links), `list_recent_videos`, `get_my_account` (credits, plan).

A video takes about 2 to 4 minutes; call `get_video` to check on it. Videos use the signed-in account's credits.
Docs: https://kolavid.com/developers. Support: support@kolavid.com.
