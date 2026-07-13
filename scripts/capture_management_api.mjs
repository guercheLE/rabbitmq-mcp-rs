const cdpUrl = process.env.RABBITMQ_CDP_URL;
const baseUrl = process.env.RABBITMQ_BASE_URL;
const username = process.env.RABBITMQ_RUNTIME_USER;
const password = process.env.RABBITMQ_RUNTIME_PASSWORD;

if (!cdpUrl || !baseUrl || !username || !password) {
  throw new Error("RABBITMQ_CDP_URL, RABBITMQ_BASE_URL, RABBITMQ_RUNTIME_USER, and RABBITMQ_RUNTIME_PASSWORD are required");
}

const sleep = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));

async function pageTarget() {
  const response = await fetch(`${cdpUrl}/json/list`);
  if (!response.ok) throw new Error(`CDP target discovery failed: ${response.status}`);
  const targets = await response.json();
  const target = targets.find(candidate => candidate.type === "page");
  if (!target) throw new Error("Chrome did not expose a page target");
  return target;
}

class CdpClient {
  constructor(webSocketUrl) {
    this.socket = new WebSocket(webSocketUrl);
    this.nextId = 1;
    this.pending = new Map();
    this.listeners = new Map();
  }

  async connect() {
    await new Promise((resolve, reject) => {
      this.socket.addEventListener("open", resolve, { once: true });
      this.socket.addEventListener("error", reject, { once: true });
    });
    this.socket.addEventListener("message", event => {
      const message = JSON.parse(event.data);
      if (message.id) {
        const pending = this.pending.get(message.id);
        if (!pending) return;
        this.pending.delete(message.id);
        if (message.error) pending.reject(new Error(message.error.message));
        else pending.resolve(message.result || {});
        return;
      }
      for (const listener of this.listeners.get(message.method) || []) {
        Promise.resolve(listener(message.params || {})).catch(() => {});
      }
    });
  }

  send(method, params = {}) {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.socket.send(JSON.stringify({ id, method, params }));
    });
  }

  on(method, listener) {
    const listeners = this.listeners.get(method) || [];
    listeners.push(listener);
    this.listeners.set(method, listeners);
  }

  close() {
    this.socket.close();
  }
}

function apiPath(url) {
  try {
    const parsed = new URL(url);
    return parsed.pathname.startsWith("/api/") ? `${parsed.pathname}${parsed.search}` : null;
  } catch {
    return null;
  }
}

function jsonValue(value) {
  if (!value) return null;
  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
}

const target = await pageTarget();
const client = new CdpClient(target.webSocketDebuggerUrl);
await client.connect();
await Promise.all([client.send("Network.enable"), client.send("Page.enable"), client.send("Runtime.enable")]);

const requests = new Map();
const observations = [];
const pendingBodies = new Set();

client.on("Network.requestWillBeSent", event => {
  const path = apiPath(event.request.url);
  if (!path) return;
  const requestHeaders = {};
  for (const [name, value] of Object.entries(event.request.headers || {})) {
    if (!["authorization", "cookie"].includes(name.toLowerCase())) requestHeaders[name] = String(value);
  }
  requests.set(event.requestId, {
    source: "browser",
    method: event.request.method,
    path,
    request: jsonValue(event.request.postData),
    requestHeaders,
    response: null,
  });
});

client.on("Network.responseReceived", event => {
  const observation = requests.get(event.requestId);
  if (!observation) return;
  observation.status = Math.trunc(event.response.status);
  observation.mimeType = event.response.mimeType || "";
});

client.on("Network.loadingFinished", event => {
  const observation = requests.get(event.requestId);
  if (!observation || !observation.status) return;
  const pending = (async () => {
    try {
      const result = await client.send("Network.getResponseBody", { requestId: event.requestId });
      const body = result.base64Encoded
        ? Buffer.from(result.body, "base64").toString("utf8")
        : result.body;
      if (Buffer.byteLength(body, "utf8") <= 2_000_000) observation.response = jsonValue(body);
    } catch {
      observation.response = null;
    }
    delete observation.mimeType;
    observations.push(observation);
    requests.delete(event.requestId);
  })();
  pendingBodies.add(pending);
  pending.finally(() => pendingBodies.delete(pending));
});

async function navigate(url) {
  await client.send("Page.navigate", { url });
  await sleep(1800);
}

async function submitManagementForm(formPattern, fields, submitPattern) {
  const expression = `(() => {
    const formPattern = new RegExp(${JSON.stringify(formPattern)}, 'i');
    const submitPattern = new RegExp(${JSON.stringify(submitPattern)}, 'i');
    const fields = ${JSON.stringify(fields)};
    const forms = [...document.querySelectorAll('form')];
    const form = forms.find(candidate => {
      if (formPattern.test(candidate.textContent || '')) return true;
      return [...candidate.querySelectorAll('button, input[type="submit"], input[type="button"]')]
        .some(control => submitPattern.test(control.textContent || control.value || ''));
    });
    if (!form) return { submitted: false, reason: 'form-not-found' };
    const populated = [];
    for (const [name, value] of Object.entries(fields)) {
      const selector = '[name="' + CSS.escape(name) + '"]';
      const input = form.querySelector(selector) || document.querySelector(selector);
      if (!input) continue;
      if (input.type === 'checkbox') input.checked = Boolean(value);
      else input.value = String(value);
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.dispatchEvent(new Event('change', { bubbles: true }));
      populated.push(name);
    }
    const controls = [...form.querySelectorAll('button, input[type="submit"], input[type="button"]')];
    const submit = controls.find(control => submitPattern.test(control.textContent || control.value || ''));
    if (!submit) return { submitted: false, reason: 'submit-not-found', populated };
    submit.click();
    return { submitted: true, populated };
  })()`;
  const result = await client.send("Runtime.evaluate", { expression, returnByValue: true });
  await sleep(1800);
  return result.result?.value || { submitted: false, reason: "no-result" };
}

async function formInventory() {
  const result = await client.send("Runtime.evaluate", {
    expression: `JSON.stringify([...document.querySelectorAll('form')].map(form => ({
      text: (form.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 240),
      inputs: [...form.querySelectorAll('input, select, textarea')].map(input => ({
        name: input.name || '', type: input.type || input.tagName.toLowerCase(), value: input.value || ''
      })),
      controls: [...form.querySelectorAll('button, input[type="submit"], input[type="button"]')]
        .map(control => (control.textContent || control.value || '').trim())
    })))`,
    returnByValue: true,
  });
  try {
    return JSON.parse(result.result?.value || "[]");
  } catch {
    return [];
  }
}

await navigate(baseUrl);
const loginExpression = `(() => {
  const username = ${JSON.stringify(username)};
  const password = ${JSON.stringify(password)};
  const userInput = document.querySelector('#username, input[name="username"], input[type="text"]');
  const passwordInput = document.querySelector('#password, input[name="password"], input[type="password"]');
  if (!userInput || !passwordInput) return false;
  userInput.value = username;
  passwordInput.value = password;
  userInput.dispatchEvent(new Event('input', { bubbles: true }));
  passwordInput.dispatchEvent(new Event('input', { bubbles: true }));
  const form = passwordInput.closest('form');
  if (form && form.requestSubmit) form.requestSubmit();
  else {
    const submit = document.querySelector('input[type="submit"], button[type="submit"]');
    if (submit) submit.click();
  }
  return true;
})()`;
const login = await client.send("Runtime.evaluate", { expression: loginExpression, returnByValue: true });
if (!login.result?.value) throw new Error("RabbitMQ Management login form was not found");
await sleep(2500);

const routes = [
  "#/",
  "#/connections",
  "#/channels",
  "#/exchanges",
  "#/queues",
  "#/admin",
  "#/users",
  "#/vhosts",
  "#/permissions",
  "#/policies",
  "#/limits",
  "#/feature-flags",
];
for (const route of routes) {
  await navigate(`${baseUrl.replace(/\/$/, "")}/${route}`);
}

const encodedVhost = encodeURIComponent("openapi-probe");
const encodedExchange = encodeURIComponent("openapi-probe-exchange");
const encodedQueue = encodeURIComponent("openapi-probe-queue");
const diagnostics = [];

await navigate(`${baseUrl.replace(/\/$/, "")}/#/queues/${encodedVhost}/${encodedQueue}`);
diagnostics.push({ screen: "queue-binding", forms: await formInventory() });
diagnostics.push({ action: "queue-binding", result: await submitManagementForm(
  "from exchange",
  { source: "openapi-probe-exchange", routing_key: "openapi-ui" },
  "^bind$",
) });

await navigate(`${baseUrl.replace(/\/$/, "")}/#/exchanges/${encodedVhost}/${encodedExchange}`);
diagnostics.push({ screen: "exchange-publish", forms: await formInventory() });
diagnostics.push({ action: "exchange-publish", result: await submitManagementForm(
  "routing key.*payload",
  { routing_key: "openapi-ui", payload: "browser runtime probe", payload_encoding: "string" },
  "^publish message$",
) });

await navigate(`${baseUrl.replace(/\/$/, "")}/#/queues/${encodedVhost}/${encodedQueue}`);
diagnostics.push({ screen: "queue-get", forms: await formInventory() });
diagnostics.push({ action: "queue-get", result: await submitManagementForm(
  "ack mode.*messages",
  { msgs: 1, count: 1, ackmode: "ack_requeue_false", encoding: "auto", truncate: 50000 },
  "^get message\\(s\\)$",
) });

await sleep(1500);
await Promise.allSettled([...pendingBodies]);
observations.push({ source: "browser-diagnostic", diagnostics });
client.close();
process.stdout.write(JSON.stringify(observations));
