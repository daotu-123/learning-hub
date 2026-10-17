/* ============ 工作台 v4 - 离线优先 + 跟手拖拽 + 时间戳计时 ============
   核心: 本地缓存=权威; 连接=同步时机; 番茄钟用时间戳计时(后台不丢);
   左右跟手拖拽切换; 二级页底部 sheet; 日记/周记/月记三文档. */
'use strict';

const $ = (id) => document.getElementById(id);
const API = { summary: '/api/summary', fav: '/api/favorites', usage: '/api/usage', diary: '/api/diary' };

const state = {
  server: '',
  connected: false,
  date: todayStr(),
  favPlatform: 'all',
  stack: [],
  sync: { online: false, lastSyncAt: 0 },
};

const PRESET_BGS = [
  'linear-gradient(160deg,#f0f4fb,#e8edf7)',
  'linear-gradient(160deg,#f7f3ef,#efe7e0)',
  'linear-gradient(160deg,#eef7f3,#e2f0ea)',
  'linear-gradient(160deg,#1f2430,#2a3040)',
  'linear-gradient(160deg,#2b2438,#3a2f4d)',
  'linear-gradient(160deg,#14263c,#1e3f5e)',
];

const PAGE_TITLES = { overview: '概览', diary: '日记', pomodoro: '专注', usage: '使用', health: '健康', fav: '收藏', ai: 'AI 助手', photos: '照片', settings: '设置' };
const TABS = ['overview', 'diary', 'pomodoro', 'usage', 'health', 'fav', 'ai'];

/* ---------------- 本地缓存层 ---------------- */
const LS = {
  get(k, def) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : def; } catch (e) { return def; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { } },
  del(k) { try { localStorage.removeItem(k); } catch (e) { } },
};

function todayStr() {
  const d = new Date();
  return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
}
function fmtMs(ms) {
  if (!ms || ms <= 0) return '0分钟';
  const h = Math.floor(ms / 3600000), m = Math.round((ms % 3600000) / 60000);
  if (h > 0) return h + '小时' + (m > 0 ? m + '分' : '');
  return Math.max(1, m) + '分钟';
}
function fmtMin(min) {
  if (!min || min <= 0) return '0分钟';
  const h = Math.floor(min / 60), m = min % 60;
  if (h > 0) return h + '小时' + (m > 0 ? m + '分' : '');
  return m + '分钟';
}
function esc(s) { const d = document.createElement('div'); d.textContent = s == null ? '' : String(s); return d.innerHTML; }
function fmtSyncTime(ts) {
  if (!ts) return '从未同步';
  const d = new Date(ts);
  const now = new Date();
  if (d.toDateString() === now.toDateString()) return '今天 ' + d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
  return (d.getMonth() + 1) + '月' + d.getDate() + '日 ' + d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
}
function isoWeekKey(d) {
  const date = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  const dayNum = date.getUTCDay() || 7;
  date.setUTCDate(date.getUTCDate() + 4 - dayNum);
  const yearStart = new Date(Date.UTC(date.getUTCFullYear(), 0, 1));
  const weekNo = Math.ceil((((date - yearStart) / 86400000) + 1) / 7);
  return date.getUTCFullYear() + '-W' + String(weekNo).padStart(2, '0');
}

/* ---------------- 导航 ---------------- */
let pendingAnim = null;

function showPage(page, dir) {
  if (pendingAnim) {
    pendingAnim.cur.classList.add('hidden');
    [pendingAnim.cur, pendingAnim.next].forEach(p => p.style.cssText = '');
    pendingAnim = null;
  }
  const content = document.querySelector('.content');
  const cur = content.querySelector('.page:not(.hidden)');
  const next = $('page-' + page);
  content.scrollTop = 0;
  $('pageTitle').textContent = PAGE_TITLES[page] || page;
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.page === page));
  $('btnBack').classList.toggle('show', state.stack.length > 0);

  if (!cur || cur === next || dir === 0) {
    next.classList.remove('hidden');
    if (cur && cur !== next) cur.classList.add('hidden');
  } else {
    const d = dir >= 0 ? 1 : -1;
    cur.classList.remove('hidden');
    next.classList.remove('hidden');
    [cur, next].forEach(p => {
      p.style.position = 'absolute'; p.style.top = '0'; p.style.left = '0'; p.style.width = '100%';
    });
    cur.style.transition = 'none'; next.style.transition = 'none';
    cur.style.transform = 'translateX(0)'; cur.style.opacity = '1';
    next.style.transform = 'translateX(' + d * 100 + '%)'; next.style.opacity = '0';
    void content.offsetHeight;
    const EASE = 'transform .3s cubic-bezier(.25,.8,.3,1), opacity .3s ease';
    cur.style.transition = EASE; next.style.transition = EASE;
    cur.style.transform = 'translateX(' + (-d * 30) + '%)'; cur.style.opacity = '0';
    next.style.transform = 'translateX(0)'; next.style.opacity = '1';
    pendingAnim = { cur, next };
    setTimeout(() => {
      if (pendingAnim && pendingAnim.cur === cur) {
        cur.classList.add('hidden');
        [cur, next].forEach(p => p.style.cssText = '');
        pendingAnim = null;
      }
    }, 330);
  }
  onPageShown(page);
}
function onPageShown(page) {
  if (page === 'fav') loadFavorites();
  if (page === 'usage') loadUsage();
  if (page === 'diary') loadDiary();
  if (page === 'overview') loadOverview();
  if (page === 'pomodoro') loadPomodoro();
  if (page === 'health') loadHealth();
  if (page === 'photos') loadPhotos();
}
function goTab(page, dir) { state.stack = []; showPage(page, dir == null ? 1 : dir); }
function pushPage(page) {
  state.stack.push(currentPage());
  if (page === 'settings') showSheet('settings');
  else showPage(page, 1);
}
function goBack() {
  if (state.stack.length === 0) return;
  const prev = state.stack.pop();
  const cur = currentPage();
  if (cur === 'settings') {
    const el = $('page-settings');
    el.style.transition = 'transform .28s ease';
    el.style.transform = 'translateY(105%)';
    setTimeout(() => {
      el.classList.add('hidden');
      el.style.cssText = '';
      showPage(prev, 0);
    }, 280);
  } else {
    showPage(prev, -1);
  }
}
function currentPage() {
  const el = document.querySelector('.page:not(.hidden)');
  return el ? el.id.replace('page-', '') : 'overview';
}
/** 底部 sheet 滑入 (设置页) */
function showSheet(page) {
  const content = document.querySelector('.content');
  content.scrollTop = 0;
  document.querySelectorAll('.page').forEach(p => p.classList.add('hidden'));
  $('pageTitle').textContent = PAGE_TITLES[page];
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  $('btnBack').classList.toggle('show', state.stack.length > 0);
  const el = $('page-' + page);
  el.classList.remove('hidden');
  el.style.transition = 'none';
  el.style.transform = 'translateY(100%)';
  void el.offsetHeight;
  el.style.transition = 'transform .32s cubic-bezier(.25,.8,.3,1)';
  el.style.transform = 'translateY(0)';
}

/* ---------------- 网络 + 连接状态机 (8s 超时, 20s 心跳) ---------------- */
async function api(path, opts = {}) {
  if (!state.server) throw new Error('未设置服务器地址');
  const url = state.server.replace(/\/+$/, '') + path;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 8000);
  try {
    const res = await fetch(url, Object.assign({ headers: { 'Content-Type': 'application/json' }, signal: ctrl.signal }, opts));
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const err = new Error(data.detail ? (typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)) : ('HTTP ' + res.status));
      err.status = res.status; err.data = data;
      throw err;
    }
    return data;
  } finally {
    clearTimeout(timer);
  }
}

async function checkConnection() {
  if (!state.server) return false;
  try {
    await api('/');
    if (!state.sync.online) {
      state.sync.online = true;
      state.sync.lastSyncAt = Date.now();
      setConn('ok');
      updateSyncStatus();
      await syncAll();
      toast('已连接 PC，正在同步');
    } else {
      state.sync.lastSyncAt = Date.now();
      setConn('ok');
      updateSyncStatus();
    }
    return true;
  } catch (e) {
    if (state.sync.online) {
      state.sync.online = false;
      setConn('off');
      updateSyncStatus();
    }
    return false;
  }
}
function setConn(s) {
  state.connected = s === 'ok';
  state.sync.online = s === 'ok';
  const dot = $('connDot');
  dot.className = 'conn-dot' + (s === 'ok' ? ' ok' : s === 'busy' ? ' busy' : '');
}
function updateSyncStatus() {
  const el = $('syncStatusText');
  if (!el) return;
  if (state.sync.online) {
    el.textContent = '已连接 · 同步于 ' + fmtSyncTime(state.sync.lastSyncAt);
    el.classList.remove('offline');
  } else {
    el.textContent = '离线模式 · 上次同步 ' + fmtSyncTime(state.sync.lastSyncAt) + ' · 重连后自动同步';
    el.classList.add('offline');
  }
}
function startHeartbeat() {
  setInterval(() => checkConnection(), 20000);
}

/** 重连后全量同步 (以手机为基准) */
async function syncAll() {
  await syncTasks();
  await syncDocs();
  await syncPomos();
  await pushHealth();
  await refreshSummary();
  await refreshFavorites();
  await refreshUsageTrend();
  await refreshHealth();
}

/* ---------------- 概览 (工作台聚合中心) ---------------- */
function renderOverview(s) {
  $('focusFav').textContent = '抖音 ' + s.favorites.douyin + ' 条 · 小红书 ' + s.favorites.xiaohongshu + ' 条';
  const notes = s.deeptutor.notes || {};
  const noteTxt = Object.keys(notes).length
    ? ' · 新增 ' + Object.entries(notes).map(([k, v]) => k + v).join(' ')
    : '';
  $('deptSummary').textContent = s.deeptutor.ok
    ? '今日会话 ' + s.deeptutor.sessions + ' 个 · 消息 ' + s.deeptutor.messages + ' 条' + noteTxt
    : '未读取到 DeepTutor 数据';
}
function renderFocus() {
  // 番茄
  const pomos = LS.get('pomos', []).filter(r => r.date === state.date);
  $('focusPomo').textContent = pomos.length ? pomos.length + ' 个' : '0 个';
  // 使用
  const usage = LS.get('usage_today_' + state.date, []);
  if (usage.length) {
    const t = usage.reduce((s, a) => s + a.day_ms, 0);
    $('focusUsage').textContent = fmtMs(t).replace('分钟', '分').replace('小时', '时');
  } else {
    $('focusUsage').textContent = '0分';
  }
  // 健康
  const hd = LS.get('health_' + state.date, null);
  $('focusSleep').textContent = hd && hd.sleep_min ? fmtMin(hd.sleep_min).replace('分钟', '分').replace('小时', '时') : '-';
  $('focusEx').textContent = hd && hd.exercise_min ? fmtMin(hd.exercise_min).replace('分钟', '分').replace('小时', '时') : '-';
  // 今日目标: 未完成任务 Top 2
  const tasks = LS.get('tasks', []).filter(t => !t.done);
  if (tasks.length) {
    $('focusTask').textContent = tasks.slice(0, 2).map(t => t.name).join('、') + (tasks.length > 2 ? ' 等 ' + tasks.length + ' 项' : '');
  } else {
    $('focusTask').textContent = '暂无未完成任务';
  }
}
function loadOverview() {
  const cached = LS.get('summary', null);
  if (cached && cached.date === state.date) renderOverview(cached.data);
  else if (!state.sync.online) $('focusFav').textContent = '离线模式，暂无缓存数据';
  renderFocus();
  const dl = LS.get('doc_diary_' + state.date, null);
  if (dl) $('diaryPreview').textContent = dl.content.slice(0, 140) || '（日记为空）';
  else if (state.sync.online) $('diaryPreview').textContent = '加载中…';
  else $('diaryPreview').textContent = '离线模式，日记无缓存';
  if (state.sync.online) refreshSummary();
}
async function refreshSummary() {
  try {
    const s = await api('/api/summary?date=' + state.date);
    LS.set('summary', { date: state.date, data: s });
    renderOverview(s);
  } catch (e) { }
}

/* ---------------- 收藏 ---------------- */
function loadFavorites() {
  const list = $('favList');
  const date = $('favDate').value;
  const cached = LS.get('fav_' + date + '_' + state.favPlatform, null);
  if (cached) renderFavList(cached);
  else if (!state.sync.online) { list.innerHTML = '<div class="empty">离线模式，该日期无缓存</div>'; return; }
  else list.innerHTML = '<div class="empty">加载中…</div>';
  if (state.sync.online) refreshFavorites();
}
function renderFavList(items) {
  const list = $('favList');
  if (!items.length) { list.innerHTML = '<div class="empty">这一天没有新增收藏</div>'; return; }
  list.innerHTML = '';
  items.forEach(it => {
    const el = document.createElement('a');
    el.className = 'fav-item';
    el.href = it.url || '#';
    el.target = '_blank';
    const badge = it.platform === 'douyin' ? '抖音' : '小红书';
    const time = (it.collected_at || '').replace('T', ' ').slice(5, 16);
    el.innerHTML =
      '<div class="fav-body">' +
        '<div class="fav-title">' + esc(it.title || '') + '</div>' +
        '<div class="fav-meta">' + esc(it.author || '') + ' · ' + time + '</div>' +
      '</div>' +
      '<div class="fav-badge ' + it.platform + '">' + badge + '</div>';
    list.appendChild(el);
  });
}
async function refreshFavorites() {
  const date = $('favDate') ? $('favDate').value : state.date;
  try {
    const d = await api(API.fav + '?date=' + date);
    const items = [];
    if (state.favPlatform === 'all' || state.favPlatform === 'douyin') items.push(...(d.douyin || []).map(x => Object.assign({ platform: 'douyin' }, x)));
    if (state.favPlatform === 'all' || state.favPlatform === 'xiaohongshu') items.push(...(d.xiaohongshu || []).map(x => Object.assign({ platform: 'xiaohongshu' }, x)));
    items.sort((a, b) => (a.collected_at < b.collected_at ? 1 : -1));
    LS.set('fav_' + date + '_' + state.favPlatform, items);
    if (currentPage() === 'fav') renderFavList(items);
  } catch (e) { }
}

/* ---------------- 使用统计 ---------------- */
async function collectAndReport() {
  try {
    const raw = window.Native.getUsageStats(7);
    const apps = JSON.parse(raw || '[]').filter(a => a.day_ms > 0 || a.total_ms > 0);
    if (!apps.length) { toast('未获取到使用数据，请先开启使用情况访问权限'); return 0; }
    LS.set('usage_today_' + state.date, apps);
    let hourly = [];
    try { hourly = JSON.parse(window.Native.getHourlyUsage() || '{}').hours || []; } catch (e) { }
    if (state.sync.online) {
      try {
        await api(API.usage, { method: 'POST', body: JSON.stringify({ date: state.date, apps, hourly }) });
        toast('已上报 ' + apps.length + ' 个应用');
      }
      catch (e) { toast('上报失败（离线已存档）'); }
    } else { toast('离线：已存本地，重连后同步'); }
    await loadUsage();
    return apps.length;
  } catch (e) { toast('未获取到使用数据'); return 0; }
}

/* ---------------- 类别体系 (仿 Work Review 时间分配) ---------------- */
const CAT_COLORS = { 娱乐: '#EF4444', 社交: '#3B82F6', 学习: '#10B981', 工作: '#8B5CF6', 工具: '#6B7280', 购物: '#F59E0B', 其他: '#9CA3AF' };
const CAT_ORDER = ['娱乐', '社交', '学习', '工作', '工具', '购物', '其他'];
const CAT_MAP = {
  'com.ss.android.ugc.aweme': '娱乐', 'com.ss.android.ugc.live': '娱乐',
  'tv.danmaku.bili': '娱乐', 'com.smile.gifmaker': '娱乐',
  'com.tencent.qqmusic': '娱乐', 'com.netease.cloudmusic': '娱乐',
  'com.tencent.mobileqq': '社交', 'com.tencent.mm': '社交',
  'com.xingin.xhs': '社交', 'com.sina.weibo': '社交',
  'com.zhihu.android': '学习', 'com.duokan.reader': '学习',
  'com.kaoyanbang': '学习', 'com.baidu.netdisk': '工具',
  'com.alibaba.android.rimet': '工作', 'com.tencent.wework': '工作',
  'com.huawei.hidisk': '工具', 'com.android.settings': '工具',
  'com.taobao.taobao': '购物', 'com.jingdong.app.mall': '购物',
  'com.xunmeng.pinduoduo': '购物', 'com.eg.android.AlipayGphone': '购物',
};
function categorize(pkg, name) {
  if (CAT_MAP[pkg]) return CAT_MAP[pkg];
  const n = (name || '') + ' ' + (pkg || '');
  if (/(抖音|快手|哔哩|bilibili|爱奇艺|优酷|腾讯视频|芒果|音乐|游戏|王者|和平精英|原神|微博|贴吧|小红书|直播)/.test(n)) return '娱乐';
  if (/(微信|QQ|钉钉|企业微信|飞书|Telegram|Discord|陌陌|探探)/.test(n)) return '社交';
  if (/(学习|考研|慕课|网课|知网|百度网盘|WPS|Office|Word|Excel|PowerPoint|笔记|Obsidian|Anki|词典|英语|题库|课程|阅读)/.test(n)) return '学习';
  if (/(浏览器|Chrome|Edge|Safari|Firefox|夸克|UC|编程|代码|终端|远程|GitHub)/.test(n)) return '工作';
  if (/(设置|桌面|相册|相机|文件|电话|短信|时钟|日历|计算器|天气|应用商店|系统|工具|输入法|安全|管家|服务|健康|地图|导航)/.test(n)) return '工具';
  if (/(淘宝|京东|拼多多|天猫|闲鱼|美团|饿了么|支付宝|银行|云闪付|唯品会|得物)/.test(n)) return '购物';
  return '其他';
}
function catOf(app) { return categorize(app.package, app.app_name); }

/** 时间分配 (类别横向条形) -> 返回 {total, entries:[[cat,ms]...]} */
function renderCategoryChart(apps) {
  const el = $('categoryChart');
  const total = apps.reduce((s, a) => s + a.day_ms, 0);
  if (!total || !apps.length) { el.innerHTML = '<div class="empty">暂无数据</div>'; return { total: 0, entries: [] }; }
  const catMs = {};
  apps.forEach(a => { const c = catOf(a); catMs[c] = (catMs[c] || 0) + a.day_ms; });
  const entries = CAT_ORDER.filter(c => catMs[c]).map(c => [c, catMs[c]]).sort((x, y) => y[1] - x[1]);
  const max = entries[0][1];
  let html = '';
  entries.forEach(([cat, ms]) => {
    const pct = Math.round(ms / total * 100);
    html += '<div class="cat-row">' +
      '<div class="cat-name">' + cat + '</div>' +
      '<div class="cat-bar-wrap"><div class="cat-bar" data-w="' + Math.round(ms / max * 100) + '" style="background:' + CAT_COLORS[cat] + '"></div></div>' +
      '<div class="cat-ms">' + fmtMs(ms) + '</div>' +
      '<div class="cat-pct">' + pct + '%</div></div>';
  });
  el.innerHTML = html;
  requestAnimationFrame(() => el.querySelectorAll('.cat-bar').forEach(b => b.style.width = b.dataset.w + '%'));
  return { total, entries };
}

/** 按小时活跃度 (24h 柱状) */
function renderHourChart(hours) {
  const el = $('hourChart');
  const arr = hours || [];
  if (!arr.length) { el.innerHTML = '<div class="empty">暂无数据</div>'; return; }
  const max = Math.max(...arr.map(h => h.seconds), 1);
  const W = 340, H = 100, padB = 20, padT = 8;
  let bars = '';
  arr.forEach(h => {
    const bh = Math.max(1, h.seconds / max * (H - padB - padT));
    const x = 6 + h.hour * (W - 12) / 24;
    const bw = (W - 12) / 24 * 0.62;
    bars += '<rect class="h-bar' + (h.seconds > 0 ? '' : ' h-off') + '" x="' + x.toFixed(1) + '" y="' + (H - padB - bh).toFixed(1) + '" width="' + bw.toFixed(1) + '" height="' + bh.toFixed(1) + '"></rect>';
    if (h.hour % 4 === 0) bars += '<text class="lbl" x="' + (x + bw / 2).toFixed(1) + '" y="' + (H - 5) + '" text-anchor="middle">' + h.hour + '</text>';
  });
  el.innerHTML = '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none">' + bars + '</svg>';
}

/** 生成 Work Review 风格日报 -> 同步到 Obsidian */
async function generateDailyReport() {
  if (!state.sync.online) { toast('离线：无法生成日报（需连接 PC）'); return; }
  const date = state.date;
  try {
    // 1) 使用数据
    let todayApps = [];
    try {
      const raw = window.Native.getUsageStats(1);
      todayApps = JSON.parse(raw || '[]').filter(a => a.day_ms > 0);
    } catch (e) { }
    if (!todayApps.length) todayApps = LS.get('usage_today_' + date, []);
    const catData = renderCategoryChart(todayApps);
    let hourly = [];
    try {
      const hd = JSON.parse(window.Native.getHourlyUsage() || '{}');
      hourly = hd.hours || [];
    } catch (e) { }
    const trend = LS.get('usage_trend', null) || {};
    // 2) 番茄钟
    const pomos = LS.get('pomos', []).filter(r => r.date === date);
    // 3) 健康
    let health = LS.get('health_' + date, null);
    if (!health) { try { health = await api('/api/health?date=' + date); } catch (e) { } }
    // 4) 收藏摘要
    let fav = { douyin: 0, xiaohongshu: 0 };
    try { const s = await api('/api/summary?date=' + date); fav = s.favorites; } catch (e) { }

    // ---- 组装 markdown (Work Review 风格) ----
    const L = [];
    L.push('# 工作台日报');
    L.push('');
    L.push('**日期：' + date + '**');
    L.push('');
    L.push('## 使用概览');
    const total = todayApps.reduce((s, a) => s + a.day_ms, 0);
    L.push('> ' + buildShortConclusion(todayApps, catData));
    L.push('');
    L.push('| 今日使用 | 应用数 | 较昨日 |');
    L.push('|--:|--:|--:|');
    const dates = Object.keys(trend).sort();
    let deltaTxt = '-';
    if (dates.length >= 2 && trend[dates[dates.length - 2]] > 0) {
      const diff = total - trend[dates[dates.length - 2]];
      deltaTxt = (diff >= 0 ? '+' : '') + Math.round(diff / trend[dates[dates.length - 2]] * 100) + '%';
    }
    L.push('| ' + fmtMs(total) + ' | ' + todayApps.length + ' | ' + deltaTxt + ' |');
    L.push('');
    // 时间分配
    L.push('## 时间分配');
    L.push('');
    L.push('| 类别 | 时长 | 占比 |');
    L.push('|:--|--:|--:|');
    if (catData.entries.length) {
      catData.entries.forEach(([cat, ms]) => {
        L.push('| ' + cat + ' | ' + fmtMs(ms) + ' | ' + Math.round(ms / catData.total * 100) + '% |');
      });
    }
    L.push('');
    // 应用 Top 10
    L.push('## 应用时长 Top 10');
    L.push('');
    L.push('| 序号 | 应用 | 时长 |');
    L.push('|--:|:--|--:|');
    todayApps.slice().sort((a, b) => b.day_ms - a.day_ms).slice(0, 10).forEach((a, i) => {
      L.push('| ' + (i + 1) + ' | ' + a.app_name + ' | ' + fmtMs(a.day_ms) + ' |');
    });
    L.push('');
    // 小时活跃度
    L.push('## 按小时活跃度');
    L.push('');
    const peak = hourly.reduce((m, h) => h.seconds > m.seconds ? h : m, { seconds: 0 });
    const activeHours = hourly.filter(h => h.seconds > 0).length;
    L.push('- 高峰时段: ' + (peak.seconds > 0 ? peak.hour + ':00-' + (peak.hour + 1) + ':00（' + fmtMs(peak.seconds * 1000) + '）' : '暂无'));
    L.push('- 活跃小时数: ' + activeHours + ' 个');
    L.push('');
    // 分析
    L.push('## 今日分析');
    L.push('');
    L.push(buildAnalysis(todayApps, catData, trend, hourly));
    L.push('');
    // 番茄钟
    L.push('## 番茄钟');
    L.push('');
    const pomoMin = pomos.reduce((s, r) => s + r.minutes, 0);
    L.push('- 今日完成 ' + pomos.length + ' 个番茄 · 专注 ' + fmtMin(pomoMin));
    const doneTasks = LS.get('tasks', []).filter(t => t.done);
    if (doneTasks.length) L.push('- 已完成任务: ' + doneTasks.map(t => t.name).join('、'));
    L.push('');
    // 健康
    L.push('## 健康');
    L.push('');
    if (health) L.push('- 睡眠 ' + fmtMin(health.sleep_min) + ' · 运动 ' + fmtMin(health.exercise_min));
    else L.push('- 暂无记录');
    L.push('');
    // 收藏
    L.push('## 收藏');
    L.push('');
    L.push('- 抖音新增 ' + fav.douyin + ' 条 · 小红书新增 ' + fav.xiaohongshu + ' 条');
    L.push('');
    L.push('---');
    L.push('*由工作台生成 · ' + new Date().toLocaleString('zh-CN') + '*');

    const r = await api('/api/daily-report', {
      method: 'POST',
      body: JSON.stringify({ date, content: L.join('\n') }),
    });
    toast('日报已生成：' + r.path);
    console.log('report saved:', r.path);
  } catch (e) {
    toast('日报生成失败：' + e.message);
  }
}

/** 短结论 (Work Review 风格) */
function buildShortConclusion(todayApps, catData) {
  if (!todayApps.length) return '暂无使用数据，点击下方按钮同步';
  const top = todayApps.slice().sort((a, b) => b.day_ms - a.day_ms)[0];
  const parts = ['使用最久的是「' + top.app_name + '」（' + fmtMs(top.day_ms) + '）；今天共记录 ' + todayApps.length + ' 个应用。'];
  if (catData.entries.length) {
    const [topCat, ms] = catData.entries[0];
    parts.push(topCat + '类占比最高（' + Math.round(ms / catData.total * 100) + '%，' + fmtMs(ms) + '）');
  }
  return parts.join('');
}

/** 今日分析 (规则式, 仿 Work Review AI 分析) */
function buildAnalysis(todayApps, catData, trend, hourly) {
  if (!catData.total) return '暂无数据';
  const lines = [];
  const total = catData.total;
  const find = c => { const e = catData.entries.find(x => x[0] === c); return e ? e[1] : 0; };
  const studyWork = find('学习') + find('工作');
  const fun = find('娱乐');
  const social = find('社交');
  const studyPct = Math.round(studyWork / total * 100);
  const funPct = Math.round(fun / total * 100);
  lines.push('· 有效投入（学习+工作）占 ' + studyPct + '%，娱乐占 ' + funPct + '%' +
    (funPct > 40 ? '，娱乐占比偏高，建议压缩' : funPct > 25 ? '，娱乐占比适中' : '，节奏控制不错'));
  // 与昨日对比
  const dates = Object.keys(trend || {}).sort();
  if (dates.length >= 2) {
    const y = trend[dates[dates.length - 2]] || 0;
    if (y > 0) {
      const diff = total - y;
      const pct = Math.round(diff / y * 100);
      lines.push('· 总时长' + (diff > 0 ? '较昨日增加 ' + pct + '%' : '较昨日减少 ' + Math.abs(pct) + '%') + '（' + fmtMs(total) + '）');
    }
  }
  // 高峰
  if (hourly && hourly.length) {
    const peak = hourly.reduce((m, h) => h.seconds > m.seconds ? h : m, { seconds: 0 });
    if (peak.seconds > 0) lines.push('· 活跃高峰出现在 ' + peak.hour + ':00-' + (peak.hour + 1) + ':00（' + fmtMs(peak.seconds * 1000) + '）');
  }
  // 社交提醒
  if (social > total * 0.3) lines.push('· 社交类占比较高（' + fmtMs(social) + '），注意碎片化干扰');
  // 建议
  const top = todayApps.slice().sort((a, b) => b.day_ms - a.day_ms)[0];
  if (funPct > 40 && top) {
    lines.push('· 建议：将「' + top.app_name + '」等娱乐应用限制在固定时段，工作时段保持专注');
  }
  return lines.join('\n');
}

async function loadUsage() {
  const warn = $('usagePermWarn');
  try {
    const hasPerm = window.Native.hasUsagePermission();
    warn.classList.toggle('hidden', !!hasPerm);
  } catch (e) { warn.classList.remove('hidden'); }

  let todayApps = [];
  try {
    const raw = window.Native.getUsageStats(1);
    todayApps = JSON.parse(raw || '[]').filter(a => a.day_ms > 0);
  } catch (e) { }
  if (!todayApps.length) todayApps = LS.get('usage_today_' + state.date, []);
  else LS.set('usage_today_' + state.date, todayApps);

  let trend = LS.get('usage_trend', null) || {};
  if (state.sync.online) {
    try {
      const t = await api(API.usage + '?days=7');
      trend = t.daily_total_ms || {};
      LS.set('usage_trend', trend);
    } catch (e) { }
  }

  const total = todayApps.reduce((s, a) => s + a.day_ms, 0);
  $('usageTotal').textContent = total ? fmtMs(total) : '0分钟';
  renderDonut(todayApps);

  // 时间分配 (类别) + 短结论 + 分析
  const catData = renderCategoryChart(todayApps);
  $('usageSummary').textContent = buildShortConclusion(todayApps, catData);

  // 按小时活跃度 (原生 UsageEvents 聚合)
  let hourly = null;
  try {
    const rawH = window.Native.getHourlyUsage();
    const hd = JSON.parse(rawH || '{}');
    hourly = hd.hours || null;
    renderHourChart(hourly);
  } catch (e) { renderHourChart(null); }

  const dates = Object.keys(trend).sort();
  let deltaText = '-';
  if (dates.length >= 2) {
    const y = trend[dates[dates.length - 2]] || 0;
    if (y > 0) {
      const diff = total - y;
      const pct = Math.round(diff / y * 100);
      deltaText = diff >= 0 ? '较昨日 +' + pct + '%' : '较昨日 ' + pct + '%';
    }
  }
  $('usageDelta').textContent = deltaText;
  $('usageAnalysis').textContent = buildAnalysis(todayApps, catData, trend, hourly);

  const list = $('usageList');
  if (!todayApps.length) list.innerHTML = '<div class="empty">暂无数据</div>';
  else {
    const max = Math.max(...todayApps.map(a => a.day_ms), 1);
    list.innerHTML = '';
    todayApps.sort((a, b) => b.day_ms - a.day_ms).forEach(a => {
      const row = document.createElement('div');
      row.className = 'usage-row';
      row.innerHTML =
        '<div class="usage-name">' + esc(a.app_name || a.package) + '</div>' +
        '<div class="usage-bar-wrap"><div class="usage-bar" data-w="' + Math.round(a.day_ms / max * 100) + '"></div></div>' +
        '<div class="usage-ms">' + fmtMs(a.day_ms) + '</div>' +
        '<div class="usage-pct">' + Math.round(a.day_ms / total * 100) + '%</div>';
      list.appendChild(row);
    });
    requestAnimationFrame(() => list.querySelectorAll('.usage-bar').forEach(b => b.style.width = b.dataset.w + '%'));
  }
  renderChart(trend);
}
async function refreshUsageTrend() {
  try {
    const t = await api(API.usage + '?days=7');
    LS.set('usage_trend', t.daily_total_ms || {});
    if (currentPage() === 'usage') loadUsage();
  } catch (e) { }
}

function renderDonut(apps) {
  const el = $('usageDonut');
  const legend = $('usageLegend');
  const sorted = apps.slice().sort((a, b) => b.day_ms - a.day_ms);
  const total = sorted.reduce((s, a) => s + a.day_ms, 0);
  if (!total || !sorted.length) { el.innerHTML = '<div class="empty">暂无数据</div>'; legend.innerHTML = ''; return; }
  const COLORS = ['#2563eb', '#f59e0b', '#10b981', '#ef4444', '#8b5cf6', '#06b6d4', '#f97316', '#ec4899', '#84cc16', '#64748b'];
  const R = 70, CX = 90, CY = 90, C = 2 * Math.PI * R;
  const top = sorted.slice(0, 10);
  let offset = 0, segs = '', legendHtml = '';
  top.forEach((a, i) => {
    const frac = a.day_ms / total;
    const len = frac * C;
    const color = COLORS[i % COLORS.length];
    segs += '<circle class="donut-seg" cx="' + CX + '" cy="' + CY + '" r="' + R + '" fill="none" stroke="' + color +
      '" stroke-width="17" stroke-dasharray="' + len.toFixed(1) + ' ' + (C - len).toFixed(1) + '" stroke-dashoffset="' + (-offset).toFixed(1) + '" transform="rotate(-90 ' + CX + ' ' + CY + ')"/>';
    offset += len;
    legendHtml += '<div class="legend-item"><span class="legend-dot" style="background:' + color + '"></span>' +
      '<span class="legend-name">' + esc(a.app_name || a.package) + '</span><span>' + Math.round(frac * 100) + '%</span></div>';
  });
  el.innerHTML =
    '<svg viewBox="0 0 180 180">' + segs + '</svg>' +
    '<div class="donut-center"><div class="donut-total">' + fmtMs(total) + '</div><div class="donut-sub">今日共 ' + sorted.length + ' 个应用</div></div>';
  legend.innerHTML = legendHtml;
}

function renderChart(daily) {
  const el = $('usageChart');
  const days = Object.keys(daily || {}).sort();
  if (!days.length) { el.innerHTML = '<div class="empty">暂无趋势数据</div>'; return; }
  const W = 340, H = 140, padB = 22, padT = 14;
  const vals = days.map(d => daily[d] || 0);
  const max = Math.max(...vals, 1);
  const bw = (W - 40) / days.length * 0.5;
  let bars = '';
  vals.forEach((v, i) => {
    const h = Math.max(2, (v / max) * (H - padB - padT));
    const x = 24 + i * (W - 40) / days.length + ((W - 40) / days.length - bw) / 2;
    const y = H - padB - h;
    bars += '<rect class="bar" x="' + x.toFixed(1) + '" y="' + y.toFixed(1) + '" width="' + bw.toFixed(1) + '" height="' + h.toFixed(1) + '"></rect>';
    bars += '<text class="lbl" x="' + (x + bw / 2).toFixed(1) + '" y="' + (H - 5) + '" text-anchor="middle">' + days[i].slice(5) + '</text>';
    if (v > 0) bars += '<text class="val" x="' + (x + bw / 2).toFixed(1) + '" y="' + (y - 4).toFixed(1) + '" text-anchor="middle">' + (v >= 3600000 ? (v / 3600000).toFixed(1) + 'h' : Math.round(v / 60000) + 'm') + '</text>';
  });
  el.innerHTML =
    '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none">' +
    '<line class="axis" x1="20" y1="' + (H - padB) + '" x2="' + (W - 10) + '" y2="' + (H - padB) + '"></line>' +
    bars + '</svg>';
}

/* ---------------- 健康 ---------------- */
function loadHealth() {
  renderHealthLocal();
  if (state.sync.online) refreshHealth();
}
function renderHealthLocal() {
  const d = LS.get('health_' + state.date, null);
  $('healthSleepToday').textContent = d ? fmtMin(d.sleep_min) : '-';
  $('healthExToday').textContent = d ? fmtMin(d.exercise_min) : '-';
  renderHealthChart(LS.get('health_trend', null));
}
async function refreshHealth() {
  try {
    const d = await api('/api/health?date=' + state.date);
    LS.set('health_' + state.date, d);
    const t = await api('/api/health?days=7');
    LS.set('health_trend', t);
    renderHealthLocal();
  } catch (e) { }
}
function recordHealth(kind, label, valueMin, startTs, endTs) {
  const rec = { date: state.date, kind, label, valueMin, startTs, endTs, synced: false };
  const list = LS.get('health_recs', []);
  list.push(rec);
  LS.set('health_recs', list);
  if (state.sync.online) pushHealth();
  else toast('离线：已存本地，重连后同步');
  refreshHealthLocalSummary();
}
async function pushHealth() {
  const list = LS.get('health_recs', []);
  let changed = false;
  for (const r of list) {
    if (r.synced) continue;
    try {
      await api('/api/health', {
        method: 'POST',
        body: JSON.stringify({ date: r.date, kind: r.kind, label: r.label, value_min: r.valueMin, start_ts: r.startTs || '', end_ts: r.endTs || '' }),
      });
      r.synced = true; changed = true;
    } catch (e) { break; }
  }
  if (changed) LS.set('health_recs', list);
  refreshHealth();
}
function refreshHealthLocalSummary() {
  // 用本地记录更新今日统计 (离线时)
  const recs = LS.get('health_recs', []).filter(r => r.date === state.date);
  const sleepMin = recs.filter(r => r.kind === 'sleep').reduce((s, r) => s + r.valueMin, 0);
  const exMin = recs.filter(r => r.kind === 'exercise').reduce((s, r) => s + r.valueMin, 0);
  if (!state.sync.online) {
    $('healthSleepToday').textContent = fmtMin(sleepMin);
    $('healthExToday').textContent = fmtMin(exMin);
    $('focusSleep').textContent = fmtMin(sleepMin).replace('分钟', '分').replace('小时', '时');
    $('focusEx').textContent = fmtMin(exMin).replace('分钟', '分').replace('小时', '时');
  }
}
function calcSleepMin(start, end) {
  const [sh, sm] = (start || '23:30').split(':').map(Number);
  const [eh, em] = (end || '07:00').split(':').map(Number);
  let mins = (eh * 60 + em) - (sh * 60 + sm);
  if (mins <= 0) mins += 24 * 60;
  return mins;
}
function renderHealthChart(trend) {
  const el = $('healthChart');
  const days = Object.keys(trend || {}).sort();
  if (!days.length) { el.innerHTML = '<div class="empty">暂无趋势数据</div>'; return; }
  const W = 340, H = 140, padB = 22, padT = 14;
  const vals = days.map(d => Math.max((trend[d].sleep || 0), (trend[d].exercise || 0)));
  const max = Math.max(...vals, 1);
  const bw = (W - 40) / days.length * 0.35;
  let bars = '';
  days.forEach((d, i) => {
    const x = 24 + i * (W - 40) / days.length + ((W - 40) / days.length - bw * 2) / 2;
    const sleep = trend[d].sleep || 0, ex = trend[d].exercise || 0;
    const hs = Math.max(2, (sleep / max) * (H - padB - padT));
    const he = Math.max(2, (ex / max) * (H - padB - padT));
    bars += '<rect class="bar bar-sleep" x="' + x.toFixed(1) + '" y="' + (H - padB - hs).toFixed(1) + '" width="' + bw.toFixed(1) + '" height="' + hs.toFixed(1) + '"></rect>';
    bars += '<rect class="bar bar-ex" x="' + (x + bw + 3).toFixed(1) + '" y="' + (H - padB - he).toFixed(1) + '" width="' + bw.toFixed(1) + '" height="' + he.toFixed(1) + '"></rect>';
    bars += '<text class="lbl" x="' + (x + bw + 1.5).toFixed(1) + '" y="' + (H - 5) + '" text-anchor="middle">' + d.slice(5) + '</text>';
  });
  el.innerHTML =
    '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none">' +
    '<line class="axis" x1="20" y1="' + (H - padB) + '" x2="' + (W - 10) + '" y2="' + (H - padB) + '"></line>' +
    bars + '</svg>' +
    '<div class="chart-legend"><span class="legend-dot" style="background:#2563eb"></span>睡眠 <span class="legend-dot" style="background:#10b981"></span>运动</div>';
}

/* ---------------- 文档 (日记/周记/月记) ---------------- */
const docState = { type: 'diary', key: todayStr(), mtime: 0 };
function docCacheKey() { return 'doc_' + docState.type + '_' + docState.key; }
function docKeyFromCache(cacheKey) {
  // doc_diary_2026-08-02 / doc_weekly_2026-W32 / doc_monthly_2026-08
  const rest = cacheKey.slice(4);
  const idx = rest.indexOf('_');
  return { type: rest.slice(0, idx), key: rest.slice(idx + 1) };
}
function currentDocKey() {
  const t = docState.type;
  if (t === 'diary') return $('docKeyDiary').value;
  if (t === 'weekly') return $('docKeyWeekly').value;
  return $('docKeyMonthly').value;
}
function switchDocType(t) {
  docState.type = t;
  $('docKeyDiary').classList.toggle('hidden', t !== 'diary');
  $('docKeyWeekly').classList.toggle('hidden', t !== 'weekly');
  $('docKeyMonthly').classList.toggle('hidden', t !== 'monthly');
  loadDiary();
}
function loadDiary() {
  const key = currentDocKey();
  if (!key) return;
  docState.key = key;
  const local = LS.get(docCacheKey(), null);
  const ta = $('diaryEditor');
  if (local) {
    ta.value = local.content;
    docState.mtime = local.mtime || 0;
    $('diarySaveTag').textContent = local.dirty ? '待同步' : (state.sync.online ? '已同步' : '已存档');
    $('diaryMeta').textContent = (state.sync.online ? '' : '离线 · ') + '最后修改 ' + new Date(local.mtime * 1000).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
    if (state.sync.online && !local.dirty) fetchDoc();
  } else if (state.sync.online) {
    $('diarySaveTag').textContent = '加载中…';
    fetchDoc();
  } else {
    ta.value = '';
    $('diarySaveTag').textContent = '离线';
    $('diaryMeta').textContent = '离线模式，无本地缓存';
  }
  renderDiaryImgs();
}
async function fetchDoc() {
  try {
    const d = await api('/api/doc?dtype=' + docState.type + '&key=' + encodeURIComponent(docState.key));
    const local = LS.get(docCacheKey(), null);
    if (local && local.dirty) return;
    docState.mtime = d.mtime || 0;
    LS.set(docCacheKey(), { content: d.content || '', mtime: d.mtime || 0, dirty: false });
    if (currentPage() === 'diary') {
      $('diaryEditor').value = d.content || '';
      renderDiaryImgs();
      $('diarySaveTag').textContent = d.exists ? '已同步' : '新建';
      $('diaryMeta').textContent = d.exists
        ? '已存在 · 最后修改 ' + new Date(d.mtime * 1000).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
        : '该文档不存在，保存将创建';
    }
  } catch (e) { }
}
async function saveDiary() {
  const content = $('diaryEditor').value;
  if (!content.trim()) { toast('内容为空'); return; }
  docState.mtime = Date.now() / 1000;
  LS.set(docCacheKey(), { content, mtime: docState.mtime, dirty: true });
  $('diarySaveTag').textContent = '已存本地';
  if (state.sync.online) await pushDocByCache(docCacheKey());
  else toast('离线：已存本地，重连后自动同步');
  loadOverview();
}
async function pushDocByCache(cacheKey) {
  const local = LS.get(cacheKey, null);
  if (!local || !local.dirty) return true;
  const { type, key } = docKeyFromCache(cacheKey);
  try {
    const cur = await api('/api/doc?dtype=' + type + '&key=' + encodeURIComponent(key)).catch(() => null);
    const base = (cur && cur.mtime) || 0;
    const r = await api('/api/doc', {
      method: 'PUT',
      body: JSON.stringify({ dtype: type, key, content: local.content, base_updated_at: base }),
    });
    LS.set(cacheKey, { content: local.content, mtime: r.mtime, dirty: false });
    if (type === docState.type && key === docState.key) {
      docState.mtime = r.mtime;
      $('diarySaveTag').textContent = '已同步';
    }
    toast('文档已同步到 PC');
    return true;
  } catch (e) {
    if (type === docState.type && key === docState.key) $('diarySaveTag').textContent = '同步失败';
    toast('同步失败：' + e.message);
    return false;
  }
}
async function syncDocs() {
  const keys = [];
  for (let i = 0; i < localStorage.length; i++) {
    const k = localStorage.key(i);
    if (k && k.startsWith('doc_')) keys.push(k);
  }
  for (const k of keys) {
    const local = LS.get(k, null);
    if (local && local.dirty) await pushDocByCache(k);
  }
}

/* ---------------- 番茄钟 (时间戳计时 + 持久化) ---------------- */
const FOCUS_MIN = 25, BREAK_MIN = 5;
const pomo = {
  mode: 'focus',
  running: false,
  totalSec: FOCUS_MIN * 60,
  remainSec: FOCUS_MIN * 60,
  endAt: 0,
  timerId: null,
  task: null,
  tasks: [],
  startTs: null,
};

function pomoPersist() {
  LS.set('pomo_state', {
    mode: pomo.mode, running: pomo.running,
    totalSec: pomo.totalSec, remainSec: pomo.remainSec,
    endAt: pomo.endAt, task: pomo.task, startTs: pomo.startTs,
  });
}
function pomoRestore() {
  const s = LS.get('pomo_state', null);
  if (!s) return;
  pomo.mode = s.mode || 'focus';
  pomo.totalSec = s.totalSec || FOCUS_MIN * 60;
  pomo.remainSec = s.remainSec || pomo.totalSec;
  pomo.task = s.task || null;
  pomo.startTs = s.startTs || null;
  if (s.running && s.endAt) {
    const remain = Math.round((s.endAt - Date.now()) / 1000);
    if (remain > 0) {
      pomo.running = true;
      pomo.endAt = s.endAt;
      pomo.timerId = setInterval(pomoTick, 1000);
    } else {
      // 后台期间已到点: 补完成
      pomo.running = false;
      pomo.remainSec = 0;
      setTimeout(() => pomoComplete(), 100);
    }
  }
}
function loadPomodoro() {
  loadTasks();
  renderTimer();
  loadPomoToday();
}
function pomoRemain() {
  if (pomo.running && pomo.endAt) return Math.max(0, Math.round((pomo.endAt - Date.now()) / 1000));
  return pomo.remainSec;
}
function renderTimer() {
  const remain = pomoRemain();
  const mm = String(Math.floor(remain / 60)).padStart(2, '0');
  const ss = String(remain % 60).padStart(2, '0');
  $('timerTime').textContent = mm + ':' + ss;
  const circ = 2 * Math.PI * 88;
  const pct = pomo.totalSec ? (1 - remain / pomo.totalSec) : 0;
  $('ringFg').style.strokeDashoffset = (circ * (1 - Math.max(0, Math.min(1, pct)))).toFixed(1);
  $('btnPomoToggle').textContent = pomo.running ? '暂停' : '开始';
  $('timerTask').textContent = pomo.task ? pomo.task.name : '未选择任务';
  document.querySelectorAll('#pomoModeSeg .seg-btn').forEach(b =>
    b.classList.toggle('active', b.dataset.mode === pomo.mode));
}
function pomoTick() {
  if (pomoRemain() <= 0) { pomoComplete(); return; }
  renderTimer();
}
function pomoToggle() {
  if (pomo.running) {
    pomo.remainSec = pomoRemain();
    pomo.running = false;
    if (pomo.timerId) { clearInterval(pomo.timerId); pomo.timerId = null; }
  } else {
    if (pomo.remainSec <= 0) pomo.remainSec = pomo.totalSec;
    pomo.running = true;
    pomo.endAt = Date.now() + pomo.remainSec * 1000;
    pomo.startTs = new Date().toISOString().replace(/\.\d+Z$/, 'Z');
    pomo.timerId = setInterval(pomoTick, 1000);
  }
  pomoPersist();
  renderTimer();
}
function pomoReset() {
  pomo.running = false;
  if (pomo.timerId) { clearInterval(pomo.timerId); pomo.timerId = null; }
  pomo.remainSec = pomo.totalSec;
  pomo.startTs = null;
  pomoPersist();
  renderTimer();
}
function pomoSkip() { pomoComplete(); }
async function pomoComplete() {
  const wasRunning = pomo.running;
  pomo.running = false;
  if (pomo.timerId) { clearInterval(pomo.timerId); pomo.timerId = null; }
  if (pomo.mode === 'focus') {
    const taskName = pomo.task ? pomo.task.name : '';
    recordPomoLocal(state.date, taskName, FOCUS_MIN);
    if (state.sync.online) pushPomos();
    if (pomo.task) {
      const t = pomo.tasks.find(x => x.file === pomo.task.file);
      if (t) { t.done = true; t.dirty = t.dirty === 'add' ? 'add' : 'toggle'; saveTasksLocal(); }
      if (state.sync.online) {
        const endTs = new Date().toISOString().replace(/\.\d+Z$/, 'Z');
        const startTs = pomo.startTs || endTs;
        api('/api/tasks/patch', { method: 'POST', body: JSON.stringify({ file: pomo.task.file, action: 'timeEntry', start_ts: startTs, end_ts: endTs }) }).catch(() => { });
        syncTasks();
      } else {
        toast('离线：任务已标记，重连后同步');
      }
    }
    pomo.mode = 'break';
    pomo.totalSec = BREAK_MIN * 60;
    pomo.remainSec = pomo.totalSec;
    toast('专注完成！休息一下 ☕');
  } else {
    pomo.mode = 'focus';
    pomo.totalSec = FOCUS_MIN * 60;
    pomo.remainSec = pomo.totalSec;
    toast('休息结束，继续专注 💪');
  }
  pomo.startTs = null;
  pomoPersist();
  renderTimer();
  loadPomoToday();
  loadOverview();
}

/* --- 任务 (本地权威) --- */
function loadTasks() {
  pomo.tasks = LS.get('tasks', []);
  renderTasks();
  if (state.sync.online) fetchTasks();
}
async function fetchTasks() {
  try {
    const d = await api('/api/tasks');
    const serverTasks = d.tasks || [];
    const local = pomo.tasks;
    const localFiles = {};
    local.forEach(t => { if (t.file) localFiles[t.file] = true; });
    serverTasks.forEach(st => {
      if (!localFiles[st.file]) {
        local.push({ file: st.file, name: st.name, done: st.status === 'done', priority: st.priority || 'normal', mtime: st.mtime, dirty: false });
      }
    });
    LS.set('tasks', local);
    renderTasks();
  } catch (e) { }
}
function saveTasksLocal() {
  LS.set('tasks', pomo.tasks);
  renderTasks();
}
function renderTasks() {
  const list = $('taskList');
  $('taskCount').textContent = pomo.tasks.length + ' 个';
  if (!pomo.tasks.length) { list.innerHTML = '<div class="empty">暂无任务，添加一个开始专注</div>'; return; }
  list.innerHTML = '';
  pomo.tasks.forEach((t, i) => {
    const el = document.createElement('div');
    el.className = 'task-item' + (t.done ? ' done' : '');
    const pri = t.priority === 'high' ? ' 🔥' : t.priority === 'medium' ? ' ·' : '';
    el.innerHTML =
      '<button class="task-check" data-i="' + i + '">✓</button>' +
      '<div class="task-name' + (pomo.task && pomo.task.file === t.file ? ' active' : '') + '" data-i="' + i + '">' + esc(t.name) + pri + '</div>' +
      '<button class="task-del" data-i="' + i + '">✕</button>';
    list.appendChild(el);
  });
}
async function addTask() {
  const v = $('taskInput').value.trim();
  if (!v) return;
  pomo.tasks.unshift({ file: null, name: v, done: false, priority: 'normal', mtime: 0, dirty: 'add' });
  saveTasksLocal();
  $('taskInput').value = '';
  if (state.sync.online) await syncTasks();
  else toast('离线：已存本地，重连后创建到 PC');
}
async function toggleTask(i) {
  const t = pomo.tasks[i];
  if (!t) return;
  t.done = !t.done;
  t.dirty = t.dirty === 'add' ? 'add' : 'toggle';
  saveTasksLocal();
  if (state.sync.online) await syncTasks();
  else toast('离线：已存本地，重连后同步');
}
async function deleteTask(i) {
  const t = pomo.tasks[i];
  if (!t) return;
  if (t.file) {
    const deleted = LS.get('deletedTasks', []);
    if (deleted.indexOf(t.file) < 0) deleted.push(t.file);
    LS.set('deletedTasks', deleted);
  }
  pomo.tasks.splice(i, 1);
  saveTasksLocal();
  if (state.sync.online) await syncTasks();
  else toast('离线：已存本地，重连后同步');
}
async function syncTasks() {
  const deleted = LS.get('deletedTasks', []);
  const tasks = LS.get('tasks', []);
  try {
    for (const f of deleted) {
      try { await api('/api/tasks/patch', { method: 'POST', body: JSON.stringify({ file: f, action: 'delete' }) }); } catch (e) { }
    }
    LS.set('deletedTasks', []);
    const d = await api('/api/tasks');
    const serverByName = {};
    (d.tasks || []).forEach(st => { serverByName[st.name] = st; });
    for (const t of tasks) {
      if (!t.dirty) continue;
      try {
        if (t.dirty === 'add' || !t.file) {
          const r = await api('/api/tasks/add', { method: 'POST', body: JSON.stringify({ name: t.name }) });
          t.file = r.task.file;
          t.dirty = false;
        } else if (t.dirty === 'toggle') {
          const st = serverByName[t.name];
          if (st) {
            await api('/api/tasks/patch', { method: 'POST', body: JSON.stringify({ file: st.file, action: 'toggle', done: t.done, base_mtime: t.mtime }) });
            t.file = st.file; t.mtime = Date.now() / 1000; t.dirty = false;
          }
        }
      } catch (e) { }
    }
    LS.set('tasks', tasks);
    await fetchTasks();
    renderTasks();
  } catch (e) { }
}

/* --- 番茄记录 --- */
function recordPomoLocal(date, task, minutes) {
  const list = LS.get('pomos', []);
  list.push({ date, task, minutes, ts: Date.now(), synced: false });
  LS.set('pomos', list);
}
async function pushPomos() {
  const list = LS.get('pomos', []);
  let changed = false;
  for (const r of list) {
    if (r.synced) continue;
    try {
      await api('/api/pomodoro', { method: 'POST', body: JSON.stringify({ date: r.date, task: r.task, minutes: r.minutes }) });
      r.synced = true; changed = true;
    } catch (e) { break; }
  }
  if (changed) LS.set('pomos', list);
}
async function syncPomos() { await pushPomos(); }
function loadPomoToday() {
  if (state.sync.online) {
    api('/api/pomodoro?date=' + state.date).then(d => {
      $('pomoToday').textContent = '今日：' + d.count + ' 个番茄 · 专注 ' + d.focus_min + ' 分钟';
    }).catch(() => { $('pomoToday').textContent = '今日：-'; });
  } else {
    const list = LS.get('pomos', []).filter(r => r.date === state.date);
    const cnt = list.length;
    const mins = list.reduce((s, r) => s + r.minutes, 0);
    $('pomoToday').textContent = '今日：' + cnt + ' 个番茄 · 专注 ' + mins + ' 分钟（离线）';
  }
}

/* ---------------- AI 助手 (WorkBuddy 风格对话) ---------------- */
const aiState = { history: [] };

function initAi() {
  $('aiSend').addEventListener('click', sendAi);
  $('aiInput').addEventListener('keydown', e => { if (e.key === 'Enter') sendAi(); });
  $('aiChips').addEventListener('click', e => {
    const c = e.target.closest('.chip');
    if (c) { $('aiInput').value = c.dataset.q; sendAi(); }
  });
}
function mdRender(t) {
  let s = esc(t);
  s = s.replace(/\*\*(.*?)\*\*/g, '<b>$1</b>');
  s = s.replace(/^- (.*)$/gm, '• $1');
  s = s.replace(/\n{2,}/g, '<br><br>').replace(/\n/g, '<br>');
  return s;
}
function appendAiMsg(role, text, isTyping) {
  const el = document.createElement('div');
  el.className = 'ai-msg ' + role;
  el.innerHTML = isTyping ? '…' : mdRender(text);
  $('aiChat').appendChild(el);
  $('aiChat').scrollTop = $('aiChat').scrollHeight;
  return el;
}
async function sendAi() {
  const v = $('aiInput').value.trim();
  if (!v) return;
  if (!state.sync.online) {
    appendAiMsg('assistant', '📴 离线模式：AI 助手需要连接 PC 才能使用（AI 在 PC 端分析你的工作台数据）。连接后可继续提问。');
    return;
  }
  $('aiInput').value = '';
  appendAiMsg('user', v);
  const typing = appendAiMsg('assistant', '', true);
  aiState.history.push({ role: 'user', content: v });
  try {
    const r = await api('/api/ai/chat', {
      method: 'POST',
      body: JSON.stringify({ messages: aiState.history.slice(-10), date: state.date }),
    });
    aiState.history.push({ role: 'assistant', content: r.reply });
    typing.innerHTML = mdRender(r.reply);
  } catch (e) {
    typing.innerHTML = '⚠️ ' + esc((e && e.message) || 'AI 调用失败');
  }
  $('aiChat').scrollTop = $('aiChat').scrollHeight;
}

/* ---------------- 照片同步 ---------------- */
function loadPhotos() {
  const grid = $('photoGrid');
  if (!state.sync.online) {
    grid.innerHTML = '<div class="empty">离线模式：照片需连接 PC 查看</div>';
    $('photoCount').textContent = '-';
    return;
  }
  grid.innerHTML = '<div class="empty">加载中…</div>';
  api('/api/photos').then(d => {
    const photos = d.photos || [];
    $('photoCount').textContent = photos.length + ' 张';
    if (!photos.length) { grid.innerHTML = '<div class="empty">暂无照片，点击上方按钮上传</div>'; return; }
    grid.innerHTML = '';
    photos.forEach(p => {
      const el = document.createElement('div');
      el.className = 'photo-item';
      const src = state.server.replace(/\/+$/, '') + p.url;
      const day = (p.name || '').replace('.jpg', '').slice(0, 8);
      el.innerHTML = '<img src="' + src + '" loading="lazy" onclick="window.open(\'' + src + '\')" /><div class="photo-date">' + p.month + ' ' + day + '</div>';
      grid.appendChild(el);
    });
  }).catch(() => {
    grid.innerHTML = '<div class="empty">加载失败（离线或服务器不可达）</div>';
  });
}
function uploadPhoto(file) {
  if (!file) return;
  if (!state.sync.online) { toast('离线：无法上传照片'); return; }
  if (file.size > 18 * 1024 * 1024) { toast('照片超过 18MB'); return; }
  const reader = new FileReader();
  reader.onload = async () => {
    try {
      $('btnPhotoPick').textContent = '上传中…';
      const r = await api('/api/photo/upload', {
        method: 'POST',
        body: JSON.stringify({ date: state.date, name: file.name || 'photo.jpg', data: reader.result }),
      });
      toast('已同步：' + r.rel);
      loadPhotos();
    } catch (e) {
      toast('上传失败：' + ((e && e.message) || ''));
    } finally {
      $('btnPhotoPick').textContent = '选择照片上传 → 同步到 Obsidian';
    }
  };
  reader.onerror = () => toast('读取照片失败');
  reader.readAsDataURL(file);
}

/* ---------------- 日记图片 (日记同步的补充) ---------------- */
const IMG_EXTS = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'bmp'];

function imgUrl(rel) {
  return state.server.replace(/\/+$/, '') + '/img/' + rel.split('/').map(encodeURIComponent).join('/');
}
function extractDiaryImages(text) {
  const out = [];
  const re = /!\[\[([^\]]+)\]\]/g;
  let m;
  while ((m = re.exec(text || ''))) {
    let ref = m[1].split('|')[0].trim();
    if (!ref) continue;
    const ext = ref.includes('.') ? ref.split('.').pop().toLowerCase() : '';
    if (IMG_EXTS.indexOf(ext) < 0) continue;
    out.push(ref);
  }
  return out;
}
function renderDiaryImgs() {
  const wrap = $('diaryImgs');
  const imgs = extractDiaryImages($('diaryEditor').value);
  if (!imgs.length) { wrap.innerHTML = '<div class="empty">文档中的图片将显示在这里（可点开查看/下载）</div>'; return; }
  wrap.innerHTML = '';
  imgs.forEach(rel => {
    const el = document.createElement('div');
    el.className = 'diary-thumb';
    el.innerHTML = '<img src="' + imgUrl(rel) + '" loading="lazy" />';
    el.addEventListener('click', () => openViewer(imgUrl(rel)));
    wrap.appendChild(el);
  });
}
function openViewer(url) {
  $('photoViewerImg').src = url;
  $('photoViewer').classList.remove('hidden');
}
function closeViewer() {
  $('photoViewer').classList.add('hidden');
  $('photoViewerImg').src = '';
}
function insertAtCursor(ta, text) {
  const s = ta.selectionStart == null ? ta.value.length : ta.selectionStart;
  const e = ta.selectionEnd == null ? s : ta.selectionEnd;
  ta.value = ta.value.slice(0, s) + text + ta.value.slice(e);
  ta.selectionStart = ta.selectionEnd = s + text.length;
  ta.dispatchEvent(new Event('input'));
}
async function uploadDiaryImage(file) {
  if (!file) return;
  if (!state.sync.online) { toast('离线：插图需连接 PC'); return; }
  if (file.size > 18 * 1024 * 1024) { toast('图片超过 18MB'); return; }
  const reader = new FileReader();
  reader.onload = async () => {
    try {
      const r = await api('/api/photo/upload', {
        method: 'POST',
        body: JSON.stringify({ date: state.date, name: file.name || 'photo.jpg', data: reader.result }),
      });
      insertAtCursor($('diaryEditor'), '\n![[' + r.rel + ']]\n');
      renderDiaryImgs();
      toast('已插入图片');
    } catch (e) {
      toast('上传失败：' + ((e && e.message) || ''));
    }
  };
  reader.onerror = () => toast('读取图片失败');
  reader.readAsDataURL(file);
}

/* ---------------- 设置 ---------------- */
function initSettings() {
  const grid = $('bgGrid');
  grid.innerHTML = '';
  PRESET_BGS.forEach((g, i) => {
    const cell = document.createElement('div');
    cell.className = 'bg-cell' + (state.bgIndex === i && !state.customBg ? ' active' : '');
    cell.style.background = g;
    cell.onclick = () => {
      state.bgIndex = i; state.customBg = '';
      window.Native.savePref('bg_index', String(i));
      window.Native.savePref('bg_custom', '');
      applyBg();
      grid.querySelectorAll('.bg-cell').forEach(c => c.classList.remove('active'));
      cell.classList.add('active');
    };
    grid.appendChild(cell);
  });
}
function applyBg() {
  const b = document.body;
  const custom = window.Native.loadPref('bg_custom', '');
  if (custom) {
    b.classList.add('has-bgimg');
    b.style.backgroundImage = 'none';
    void b.offsetHeight;
    b.style.backgroundImage = "url('" + custom + "')";
    b.style.backgroundSize = 'cover';
    b.style.backgroundPosition = 'center';
    b.style.backgroundRepeat = 'no-repeat';
    b.style.backgroundAttachment = 'fixed';
    b.style.backgroundColor = 'transparent';
  } else {
    b.classList.remove('has-bgimg');
    const idx = parseInt(window.Native.loadPref('bg_index', '0'), 10) || 0;
    b.style.cssText = '';
    b.style.background = PRESET_BGS[idx] || PRESET_BGS[0];
  }
}
function toast(msg) {
  const el = $('connTestResult');
  if (el && currentPage() === 'settings') el.textContent = msg;
  console.log('[toast]', msg);
}

/* ---------------- 初始化 ---------------- */
function init() {
  state.server = window.Native.loadPref('server', '');
  state.bgIndex = parseInt(window.Native.loadPref('bg_index', '0'), 10) || 0;
  state.customBg = window.Native.loadPref('bg_custom', '');

  const now = new Date();
  $('dateLine').textContent = now.getMonth() + 1 + '月' + now.getDate() + '日 · 周' + ['日', '一', '二', '三', '四', '五', '六'][now.getDay()];
  const h = now.getHours();
  $('greetText').textContent = h < 6 ? '夜深了' : h < 12 ? '早上好' : h < 18 ? '下午好' : '晚上好';
  $('favDate').value = state.date;
  $('docKeyDiary').value = state.date;
  $('docKeyWeekly').value = isoWeekKey(now);
  $('docKeyMonthly').value = now.getFullYear() + '-' + String(now.getMonth() + 1).padStart(2, '0');

  applyBg();
  initSettings();
  $('inputServer').value = state.server.replace(/^https?:\/\//, '') || '';

  // 底部导航
  document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => goTab(tab.dataset.page));
  });
  $('btnBack').addEventListener('click', goBack);
  document.querySelectorAll('.stat-card[data-goto], .card[data-goto], .quick-item[data-goto], .focus-item[data-goto]').forEach(card => {
    card.addEventListener('click', () => {
      const page = card.dataset.goto;
      if (TABS.indexOf(page) >= 0) goTab(page);
      else pushPage(page);   // 非 tab 页面(照片等)作为二级页进入
    });
  });

  // AI 快捷输入条: 提问后跳转 AI 页
  const quickAsk = () => {
    const v = $('aiQuickInput').value.trim();
    if (!v) { goTab('ai'); return; }
    $('aiQuickInput').value = '';
    goTab('ai', 1);
    setTimeout(() => {
      $('aiInput').value = v;
      sendAi();
    }, 400);
  };
  $('aiQuickSend').addEventListener('click', quickAsk);
  $('aiQuickInput').addEventListener('keydown', e => { if (e.key === 'Enter') quickAsk(); });

  // 同步按钮
  $('btnSync').addEventListener('click', async () => {
    const btn = $('btnSync');
    btn.classList.add('spinning'); btn.disabled = true;
    try {
      if (state.sync.online) await syncAll();
      else await checkConnection();
      await loadUsage();
      await loadOverview();
    } finally {
      btn.classList.remove('spinning'); btn.disabled = false;
    }
  });
  $('btnSyncUsage').addEventListener('click', collectAndReport);
  $('btnDailyReport').addEventListener('click', generateDailyReport);

  // AI 助手
  initAi();

  // 照片同步
  $('btnPhotoPick').addEventListener('click', () => $('photoInput').click());
  $('photoInput').addEventListener('change', e => {
    const f = e.target.files && e.target.files[0];
    uploadPhoto(f);
    e.target.value = '';
  });

  // 日记图片 (日记同步补充)
  $('btnDiaryImg').addEventListener('click', () => $('diaryImgInput').click());
  $('diaryImgInput').addEventListener('change', e => {
    const f = e.target.files && e.target.files[0];
    uploadDiaryImage(f);
    e.target.value = '';
  });
  $('diaryEditor').addEventListener('input', () => renderDiaryImgs());
  $('btnViewerSave').addEventListener('click', () => {
    const src = $('photoViewerImg').src;
    if (src && window.Native && window.Native.downloadImage) {
      toast('正在下载…');
      window.Native.downloadImage(src);
    } else { toast('当前环境不支持下载'); }
  });
  $('btnViewerClose').addEventListener('click', closeViewer);

  // 收藏页
  $('favDate').addEventListener('change', loadFavorites);
  $('favPlatformSeg').addEventListener('click', e => {
    const btn = e.target.closest('.seg-btn');
    if (!btn) return;
    state.favPlatform = btn.dataset.p;
    $('favPlatformSeg').querySelectorAll('.seg-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    loadFavorites();
  });

  // 文档页 (日记/周记/月记)
  $('docTypeSeg').addEventListener('click', e => {
    const btn = e.target.closest('.seg-btn');
    if (!btn) return;
    $('docTypeSeg').querySelectorAll('.seg-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    switchDocType(btn.dataset.type);
  });
  ['docKeyDiary', 'docKeyWeekly', 'docKeyMonthly'].forEach(id => {
    $(id).addEventListener('change', loadDiary);
  });
  $('btnDiarySave').addEventListener('click', saveDiary);
  $('btnDiaryReload').addEventListener('click', loadDiary);

  // 番茄钟
  $('btnPomoToggle').addEventListener('click', pomoToggle);
  $('btnPomoReset').addEventListener('click', pomoReset);
  $('btnPomoSkip').addEventListener('click', pomoSkip);
  $('pomoModeSeg').addEventListener('click', e => {
    const btn = e.target.closest('.seg-btn');
    if (!btn) return;
    if (pomo.running) { pomoReset(); }
    pomo.mode = btn.dataset.mode;
    pomo.totalSec = (pomo.mode === 'focus' ? FOCUS_MIN : BREAK_MIN) * 60;
    pomo.remainSec = pomo.totalSec;
    pomoPersist();
    renderTimer();
  });
  $('btnAddTask').addEventListener('click', addTask);
  $('taskInput').addEventListener('keydown', e => { if (e.key === 'Enter') addTask(); });
  $('taskList').addEventListener('click', e => {
    const chk = e.target.closest('.task-check');
    const del = e.target.closest('.task-del');
    const name = e.target.closest('.task-name');
    if (chk) toggleTask(+chk.dataset.i);
    else if (del) deleteTask(+del.dataset.i);
    else if (name) {
      const t = pomo.tasks[+name.dataset.i];
      if (t && !t.done) { pomo.task = (pomo.task && pomo.task.file === t.file) ? null : t; renderTasks(); renderTimer(); }
    }
  });

  // 健康
  $('btnSleepAdd').addEventListener('click', () => {
    const start = $('sleepStart').value || '23:30';
    const end = $('sleepEnd').value || '07:00';
    const mins = calcSleepMin(start, end);
    recordHealth('sleep', '夜间睡眠', mins, start, end);
    $('sleepHint').textContent = '睡眠 ' + fmtMin(mins);
  });
  $('btnExAdd').addEventListener('click', () => {
    const type = $('exType').value;
    const min = parseInt($('exMin').value, 10);
    if (!min || min <= 0) { toast('请输入运动分钟数'); return; }
    recordHealth('exercise', type, min, '', '');
    $('exMin').value = '';
  });

  // 权限引导
  $('btnOpenPerm').addEventListener('click', () => window.Native.openUsageAccessSettings());

  // 设置
  $('btnSettings').addEventListener('click', () => pushPage('settings'));
  $('btnTestConn').addEventListener('click', async () => {
    let v = $('inputServer').value.trim();
    if (v && !/^https?:\/\//.test(v)) v = 'http://' + v;
    state.server = v;
    window.Native.savePref('server', v);
    const r = $('connTestResult');
    r.textContent = '测试中…';
    const ok = await checkConnection();
    r.textContent = ok ? '已连接：' + state.server + ' · 数据已同步' : '连接失败：请检查地址与网络';
    if (ok) loadOverview();
  });
  $('btnPickBg').addEventListener('click', () => window.Native.pickBackground());
  $('btnClearBg').addEventListener('click', () => {
    window.Native.clearBackground();
    window.Native.savePref('bg_custom', '');
    applyBg();
  });
  window.__onBackgroundChanged = () => {
    window.Native.savePref('bg_custom', window.Native.getBackgroundUri());
    applyBg();
  };

  // 物理返回键
  window.__goBackApp = function () {
    if (state.stack.length > 0) { goBack(); return 'ok'; }
    return 'none';
  };

  /* --- 跟手拖拽 (左右切换 tab) --- */
  let drag = null;
  document.addEventListener('touchstart', e => {
    if (e.touches.length !== 1) return;
    const active = document.activeElement;
    if (active && (active.tagName === 'TEXTAREA' || active.tagName === 'INPUT' || active.tagName === 'SELECT')) return;
    const page = currentPage();
    if (TABS.indexOf(page) < 0) return;
    drag = { startX: e.touches[0].clientX, startY: e.touches[0].clientY, axis: null, page, next: null, dir: 0 };
  }, { passive: true });

  document.addEventListener('touchmove', e => {
    if (!drag || drag.axis === 'v') return;
    const dx = e.touches[0].clientX - drag.startX;
    const dy = e.touches[0].clientY - drag.startY;
    if (drag.axis === null) {
      if (Math.abs(dx) < 10 && Math.abs(dy) < 10) return;
      drag.axis = Math.abs(dx) > Math.abs(dy) ? 'h' : 'v';
      if (drag.axis === 'h') {
        const idx = TABS.indexOf(drag.page);
        drag.dir = dx < 0 ? 1 : -1;
        const nIdx = idx + drag.dir;
        if (nIdx < 0 || nIdx >= TABS.length) { drag.axis = 'v'; return; }
        drag.next = TABS[nIdx];
        const curEl = $('page-' + drag.page);
        const nextEl = $('page-' + drag.next);
        nextEl.classList.remove('hidden');
        [curEl, nextEl].forEach(p => { p.style.position = 'absolute'; p.style.top = '0'; p.style.left = '0'; p.style.width = '100%'; });
        curEl.style.transition = 'none'; nextEl.style.transition = 'none';
        curEl.style.transform = 'translateX(0)'; curEl.style.opacity = '1';
        nextEl.style.transform = 'translateX(' + (drag.dir > 0 ? 100 : -100) + '%)'; nextEl.style.opacity = '1';
      }
    }
    if (drag.axis === 'h') {
      e.preventDefault();
      const W = window.innerWidth;
      const curEl = $('page-' + drag.page);
      const nextEl = $('page-' + drag.next);
      curEl.style.transform = 'translateX(' + dx + 'px)';
      nextEl.style.transform = 'translateX(' + (dx + (drag.dir > 0 ? W : -W)) + 'px)';
      const progress = Math.min(1, Math.abs(dx) / W);
      curEl.style.opacity = (1 - progress * 0.4).toFixed(2);
    }
  }, { passive: false });

  document.addEventListener('touchend', e => {
    if (!drag) return;
    if (drag.axis === 'h' && drag.next) {
      const dx = e.changedTouches[0].clientX - drag.startX;
      const W = window.innerWidth;
      const shouldSwitch = Math.abs(dx) > W / 3;
      const curEl = $('page-' + drag.page);
      const nextEl = $('page-' + drag.next);
      const EASE = 'transform .28s cubic-bezier(.25,.8,.3,1), opacity .28s ease';
      curEl.style.transition = EASE; nextEl.style.transition = EASE;
      if (shouldSwitch) {
        curEl.style.transform = 'translateX(' + (-drag.dir * W * 0.4) + 'px)';
        curEl.style.opacity = '0';
        nextEl.style.transform = 'translateX(0)';
        nextEl.style.opacity = '1';
        const target = drag.next;
        setTimeout(() => {
          curEl.classList.add('hidden');
          [curEl, nextEl].forEach(p => p.style.cssText = '');
          state.stack = [];
          showPage(target, 0);
        }, 300);
      } else {
        curEl.style.transform = 'translateX(0)';
        curEl.style.opacity = '1';
        nextEl.style.transform = 'translateX(' + (drag.dir > 0 ? W : -W) + 'px)';
        setTimeout(() => {
          nextEl.classList.add('hidden');
          [curEl, nextEl].forEach(p => p.style.cssText = '');
        }, 300);
      }
    }
    drag = null;
  }, { passive: true });

  /* --- 离线优先启动 --- */
  updateSyncStatus();
  pomoRestore();
  loadTasks();
  loadDiary();
  loadOverview();
  loadHealth();
  if (state.server) {
    checkConnection().then(ok => {
      if (!ok) toast('离线模式：数据已存档，重连后自动同步');
    });
    startHeartbeat();
  } else {
    $('syncStatusText').textContent = '未配置服务器地址';
    pushPage('settings');
  }
}

document.addEventListener('DOMContentLoaded', init);
