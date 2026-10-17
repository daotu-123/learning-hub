package com.xinghui.learninghub;

import android.annotation.SuppressLint;
import android.app.AlarmManager;
import android.app.PendingIntent;
import android.content.ContentValues;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.media.MediaScannerConnection;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.os.SystemClock;
import android.provider.MediaStore;
import android.provider.Settings;
import android.webkit.JavascriptInterface;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.InetAddress;
import java.nio.charset.StandardCharsets;
import java.util.Locale;
import java.util.concurrent.ConcurrentHashMap;

/**
 * 原生桥: 供 WebView 中的 JS 调用
 *  - 本地偏好存储 (服务器地址/背景/提醒等)
 *  - PC 服务 UDP 自动发现 (端口 8638)
 *  - 网页热更新 (缓存目录 www/)
 *  - 每日提醒 (AlarmManager + 通知)
 *  - 图片下载 / 背景图选择
 */
public class JsBridge {
    private final MainActivity activity;
    private final SharedPreferences prefs;

    /** UDP 发现缓存: ip -> [name, port, lastSeenMs] */
    private final ConcurrentHashMap<String, String[]> discovered = new ConcurrentHashMap<>();
    private volatile boolean discovering = false;

    public JsBridge(MainActivity activity) {
        this.activity = activity;
        this.prefs = activity.getSharedPreferences("learninghub", Context.MODE_PRIVATE);
    }

    // ---------------------------------------------------------------- prefs
    @JavascriptInterface
    public void savePref(String key, String value) {
        prefs.edit().putString(key, value).apply();
    }

    @JavascriptInterface
    public String loadPref(String key, String def) {
        return prefs.getString(key, def);
    }

    // ---------------------------------------------------------------- device
    @JavascriptInterface
    public String getDeviceInfo() {
        try {
            JSONObject o = new JSONObject();
            o.put("brand", Build.BRAND);
            o.put("model", Build.MODEL);
            o.put("android", Build.VERSION.RELEASE);
            o.put("sdk", Build.VERSION.SDK_INT);
            return o.toString();
        } catch (Exception e) {
            return "{}";
        }
    }

    // ---------------------------------------------------------------- UDP 自动发现 (PC 服务广播, 端口 8638)
    @JavascriptInterface
    public void startDiscovery() {
        if (discovering) return;
        discovering = true;
        new Thread(() -> {
            DatagramSocket socket = null;
            try {
                socket = new DatagramSocket(8638, InetAddress.getByName("0.0.0.0"));
                socket.setBroadcast(true);
                socket.setSoTimeout(1500);
                byte[] buf = new byte[1024];
                while (discovering) {
                    try {
                        DatagramPacket packet = new DatagramPacket(buf, buf.length);
                        socket.receive(packet);
                        String msg = new String(packet.getData(), packet.getOffset(), packet.getLength(), StandardCharsets.UTF_8).trim();
                        // 协议: LEARNINGHUB|<name>|<port>
                        String[] parts = msg.split("\\|");
                        if (parts.length >= 3 && "LEARNINGHUB".equals(parts[0])) {
                            String ip = packet.getAddress().getHostAddress();
                            discovered.put(ip, new String[]{parts[1], parts[2], String.valueOf(System.currentTimeMillis())});
                        }
                    } catch (java.net.SocketTimeoutException ignored) {
                        // 超时是正常的, 继续等; 顺带清理 15s 未出现的设备
                        long now = System.currentTimeMillis();
                        for (String k : discovered.keySet()) {
                            String[] v = discovered.get(k);
                            if (v != null && now - Long.parseLong(v[2]) > 15000) discovered.remove(k);
                        }
                    }
                }
            } catch (Exception ignored) {
            } finally {
                if (socket != null) socket.close();
            }
        }).start();
    }

    /** 返回已发现的 PC 列表 [{name, ip, port}] */
    @JavascriptInterface
    public String discoverServers() {
        JSONArray out = new JSONArray();
        try {
            long now = System.currentTimeMillis();
            for (java.util.Map.Entry<String, String[]> e : discovered.entrySet()) {
                String[] v = e.getValue();
                if (now - Long.parseLong(v[2]) > 15000) continue;
                JSONObject o = new JSONObject();
                o.put("ip", e.getKey());
                o.put("name", v[0]);
                o.put("port", Integer.parseInt(v[1]));
                out.put(o);
            }
        } catch (Exception ignored) {
        }
        return out.toString();
    }

    // ---------------------------------------------------------------- 网页热更新
    /** 当前内置网页版本号 (缓存优先) */
    @JavascriptInterface
    public int getWebVersion() {
        return prefs.getInt("web_version", 1);
    }

    /** 保存一个网页文件到缓存目录 files/www/<name> (name 形如 index.html / hub.html / tools/app.js) */
    @JavascriptInterface
    public boolean saveWebFile(String name, String content) {
        try {
            if (name == null || name.isEmpty() || name.contains("..") || name.contains(":\\")) return false;
            File f = new File(new File(activity.getFilesDir(), "www"), name);
            File parent = f.getParentFile();
            if (parent != null) parent.mkdirs();
            try (FileOutputStream fos = new FileOutputStream(f)) {
                fos.write(content.getBytes(StandardCharsets.UTF_8));
            }
            prefs.edit().putInt("web_version", Math.max(prefs.getInt("web_version", 1), 1)).apply();
            return true;
        } catch (Exception e) {
            return false;
        }
    }

    /** 记录网页版本号 (全部文件下载完成后调用) */
    @JavascriptInterface
    public void setWebVersion(int version) {
        prefs.edit().putInt("web_version", version).apply();
    }

    /** 清除网页缓存 (回退到内置版) */
    @JavascriptInterface
    public void clearWebCache() {
        File dir = new File(activity.getFilesDir(), "www");
        File[] files = dir.listFiles();
        if (files != null) for (File f : files) deleteRec(f);
        prefs.edit().putInt("web_version", 1).apply();
    }

    private void deleteRec(File f) {
        if (f.isDirectory()) {
            File[] cs = f.listFiles();
            if (cs != null) for (File c : cs) deleteRec(c);
        }
        f.delete();
    }

    // ---------------------------------------------------------------- 每日提醒
    /** JSON: {enabled, hour, minute} */
    @JavascriptInterface
    public void setReminder(String json) {
        try {
            JSONObject o = new JSONObject(json);
            boolean enabled = o.optBoolean("enabled", false);
            int hour = o.optInt("hour", 20);
            int minute = o.optInt("minute", 0);
            prefs.edit()
                    .putBoolean("reminder_enabled", enabled)
                    .putInt("reminder_hour", hour)
                    .putInt("reminder_minute", minute)
                    .apply();
            scheduleReminder(enabled, hour, minute);
        } catch (Exception ignored) {
        }
    }

    @JavascriptInterface
    public String getReminder() {
        try {
            JSONObject o = new JSONObject();
            o.put("enabled", prefs.getBoolean("reminder_enabled", false));
            o.put("hour", prefs.getInt("reminder_hour", 20));
            o.put("minute", prefs.getInt("reminder_minute", 0));
            return o.toString();
        } catch (Exception e) {
            return "{\"enabled\":false,\"hour\":20,\"minute\":0}";
        }
    }

    /** 设置/取消每日重复提醒 */
    public void scheduleReminder(boolean enabled, int hour, int minute) {
        AlarmManager am = (AlarmManager) activity.getSystemService(Context.ALARM_SERVICE);
        if (am == null) return;
        Intent intent = new Intent(activity, ReminderReceiver.class);
        PendingIntent pi = PendingIntent.getBroadcast(activity, 1001, intent,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        am.cancel(pi);
        if (!enabled) return;
        java.util.Calendar cal = java.util.Calendar.getInstance();
        cal.set(java.util.Calendar.HOUR_OF_DAY, hour);
        cal.set(java.util.Calendar.MINUTE, minute);
        cal.set(java.util.Calendar.SECOND, 0);
        cal.set(java.util.Calendar.MILLISECOND, 0);
        long trigger = cal.getTimeInMillis();
        if (trigger <= System.currentTimeMillis()) trigger += 24L * 3600 * 1000;
        try {
            am.setRepeating(AlarmManager.RTC_WAKEUP, trigger,
                    AlarmManager.INTERVAL_DAY, pi);
        } catch (Exception e) {
            // 部分机型禁止精确闹钟, 降级为非精确
            am.setInexactRepeating(AlarmManager.RTC_WAKEUP, trigger,
                    AlarmManager.INTERVAL_DAY, pi);
        }
    }

    /** 开机后重新排程 (BootReceiver 调用) */
    public void rescheduleAfterBoot() {
        if (prefs.getBoolean("reminder_enabled", false)) {
            scheduleReminder(true, prefs.getInt("reminder_hour", 20), prefs.getInt("reminder_minute", 0));
        }
    }

    // ---------------------------------------------------------------- 图片下载
    /** 下载图片到手机相册 (日记图片双端同步的"下载"端) */
    @JavascriptInterface
    public void downloadImage(final String url) {
        if (url == null || url.isEmpty()) {
            Toast.makeText(activity, "无效的图片地址", Toast.LENGTH_SHORT).show();
            return;
        }
        new Thread(() -> {
            byte[] data = null;
            String ext = ".jpg";
            try {
                java.net.URL u = new java.net.URL(url);
                java.net.HttpURLConnection conn = (java.net.HttpURLConnection) u.openConnection();
                conn.setConnectTimeout(8000);
                conn.setReadTimeout(20000);
                conn.setRequestProperty("User-Agent", "LearningHub-Sync/1.0");
                try (java.io.InputStream in = conn.getInputStream();
                     java.io.ByteArrayOutputStream bos = new java.io.ByteArrayOutputStream()) {
                    byte[] buf = new byte[8192];
                    int n;
                    while ((n = in.read(buf)) != -1) {
                        bos.write(buf, 0, n);
                    }
                    data = bos.toByteArray();
                }
                String p = u.getPath();
                if (p != null) {
                    int dot = p.lastIndexOf('.');
                    if (dot >= 0 && p.length() - dot <= 6) {
                        ext = p.substring(dot).toLowerCase(Locale.US);
                    }
                }
            } catch (Exception e) {
                final String err = e.getMessage();
                activity.runOnUiThread(() ->
                        Toast.makeText(activity, "下载失败: " + (err == null ? "网络错误" : err), Toast.LENGTH_SHORT).show());
                return;
            }
            final byte[] finalData = data;
            final String finalExt = ext;
            activity.runOnUiThread(() -> saveToGallery(finalData, finalExt));
        }).start();
    }

    private void saveToGallery(byte[] data, String ext) {
        try {
            String name = "learninghub_" + System.currentTimeMillis() + ext;
            String mime = ext.equalsIgnoreCase(".png") ? "image/png"
                    : ext.equalsIgnoreCase(".gif") ? "image/gif"
                    : ext.equalsIgnoreCase(".webp") ? "image/webp" : "image/jpeg";
            if (Build.VERSION.SDK_INT >= 29) {
                ContentValues cv = new ContentValues();
                cv.put(MediaStore.Images.Media.DISPLAY_NAME, name);
                cv.put(MediaStore.Images.Media.MIME_TYPE, mime);
                cv.put(MediaStore.Images.Media.RELATIVE_PATH, Environment.DIRECTORY_PICTURES + "/LearningHub");
                Uri uri = activity.getContentResolver().insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, cv);
                if (uri == null) {
                    Toast.makeText(activity, "保存失败", Toast.LENGTH_SHORT).show();
                    return;
                }
                try (java.io.OutputStream os = activity.getContentResolver().openOutputStream(uri)) {
                    if (os != null) os.write(data);
                }
                Toast.makeText(activity, "已保存到相册 Pictures/LearningHub", Toast.LENGTH_SHORT).show();
            } else {
                File dir = new File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_PICTURES), "LearningHub");
                if (!dir.exists()) dir.mkdirs();
                File f = new File(dir, name);
                try (FileOutputStream fos = new FileOutputStream(f)) {
                    fos.write(data);
                }
                MediaScannerConnection.scanFile(activity, new String[]{f.getAbsolutePath()}, new String[]{mime}, null);
                Toast.makeText(activity, "已保存到相册 " + f.getAbsolutePath(), Toast.LENGTH_SHORT).show();
            }
        } catch (Exception e) {
            Toast.makeText(activity, "保存失败: " + e.getMessage(), Toast.LENGTH_SHORT).show();
        }
    }

    // ---------------------------------------------------------------- background image
    @JavascriptInterface
    public void pickBackground() {
        activity.runOnUiThread(() -> activity.launchImagePicker());
    }

    /** 返回最新背景文件 URI (bg_<ts>.jpg 优先, 兼容旧 background.jpg) */
    @JavascriptInterface
    public String getBackgroundUri() {
        File dir = activity.getFilesDir();
        File[] files = dir.listFiles((d, n) -> n.startsWith("bg_") && n.endsWith(".jpg"));
        File latest = null;
        if (files != null) {
            for (File f : files) {
                if (latest == null || f.lastModified() > latest.lastModified()) latest = f;
            }
        }
        if (latest != null && latest.exists()) return Uri.fromFile(latest).toString();
        File legacy = new File(dir, "background.jpg");
        if (legacy.exists()) return Uri.fromFile(legacy).toString();
        return "";
    }

    @JavascriptInterface
    public void clearBackground() {
        File dir = activity.getFilesDir();
        File[] files = dir.listFiles((d, n) -> (n.startsWith("bg_") && n.endsWith(".jpg")) || n.equals("background.jpg"));
        if (files != null) for (File f : files) f.delete();
    }

    /** 把相册选中的 Uri 拷贝为带时间戳的新文件 (URI 变化 -> WebView 强制重新加载, 不缓存) */
    public void saveBackgroundUri(Uri uri) {
        try {
            File dir = activity.getFilesDir();
            File out = new File(dir, "bg_" + System.currentTimeMillis() + ".jpg");
            try (FileInputStream fis = (FileInputStream) activity.getContentResolver().openInputStream(uri);
                 FileOutputStream fos = new FileOutputStream(out)) {
                byte[] buf = new byte[8192];
                int n;
                while ((n = fis.read(buf)) > 0) fos.write(buf, 0, n);
            }
            // 清理旧背景文件
            File[] old = dir.listFiles((d, name) ->
                    (name.startsWith("bg_") && name.endsWith(".jpg")) || name.equals("background.jpg"));
            if (old != null) {
                for (File f : old) {
                    if (!f.getName().equals(out.getName())) f.delete();
                }
            }
            // 通知 WebView 刷新背景
            activity.runOnUiThread(() -> activity.getWebView().evaluateJavascript(
                    "window.__onBackgroundChanged && window.__onBackgroundChanged();", null));
        } catch (Exception e) {
            Toast.makeText(activity, "背景保存失败", Toast.LENGTH_SHORT).show();
        }
    }
}
