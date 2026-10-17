package com.xinghui.workbench;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.view.View;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.appcompat.app.AppCompatActivity;

public class MainActivity extends AppCompatActivity {

    private WebView webView;
    private JsBridge bridge;
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
        WebSettings s = webView.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setAllowFileAccess(true);
        s.setAllowContentAccess(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setCacheMode(WebSettings.LOAD_DEFAULT);

        webView.addJavascriptInterface(bridge, "Native");
        webView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                String scheme = uri.getScheme() == null ? "" : uri.getScheme();
                if ("http".equals(scheme) || "https".equals(scheme)) {
                    // 外部链接(收藏原文等)交给系统浏览器
                    if (!uri.getHost().contains("127.0.0.1") && !isLanHost(uri.getHost())) {
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

        // <input type="file"> 支持: 调起系统文件/相册选择器 (照片同步等)
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

        webView.loadUrl("file:///android_asset/www/index.html");
        hideSystemUi();
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

    /** 沉浸式: 隐藏系统状态栏/导航栏, 全屏工作台体验 */
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
        // 优先交给 WebView 的页面栈处理(返回上级场景), 无上级再退出
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
}
