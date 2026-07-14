const fs = require('fs');
const path = require('path');
const express = require('express');
const cors = require('cors');
const { spawn } = require('child_process');

const app = express();
app.use(cors());
app.use(express.json());

const ROOT = path.resolve(__dirname);
const BOTS_DIR = path.join(ROOT, 'bots');
const BOTS_FILE = path.join(ROOT, 'bots.json');
const STATIC_DIR = path.join(ROOT, 'dist');
const PYTHON_CMD = process.env.PYTHON || process.env.PYTHON3 || 'python';

const knownPackages = {
  discord: 'discord.py',
  'discord.ext': 'discord.py',
  aiohttp: 'aiohttp',
  requests: 'requests',
};

if (!fs.existsSync(BOTS_DIR)) {
  fs.mkdirSync(BOTS_DIR, { recursive: true });
}

if (!fs.existsSync(BOTS_FILE)) {
  fs.writeFileSync(BOTS_FILE, JSON.stringify({ bots: [] }, null, 2), 'utf8');
}

const processes = {};
const logs = {};

function loadBots() {
  try {
    const raw = fs.readFileSync(BOTS_FILE, 'utf8');
    return JSON.parse(raw);
  } catch (error) {
    return { bots: [] };
  }
}

function saveBots(data) {
  fs.writeFileSync(BOTS_FILE, JSON.stringify(data, null, 2), 'utf8');
}

function botDir(botId) {
  return path.join(BOTS_DIR, botId);
}

function safePath(botId, requestedPath) {
  const base = botDir(botId);
  const target = path.resolve(base, requestedPath);
  if (!target.startsWith(base)) {
    throw new Error('Invalid file path');
  }
  return target;
}

function currentBotStatus(botId) {
  const proc = processes[botId];
  if (!proc) return 'stopped';
  return proc.killed ? 'stopped' : 'running';
}

function appendLog(botId, message) {
  if (!logs[botId]) logs[botId] = [];
  logs[botId].push(`${new Date().toISOString()} ${message}`);
  if (logs[botId].length > 250) logs[botId].shift();
}

function scanPackages(botDirPath) {
  const requirementsPath = path.join(botDirPath, 'requirements.txt');
  const mainPath = path.join(botDirPath, 'main.py');
  const found = new Set();
  if (fs.existsSync(mainPath)) {
    const source = fs.readFileSync(mainPath, 'utf8');
    for (const [module, packageName] of Object.entries(knownPackages)) {
      const regex = new RegExp(`^(?:from|import)\\s+${module}\\b`, 'm');
      if (regex.test(source)) {
        found.add(packageName);
      }
    }
  }

  if (fs.existsSync(requirementsPath)) {
    const current = fs.readFileSync(requirementsPath, 'utf8');
    const lines = current.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
    lines.forEach((line) => found.add(line));
  }

  return Array.from(found);
}

function ensurePackages(botId) {
  const dir = botDir(botId);
  const requirementsPath = path.join(dir, 'requirements.txt');
  const current = fs.existsSync(requirementsPath) ? fs.readFileSync(requirementsPath, 'utf8').split(/\r?\n/).map((line) => line.trim()).filter(Boolean) : [];
  const detected = scanPackages(dir);
  const merged = Array.from(new Set([...current, ...detected]));
  fs.writeFileSync(requirementsPath, merged.join('\n') + '\n', 'utf8');
  return merged;
}

function createBotProcess(botId, botDirPath) {
  const tokenPath = path.join(botDirPath, 'config.json');
  const mainPath = path.join(botDirPath, 'main.py');
  if (!fs.existsSync(tokenPath) || !fs.existsSync(mainPath)) {
    throw new Error('Bot folder is missing required files');
  }

  const child = spawn(PYTHON_CMD, ['main.py'], { cwd: botDirPath });
  child.stdout.on('data', (chunk) => appendLog(botId, chunk.toString().trim()));
  child.stderr.on('data', (chunk) => appendLog(botId, `ERR ${chunk.toString().trim()}`));
  child.on('exit', (code, signal) => {
    appendLog(botId, `Process exited with code=${code} signal=${signal}`);
  });
  processes[botId] = child;
  appendLog(botId, 'Bot process started');
  return child;
}

app.get('/api/bots', (req, res) => {
  const data = loadBots();
  const bots = data.bots.map((bot) => ({
    id: bot.id,
    name: bot.name,
    createdAt: bot.createdAt,
    status: currentBotStatus(bot.id),
  }));
  res.json({ bots });
});

app.post('/api/bots', (req, res) => {
  const { name, token } = req.body;
  if (!name || !token) {
    return res.status(400).json({ error: 'Name and token are required' });
  }
  const data = loadBots();
  const id = Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
  const botFolder = botDir(id);
  fs.mkdirSync(botFolder, { recursive: true });

  const mainTemplate = `import json
import discord
from discord.ext import commands

with open('config.json', 'r', encoding='utf-8') as config_file:
    config = json.load(config_file)

bot = commands.Bot(command_prefix='!', intents=discord.Intents.default())

@bot.event
async def on_ready():
    print(f'Bot ready: {bot.user}')

@bot.command()
async def ping(ctx):
    await ctx.send('Pong!')

bot.run(config['token'])
`;

  fs.writeFileSync(path.join(botFolder, 'main.py'), mainTemplate, 'utf8');
  fs.writeFileSync(path.join(botFolder, 'config.json'), JSON.stringify({ token }, null, 2), 'utf8');
  fs.writeFileSync(path.join(botFolder, 'requirements.txt'), 'discord.py\n', 'utf8');

  const newBot = { id, name, createdAt: new Date().toISOString() };
  data.bots.push(newBot);
  saveBots(data);
  res.json({ bot: newBot });
});

app.get('/api/bots/:id/files', (req, res) => {
  const { id } = req.params;
  const dir = botDir(id);
  if (!fs.existsSync(dir)) {
    return res.status(404).json({ error: 'Bot not found' });
  }

  function listDir(relativePath = '.') {
    const absolutePath = safePath(id, relativePath);
    const entries = fs.readdirSync(absolutePath, { withFileTypes: true });
    const items = [];
    for (const entry of entries) {
      if (entry.name.startsWith('.')) continue;
      const entryPath = path.join(relativePath, entry.name);
      if (entry.isDirectory()) {
        items.push({ path: entryPath, name: entry.name, type: 'folder' });
        items.push(...listDir(entryPath));
      } else {
        items.push({ path: entryPath, name: entry.name, type: 'file' });
      }
    }
    return items;
  }

  const files = listDir();
  res.json({ files });
});

app.get('/api/bots/:id/file', (req, res) => {
  const { id } = req.params;
  const filePath = req.query.path;
  if (!filePath) {
    return res.status(400).json({ error: 'File path is required' });
  }
  try {
    const absolutePath = safePath(id, filePath);
    if (!fs.existsSync(absolutePath)) {
      return res.status(404).json({ error: 'File not found' });
    }
    const content = fs.readFileSync(absolutePath, 'utf8');
    res.json({ content });
  } catch (error) {
    res.status(400).json({ error: error.message });
  }
});

app.post('/api/bots/:id/file', (req, res) => {
  const { id } = req.params;
  const { path: filePath, content } = req.body;
  if (!filePath || content == null) {
    return res.status(400).json({ error: 'File path and content are required' });
  }
  try {
    const absolutePath = safePath(id, filePath);
    fs.writeFileSync(absolutePath, content, 'utf8');
    if (filePath.endsWith('.py') || filePath === 'main.py') {
      ensurePackages(id);
    }
    res.json({ success: true });
  } catch (error) {
    res.status(400).json({ error: error.message });
  }
});

app.post('/api/bots/:id/package', (req, res) => {
  const { id } = req.params;
  const { package: packageName } = req.body;
  if (!packageName) {
    return res.status(400).json({ error: 'Package name is required' });
  }
  const dir = botDir(id);
  const requirementsPath = path.join(dir, 'requirements.txt');
  const current = fs.existsSync(requirementsPath) ? fs.readFileSync(requirementsPath, 'utf8').split(/\r?\n/).map((line) => line.trim()).filter(Boolean) : [];
  if (!current.includes(packageName)) {
    current.push(packageName);
    fs.writeFileSync(requirementsPath, current.join('\n') + '\n', 'utf8');
  }
  res.json({ packages: current });
});

app.get('/api/bots/:id/packages', (req, res) => {
  const { id } = req.params;
  const dir = botDir(id);
  const requirementsPath = path.join(dir, 'requirements.txt');
  const packages = fs.existsSync(requirementsPath) ? fs.readFileSync(requirementsPath, 'utf8').split(/\r?\n/).map((line) => line.trim()).filter(Boolean) : [];
  res.json({ packages });
});

app.post('/api/bots/:id/start', (req, res) => {
  const { id } = req.params;
  const dir = botDir(id);
  if (!fs.existsSync(dir)) {
    return res.status(404).json({ error: 'Bot not found' });
  }
  if (processes[id] && !processes[id].killed) {
    return res.json({ status: 'running' });
  }
  try {
    createBotProcess(id, dir);
    res.json({ status: 'running' });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

app.post('/api/bots/:id/kill', (req, res) => {
  const { id } = req.params;
  const proc = processes[id];
  if (!proc) {
    return res.json({ status: 'stopped' });
  }
  proc.kill();
  processes[id] = null;
  appendLog(id, 'Bot process killed');
  res.json({ status: 'stopped' });
});

app.post('/api/bots/:id/restart', async (req, res) => {
  const { id } = req.params;
  const proc = processes[id];
  if (proc && !proc.killed) {
    proc.kill();
  }
  try {
    createBotProcess(id, botDir(id));
    res.json({ status: 'running' });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

app.get('/api/bots/:id/logs', (req, res) => {
  const { id } = req.params;
  res.json({ logs: logs[id] || [] });
});

app.use(express.static(STATIC_DIR));
app.get('*', (req, res) => {
  if (req.path.startsWith('/api')) {
    return res.status(404).json({ error: 'Not found' });
  }
  res.sendFile(path.join(STATIC_DIR, 'index.html'));
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`@2bc Bot Panel server listening on port ${PORT}`);
});
