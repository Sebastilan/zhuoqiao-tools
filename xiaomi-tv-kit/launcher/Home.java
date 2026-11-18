package io.github.tvkit.home;
import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.provider.Settings;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.View;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

/** 设计稿 A：简洁深色。上排六入口，下排常看。 */
public class Home extends Activity {
  static final String STREMIO = "com.stremio.one";
  // 名称, 副标题, 颜色, 包名, 深链(可空)
  static final String[][] APPS = {
    {"电影", "Stremio · 全球片源", "#E50914", STREMIO, null},
    {"YouTube", "SmartTube · 无广告", "#FF3D3D", "org.smarttube.stable", null},
    {"美国直播", "Pluto TV", "#2D6BFF", "tv.pluto.android", null},
    {"免费大片", "Tubi", "#7B2CF5", "com.tubitv", null},
    {"央视", "CCTV 直播", "#C8102E", "com.newtv.cboxtv", null},
    {"国内剧", "影视", "#12A150", "com.fongmi.android.tv", null},
  };
  static final String[][] SHOWS = {
    {"宫崎骏", "全部作品 ›", "#3A7D5C", STREMIO, "#miyazaki", "tt0119698"},
    {"海贼王", "追剧", "#D9822B", STREMIO, "stremio:///search?search=One%20Piece", "tt0388629"},
    {"千与千寻", "宫崎骏", "#4A5FA8", STREMIO, "stremio:///detail/movie/tt0245429", "tt0245429"},
    {"龙猫", "宫崎骏", "#5E8C3A", STREMIO, "stremio:///detail/movie/tt0096283", "tt0096283"},
    {"哈尔的移动城堡", "宫崎骏", "#8A4F7D", STREMIO, "stremio:///detail/movie/tt0347149", "tt0347149"},
  };

  // 电视版 Stremio 只认电影详情深链（剧集详情链接会报找不到）
  static final String[][] MIYAZAKI = {
    {"千与千寻", "2001", "#4A5FA8", STREMIO, "stremio:///detail/movie/tt0245429", "tt0245429"},
    {"龙猫", "1988", "#5E8C3A", STREMIO, "stremio:///detail/movie/tt0096283", "tt0096283"},
    {"哈尔的移动城堡", "2004", "#8A4F7D", STREMIO, "stremio:///detail/movie/tt0347149", "tt0347149"},
    {"幽灵公主", "1997", "#3E6E4E", STREMIO, "stremio:///detail/movie/tt0119698", "tt0119698"},
    {"天空之城", "1986", "#3B78A8", STREMIO, "stremio:///detail/movie/tt0092067", "tt0092067"},
    {"魔女宅急便", "1989", "#A84A5A", STREMIO, "stremio:///detail/movie/tt0097814", "tt0097814"},
    {"风之谷", "1984", "#7A6A3A", STREMIO, "stremio:///detail/movie/tt0087544", "tt0087544"},
    {"红猪", "1992", "#B0503A", STREMIO, "stremio:///detail/movie/tt0104652", "tt0104652"},
    {"悬崖上的金鱼姬", "2008", "#2E7FA0", STREMIO, "stremio:///detail/movie/tt0876563", "tt0876563"},
    {"起风了", "2013", "#6A7FA0", STREMIO, "stremio:///detail/movie/tt2013293", "tt2013293"},
    {"你想活出怎样的人生", "2023", "#5A4A8A", STREMIO, "stremio:///detail/movie/tt6587046", "tt6587046"},
  };
  LinearLayout row2; TextView row2Title; boolean sub;
  TextView clock, date, net;
  final Handler h = new Handler();
  float dp;

  @Override protected void onCreate(Bundle b) {
    super.onCreate(b);
    dp = getResources().getDisplayMetrics().widthPixels / 1920f; // 按 1920 设计稿等比
    FrameLayout root = new FrameLayout(this);
    GradientDrawable bg = new GradientDrawable(GradientDrawable.Orientation.TL_BR,
        new int[]{Color.parseColor("#161A22"), Color.parseColor("#07080B")});
    root.setBackground(bg);

    LinearLayout col = new LinearLayout(this);
    col.setOrientation(LinearLayout.VERTICAL); col.setClipChildren(false); col.setClipToPadding(false); root.setClipChildren(false);
    col.setPadding(px(96), px(64), px(96), px(48));
    root.addView(col);

    // 顶栏：时间日期 | 网络
    FrameLayout top = new FrameLayout(this);
    LinearLayout tl = new LinearLayout(this);
    tl.setOrientation(LinearLayout.VERTICAL);
    clock = text("", 72, "#FFFFFF", true);
    date = text("", 26, "#9AA3B2", false);
    tl.addView(clock); tl.addView(date);
    top.addView(tl);
    net = text("网络 …", 24, "#FFFFFF", false);
    net.setPadding(px(24), px(10), px(24), px(10));
    top.addView(net, new FrameLayout.LayoutParams(-2, -2, Gravity.END | Gravity.TOP));
    col.addView(top);

    col.addView(space(56));
    col.addView(text("入口", 30, "#C9D1DD", true));
    col.addView(space(20));
    LinearLayout row1 = row();
    for (int i = 0; i < APPS.length; i++) row1.addView(tile(APPS[i], 260, 200, i == 0), lp(260, 200, i));
    col.addView(row1);

    col.addView(space(56));
    row2Title = text("常看", 30, "#C9D1DD", true);
    col.addView(row2Title);
    col.addView(space(20));
    row2 = row();
    android.widget.HorizontalScrollView hs = new android.widget.HorizontalScrollView(this);
    hs.setHorizontalScrollBarEnabled(false); hs.setClipChildren(false); hs.setClipToPadding(false);
    hs.setPadding(px(16), 0, px(16), 0);
    hs.addView(row2);
    col.addView(hs);
    fill(SHOWS, 240);

    setContentView(root);
    tick.run();
  }

  final Runnable tick = new Runnable() { public void run() {
    Date d = new Date();
    clock.setText(new SimpleDateFormat("HH:mm", Locale.CHINA).format(d));
    date.setText(new SimpleDateFormat("M月d日 EEEE", Locale.CHINA).format(d));
    // 看门狗每分钟写入：ok|出口名|速度  或  down|原因
    String s = Settings.Global.getString(getContentResolver(), "tvkit_net");
    GradientDrawable pill = new GradientDrawable();
    pill.setCornerRadius(px(40));
    if (s != null && s.startsWith("ok|")) {
      String[] f = s.split("\\|");
      net.setText("● 网络正常  " + (f.length > 1 ? f[1] : "") + (f.length > 2 ? "  " + f[2] : ""));
      pill.setColor(Color.parseColor("#1E3A2A")); net.setTextColor(Color.parseColor("#5BE38A"));
    } else if (s != null && s.startsWith("down")) {
      net.setText("● 国外网络中断，正在修复");
      pill.setColor(Color.parseColor("#3A1E1E")); net.setTextColor(Color.parseColor("#FF6B6B"));
    } else {
      net.setText("● 网络状态未知");
      pill.setColor(Color.parseColor("#2A2E36")); net.setTextColor(Color.parseColor("#9AA3B2"));
    }
    net.setBackground(pill);
    h.postDelayed(this, 15000);
  }};

  View tile(final String[] a, int w, int hgt, boolean first) {
    final FrameLayout t = new FrameLayout(this);
    final GradientDrawable g = new GradientDrawable(GradientDrawable.Orientation.TL_BR,
        new int[]{Color.parseColor(a[2]), darker(Color.parseColor(a[2]))});
    g.setCornerRadius(px(22));
    t.setBackground(g);
    t.setClipToOutline(true);
    String poster = a.length > 5 ? a[5] : null;
    boolean hasImg = false;
    if (poster != null) {
      try {
        java.io.InputStream in = getAssets().open("poster/" + poster + ".jpg");
        android.graphics.BitmapFactory.Options o = new android.graphics.BitmapFactory.Options();
        o.inPreferredConfig = android.graphics.Bitmap.Config.RGB_565;
        android.widget.ImageView iv = new android.widget.ImageView(this);
        iv.setImageBitmap(android.graphics.BitmapFactory.decodeStream(in, null, o));
        iv.setScaleType(android.widget.ImageView.ScaleType.CENTER_CROP);
        t.addView(iv, new FrameLayout.LayoutParams(-1, -1));
        View scrim = new View(this);
        scrim.setBackground(new GradientDrawable(GradientDrawable.Orientation.TOP_BOTTOM,
            new int[]{0x00000000, 0x00000000, 0xE6000000}));
        t.addView(scrim, new FrameLayout.LayoutParams(-1, -1));
        hasImg = true;
      } catch (Exception ignored) {}
    }
    if (!hasImg && a[4] == null) { // 入口卡：App 真图标
      try {
        android.widget.ImageView ic = new android.widget.ImageView(this);
        ic.setImageDrawable(getPackageManager().getApplicationIcon(a[3]));
        FrameLayout.LayoutParams ip = new FrameLayout.LayoutParams(px(72), px(72), Gravity.TOP | Gravity.START);
        ip.leftMargin = px(22); ip.topMargin = px(20);
        t.addView(ic, ip);
      } catch (Exception ignored) {}
    }
    LinearLayout txt = new LinearLayout(this);
    txt.setOrientation(LinearLayout.VERTICAL);
    txt.setPadding(px(22), 0, px(22), px(20));
    txt.addView(text(a[0], a[0].length() > 6 ? 24 : a[0].length() > 4 ? 30 : 40, "#FFFFFF", true));
    txt.addView(text(a[1], 20, "#E6FFFFFF", false));
    t.addView(txt, new FrameLayout.LayoutParams(-1, -2, Gravity.BOTTOM));
    final GradientDrawable ring = new GradientDrawable();
    ring.setCornerRadius(px(22)); ring.setColor(0);
    t.setForeground(ring);
    t.setFocusable(true);
    t.setOnFocusChangeListener(new View.OnFocusChangeListener() { public void onFocusChange(View v, boolean f) {
      ring.setStroke(f ? px(6) : 0, Color.WHITE);
      v.animate().scaleX(f ? 1.08f : 1f).scaleY(f ? 1.08f : 1f).translationZ(f ? 20 : 0).setDuration(120).start();
    }});
    t.setOnClickListener(new View.OnClickListener() { public void onClick(View v) { open(a); }});
    if (first) t.post(new Runnable() { public void run() { t.requestFocus(); }});
    return t;
  }

  void fill(String[][] items, int w) {
    row2.removeAllViews();
    for (int i = 0; i < items.length; i++) row2.addView(tile(items[i], w, 300, false), lp(w, 300, i));
  }

  void open(String[] a) {
    if ("#miyazaki".equals(a[4])) {
      sub = true; row2Title.setText("宫崎骏 · 按返回键收起");
      fill(MIYAZAKI, 240);
      row2.getChildAt(0).requestFocus();
      return;
    }
    try {
      if (a[4] != null) {
        Intent i = new Intent(Intent.ACTION_VIEW, Uri.parse(a[4]));
        i.setPackage(a[3]);
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        startActivity(i);
        return;
      }
    } catch (Exception ignored) {}
    Intent i = getPackageManager().getLeanbackLaunchIntentForPackage(a[3]);
    if (i == null) i = getPackageManager().getLaunchIntentForPackage(a[3]);
    if (i == null) { Toast.makeText(this, a[0] + " 没装", Toast.LENGTH_SHORT).show(); return; }
    i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
    startActivity(i);
  }

  @Override public boolean onKeyDown(int k, KeyEvent e) {
    if (k == KeyEvent.KEYCODE_BACK) {
      if (sub) { sub = false; row2Title.setText("常看"); fill(SHOWS, 240); row2.getChildAt(0).requestFocus(); }
      return true;
    } // 桌面上按返回不退出
    if (k == KeyEvent.KEYCODE_MENU) { startActivity(new Intent(Settings.ACTION_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)); return true; }
    return super.onKeyDown(k, e);
  }

  @Override protected void onDestroy() { h.removeCallbacks(tick); super.onDestroy(); }

  // —— 小工具 ——
  int px(int v) { return Math.round(v * dp); }
  static int darker(int c) { return Color.rgb(Color.red(c) * 6 / 10, Color.green(c) * 6 / 10, Color.blue(c) * 6 / 10); }
  TextView text(String s, int size, String color, boolean bold) {
    TextView t = new TextView(this);
    t.setText(s); t.setTextSize(0, px(size)); t.setTextColor(Color.parseColor(color));
    if (bold) t.setTypeface(Typeface.DEFAULT_BOLD);
    t.setSingleLine(true);
    return t;
  }
  View space(int hgt) { View v = new View(this); v.setLayoutParams(new LinearLayout.LayoutParams(1, px(hgt))); return v; }
  LinearLayout row() { LinearLayout r = new LinearLayout(this); r.setClipChildren(false); r.setClipToPadding(false); r.setPadding(0, px(12), 0, px(12)); return r; }
  LinearLayout.LayoutParams lp(int w, int hgt, int i) { LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(px(w), px(hgt)); p.leftMargin = i == 0 ? 0 : px(28); return p; }
}
