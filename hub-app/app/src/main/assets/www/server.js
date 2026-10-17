/* ============================================================
   学习中枢 · 公共服务器模块（门户 / 学习中枢 / 工具箱 共用）
   - 服务器地址存取（App 内走原生桥，浏览器端走 localStorage）
   - api() 统一请求（8s 超时）
   - discover() UDP 自动发现 PC（App 内）
   ============================================================ */
(function () {
  'use strict';
  var KEY = 'hub_server';
  var IS_APP = typeof window.Native !== 'undefined';

  function getServer() {
    var v = '';
    try { if (IS_APP && window.Native.loadPref) v = window.Native.loadPref(KEY, '') || ''; } catch (e) { }
    if (!v) { try { v = localStorage.getItem(KEY) || ''; } catch (e) { } }
    return String(v).trim().replace(/\/+$/, '');
  }

  function setServer(v) {
    v = String(v || '').trim().replace(/\/+$/, '');
    try { if (IS_APP && window.Native.savePref) window.Native.savePref(KEY, v); } catch (e) { }
    try { localStorage.setItem(KEY, v); } catch (e) { }
    return v;
  }

  function api(path, opts) {
    opts = opts || {};
    var server = getServer();
    if (!server) return Promise.reject(new Error('未设置服务器地址'));
    var url = server + path;
    var ctrl = new AbortController();
    var timer = setTimeout(function () { ctrl.abort(); }, 8000);
    return fetch(url, Object.assign({ headers: { 'Content-Type': 'application/json' }, signal: ctrl.signal }, opts))
      .then(function (res) {
        return res.json().catch(function () { return {}; }).then(function (data) {
          if (!res.ok) {
            var err = new Error(data.detail ? (typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)) : ('HTTP ' + res.status));
            err.status = res.status; err.data = data;
            throw err;
          }
          return data;
        });
      })
      .finally(function () { clearTimeout(timer); });
  }

  function health() {
    return api('/').then(function () { return true; }).catch(function () { return false; });
  }

  /** UDP 自动发现：返回 [{name, ip, port, url}] */
  function discover() {
    if (IS_APP && window.Native.discoverServers) {
      try {
        var list = JSON.parse(window.Native.discoverServers() || '[]');
        return (list || []).map(function (s) {
          s.url = 'http://' + s.ip + ':' + (s.port || 8637);
          return s;
        });
      } catch (e) { return []; }
    }
    return [];
  }

  /** 发现并自动连接：返回 url 或 null */
  async function autoConnect() {
    var list = discover();
    for (var i = 0; i < list.length; i++) {
      setServer(list[i].url);
      if (await health()) return list[i].url;
    }
    return null;
  }

  window.ServerMod = {
    IS_APP: IS_APP,
    KEY: KEY,
    getServer: getServer,
    setServer: setServer,
    api: api,
    health: health,
    discover: discover,
    autoConnect: autoConnect
  };
})();
