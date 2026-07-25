window.App = (function () {
  const THEME_KEY = "sms-theme";
  const ROLE_MARKER_META = {
    admin: {
      label: "管理中枢",
      badge: "系统控制台",
      iconClass: "fa-solid fa-terminal",
      accentClass: "fa-solid fa-gear"
    },
    teacher: {
      label: "教学批改台",
      badge: "成绩批阅板",
      iconClass: "fa-solid fa-chalkboard",
      accentClass: "fa-solid fa-pen-nib"
    },
    student: {
      label: "学习任务栏",
      badge: "作业已就绪",
      iconClass: "fa-solid fa-file-circle-check",
      accentClass: "fa-solid fa-check"
    }
  };
  let ws = null;
  let notifList = [];

  function initTheme() {
    const saved = localStorage.getItem(THEME_KEY) || "light";
    document.documentElement.setAttribute("data-theme", saved);
    updateThemeIcon(saved);
    initRoleIdentityMarker();
  }

  function toggleTheme() {
    const cur = document.documentElement.getAttribute("data-theme") || "light";
    const next = cur === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem(THEME_KEY, next);
    updateThemeIcon(next);
  }

  function updateThemeIcon(theme) {
    const btn = document.getElementById("themeToggle");
    if (btn) btn.innerHTML = theme === "dark" ? '<i class="fa-solid fa-sun"></i>' : '<i class="fa-solid fa-moon"></i>';
  }

  function setBreadcrumb(items) {
    const bar = document.getElementById("breadcrumb");
    if (!bar) return;
    bar.innerHTML = items.map((it, i) =>
      '<span class="crumb ' + (i === items.length - 1 ? "active" : "") + '">' + it + "</span>" +
      (i < items.length - 1 ? '<span class="sep">/</span>' : "")
    ).join("");
  }

  function initRoleIdentityMarker() {
    const role = (document.body && document.body.dataset && document.body.dataset.role || "").toLowerCase();
    const meta = ROLE_MARKER_META[role];
    if (!meta) return;
    const topbar = document.querySelector(".topbar");
    if (!topbar || topbar.querySelector(".topbar-role-slot")) return;

    const children = Array.from(topbar.children);
    if (children.length < 2) return;

    const slot = document.createElement("div");
    slot.className = "topbar-role-slot";

    const marker = document.createElement("div");
    marker.className = "role-identity-marker";
    marker.setAttribute("tabindex", "0");
    marker.setAttribute("aria-label", meta.badge + " · " + meta.label);

    const iconWrap = document.createElement("div");
    iconWrap.className = "role-identity-icon";

    const mainIcon = document.createElement("i");
    mainIcon.className = meta.iconClass;

    const accentIcon = document.createElement("i");
    accentIcon.className = "role-identity-accent " + meta.accentClass;

    const textWrap = document.createElement("div");
    textWrap.className = "role-identity-copy";

    const badge = document.createElement("div");
    badge.className = "role-identity-badge";
    badge.textContent = meta.badge;

    const label = document.createElement("div");
    label.className = "role-identity-label";
    label.textContent = meta.label;

    iconWrap.appendChild(mainIcon);
    iconWrap.appendChild(accentIcon);
    textWrap.appendChild(badge);
    textWrap.appendChild(label);
    marker.appendChild(iconWrap);
    marker.appendChild(textWrap);
    slot.appendChild(marker);
    topbar.insertBefore(slot, children[1]);
  }

  function skeletonTable(rows) {
    if (rows === undefined) rows = 5;
    let html = '<div class="table-wrap">';
    for (let i = 0; i < rows; i++) html += '<div class="skeleton skeleton-line ' + (i === 0 ? "w-40" : "w-80") + '"></div>';
    return html + "</div>";
  }

  function fmtTime(t) {
    if (!t) return "";
    return String(t).replace("T", " ").slice(0, 19);
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function escapeAttr(value) {
    return escapeHtml(value);
  }

  function timeAgo(t) {
    if (!t) return "";
    const diff = (Date.now() - new Date(t).getTime()) / 1000;
    if (diff < 60) return "刚刚";
    if (diff < 3600) return Math.floor(diff / 60) + "分钟前";
    if (diff < 86400) return Math.floor(diff / 3600) + "小时前";
    return Math.floor(diff / 86400) + " 天前";
  }

  async function initNotifications(token) {
    await loadNotifications();
    connectWebSocket(token);
  }

  async function loadNotifications() {
    try {
      const data = await api("/notifications");
      if (data) {
        notifList = data;
        renderNotifications();
      }
    } catch (e) {}
  }

  function connectWebSocket(token) {
    if (!token) return;
    try {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(proto + "://" + location.host + "/ws/notifications?token=" + token);
      ws.onmessage = function(evt) {
        var msg;
        try { msg = JSON.parse(evt.data); } catch (e) { return; }
        if (msg.type === "CONNECTED") return;
        notifList.unshift(msg);
        renderNotifications();
        showNotifToast(msg);
      };
      ws.onclose = function() { setTimeout(function() { connectWebSocket(token); }, 5000); };
    } catch (e) {}
  }

  function toggleNotifPanel() {
    const panel = document.getElementById("notifPanel");
    if (panel) panel.classList.toggle("show");
  }

  function hideNotifPanel() {
    const panel = document.getElementById("notifPanel");
    if (panel) panel.classList.remove("show");
  }

  function renderNotifications() {
    const badge = document.getElementById("notifBadge");
    const body = document.getElementById("notifBody");
    const unread = notifList.filter(function(n) { return !n.read; }).length;
    if (badge) {
      badge.textContent = unread > 99 ? "99+" : unread;
      badge.style.display = unread > 0 ? "flex" : "none";
    }
    if (!body) return;
    if (!notifList.length) {
      body.innerHTML = '<div class="notif-empty">暂无通知</div>';
      return;
    }
    body.innerHTML = notifList.map(function(n) {
      return '<div class="notif-item ' + (n.read ? "" : "unread") + '" onclick="App.readNotif(' + n.id + ')">' +
        '<div class="nt">' + (n.title || "") + '</div>' +
        '<div class="nc">' + (n.content || "") + '</div>' +
        '<div class="ntime">' + timeAgo(n.createdAt) + '</div></div>';
    }).join("");
  }

  function showNotifToast(msg) {
    var el = document.createElement("div");
    el.className = "notif-toast";
    el.innerHTML = '<div class="ntt">' + (msg.title || "") + '</div><div class="ntb">' + (msg.content || "") + '</div>';
    document.body.appendChild(el);
    setTimeout(function() {
      el.style.opacity = "0";
      el.style.transition = "opacity .4s";
      setTimeout(function() { el.remove(); }, 400);
    }, 4500);
  }

  async function readNotif(id) {
    await api("/notifications/" + id + "/read", "PUT");
    var n = notifList.find(function(x) { return x.id === id; });
    if (n) n.read = true;
    renderNotifications();
  }

  async function markAllRead() {
    await api("/notifications/read-all", "PUT");
    notifList.forEach(function(n) { n.read = true; });
    renderNotifications();
  }

  function parseStoredFiles(value) {
    if (!value) return [];
    return String(value).split(',').map(function(item) {
      var raw = String(item || '').trim();
      if (!raw) return null;
      var parts = raw.split('::');
      return {
        path: parts[0],
        name: parts[1] || '附件'
      };
    }).filter(Boolean);
  }

  async function previewFile(path) {
    var res = await fetch('/api/files/preview?path=' + encodeURIComponent(path), { headers: { Authorization: 'Bearer ' + window.TOKEN } });
    if (!res.ok) throw new Error('预览失败');
    var blob = await res.blob();
    var url = URL.createObjectURL(blob);
    window.open(url, '_blank', 'noopener');
    setTimeout(function() { URL.revokeObjectURL(url); }, 60000);
  }

  async function downloadFile(url, filename) {
    var res = await fetch("/api" + url, { headers: { Authorization: "Bearer " + window.TOKEN } });
    if (!res.ok) throw new Error("下载失败");
    var blob = await res.blob();
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename || "download";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(a.href);
  }

  function logout() {
    localStorage.removeItem("token");
    localStorage.removeItem("role");
    localStorage.removeItem("displayName");
    localStorage.removeItem("username");
    if (ws) { ws.close(); ws = null; }
    window.location.href = "/login.html";
  }

  function showToast(message, type) {
    if (type === undefined) type = "success";
    var existing = document.querySelector(".app-toast");
    if (existing) existing.remove();
    var el = document.createElement("div");
    el.className = "app-toast toast align-items-center text-bg-" + type + " border-0 position-fixed top-0 end-0 m-3";
    el.setAttribute("role", "alert");
    el.innerHTML = '<div class="d-flex"><div class="toast-body">' + message + '</div><button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div>';
    document.body.appendChild(el);
    var toast = new bootstrap.Toast(el, { autohide: true, delay: 3500 });
    toast.show();
  }

  return {
    initTheme: initTheme,
    initRoleIdentityMarker: initRoleIdentityMarker,
    toggleTheme: toggleTheme,
    setBreadcrumb: setBreadcrumb,
    skeletonTable: skeletonTable,
    fmtTime: fmtTime,
    escapeHtml: escapeHtml,
    escapeAttr: escapeAttr,
    timeAgo: timeAgo,
    initNotifications: initNotifications,
    toggleNotifPanel: toggleNotifPanel,
    hideNotifPanel: hideNotifPanel,
    readNotif: readNotif,
    markAllRead: markAllRead,
    parseStoredFiles: parseStoredFiles,
    previewFile: previewFile,
    downloadFile: downloadFile,
    logout: logout,
    showToast: showToast,
    toast: showToast
  };
})();
