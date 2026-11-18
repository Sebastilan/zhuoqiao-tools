package io.github.tvkit.home;
import android.accessibilityservice.AccessibilityService;
import android.content.Intent;
import android.view.accessibility.AccessibilityEvent;
/** 小米桌面一冒头就切回「家」。 */
public class HomeGuard extends AccessibilityService {
  @Override public void onAccessibilityEvent(AccessibilityEvent e) {
    if (e.getEventType() != AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED) return;
    CharSequence p = e.getPackageName(), c = e.getClassName();
    boolean stock = p != null && "com.mitv.tvhome".contentEquals(p);
    boolean fallback = c != null && c.toString().endsWith("FallbackHome");
    if (!stock && !fallback) return;
    Intent i = new Intent(this, Home.class);
    i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_REORDER_TO_FRONT);
    startActivity(i);
  }
  @Override public void onInterrupt() {}
}
