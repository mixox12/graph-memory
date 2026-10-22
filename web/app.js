// Graph RAG Studio — Frontend Controller
let network = null;
let nodesDataSet = null;
let edgesDataSet = null;
let isPhysicsEnabled = true;
let csrfToken = '';

const COMMUNITY_COLORS = [
  '#4E79A7', '#F28E2B', '#E15759', '#76B7B2', '#59A14F',
  '#EDC948', '#B07AA1', '#FF9DA7', '#9C755F', '#BAB0AC',
  '#2b5c8f', '#d46b08', '#cf1322', '#08979c', '#389e0d'
];

async function ensureCsrfToken() {
  if (!csrfToken) {
    try {
      const res = await fetch('/api/auth/token');
      const data = await res.json();
      if (data.ok && data.token) {
        csrfToken = data.token;
      }
    } catch (err) {
      console.warn('Failed to fetch CSRF token:', err);
    }
  }
  return csrfToken;
}

function getSecureHeaders() {
  const headers = {
    'Content-Type': 'application/json',
    'X-Requested-With': 'XMLHttpRequest'
  };
  if (csrfToken) {
    headers['X-CSRF-Token'] = csrfToken;
  }
  return headers;
}

document.addEventListener('DOMContentLoaded', async () => {
  await ensureCsrfToken();
  fetchStats();
  initGraph();
});

async function fetchStats() {
  try {
    const res = await fetch('/api/stats');
    const data = await res.json();
    if (data.ok) {
      const neo = data.neo4j;
      const gfy = data.localGraph;
      document.getElementById('stat-nodes').textContent = (neo.totalNodes || 0).toLocaleString();
      document.getElementById('stat-graphify-nodes').textContent = (gfy.totalNodes || 0).toLocaleString();
      
      const p = neo.plugins || {};
      const pill = document.getElementById('pill-plugins');
      pill.innerHTML = `<span class="dot"></span> Plugins: APOC (${p.apoc?.proceduresCount || 0}) · GDS (${p.gds?.proceduresCount || 0}) · GenAI (${p.genai?.proceduresCount || 0})`;
    }
  } catch (err) {
    console.error('Failed to fetch stats:', err);
  }
}

async function initGraph(searchQuery = '') {
  try {
    const url = searchQuery ? `/api/graph?search=${encodeURIComponent(searchQuery)}` : '/api/graph';
    const res = await fetch(url);
    const data = await res.json();
    
    if (!data.ok) return;

    const formattedNodes = data.nodes.map(n => {
      const color = COMMUNITY_COLORS[Math.abs(n.group || 0) % COMMUNITY_COLORS.length];
      return {
        id: n.id,
        label: n.label,
        title: n.title,
        value: n.value || 15,
        color: {
          background: color,
          border: '#ffffff',
          highlight: { background: '#ffffff', border: color }
        },
        font: { color: '#ffffff', size: 12, face: '-apple-system, sans-serif' }
      };
    });

    const formattedEdges = data.edges.map((e, idx) => ({
      id: `e-${idx}`,
      from: e.from,
      to: e.to,
      title: e.title,
      arrows: 'to',
      color: { color: '#2a344d', highlight: '#60a5fa' },
      smooth: { type: 'continuous' }
    }));

    nodesDataSet = new vis.DataSet(formattedNodes);
    edgesDataSet = new vis.DataSet(formattedEdges);

    const container = document.getElementById('network-canvas');
    const graphData = { nodes: nodesDataSet, edges: edgesDataSet };
    const options = {
      nodes: {
        shape: 'dot',
        scaling: { min: 8, max: 40 }
      },
      edges: {
        width: 1.2,
        selectionWidth: 2.5
      },
      physics: {
        stabilization: { iterations: 100 },
        barnesHut: {
          gravitationalConstant: -3500,
          springConstant: 0.04,
          springLength: 95
        }
      },
      interaction: {
        hover: true,
        tooltipDelay: 100,
        hideEdgesOnDrag: true
      }
    };

    network = new vis.Network(container, graphData, options);

    network.on('click', async (params) => {
      if (params.nodes.length > 0) {
        const nodeId = params.nodes[0];
        inspectNode(nodeId);
      }
    });

  } catch (err) {
    console.error('Failed to initialize graph:', err);
  }
}

async function inspectNode(nodeId) {
  const container = document.getElementById('inspector-content');
  container.innerHTML = '<div class="placeholder-text">Loading component details...</div>';
  
  try {
    await ensureCsrfToken();
    const res = await fetch('/api/explain', {
      method: 'POST',
      headers: getSecureHeaders(),
      body: JSON.stringify({ nodeId })
    });
    const data = await res.json();
    
    if (!data.found && !data.name) {
      container.innerHTML = `<div class="placeholder-text">Node ${nodeId} not found.</div>`;
      return;
    }

    const outRels = (data.outgoing || []).map(r => `<div>──[:${r.rel}]─➔ <b>${r.target}</b></div>`).join('');
    const inRels = (data.incoming || []).map(r => `<div>◀──[:${r.rel}]── <b>${r.source}</b></div>`).join('');

    container.innerHTML = `
      <div style="font-size: 13px; font-weight: 700; color: #fff; margin-bottom: 4px;">${data.name || data.id}</div>
      <div><b>Labels:</b> ${(data.labels || []).join(', ') || 'Entity'}</div>
      <div><b>Community:</b> ${data.community ?? 'N/A'}</div>
      ${data.outgoing?.length ? `<div style="margin-top:6px;"><b>Outgoing (${data.outgoing.length}):</b><div class="inspector-rel-list">${outRels}</div></div>` : ''}
      ${data.incoming?.length ? `<div style="margin-top:6px;"><b>Incoming (${data.incoming.length}):</b><div class="inspector-rel-list">${inRels}</div></div>` : ''}
    `;
  } catch (err) {
    container.innerHTML = `<div class="placeholder-text">Error inspecting node: ${err.message}</div>`;
  }
}

async function executeRagQuery() {
  const input = document.getElementById('rag-query-input');
  const question = input.value.trim();
  if (!question) return;

  const promptBox = document.getElementById('prompt-context-box');
  promptBox.value = 'Running hybrid Graph RAG retrieval across Neo4j & Graphify...';

  try {
    await ensureCsrfToken();
    const res = await fetch('/api/query', {
      method: 'POST',
      headers: getSecureHeaders(),
      body: JSON.stringify({ question })
    });
    const data = await res.json();

    if (data.ok) {
      promptBox.value = data.contextBlock;

      // Highlight matched seed nodes on the canvas
      const matchedIds = data.seedNodes.map(s => s.id || s.name).filter(Boolean);
      if (matchedIds.length > 0 && network) {
        network.selectNodes(matchedIds);
        network.fit({ nodes: matchedIds, animation: true });
        inspectNode(matchedIds[0]);
      }
    }
  } catch (err) {
    promptBox.value = `Error executing query: ${err.message}`;
  }
}

async function findShortestPath() {
  const from = document.getElementById('path-from').value.trim();
  const to = document.getElementById('path-to').value.trim();
  const resBox = document.getElementById('path-result');
  
  if (!from || !to) return;
  resBox.style.display = 'block';
  resBox.textContent = 'Calculating shortest path...';

  try {
    await ensureCsrfToken();
    const res = await fetch('/api/path', {
      method: 'POST',
      headers: getSecureHeaders(),
      body: JSON.stringify({ from, to })
    });
    const data = await res.json();

    if (!data.found || !data.nodes?.length) {
      resBox.textContent = `No path found between ${from} and ${to}.`;
      return;
    }

    const route = [];
    for (let i = 0; i < data.nodes.length; i++) {
      route.push(data.nodes[i]);
      if (i < (data.rels || []).length) {
        route.push(`──[:${data.rels[i]}]──➔`);
      }
    }

    resBox.innerHTML = `<b>${data.hops} hops (${data.source}):</b><br>${route.join(' ')}`;

    // Highlight path nodes in network
    if (network && nodesDataSet) {
      const pathNodeIds = data.nodes.filter(nid => nodesDataSet.get(nid));
      if (pathNodeIds.length > 0) {
        network.selectNodes(pathNodeIds);
        network.fit({ nodes: pathNodeIds, animation: true });
      }
    }
  } catch (err) {
    resBox.textContent = `Error: ${err.message}`;
  }
}

async function openModal(modalId) {
  const m = document.getElementById(modalId);
  if (!m) return;
  m.classList.add('active');

  if (modalId === 'pagerank-modal') {
    loadPageRankLeaderboard();
  }
}

function closeModal(modalId) {
  const m = document.getElementById(modalId);
  if (m) m.classList.remove('active');
}

async function loadPageRankLeaderboard() {
  const list = document.getElementById('pagerank-list');
  list.innerHTML = '<div class="placeholder-text">Computing PageRank god nodes via GDS...</div>';

  try {
    const res = await fetch('/api/pagerank');
    const data = await res.json();
    if (data.ok && Array.isArray(data.nodes)) {
      list.innerHTML = data.nodes.map((n, i) => `
        <div class="leaderboard-row" onclick="selectGodNode('${n.name}')" style="cursor: pointer;">
          <span class="lb-rank">#${i + 1}</span>
          <span class="lb-name">${n.name} <span class="lb-meta">(${n.labels?.[0] || 'Entity'})</span></span>
          <span class="lb-degree">Degree: ${n.degree}</span>
        </div>
      `).join('');
    }
  } catch (err) {
    list.innerHTML = `<div class="placeholder-text">Error: ${err.message}</div>`;
  }
}

function selectGodNode(name) {
  closeModal('pagerank-modal');
  initGraph(name);
  setTimeout(() => {
    inspectNode(name);
  }, 400);
}

function setCypherExample(type) {
  const input = document.getElementById('cypher-input');
  if (type === 'apoc') {
    input.value = 'CALL apoc.meta.stats() YIELD nodeCount, relCount, labelCount RETURN nodeCount, relCount, labelCount';
  } else if (type === 'labels') {
    input.value = 'CALL db.labels() YIELD label RETURN label';
  } else if (type === 'pagerank') {
    input.value = 'MATCH (n:Entity) RETURN n.name AS component, count{(n)--()} AS degree ORDER BY degree DESC LIMIT 10';
  }
}

async function runCypherFromModal() {
  const statement = document.getElementById('cypher-input').value.trim();
  const output = document.getElementById('cypher-output');
  output.textContent = 'Executing Cypher...';

  try {
    await ensureCsrfToken();
    const res = await fetch('/api/cypher', {
      method: 'POST',
      headers: getSecureHeaders(),
      body: JSON.stringify({ statement })
    });
    const data = await res.json();
    if (!data.ok) {
      output.textContent = `Security/Error: ${data.error || 'Execution failed'}`;
    } else {
      output.textContent = JSON.stringify(data.results, null, 2);
    }
  } catch (err) {
    output.textContent = `Cypher execution failed: ${err.message}`;
  }
}

async function triggerSync() {
  if (!confirm('Sync Graphify AST knowledge graph into Neo4j?')) return;
  alert('Sync triggered in background! Check terminal for progress.');
  try {
    await ensureCsrfToken();
    await fetch('/api/sync', {
      method: 'POST',
      headers: getSecureHeaders()
    });
  } catch {}
}

function copyPromptContext() {
  const box = document.getElementById('prompt-context-box');
  box.select();
  document.execCommand('copy');
  alert('LLM Context Block copied to clipboard!');
}

function zoomIn() {
  if (!network) return;
  const scale = network.getScale() * 1.3;
  network.moveTo({ scale, animation: true });
}

function zoomOut() {
  if (!network) return;
  const scale = network.getScale() * 0.7;
  network.moveTo({ scale, animation: true });
}

function togglePhysics() {
  if (!network) return;
  isPhysicsEnabled = !isPhysicsEnabled;
  network.setOptions({ physics: { enabled: isPhysicsEnabled } });
  document.getElementById('btn-physics').textContent = isPhysicsEnabled ? '⚡ Physics' : '⏸️ Static';
}

function resetView() {
  if (network) network.fit({ animation: true });
}
