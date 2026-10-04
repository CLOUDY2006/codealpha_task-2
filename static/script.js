const CHAT_KEY = "shopease_chat";
const THEME_KEY = "shopease_theme";
const MAX_SAVED = 50;

const messages = document.getElementById("messages");
const welcome = document.getElementById("welcome");
const input = document.getElementById("input");
const sendBtn = document.getElementById("send");
const themeBtn = document.getElementById("themeBtn");
const newChatBtn = document.getElementById("newChat");

const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
let history = loadHistory();

function loadHistory() {
  try {
    return JSON.parse(localStorage.getItem(CHAT_KEY)) || [];
  } catch (error) {
    return [];
  }
}

function saveHistory() {
  try {
    localStorage.setItem(CHAT_KEY, JSON.stringify(history.slice(-MAX_SAVED)));
  } catch (error) {}
}

function scrollDown() {
  messages.scrollTop = messages.scrollHeight;
}

function formatTime(timestamp) {
  return new Date(timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function typeText(element, text) {
  if (reduceMotion) {
    element.textContent = text;
    return Promise.resolve();
  }

  return new Promise((resolve) => {
    let position = 0;
    const timer = setInterval(() => {
      position += 2;
      element.textContent = text.slice(0, position);
      scrollDown();

      if (position >= text.length) {
        clearInterval(timer);
        resolve();
      }
    }, 14);
  });
}

async function renderMessage(entry, animate) {
  welcome.hidden = true;

  const row = document.createElement("div");
  row.className = "msg " + entry.who;

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  row.appendChild(bubble);
  messages.appendChild(row);

  if (animate && entry.who === "bot") {
    await typeText(bubble, entry.text);
  } else {
    bubble.textContent = entry.text;
  }

  if (entry.matched) {
    const matched = document.createElement("div");
    matched.className = "matched";
    matched.textContent = "Matched FAQ: " + entry.matched;
    row.appendChild(matched);
  }

  const meta = document.createElement("div");
  meta.className = "meta";
  meta.textContent = formatTime(entry.time);
  row.appendChild(meta);

  scrollDown();
}

function addSuggestions(questions) {
  if (!questions.length) return;

  const wrap = document.createElement("div");
  wrap.className = "chips";

  questions.forEach((question) => {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "chip";
    chip.textContent = question;
    chip.addEventListener("click", () => {
      wrap.remove();
      ask(question);
    });
    wrap.appendChild(chip);
  });

  messages.appendChild(wrap);
  scrollDown();
}

function showTyping() {
  const row = document.createElement("div");
  row.className = "msg bot typing";
  row.innerHTML = '<div class="bubble"><span></span><span></span><span></span></div>';
  messages.appendChild(row);
  scrollDown();
  return row;
}

async function ask(text) {
  const message = text.trim();
  if (!message) return;

  messages.querySelectorAll(".chips").forEach((chips) => chips.remove());

  const recent = history.slice(-8).map((entry) => ({
    role: entry.who === "user" ? "user" : "assistant",
    content: entry.text
  }));

  const userEntry = { who: "user", text: message, time: Date.now() };
  history.push(userEntry);
  saveHistory();
  renderMessage(userEntry, false);

  input.value = "";
  sendBtn.disabled = true;
  const typing = showTyping();

  try {
    const response = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, history: recent })
    });

    if (!response.ok) throw new Error("Server error");

    const data = await response.json();
    await new Promise((resolve) => setTimeout(resolve, 450));
    typing.remove();

    const botEntry = { who: "bot", text: data.answer, matched: data.matched, time: Date.now() };
    history.push(botEntry);
    saveHistory();

    await renderMessage(botEntry, true);
    addSuggestions(data.suggestions || []);
  } catch (error) {
    typing.remove();
    renderMessage({ who: "bot", text: "Something went wrong. Please try again.", time: Date.now() }, false);
  } finally {
    sendBtn.disabled = false;
    input.focus();
  }
}

function startNewChat() {
  history = [];
  saveHistory();
  messages.querySelectorAll(".msg, .chips").forEach((node) => node.remove());
  welcome.hidden = false;
  input.focus();
}

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  themeBtn.textContent = theme === "dark" ? "Light mode" : "Dark mode";

  try {
    localStorage.setItem(THEME_KEY, theme);
  } catch (error) {}
}

function toggleTheme() {
  const current = document.documentElement.getAttribute("data-theme");
  applyTheme(current === "dark" ? "light" : "dark");
}

sendBtn.addEventListener("click", () => ask(input.value));
input.addEventListener("keydown", (event) => {
  if (event.key === "Enter") ask(input.value);
});

themeBtn.addEventListener("click", toggleTheme);
newChatBtn.addEventListener("click", startNewChat);

document.querySelectorAll("#starters .starter").forEach((button) => {
  button.addEventListener("click", () => ask(button.textContent));
});

applyTheme(document.documentElement.getAttribute("data-theme") || "light");
history.forEach((entry) => renderMessage(entry, false));
input.focus();