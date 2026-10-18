package com.xinghui.workbench;

import android.annotation.SuppressLint;
import android.app.usage.UsageEvents;
import android.app.usage.UsageStats;
import android.app.usage.UsageStatsManager;
import android.content.ContentValues;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.media.MediaScannerConnection;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.provider.MediaStore;
import android.provider.Settings;
import android.webkit.JavascriptInterface;
import android.webkit.MimeTypeMap;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.Calendar;
import java.util.Date;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.TimeZone;

/**
 * 原生桥: 供 WebView 中的 JS 调用
 *  - 应用使用时间统计 (UsageStatsManager)
 *  - 本地偏好存储 (服务器地址/背景等)
 *  - 引导开启"使用情况访问"权限
 */
public class JsBridge {
    private final MainActivity activity;
    private final SharedPreferences prefs;

    public JsBridge(MainActivity activity) {
        this.activity = activity;
        this.prefs = activity.getSharedPreferences("workbench", Context.MODE_PRIVATE);
    }

    // ---------------------------------------------------------------- usage stats
    @JavascriptInterface
    public String getUsageStats(int days) {
        JSONArray out = new JSONArray();
        try {
            UsageStatsManager usm = (UsageStatsManager) activity.getSystemService(Context.USAGE_STATS_SERVICE);
            if (usm == null) return out.toString();

            Calendar cal = Calendar.getInstance();
            cal.add(Calendar.DAY_OF_YEAR, -(Math.max(1, Math.min(days, 30))));
            long start = cal.getTimeInMillis();
            long end = System.currentTimeMillis();

            List<UsageStats> stats = usm.queryUsageStats(UsageStatsManager.INTERVAL_DAILY, start, end);
            Map<String, UsageStats> merged = new HashMap<>();
            for (UsageStats s : stats) {
                if (s == null || s.getTotalTimeInForeground() <= 0) continue;
                UsageStats prev = merged.get(s.getPackageName());
                if (prev == null) {
                    merged.put(s.getPackageName(), s);
                } else {
                    // 跨天聚合同一应用
                    prev.add(s);
                }
            }

            // 按天粒度统计每日前台时长
            Map<String, Map<String, Long>> dayMap = new HashMap<>(); // package -> (date -> ms)
            UsageEvents events = usm.queryEvents(start, end);
            UsageEvents.Event ev = new UsageEvents.Event();
            SimpleDateFormat df = new SimpleDateFormat("yyyy-MM-dd", Locale.US);
            df.setTimeZone(TimeZone.getDefault());
            while (events.hasNextEvent()) {
                events.getNextEvent(ev);
                if (ev.getEventType() == UsageEvents.Event.ACTIVITY_RESUMED
                        || ev.getEventType() == UsageEvents.Event.ACTIVITY_PAUSED) {
                    if (ev.getPackageName() == null) continue;
                    String date = df.format(new Date(ev.getTimeStamp()));
                    Map<String, Long> byDate = dayMap.computeIfAbsent(ev.getPackageName(), k -> new HashMap<>());
                    byDate.merge(date, 1L, Long::sum); // 事件计数, 仅用于"当天是否活跃"
                }
            }

            for (Map.Entry<String, UsageStats> e : merged.entrySet()) {
                UsageStats s = e.getValue();
                JSONObject o = new JSONObject();
                o.put("package", s.getPackageName());
                o.put("app_name", friendlyName(s.getPackageName()));
                o.put("total_ms", s.getTotalTimeInForeground());
                // 今日使用时长: 用事件近似 (RESUMED-PAUSED 差)
                long todayMs = dailyMs(s, usm, df);
                o.put("day_ms", todayMs);
                o.put("active_days", dayMap.containsKey(s.getPackageName()) ? dayMap.get(s.getPackageName()).size() : 0);
                out.put(o);
            }
        } catch (Exception ignored) {
        }
        return out.toString();
    }

    /** 今日按小时活跃分布 (秒): 用 UsageEvents 把前台时段按小时切分累计 */
    @JavascriptInterface
    public String getHourlyUsage() {
        JSONObject out = new JSONObject();
        try {
            UsageStatsManager usm = (UsageStatsManager) activity.getSystemService(Context.USAGE_STATS_SERVICE);
            if (usm == null) return out.toString();
            Calendar cal = Calendar.getInstance();
            cal.set(Calendar.HOUR_OF_DAY, 0);
            cal.set(Calendar.MINUTE, 0);
            cal.set(Calendar.SECOND, 0);
            cal.set(Calendar.MILLISECOND, 0);
            long dayStart = cal.getTimeInMillis();
            long now = System.currentTimeMillis();
            UsageEvents events = usm.queryEvents(dayStart, now);
            UsageEvents.Event ev = new UsageEvents.Event();
            Map<String, Long> lastResume = new HashMap<>();
            long[] hourSec = new long[24];
            while (events.hasNextEvent()) {
                events.getNextEvent(ev);
                if (ev.getPackageName() == null) continue;
                int type = ev.getEventType();
                long ts = ev.getTimeStamp();
                if (type == UsageEvents.Event.ACTIVITY_RESUMED) {
                    lastResume.put(ev.getPackageName(), ts);
                } else if (type == UsageEvents.Event.ACTIVITY_PAUSED) {
                    Long rs = lastResume.remove(ev.getPackageName());
                    if (rs != null) addSpan(hourSec, rs, ts);
                }
            }
            // 未结算的前台应用 (当前正打开)
            for (Map.Entry<String, Long> e : lastResume.entrySet()) {
                addSpan(hourSec, e.getValue(), now);
            }
            JSONArray arr = new JSONArray();
            for (int h = 0; h < 24; h++) {
                JSONObject o = new JSONObject();
                o.put("hour", h);
                o.put("seconds", hourSec[h]);
                arr.put(o);
            }
            out.put("hours", arr);
            out.put("date", new SimpleDateFormat("yyyy-MM-dd", Locale.US).format(new Date()));
        } catch (Exception ignored) {
        }
        return out.toString();
    }

    /** 把 [start,end] 区间按小时切分累加到 hourSec */
    private void addSpan(long[] hourSec, long start, long end) {
        if (end <= start) return;
        Calendar c = Calendar.getInstance();
        c.setTimeInMillis(start);
        while (start < end) {
            int h = c.get(Calendar.HOUR_OF_DAY);
            if (h < 0 || h > 23) break;
            Calendar nxt = (Calendar) c.clone();
            nxt.set(Calendar.HOUR_OF_DAY, h + 1);
            nxt.set(Calendar.MINUTE, 0);
            nxt.set(Calendar.SECOND, 0);
            nxt.set(Calendar.MILLISECOND, 0);
            long segEnd = Math.min(end, nxt.getTimeInMillis());
            hourSec[h] += (segEnd - start);
            start = segEnd;
            c.setTimeInMillis(start);
        }
    }

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
                conn.setRequestProperty("User-Agent", "Workbench-Sync/1.0");
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
            String name = "workbench_" + System.currentTimeMillis() + ext;
            String mime = ext.equalsIgnoreCase(".png") ? "image/png"
                    : ext.equalsIgnoreCase(".gif") ? "image/gif"
                    : ext.equalsIgnoreCase(".webp") ? "image/webp" : "image/jpeg";
            if (Build.VERSION.SDK_INT >= 29) {
                ContentValues cv = new ContentValues();
                cv.put(MediaStore.Images.Media.DISPLAY_NAME, name);
                cv.put(MediaStore.Images.Media.MIME_TYPE, mime);
                cv.put(MediaStore.Images.Media.RELATIVE_PATH, Environment.DIRECTORY_PICTURES + "/Workbench");
                Uri uri = activity.getContentResolver().insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, cv);
                if (uri == null) {
                    Toast.makeText(activity, "保存失败", Toast.LENGTH_SHORT).show();
                    return;
                }
                try (java.io.OutputStream os = activity.getContentResolver().openOutputStream(uri)) {
                    if (os != null) os.write(data);
                }
                Toast.makeText(activity, "已保存到相册 Pictures/Workbench", Toast.LENGTH_SHORT).show();
            } else {
                File dir = new File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_PICTURES), "Workbench");
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

    /** 计算指定应用今日前台毫秒 (从当日 0 点起) */
    private long dailyMs(UsageStats s, UsageStatsManager usm, SimpleDateFormat df) {
        try {
            Calendar cal = Calendar.getInstance();
            cal.set(Calendar.HOUR_OF_DAY, 0);
            cal.set(Calendar.MINUTE, 0);
            cal.set(Calendar.SECOND, 0);
            cal.set(Calendar.MILLISECOND, 0);
            long dayStart = cal.getTimeInMillis();
            UsageStats today = usm.queryUsageStats(UsageStatsManager.INTERVAL_BEST, dayStart, System.currentTimeMillis())
                    .stream()
                    .filter(x -> x.getPackageName().equals(s.getPackageName()))
                    .findFirst().orElse(null);
            if (today != null) return today.getTotalTimeInForeground();
        } catch (Exception ignored) {
        }
        return 0;
    }

    private String friendlyName(String pkg) {
        try {
            android.content.pm.ApplicationInfo ai = activity.getPackageManager().getApplicationInfo(pkg, 0);
            CharSequence label = activity.getPackageManager().getApplicationLabel(ai);
            return label != null ? label.toString() : pkg;
        } catch (Exception e) {
            return pkg;
        }
    }

    // ---------------------------------------------------------------- usage permission
    @JavascriptInterface
    public boolean hasUsagePermission() {
        try {
            UsageStatsManager usm = (UsageStatsManager) activity.getSystemService(Context.USAGE_STATS_SERVICE);
            if (usm == null) return false;
            long end = System.currentTimeMillis();
            long start = end - 1000 * 60 * 60;
            List<UsageStats> stats = usm.queryUsageStats(UsageStatsManager.INTERVAL_DAILY, start, end);
            return stats != null && !stats.isEmpty();
        } catch (Exception e) {
            return false;
        }
    }

    @JavascriptInterface
    public void openUsageAccessSettings() {
        try {
            Intent intent = new Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS);
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            activity.startActivity(intent);
        } catch (Exception e) {
            Toast.makeText(activity, "无法打开设置页", Toast.LENGTH_SHORT).show();
        }
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
