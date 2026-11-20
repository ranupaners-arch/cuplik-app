package app.cuplik;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.media.MediaMetadataRetriever;
import android.os.Build;
import android.os.IBinder;
import android.os.PowerManager;
import java.io.File;
import java.io.FileOutputStream;
import java.io.RandomAccessFile;
import java.net.URL;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;
import javax.net.ssl.HttpsURLConnection;
import org.json.JSONArray;
import org.json.JSONObject;

public final class ProcessingService extends Service {
  static volatile boolean running;
  private final AtomicBoolean cancelled = new AtomicBoolean(false);
  private final java.util.concurrent.ExecutorService executor = Executors.newSingleThreadExecutor();
  private RenderEngine renderer;
  private Store store;
  private PowerManager.WakeLock wake;

  @Override
  public IBinder onBind(Intent intent) {
    return null;
  }

  @Override
  public void onCreate() {
    super.onCreate();
    store = Store.get(this);
  }

  @Override
  public int onStartCommand(Intent intent, int flags, int id) {
    String action = intent == null ? "" : intent.getAction();
    if ("cancel".equals(action)) {
      cancelled.set(true);
      if (renderer != null) renderer.cancel();
      return START_NOT_STICKY;
    }
    if (running) return START_NOT_STICKY;
    running = true;
    cancelled.set(false);
    NotificationManager manager = getSystemService(NotificationManager.class);
    manager.createNotificationChannel(
        new NotificationChannel(
            "processing", "Pemrosesan video", NotificationManager.IMPORTANCE_LOW));
    Notification notification =
        new Notification.Builder(this, "processing")
            .setSmallIcon(app.cuplik.R.drawable.ic_cuplik)
            .setContentTitle("Cuplik memproses di perangkat")
            .setContentText("Buka Cuplik untuk melihat progres atau membatalkan.")
            .setOngoing(true)
            .build();
    startForeground(
        42,
        notification,
        Build.VERSION.SDK_INT >= 35
            ? ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROCESSING
            : ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC);
    wake =
        ((PowerManager) getSystemService(POWER_SERVICE))
            .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "Cuplik:media");
    wake.acquire(3 * 60 * 60 * 1000L);
    String payload = intent == null ? "{}" : intent.getStringExtra("payload");
    executor.execute(
        () -> {
          try {
            JSONObject options = new JSONObject(payload == null ? "{}" : payload);
            switch (action == null ? "" : action) {
              case "model":
                downloadModel();
                break;
              case "import":
                importVideo(options);
                break;
              case "analyze":
                analyze(options);
                break;
              case "render":
                render(options);
                break;
              case "connection":
                connection();
                break;
              default:
                throw new IllegalArgumentException("Operasi tidak dikenal.");
            }
          } catch (Throwable error) {
            store.update(
                s -> {
                  s.put("status", cancelled.get() ? "cancelled" : "failed");
                  s.put(
                      "error",
                      cancelled.get()
                          ? "Proses dibatalkan. Cache transkripsi tetap tersedia."
                          : safeError(error));
                  s.put(
                      "note",
                      "Periksa pesan dan coba ulang. Sumber dan hasil yang selesai tetap"
                          + " tersimpan.");
                });
          } finally {
            running = false;
            if (wake != null && wake.isHeld()) wake.release();
            stopForeground(STOP_FOREGROUND_REMOVE);
            stopSelf();
          }
        });
    return START_NOT_STICKY;
  }

  private String safeError(Throwable error) {
    String message = error.getMessage();
    if (message == null) return "Pemrosesan gagal: " + error.getClass().getSimpleName();
    return message.length() > 500 ? message.substring(0, 500) : message;
  }

  private void check() throws InterruptedException {
    if (cancelled.get()) throw new InterruptedException("Dibatalkan.");
  }

  private void importVideo(JSONObject options) throws Exception {
    store.progress("importing", 0, "Menyalin video ke penyimpanan aplikasi…");
    File file = store.media("source-" + UUID.randomUUID() + ".mp4");
    long total = 0;
    try (var input =
            getContentResolver().openInputStream(android.net.Uri.parse(options.getString("uri")));
        var output = new FileOutputStream(file)) {
      byte[] buffer = new byte[1024 * 1024];
      int count;
      while ((count = input.read(buffer)) != -1) {
        check();
        total += count;
        if (total > 2_000_000_000L)
          throw new IllegalArgumentException("Batas video Android saat ini 2 GB.");
        if (file.getUsableSpace() < 64 * 1024 * 1024L)
          throw new IllegalStateException("Ruang penyimpanan hampir habis.");
        output.write(buffer, 0, count);
      }
    } catch (Exception error) {
      file.delete();
      throw error;
    }
    MediaMetadataRetriever metadata = new MediaMetadataRetriever();
    try {
      metadata.setDataSource(file.getPath());
      double duration =
          Double.parseDouble(metadata.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION))
              / 1000.0;
      if (!Double.isFinite(duration) || duration <= 0 || duration > 3600)
        throw new IllegalArgumentException("Gunakan video maksimal satu jam.");
      JSONObject source =
          Json.obj(
              "file",
              file.getName(),
              "name",
              options.optString("name", "Video perangkat"),
              "duration_s",
              duration,
              "url",
              "https://appassets.androidplatform.net/media/" + file.getName());
      store.update(
          s -> {
            s.put("source", source);
            s.put("sentences", new JSONArray());
            s.put("plan", new JSONArray());
            s.put("next_chunk", 0);
            s.put("status", "ready");
            s.put("progress", 0);
            s.put("note", "Video tersimpan lokal. Pilih transkripsi atau susun rencana manual.");
            s.remove("error");
          });
    } catch (Exception error) {
      file.delete();
      throw error;
    } finally {
      metadata.release();
    }
  }

  private void downloadModel() throws Exception {
    final String expected = "be07e048e1e599ad46341c8d2a135645097a538221678b7acdd1b1919c6e1b21";
    if (store.model().exists()) {
      store.progress("ready", 1, "Model transkripsi sudah tersedia.");
      return;
    }
    if (getFilesDir().getUsableSpace() < 160_000_000)
      throw new IllegalStateException("Sediakan setidaknya 160 MB untuk model transkripsi.");
    File temporary = new File(store.model().getPath() + ".download");
    HttpsURLConnection connection =
        (HttpsURLConnection)
            new URL("https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.bin")
                .openConnection();
    connection.setConnectTimeout(20000);
    connection.setReadTimeout(60000);
    MessageDigest digest = MessageDigest.getInstance("SHA-256");
    long bytes = 0, last = 0;
    store.progress("model", 0, "Mengunduh model Whisper tiny multibahasa, sekitar 78 MB…");
    try (var in = connection.getInputStream();
        var out = new FileOutputStream(temporary)) {
      byte[] buffer = new byte[65536];
      int count;
      while ((count = in.read(buffer)) != -1) {
        check();
        bytes += count;
        if (bytes > 80_000_000) throw new IllegalStateException("Ukuran model tidak sesuai.");
        digest.update(buffer, 0, count);
        out.write(buffer, 0, count);
        if (bytes - last > 1_000_000) {
          last = bytes;
          store.progress(
              "model", bytes / 77691713.0, "Mengunduh model: " + bytes / 1_000_000 + "/78 MB");
        }
      }
    } catch (Exception error) {
      temporary.delete();
      throw error;
    } finally {
      connection.disconnect();
    }
    StringBuilder hash = new StringBuilder();
    for (byte b : digest.digest())
      hash.append(String.format(java.util.Locale.ROOT, "%02x", b & 255));
    if (!hash.toString().equals(expected)) {
      temporary.delete();
      throw new IllegalStateException("Checksum model tidak cocok. Unduh ulang.");
    }
    if (!temporary.renameTo(store.model()))
      throw new IllegalStateException("Model tidak dapat disimpan.");
    store.progress("ready", 1, "Model siap. Transkripsi berikutnya diproses di perangkat.");
  }

  private void transcribe(JSONObject source, String language) throws Exception {
    if (!store.model().exists())
      throw new IllegalArgumentException("Unduh model transkripsi terlebih dahulu.");
    if (!language.matches("auto|id|en|ar"))
      throw new IllegalArgumentException("Bahasa tidak valid.");
    File audio = store.media(source.getString("file") + ".f32");
    if (!audio.exists()) {
      if (getFilesDir().getUsableSpace() < source.getDouble("duration_s") * 16000 * 4 + 64_000_000)
        throw new IllegalStateException(
            "Ruang kosong tidak cukup untuk audio transkripsi. Bersihkan cache setelah menyimpan"
                + " hasil.");
      store.progress("transcribing", 0, "Mendekode audio di perangkat…");
      AudioDecoder.decode(store.media(source.getString("file")), audio, cancelled);
    }
    JSONObject current = store.state();
    JSONArray sentences = current.optJSONArray("sentences");
    if (sentences == null) sentences = new JSONArray();
    if (!language.equals(current.optString("transcript_language", language))) {
      sentences = new JSONArray();
      store.update(
          s -> {
            s.put("next_chunk", 0);
            s.put("sentences", new JSONArray());
          });
    }
    int nextChunk = store.state().optInt("next_chunk", 0), chunkSamples = 30 * 16000;
    long samples = audio.length() / 4, chunks = (samples + chunkSamples - 1) / chunkSamples;
    long handle = Whisper.open(store.model().getPath());
    if (handle == 0)
      throw new IllegalStateException("Model tidak dapat dimuat; pastikan memori perangkat cukup.");
    try (RandomAccessFile file = new RandomAccessFile(audio, "r")) {
      for (int index = nextChunk; index < chunks; index++) {
        check();
        int count = (int) Math.min(chunkSamples, samples - (long) index * chunkSamples);
        byte[] raw = new byte[count * 4];
        file.seek((long) index * chunkSamples * 4);
        file.readFully(raw);
        float[] pcm = new float[count];
        ByteBuffer.wrap(raw).order(ByteOrder.LITTLE_ENDIAN).asFloatBuffer().get(pcm);
        store.progress(
            "transcribing",
            index / (double) chunks,
            "Mentranskrip bagian " + (index + 1) + "/" + chunks + " di perangkat…");
        JSONArray decoded =
            new JSONArray(
                new String(Whisper.transcribe(handle, pcm, language), StandardCharsets.UTF_8));
        for (int j = 0; j < decoded.length(); j++) {
          JSONObject row = decoded.getJSONObject(j);
          double a = index * 30 + row.getDouble("start_s"),
              b = Math.min(source.getDouble("duration_s"), index * 30 + row.getDouble("end_s"));
          String text = row.getString("text").trim();
          if (b > a && !text.isEmpty() && Double.isFinite(a) && Double.isFinite(b))
            sentences.put(
                Json.obj(
                    "id", "s" + (sentences.length() + 1), "start_s", a, "end_s", b, "text", text));
        }
        JSONArray snapshot = new JSONArray(sentences.toString());
        int completed = index + 1;
        store.update(
            s -> {
              s.put("sentences", snapshot);
              s.put("next_chunk", completed);
              s.put("transcript_language", language);
            });
      }
    } finally {
      Whisper.close(handle);
    }
    if (sentences.length() == 0)
      throw new IllegalStateException(
          "Ucapan belum terdeteksi. Gunakan rencana manual atau periksa audio.");
  }

  private void analyze(JSONObject options) throws Exception {
    JSONObject source = store.state().getJSONObject("source");
    String mode = options.optString("mode", "clips");
    if (!mode.equals("clips") && !mode.equals("condense"))
      throw new IllegalArgumentException("Mode tidak valid.");
    int count = Math.max(1, Math.min(12, options.optInt("clip_count", 3)));
    double maximum = options.optDouble("max_clip_seconds", 60);
    if (!Double.isFinite(maximum) || maximum < 3 || maximum > 180)
      throw new IllegalArgumentException("Durasi klip harus 3–180 detik.");
    if (!options.optBoolean("manual")) transcribe(source, options.optString("language", "id"));
    JSONArray sentences = store.state().getJSONArray("sentences"), plan;
    Secrets secrets = new Secrets(this);
    boolean live =
        !options.optBoolean("manual")
            && secrets.publicConfig().optBoolean("consent")
            && secrets.publicConfig().optBoolean("has_key");
    if (live) {
      plan = new JSONArray();
      for (int from = 0; from < sentences.length(); ) {
        check();
        int to = from;
        JSONArray window = new JSONArray();
        double windowStart = from == 0 ? 0 : sentences.getJSONObject(from).getDouble("start_s");
        while (to < sentences.length() && to - from < 40) {
          JSONObject row = sentences.getJSONObject(to);
          if (to > from
              && (window.toString().length() + row.toString().length() > 12000
                  || row.getDouble("start_s") - windowStart > 900)) break;
          window.put(row);
          to++;
        }
        double windowEnd =
            to < sentences.length()
                ? sentences.getJSONObject(to).getDouble("start_s")
                : source.getDouble("duration_s");
        store.progress(
            "planning",
            from / (double) sentences.length(),
            "Menganalisis teks dengan API; media tetap di perangkat…");
        String cacheKey =
            sha(
                Json.obj(
                        "version",
                        1,
                        "window",
                        window,
                        "config",
                        secrets.publicConfig(),
                        "mode",
                        mode,
                        "count",
                        count,
                        "maximum",
                        maximum)
                    .toString());
        File cached = store.media("llm-" + cacheKey + ".json");
        JSONObject response = null;
        if (cached.exists())
          try {
            response =
                new JSONObject(
                    new String(Files.readAllBytes(cached.toPath()), StandardCharsets.UTF_8));
            Planner.validate(response, window, mode, windowEnd, maximum, windowStart);
          } catch (Exception invalid) {
            cached.delete();
            response = null;
          }
        if (response == null) response = new CloudLlm(secrets).plan(window, mode, count, maximum);
        JSONArray checked =
            Planner.validate(response, window, mode, windowEnd, maximum, windowStart);
        Files.write(cached.toPath(), response.toString().getBytes(StandardCharsets.UTF_8));
        for (int i = 0; i < checked.length(); i++) {
          JSONObject row = checked.getJSONObject(i);
          row.put("id", "p" + (plan.length() + 1));
          plan.put(row);
        }
        from = to;
      }
      if (mode.equals("clips") && plan.length() > count) {
        List<JSONObject> ranked = new ArrayList<>();
        for (int i = 0; i < plan.length(); i++) ranked.add(plan.getJSONObject(i));
        ranked.sort(Comparator.comparingDouble((JSONObject r) -> -r.optDouble("score")));
        plan = new JSONArray(ranked.subList(0, count));
      }
    } else plan = Planner.manual(sentences, mode, source.getDouble("duration_s"));
    JSONArray reviewed = plan;
    store.update(
        s -> {
          s.put("mode", mode);
          s.put("settings", options);
          s.put("plan", reviewed);
          s.put(
              "analysis_provider", live ? secrets.publicConfig().optString("provider") : "manual");
          s.put("status", "awaiting_review");
          s.put("progress", 1);
          s.put(
              "note",
              live
                  ? "Tinjau rencana AI dan sumber sebelum ekspor. Analisis memakai teks, tanpa"
                      + " pemeriksaan frame."
                  : "Rencana manual siap ditinjau. Belum ada pemilihan AI dari API.");
        });
  }

  private void render(JSONObject options) throws Exception {
    JSONObject state = store.state(), source = state.getJSONObject("source");
    String mode = state.optString("mode", "clips");
    JSONArray reviewed =
        Planner.review(
            state.getJSONArray("plan"),
            options.getJSONArray("plan"),
            mode,
            source.getDouble("duration_s"));
    JSONObject settings = state.getJSONObject("settings");
    store.update(
        s -> {
          s.put("plan", reviewed);
          s.put("status", "rendering");
          s.remove("error");
        });
    renderer = new RenderEngine(this, store);
    renderer.render(
        store.media(source.getString("file")),
        reviewed,
        state.getJSONArray("sentences"),
        mode,
        settings.optString("layout", "source").equals("portrait"),
        settings.optBoolean("captions", true),
        cancelled);
    store.progress(
        "done", 1, "Ekspor selesai di perangkat. Putar hasil dan periksa sebelum membagikan.");
  }

  private void connection() throws Exception {
    store.progress("connection", 0, "Memeriksa API dan daftar model akun…");
    JSONArray models = new CloudLlm(new Secrets(this)).models();
    store.update(
        s -> {
          s.put("models", models);
          s.put("status", s.optJSONArray("plan").length() > 0 ? "awaiting_review" : "ready");
          s.put("note", "API tersambung. Pilih model yang tersedia pada akunmu.");
        });
  }

  private String sha(String text) throws Exception {
    StringBuilder result = new StringBuilder();
    for (byte b :
        MessageDigest.getInstance("SHA-256").digest(text.getBytes(StandardCharsets.UTF_8)))
      result.append(String.format(java.util.Locale.ROOT, "%02x", b & 255));
    return result.toString();
  }

  @Override
  public void onDestroy() {
    cancelled.set(true);
    if (renderer != null) renderer.cancel();
    if (wake != null && wake.isHeld()) wake.release();
    super.onDestroy();
  }
}
