package app.cuplik;

import android.Manifest;
import android.content.Intent;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import android.database.Cursor;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.OpenableColumns;
import android.view.View;
import android.view.WindowInsets;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import androidx.activity.ComponentActivity;
import androidx.activity.OnBackPressedCallback;
import androidx.webkit.WebViewAssetLoader;
import java.io.ByteArrayInputStream;
import java.io.File;
import java.io.InputStream;
import java.io.RandomAccessFile;
import java.util.HashMap;
import java.util.Map;
import org.json.JSONArray;
import org.json.JSONObject;

public final class MainActivity extends ComponentActivity {
  private WebView web;
  private FrameLayout root;
  private Store store;
  private View fullScreen;
  private WebChromeClient.CustomViewCallback fullScreenCallback;
  private String saveFile;
  private static final String ORIGIN = "https://appassets.androidplatform.net";

  @Override
  public void onCreate(Bundle saved) {
    super.onCreate(saved);
    store = Store.get(this);
    if (saved != null) saveFile = saved.getString("save_file");
    root = new FrameLayout(this);
    root.setBackgroundColor(Color.rgb(20, 18, 12));
    root.setOnApplyWindowInsetsListener(
        (view, insets) -> {
          if (Build.VERSION.SDK_INT >= 30) {
            android.graphics.Insets safe =
                insets.getInsets(
                    WindowInsets.Type.systemBars()
                        | WindowInsets.Type.displayCutout()
                        | WindowInsets.Type.ime());
            view.setPadding(safe.left, safe.top, safe.right, safe.bottom);
          } else
            view.setPadding(
                insets.getSystemWindowInsetLeft(),
                insets.getSystemWindowInsetTop(),
                insets.getSystemWindowInsetRight(),
                insets.getSystemWindowInsetBottom());
          return insets;
        });
    web = new WebView(this);
    root.addView(web, new FrameLayout.LayoutParams(-1, -1));
    setContentView(root);
    web.setBackgroundColor(Color.rgb(20, 18, 12));
    WebSettings settings = web.getSettings();
    settings.setJavaScriptEnabled(true);
    settings.setDomStorageEnabled(true);
    settings.setAllowFileAccess(false);
    settings.setAllowContentAccess(false);
    settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
    settings.setMediaPlaybackRequiresUserGesture(true);
    WebView.setWebContentsDebuggingEnabled(
        (getApplicationInfo().flags & ApplicationInfo.FLAG_DEBUGGABLE) != 0);
    WebViewAssetLoader assets =
        new WebViewAssetLoader.Builder()
            .addPathHandler("/assets/", new WebViewAssetLoader.AssetsPathHandler(this))
            .build();
    web.setWebViewClient(
        new WebViewClient() {
          @Override
          public WebResourceResponse shouldInterceptRequest(
              WebView view, WebResourceRequest request) {
            Uri uri = request.getUrl();
            if (!"https".equals(uri.getScheme())
                || !"appassets.androidplatform.net".equals(uri.getHost()))
              return response(403, "Forbidden", Map.of(), new byte[0]);
            if (uri.getPath() != null && uri.getPath().startsWith("/media/")) return media(request);
            WebResourceResponse resource = assets.shouldInterceptRequest(uri);
            return resource == null ? response(404, "Not Found", Map.of(), new byte[0]) : resource;
          }

          @Override
          public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
            Uri uri = request.getUrl();
            if (uri.toString().startsWith(ORIGIN + "/assets/")) return false;
            if (request.isForMainFrame() && "https".equals(uri.getScheme()))
              startActivity(new Intent(Intent.ACTION_VIEW, uri));
            return true;
          }
        });
    web.setWebChromeClient(
        new WebChromeClient() {
          @Override
          public void onShowCustomView(View view, CustomViewCallback callback) {
            if (fullScreen != null) {
              callback.onCustomViewHidden();
              return;
            }
            fullScreen = view;
            fullScreenCallback = callback;
            root.addView(view, new FrameLayout.LayoutParams(-1, -1));
            web.setVisibility(View.GONE);
          }

          @Override
          public void onHideCustomView() {
            hideFullScreen();
          }
        });
    web.addJavascriptInterface(new Bridge(), "CuplikNative");
    web.loadUrl(ORIGIN + "/assets/www/mobile.html");
    getOnBackPressedDispatcher()
        .addCallback(
            this,
            new OnBackPressedCallback(true) {
              @Override
              public void handleOnBackPressed() {
                if (fullScreen != null) hideFullScreen();
                else if (web.canGoBack()) web.goBack();
                else finish();
              }
            });
    if (Build.VERSION.SDK_INT >= 33
        && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
            != PackageManager.PERMISSION_GRANTED)
      requestPermissions(new String[] {Manifest.permission.POST_NOTIFICATIONS}, 12);
  }

  private void hideFullScreen() {
    if (fullScreen != null) {
      root.removeView(fullScreen);
      fullScreen = null;
      web.setVisibility(View.VISIBLE);
      if (fullScreenCallback != null) fullScreenCallback.onCustomViewHidden();
      fullScreenCallback = null;
    }
  }

  private void error(Exception error) {
    store.update(
        s -> {
          s.put("error", error.getMessage() == null ? "Operasi gagal." : error.getMessage());
        });
  }

  private void dispatch(JSONObject job) {
    runOnUiThread(
        () -> {
          String id = job.optString("id");
          try {
            startForegroundService(
                new Intent(this, ProcessingService.class)
                    .setAction(job.optString("action"))
                    .putExtra("job_id", id));
          } catch (Exception failure) {
            store.finish(
                id,
                "failed",
                failure.getMessage() == null
                    ? "Layanan perangkat tidak dapat dimulai."
                    : failure.getMessage());
          }
        });
  }

  private void command(String action, String payload) {
    try {
      dispatch(store.enqueue(action, new JSONObject(payload)));
    } catch (Exception failure) {
      error(failure);
    }
  }

  public final class Bridge {
    @JavascriptInterface
    public String getState() {
      JSONObject state = store.state();
      try {
        state.put("config", new Secrets(MainActivity.this).publicConfig());
        state.put("model_ready", store.model().isFile());
        state.put("busy", store.busy());
        state.put("retryable", store.retryable());
        JSONObject job = state.optJSONObject("active_job");
        if (job != null) job.remove("payload");
      } catch (Exception failure) {
        error(failure);
      }
      return state.toString();
    }

    @JavascriptInterface
    public void chooseVideo() {
      if (store.busy()) return;
      runOnUiThread(
          () ->
              startActivityForResult(
                  new Intent(Intent.ACTION_OPEN_DOCUMENT)
                      .addCategory(Intent.CATEGORY_OPENABLE)
                      .setType("video/*")
                      .addFlags(
                          Intent.FLAG_GRANT_READ_URI_PERMISSION
                              | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION),
                  10));
    }

    @JavascriptInterface
    public void saveConfig(String json) {
      try {
        if (store.busy())
          throw new IllegalStateException("Tunggu proses selesai sebelum mengganti API.");
        new Secrets(MainActivity.this).save(new JSONObject(json));
        store.editInputs(
            s -> {
              s.put("note", "Pengaturan AI tersimpan di perangkat.");
              s.remove("error");
            });
      } catch (Exception failure) {
        error(failure);
      }
    }

    @JavascriptInterface
    public void testConnection() {
      command("connection", "{}");
    }

    @JavascriptInterface
    public void downloadModel() {
      command("model", "{}");
    }

    @JavascriptInterface
    public void analyze(String json) {
      command("analyze", json);
    }

    @JavascriptInterface
    public void render(String json) {
      command("render", json);
    }

    @JavascriptInterface
    public void cancel() {
      JSONObject job = store.state().optJSONObject("active_job");
      if (job == null || !store.busy()) return;
      String id = job.optString("id");
      store.requestCancel(id);
      runOnUiThread(
          () ->
              startService(
                  new Intent(MainActivity.this, ProcessingService.class)
                      .setAction("cancel")
                      .putExtra("job_id", id)));
    }

    @JavascriptInterface
    public void retryJob() {
      try {
        dispatch(store.retry());
      } catch (Exception failure) {
        error(failure);
      }
    }

    @JavascriptInterface
    public void clearCache() {
      if (store.busy()) return;
      runOnUiThread(
          () ->
              new android.app.AlertDialog.Builder(MainActivity.this)
                  .setTitle("Bersihkan video lokal?")
                  .setMessage(
                      "Video sumber salinan, transkrip dan hasil dalam aplikasi akan dihapus."
                          + " Simpan MP4 ke perangkat terlebih dahulu. Model dan pengaturan AI"
                          + " tetap disimpan.")
                  .setNegativeButton("Batal", null)
                  .setPositiveButton(
                      "Hapus data lokal",
                      (dialog, which) -> {
                        try {
                          synchronized (store) {
                            if (store.busy())
                              throw new IllegalStateException("Proses masih berjalan.");
                            File directory = store.media("placeholder").getParentFile();
                            File[] files = directory.listFiles();
                            if (files != null)
                              for (File file : files)
                                if (!file.delete())
                                  throw new IllegalStateException(
                                      "Sebagian cache belum dapat dihapus; coba ulang.");
                            store.editInputs(
                                s -> {
                                  s.remove("source");
                                  s.remove("settings");
                                  s.put("plan", new JSONArray());
                                  s.put("sentences", new JSONArray());
                                  s.put("outputs", new JSONArray());
                                  s.put("next_chunk", 0);
                                  s.put("status", "idle");
                                  s.put(
                                      "note",
                                      "Data video lokal dibersihkan. Berkas yang disimpan di luar"
                                          + " aplikasi tetap tersedia.");
                                  s.remove("error");
                                });
                          }
                        } catch (Exception failure) {
                          error(failure);
                        }
                      })
                  .show());
    }

    @JavascriptInterface
    public void solve(String json) {
      try {
        if (store.busy()) throw new IllegalStateException("Proses masih berjalan.");
        JSONObject options = new JSONObject(json), state = store.state();
        JSONArray reviewed =
            Planner.review(
                state.getJSONArray("plan"),
                options.getJSONArray("plan"),
                state.optString("mode"),
                state.getJSONObject("source").getDouble("duration_s"));
        JSONArray plan = Planner.solve(reviewed, options.getDouble("target_seconds"));
        store.editInputs(
            s -> {
              s.put("plan", plan);
              s.put("status", "awaiting_review");
              s.put("note", "Rencana dihitung ulang. Tinjau keputusan sebelum ekspor.");
              s.remove("error");
            });
      } catch (Exception failure) {
        error(failure);
      }
    }

    @JavascriptInterface
    public void saveTranscript(String json) {
      try {
        if (store.busy()) throw new IllegalStateException("Proses masih berjalan.");
        JSONArray rows = new JSONArray(json);
        double end = 0, duration = store.state().getJSONObject("source").getDouble("duration_s");
        if (rows.length() > 5000) throw new IllegalArgumentException("Transkrip terlalu panjang.");
        for (int i = 0; i < rows.length(); i++) {
          JSONObject row = rows.getJSONObject(i);
          double a = row.getDouble("start_s"), b = row.getDouble("end_s");
          if (!row.getString("id").equals("s" + (i + 1))
              || !Double.isFinite(a)
              || !Double.isFinite(b)
              || a < end
              || b <= a
              || b > duration
              || row.getString("text").length() > 4000)
            throw new IllegalArgumentException(
                "ID, urutan, teks atau waktu transkrip tidak valid.");
          end = b;
        }
        store.editInputs(
            s -> {
              s.put("sentences", rows);
              s.put("plan", new JSONArray());
              s.put("note", "Transkrip disimpan. Susun ulang rencana sebelum ekspor.");
              s.remove("error");
            });
      } catch (Exception failure) {
        error(failure);
      }
    }

    @JavascriptInterface
    public void saveOutput(String filename) {
      try {
        File file = store.media(filename);
        if (!filename.startsWith("export-") || !filename.endsWith(".mp4") || !file.isFile())
          throw new IllegalArgumentException("Hasil tidak ditemukan.");
        saveFile = filename;
        runOnUiThread(
            () ->
                startActivityForResult(
                    new Intent(Intent.ACTION_CREATE_DOCUMENT)
                        .addCategory(Intent.CATEGORY_OPENABLE)
                        .setType("video/mp4")
                        .putExtra(Intent.EXTRA_TITLE, "cuplik-" + filename),
                    11));
      } catch (Exception failure) {
        error(failure);
      }
    }
  }

  @Override
  protected void onSaveInstanceState(Bundle state) {
    super.onSaveInstanceState(state);
    if (saveFile != null) state.putString("save_file", saveFile);
  }

  @Override
  protected void onActivityResult(int request, int result, Intent data) {
    super.onActivityResult(request, result, data);
    if (result != RESULT_OK || data == null || data.getData() == null) return;
    Uri uri = data.getData();
    if (request == 10) {
      String name = "Video perangkat";
      try (Cursor cursor =
          getContentResolver()
              .query(uri, new String[] {OpenableColumns.DISPLAY_NAME}, null, null, null)) {
        if (cursor != null && cursor.moveToFirst()) name = cursor.getString(0);
      }
      try {
        getContentResolver()
            .takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION);
      } catch (SecurityException ignored) {
      }
      command("import", Json.obj("uri", uri.toString(), "name", name).toString());
    } else if (request == 11 && saveFile != null) {
      String filename = saveFile;
      saveFile = null;
      new Thread(
              () -> {
                try (InputStream input = new java.io.FileInputStream(store.media(filename));
                    var output = getContentResolver().openOutputStream(uri)) {
                  byte[] buffer = new byte[65536];
                  int count;
                  while ((count = input.read(buffer)) != -1) output.write(buffer, 0, count);
                  store.update(s -> s.put("note", "Video disimpan ke lokasi pilihanmu."));
                } catch (Exception failure) {
                  error(failure);
                }
              },
              "cuplik-save")
          .start();
    }
  }

  private WebResourceResponse media(WebResourceRequest request) {
    try {
      String name = request.getUrl().getLastPathSegment();
      File file = store.media(name);
      if (!name.endsWith(".mp4") || !file.isFile())
        return response(404, "Not Found", Map.of(), new byte[0]);
      long total = file.length(), start = 0, end = total - 1;
      String range = request.getRequestHeaders().get("Range");
      if (range == null) range = request.getRequestHeaders().get("range");
      if (range != null) {
        if (!range.matches("bytes=\\d*-\\d*"))
          return response(
              416,
              "Range Not Satisfiable",
              Map.of("Content-Range", "bytes */" + total),
              new byte[0]);
        String[] fields = range.substring(6).split("-", -1);
        if (fields[0].isEmpty()) start = Math.max(0, total - Long.parseLong(fields[1]));
        else {
          start = Long.parseLong(fields[0]);
          if (!fields[1].isEmpty()) end = Math.min(end, Long.parseLong(fields[1]));
        }
        if (start > end || start >= total)
          return response(
              416,
              "Range Not Satisfiable",
              Map.of("Content-Range", "bytes */" + total),
              new byte[0]);
      }
      long length = end - start + 1;
      Map<String, String> headers = new HashMap<>();
      headers.put("Accept-Ranges", "bytes");
      headers.put("Content-Length", Long.toString(length));
      if (range != null) headers.put("Content-Range", "bytes " + start + "-" + end + "/" + total);
      RandomAccessFile input = new RandomAccessFile(file, "r");
      input.seek(start);
      return new WebResourceResponse(
          "video/mp4",
          null,
          range == null ? 200 : 206,
          range == null ? "OK" : "Partial Content",
          headers,
          new InputStream() {
            long remaining = length;

            public int read() throws java.io.IOException {
              if (remaining <= 0) return -1;
              int value = input.read();
              if (value >= 0) remaining--;
              return value;
            }

            public int read(byte[] bytes, int offset, int count) throws java.io.IOException {
              if (remaining <= 0) return -1;
              int got = input.read(bytes, offset, (int) Math.min(count, remaining));
              if (got > 0) remaining -= got;
              return got;
            }

            public void close() throws java.io.IOException {
              input.close();
            }
          });
    } catch (Exception failure) {
      return response(404, "Not Found", Map.of(), new byte[0]);
    }
  }

  private WebResourceResponse response(
      int code, String reason, Map<String, String> headers, byte[] data) {
    return new WebResourceResponse(
        "text/plain", "utf-8", code, reason, headers, new ByteArrayInputStream(data));
  }

  @Override
  protected void onDestroy() {
    web.removeJavascriptInterface("CuplikNative");
    web.destroy();
    super.onDestroy();
  }
}
