import { useEffect, useState } from 'react';

const api = (path, options = {}) => fetch(path, { headers: { 'Content-Type': 'application/json' }, ...options }).then(async (res) => {
  const json = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(json.error || 'API request failed');
  return json;
});

function App() {
  const [bots, setBots] = useState([]);
  const [selectedBot, setSelectedBot] = useState(null);
  const [token, setToken] = useState('');
  const [name, setName] = useState('');
  const [files, setFiles] = useState([]);
  const [activePath, setActivePath] = useState('');
  const [content, setContent] = useState('');
  const [packages, setPackages] = useState([]);
  const [newPackage, setNewPackage] = useState('');
  const [logs, setLogs] = useState([]);
  const [error, setError] = useState('');

  const loadBots = async () => {
    try {
      const data = await api('/api/bots');
      setBots(data.bots);
      if (selectedBot) {
        const bot = data.bots.find((item) => item.id === selectedBot.id);
        setSelectedBot(bot || null);
      }
    } catch (err) {
      setError(err.message);
    }
  };

  useEffect(() => {
    loadBots();
    const interval = setInterval(loadBots, 5000);
    return () => clearInterval(interval);
  }, []);

  const createBot = async () => {
    setError('');
    try {
      const data = await api('/api/bots', { method: 'POST', body: JSON.stringify({ name, token }) });
      setName('');
      setToken('');
      await loadBots();
      setSelectedBot(data.bot);
    } catch (err) {
      setError(err.message);
    }
  };

  const selectBot = async (bot) => {
    setSelectedBot(bot);
    setActivePath('');
    setContent('');
    setPackages([]);
    setLogs([]);
    await loadFiles(bot.id);
    await loadPackages(bot.id);
    await loadLogs(bot.id);
  };

  const loadFiles = async (botId) => {
    try {
      const data = await api(`/api/bots/${botId}/files`);
      setFiles(data.files);
    } catch (err) {
      setError(err.message);
    }
  };

  const loadFile = async (botId, path) => {
    try {
      const data = await api(`/api/bots/${botId}/file?path=${encodeURIComponent(path)}`);
      setActivePath(path);
      setContent(data.content);
    } catch (err) {
      setError(err.message);
    }
  };

  const saveFile = async () => {
    if (!selectedBot || !activePath) return;
    try {
      await api(`/api/bots/${selectedBot.id}/file`, { method: 'POST', body: JSON.stringify({ path: activePath, content }) });
      await loadFiles(selectedBot.id);
    } catch (err) {
      setError(err.message);
    }
  };

  const loadPackages = async (botId) => {
    try {
      const data = await api(`/api/bots/${botId}/packages`);
      setPackages(data.packages);
    } catch (err) {
      setError(err.message);
    }
  };

  const addPackage = async () => {
    if (!selectedBot || !newPackage.trim()) return;
    try {
      const data = await api(`/api/bots/${selectedBot.id}/package`, { method: 'POST', body: JSON.stringify({ package: newPackage.trim() }) });
      setPackages(data.packages);
      setNewPackage('');
    } catch (err) {
      setError(err.message);
    }
  };

  const action = async (botId, actionName) => {
    try {
      await api(`/api/bots/${botId}/${actionName}`, { method: 'POST' });
      await loadBots();
      await loadLogs(botId);
    } catch (err) {
      setError(err.message);
    }
  };

  const loadLogs = async (botId) => {
    try {
      const data = await api(`/api/bots/${botId}/logs`);
      setLogs(data.logs);
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div>@2bc</div>
          <div>Bot Panel</div>
        </div>
        <section className="panel">
          <h2>Add bot</h2>
          <label>
            Name
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Bot name" />
          </label>
          <label>
            Token
            <input value={token} onChange={(e) => setToken(e.target.value)} placeholder="Bot token" />
          </label>
          <button onClick={createBot}>Create bot</button>
        </section>
        <section className="panel">
          <h2>Bots</h2>
          <div className="bot-list">
            {bots.map((bot) => (
              <button key={bot.id} className={selectedBot?.id === bot.id ? 'active' : ''} onClick={() => selectBot(bot)}>
                <span>{bot.name}</span>
                <small>{bot.status}</small>
              </button>
            ))}
          </div>
        </section>
      </aside>
      <main className="workspace">
        {error && <div className="message error">{error}</div>}
        {!selectedBot ? (
          <div className="empty-state">
            <h1>@2bc Bot Panel</h1>
            <p>Select a bot to manage it, or create one on the left.</p>
          </div>
        ) : (
          <div className="bot-dashboard">
            <header className="bot-header">
              <div>
                <h1>{selectedBot.name}</h1>
                <p>Status: {selectedBot.status}</p>
              </div>
              <div className="button-group">
                <button onClick={() => action(selectedBot.id, 'start')}>Start</button>
                <button onClick={() => action(selectedBot.id, 'restart')}>Restart</button>
                <button onClick={() => action(selectedBot.id, 'kill')}>Kill</button>
              </div>
            </header>

            <div className="grid-two">
              <section className="panel">
                <h2>Files</h2>
                <div className="file-list">
                  {files.map((file) => (
                    <button key={file.path} onClick={() => loadFile(selectedBot.id, file.path)} className={activePath === file.path ? 'active' : ''}>
                      {file.path}
                    </button>
                  ))}
                </div>
              </section>
              <section className="panel">
                <h2>Packages</h2>
                <div className="package-list">
                  {packages.map((pkg) => (
                    <div key={pkg} className="package-item">{pkg}</div>
                  ))}
                </div>
                <div className="package-add">
                  <input value={newPackage} onChange={(e) => setNewPackage(e.target.value)} placeholder="discord.py" />
                  <button onClick={addPackage}>Add</button>
                </div>
              </section>
            </div>

            <section className="panel file-editor">
              <div className="editor-header">
                <h2>{activePath || 'Select a file'}</h2>
                <button onClick={saveFile} disabled={!activePath}>Save file</button>
              </div>
              <textarea value={content} onChange={(e) => setContent(e.target.value)} placeholder="Open a file to edit" />
            </section>

            <section className="panel logs-panel">
              <h2>Logs</h2>
              <div className="logs">
                {logs.slice().reverse().map((line, index) => (
                  <div key={index} className="log-line">{line}</div>
                ))}
              </div>
            </section>
          </div>
        )}
      </main>
    </div>
  );
}

export default App;
