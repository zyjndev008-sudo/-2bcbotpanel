# @2bc Bot Panel

A black-and-white React dashboard with an Express API for managing multiple Python Discord bots.

## Setup
1. Install dependencies:
   ```bash
   npm install
   ```
2. Build the frontend:
   ```bash
   npm run build
   ```
3. Start the server:
   ```bash
   npm start
   ```

## Development
Run the React dev server:
```bash
npm run dev
```

## What it does
- Manage multiple Python Discord bots from one dashboard.
- Create a new bot entry with a token.
- Start, restart, or kill bot processes.
- Browse and edit bot files like a lightweight file manager.
- Add Python packages to each bot's `requirements.txt`.
- View runtime logs for each bot.

## Deployment
Railway can host this app by running `npm install`, `npm run build`, then `npm start`.

## Notes
- The dashboard serves frontend assets from `dist/`.
- Each bot folder is stored under `bots/<botId>/`.
- Bot code uses Python and dependencies are defined in `requirements.txt` per bot.
- Keep bot tokens secure and do not commit `bots.json` or `bots/` to source control.
