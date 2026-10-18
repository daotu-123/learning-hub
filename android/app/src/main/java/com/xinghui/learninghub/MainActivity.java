package com.xinghui.learninghub;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.view.View;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.appcompat.app.AppCompatActivity;
import androidx.webkit.WebViewAssetLoader;

import java.io.ByteArrayInputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.InputStream;
import java.net.URLConnection;
import java.util.HashMap;
import java.util.Locale;

/**
 * 单 App 外壳（学习中枢 / 题库 / 工作台 三 Tab 合一）
 *
 * 网页通过 WebViewAssetLoader 以 http 源加载：
 *   http://appassets.androidplatform.net/www/index.html
 * （用 http 而非 https：页面要直连 LAN 上的 http 服务，https 页面调 http 会被当混合内容拦掉）
 * 这样 ES module、动态 import、localStorage 都按正常 https 规则工作，
 * 避开 file:// 下模块脚本的 CORS 限制（旧版三个 APK 都用经典 script 才没踩到）。
 *
 * 目录优先级：files/www（热更新缓存） > assets/www（安装包内置）
 * 背景图同样走该源（/bg/），因此不需要开放 file:// 访问。
 */
public class MainActivity extends AppCompatActivity {

    static final String HOST = "appassets.androidplatform.net";
    static final String ENTRY = "http://" + HOST + "/www/index.html";

    private WebView webView;
    private JsBridge bridge;
    private WebViewAssetLoader assetLoader;
    private ActivityResultLauncher<Intent> imagePickerLauncher;
    private ActivityResultLauncher<Intent> fileChooserLauncher;
    private ValueCallback<Uri[]> uploadCallback;

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        webView = new WebView(this);
        setContentView(webView);

        bridge = new JsBridge(this);
        assetLoader = new WebViewAssetLoader.Builder()
                // 允许 http 源：页面与 LAN 上的 http://服务同协议，避免混合内容被拦
                .setHttpAllowed(true)
                .addPathHandler("/www/", new WwwHandler(this))
                .addPathHandler("/bg/", new BgHandler(this))
                .build();

        WebSettings s = webView.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setAllowFileAccess(false);          // 全部资源走 https 源，不再需要 file://
        s.setAllowContentAccess(true);        // 选择相册文件仍走 content://
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setCacheMode(WebSettings.LOAD_DEFAULT);

        webView.addJavascriptInterface(bridge, "Native");
        webView.setWebViewClient(new WebViewClient() {
            @Override
            public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                WebResourceResponse r = assetLoader.shouldInterceptRequest(request.getUrl());
                return r != null ? r : super.shouldInterceptRequest(view, request);
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                String scheme = uri.getScheme() == null ? "" : uri.getScheme();
                String host = uri.getHost() == null ? "" : uri.getHost();
                if (HOST.equals(host)) return false;   // 内部资源不拦截
                if ("http".equals(scheme) || "https".equals(scheme)) {
                    // 外部链接（收藏原文等）交给系统浏览器
                    if (!host.contains("127.0.0.1") && !isLanHost(host)) {
                        try {
                            startActivity(new Intent(Intent.ACTION_VIEW, uri));
                        } catch (Exception e) {
                            view.loadUrl(uri.toString());
                        }
                        return true;
                    }
                    return false;
                }
                return false;
            }
        });

        // <input type="file"> 支持：调起系统文件/相册选择器（照片同步等）
        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> filePathCallback,
                                             FileChooserParams fileChooserParams) {
                if (uploadCallback != null) {
                    uploadCallback.onReceiveValue(null);
                }
                uploadCallback = filePathCallback;
                Intent intent = fileChooserParams.createIntent();
                try {
                    fileChooserLauncher.launch(intent);
                } catch (Exception e) {
                    uploadCallback = null;
                    return false;
                }
                return true;
            }
        });

        imagePickerLauncher = registerForActivityResult(
                new ActivityResultContracts.StartActivityForResult(),
                result -> {
                    if (result.getResultCode() == Activity.RESULT_OK && result.getData() != null) {
                        Uri uri = result.getData().getData();
                        if (uri != null) bridge.saveBackgroundUri(uri);
                    }
                });

        fileChooserLauncher = registerForActivityResult(
                new ActivityResultContracts.StartActivityForResult(),
                result -> {
                    if (uploadCallback == null) return;
                    Uri[] uris = null;
                    if (result.getResultCode() == Activity.RESULT_OK && result.getData() != null) {
                        Uri uri = result.getData().getData();
                        if (uri != null) uris = new Uri[]{uri};
                    }
                    uploadCallback.onReceiveValue(uris);
                    uploadCallback = null;
                });

        bridge.startDiscovery();
        // 老版本把 www/index.html 当门户写进缓存，升级到单 App 后必须作废
        bridge.migrateWebCache(2);
        reloadPortal();
        hideSystemUi();
    }

    /** 加载入口（热更新后重载也走这里，缓存优先逻辑在 WwwHandler 内部） */
    public void reloadPortal() {
        webView.loadUrl(ENTRY);
    }

    private boolean isLanHost(String host) {
        if (host == null) return false;
        return host.equals("localhost")
                || host.startsWith("192.168.")
                || host.startsWith("10.")
                || host.startsWith("172.")
                || host.equals("127.0.0.1");
    }

    public WebView getWebView() {
        return webView;
    }

    public void launchImagePicker() {
        Intent intent = new Intent(Intent.ACTION_PICK);
        intent.setType("image/*");
        try {
            imagePickerLauncher.launch(intent);
        } catch (Exception e) {
            Toast.makeText(this, "无法打开相册", Toast.LENGTH_SHORT).show();
        }
    }

    /** 沉浸式：隐藏系统状态栏/导航栏 */
    private void hideSystemUi() {
        View decor = getWindow().getDecorView();
        decor.setSystemUiVisibility(
                View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                        | View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                        | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                        | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                        | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                        | View.SYSTEM_UI_FLAG_FULLSCREEN);
        decor.setOnSystemUiVisibilityChangeListener(visibility ->
                hideSystemUi());
    }

    @Override
    public void onBackPressed() {
        // 优先交给网页处理页面栈（三 Tab 内的返回），无上级再退出
        webView.evaluateJavascript(
                "window.__goBackApp ? __goBackApp() : 'none'",
                value -> {
                    String v = value == null ? "" : value.replace("\"", "");
                    if (!"ok".equals(v)) {
                        MainActivity.super.onBackPressed();
                    }
                });
    }

    @Override
    protected void onResume() {
        super.onResume();
        hideSystemUi();
    }

    // ------------------------------------------------------------ 资源处理

    static String mimeOf(String path) {
        String p = path.toLowerCase(Locale.US);
        if (p.endsWith(".js") || p.endsWith(".mjs")) return "text/javascript";
        if (p.endsWith(".css")) return "text/css";
        if (p.endsWith(".html") || p.endsWith(".htm")) return "text/html";
        if (p.endsWith(".json") || p.endsWith(".map")) return "application/json";
        if (p.endsWith(".svg")) return "image/svg+xml";
        if (p.endsWith(".png")) return "image/png";
        if (p.endsWith(".webp")) return "image/webp";
        if (p.endsWith(".jpg") || p.endsWith(".jpeg")) return "image/jpeg";
        if (p.endsWith(".gif")) return "image/gif";
        if (p.endsWith(".woff2")) return "font/woff2";
        if (p.endsWith(".woff")) return "font/woff";
        if (p.endsWith(".ttf")) return "font/ttf";
        String guess = URLConnection.guessContentTypeFromName(path);
        return guess != null ? guess : "application/octet-stream";
    }

    static boolean isText(String mime) {
        return mime.startsWith("text/") || mime.equals("application/json")
                || mime.equals("image/svg+xml");
    }

    static WebResourceResponse respond(InputStream in, String path, boolean noCache) {
        String mime = mimeOf(path);
        HashMap<String, String> headers = new HashMap<>();
        if (noCache) headers.put("Cache-Control", "no-cache, no-store, must-revalidate");
        // 模块脚本带 crossorigin 属性；显式给 CORS 头，避免个别 WebView 版本按跨域处理时报错
        headers.put("Access-Control-Allow-Origin", "*");
        return new WebResourceResponse(mime, isText(mime) ? "utf-8" : null, 200, "OK", headers, in);
    }

    static WebResourceResponse notFound(int code, String msg) {
        return new WebResourceResponse("text/plain", "utf-8", code,
                code == 403 ? "Forbidden" : "Not Found", null,
                new ByteArrayInputStream(msg.getBytes()));
    }

    /** /www/ ：files/www（热更新缓存）优先，缺失回落到 assets/www */
    static class WwwHandler implements WebViewAssetLoader.PathHandler {
        private final MainActivity act;

        WwwHandler(MainActivity act) { this.act = act; }

        @Override
        public WebResourceResponse handle(String path) {
            if (path == null || path.isEmpty() || path.equals("/")) path = "index.html";
            while (path.startsWith("/")) path = path.substring(1);
            if (path.contains("..")) return notFound(403, "bad path");
            try {
                File cache = new File(new File(act.getFilesDir(), "www"), path);
                if (cache.isFile()) {
                    return respond(new FileInputStream(cache), path, path.endsWith(".html"));
                }
                InputStream in = act.getAssets().open("www/" + path);
                return respond(in, path, path.endsWith(".html"));
            } catch (Exception e) {
                return notFound(404, "not found: " + path);
            }
        }
    }

    /** /bg/ ：自定义背景图（filesDir 下的 bg_*.jpg），避免开放 file:// */
    static class BgHandler implements WebViewAssetLoader.PathHandler {
        private final MainActivity act;

        BgHandler(MainActivity act) { this.act = act; }

        @Override
        public WebResourceResponse handle(String path) {
            if (path == null) return notFound(404, "no path");
            while (path.startsWith("/")) path = path.substring(1);
            if (path.isEmpty() || path.contains("..") || path.contains("/")) return notFound(403, "bad path");
            File f = new File(act.getFilesDir(), path);
            if (!f.isFile()) return notFound(404, "not found");
            try {
                return respond(new FileInputStream(f), path, false);
            } catch (Exception e) {
                return notFound(404, "not found");
            }
        }
    }
}
