package app.cuplik;

import static org.junit.Assert.*;

import android.Manifest;
import android.content.Context;
import android.content.Intent;
import android.media.MediaMetadataRetriever;
import android.net.Uri;
import android.os.Build;
import android.os.SystemClock;
import androidx.test.core.app.ActivityScenario;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import java.io.File;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;

/** The actual foreground-service path used by the WebView bridge, without a paid API. */
@RunWith(AndroidJUnit4.class)
public class ServiceWorkflowTest {
  private void run(
      ActivityScenario<MainActivity> activity, Store store, String action, JSONObject options)
      throws Exception {
    JSONObject job = store.enqueue(action, options);
    String id = job.getString("id");
    assertTrue("Intent must already be durable before dispatch", store.busy());
    activity.onActivity(
        screen ->
            screen.startForegroundService(
                new Intent(screen, ProcessingService.class)
                    .setAction(action)
                    .putExtra("job_id", id)));
    long deadline = SystemClock.elapsedRealtime() + 120_000;
    while (store.busy() && SystemClock.elapsedRealtime() < deadline) SystemClock.sleep(50);
    assertFalse("Foreground service did not complete within two minutes", store.busy());
    JSONObject state = store.state();
    assertEquals(
        state.optString("error"), "done", state.getJSONObject("active_job").getString("status"));
    assertEquals(id, state.getJSONObject("active_job").getString("id"));
  }

  @Test
  public void importsPlansAndExportsThroughForegroundJobs() throws Exception {
    var instrumentation = InstrumentationRegistry.getInstrumentation();
    Context context = instrumentation.getTargetContext();
    if (Build.VERSION.SDK_INT >= 33)
      instrumentation
          .getUiAutomation()
          .grantRuntimePermission(context.getPackageName(), Manifest.permission.POST_NOTIFICATIONS);
    Store store = Store.get(context);
    assertFalse(store.busy());
    JSONObject original = store.state();
    File fixture = new File(context.getCacheDir(), "service-source-" + UUID.randomUUID() + ".mp4");
    List<File> created = new ArrayList<>();
    try (var input = instrumentation.getContext().getAssets().open("source.mp4")) {
      Files.copy(input, fixture.toPath());
    }
    try (ActivityScenario<MainActivity> activity = ActivityScenario.launch(MainActivity.class)) {
      run(
          activity,
          store,
          "import",
          Json.obj("uri", Uri.fromFile(fixture).toString(), "name", "Service fixture"));
      created.add(store.media(store.state().getJSONObject("source").getString("file")));
      assertTrue(store.state().getJSONObject("source").getDouble("duration_s") > 7);
      run(
          activity,
          store,
          "analyze",
          Json.obj(
              "mode",
              "clips",
              "language",
              "en",
              "manual",
              true,
              "clip_count",
              1,
              "max_clip_seconds",
              30,
              "layout",
              "source",
              "captions",
              true));
      assertEquals("awaiting_review", store.state().getString("status"));
      assertTrue(store.state().getJSONArray("plan").length() > 0);
      // Change these after planning, as the real review UI allows.
      run(
          activity,
          store,
          "render",
          Json.obj(
              "plan", store.state().getJSONArray("plan"), "layout", "portrait", "captions", false));
      JSONObject result = store.state();
      assertEquals("done", result.getString("status"));
      assertEquals("portrait", result.getJSONObject("settings").getString("layout"));
      assertFalse(result.getJSONObject("settings").getBoolean("captions"));
      assertTrue(result.getJSONArray("outputs").length() > 0);
      JSONObject output = result.getJSONArray("outputs").getJSONObject(0);
      File mp4 = store.media(output.getString("file"));
      created.add(mp4);
      assertTrue(mp4.length() > 1000);
      assertTrue(output.getJSONObject("qc").getJSONObject("audio").getDouble("rms_dbfs") > -50);
      MediaMetadataRetriever metadata = new MediaMetadataRetriever();
      try {
        metadata.setDataSource(mp4.getPath());
        int width =
            Integer.parseInt(
                metadata.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_WIDTH));
        int height =
            Integer.parseInt(
                metadata.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_HEIGHT));
        String rotation =
            metadata.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_ROTATION);
        if ("90".equals(rotation) || "270".equals(rotation)) {
          int swapped = width;
          width = height;
          height = swapped;
        }
        assertEquals(720, width);
        assertEquals(1280, height);
      } finally {
        metadata.release();
      }
    } finally {
      context.stopService(new Intent(context, ProcessingService.class));
      store.update(
          state -> {
            List<String> keys = new ArrayList<>();
            state.keys().forEachRemaining(keys::add);
            for (String key : keys) state.remove(key);
            for (var iterator = original.keys(); iterator.hasNext(); ) {
              String key = iterator.next();
              state.put(key, original.get(key));
            }
          });
      fixture.delete();
      for (File file : created) file.delete();
    }
  }
}
