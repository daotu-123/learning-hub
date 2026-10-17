package com.xinghui.learninghub;

import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.os.Build;

import androidx.core.app.NotificationCompat;

/** 每日提醒：到点发通知，点击打开学习中枢 */
public class ReminderReceiver extends BroadcastReceiver {

    public static final String CHANNEL_ID = "hub_reminder";

    @Override
    public void onReceive(Context context, Intent intent) {
        NotificationManager nm = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
        if (nm == null) return;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel ch = new NotificationChannel(CHANNEL_ID, "学习提醒", NotificationManager.IMPORTANCE_DEFAULT);
            ch.setDescription("每日复习与打卡提醒");
            nm.createNotificationChannel(ch);
        }
        Intent open = new Intent(context, MainActivity.class);
        open.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        PendingIntent pi = PendingIntent.getActivity(context, 1002, open,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        nm.notify(1002, new NotificationCompat.Builder(context, CHANNEL_ID)
                .setSmallIcon(android.R.drawable.ic_dialog_info)
                .setContentTitle("学习中枢")
                .setContentText("今天的复习和打卡完成了嘛？打开看看今日进度 →")
                .setAutoCancel(true)
                .setContentIntent(pi)
                .build());
    }
}
