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
  private boolean running;
  private final AtomicBoolean cancelled = new AtomicBoolean(false);
  private final java.util.concurrent.ExecutorService executor = Executors.newSingleThreadExecutor();
  private RenderEngine renderer;
  private Store store;
  private PowerManager.WakeLock wake;
  private final android.os.Handler main = new android.os.Handler(android.os.Looper.getMainLooper());
  private String jobId = "";
  private boolean terminal;
  private long whisperHandle;
  private volatile HttpsURLConnection activeConnection;

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
  public int onStartCommand(Intent intent, int flags, int startId) {
    String requested = intent == null ? "" : intent.getStringExtra("job_id");
    if ("cancel".equals(intent == null ? "" : intent.getAction())) {
      if (store.owns(requested)) store.requestCancel(requested);
      if (jobId.equals(requested)) {
        cancelled.set(true);
        cancelNative();
      } else if (!running) {
        if (store.cancelled(requested))
          store.finish(requested, "cancelled", "Proses dibatalkan sebelum mulai.");
        stopSelfResult(startId);
      }
      return START_NOT_STICKY;
    }
    if (running) {
      if (!jobId.equals(requested))
        store.finish(
            requested, "failed", "Layanan sebelumnya sedang berhenti. Coba ulang sebentar lagi.");
      return START_NOT_STICKY;
    }
    if (requested == null || !store.claim(requested)) {
      stopSelfResult(startId);
      return START_NOT_STICKY;
    }
    jobId = requested;
    terminal = false;
    running = true;
    cancelled.set(false);
    JSONObject job = store.state().optJSONObject("active_job");
    String action = job.optString("action");
    JSONObject payload = job.optJSONObject("payload");
    try {
      NotificationManager manager = getSystemService(NotificationManager.class);
      manager.createNotificationChannel(
          new NotificationChannel(
              "processing", "Pemrosesan video", NotificationManager.IMPORTANCE_LOW));
      android.app.PendingIntent open =
          android.app.PendingIntent.getActivity(
              this,
              0,
              new Intent(this, MainActivity.class),
              android.app.PendingIntent.FLAG_UPDATE_CURRENT
                  | android.app.PendingIntent.FLAG_IMMUTABLE);
      android.app.PendingIntent cancel =
          android.app.PendingIntent.getService(
              this,
              1,
              new Intent(this, ProcessingService.class)
                  .setAction("cancel")
                  .putExtra("job_id", jobId),
              android.app.PendingIntent.FLAG_UPDATE_CURRENT
                  | android.app.PendingIntent.FLAG_IMMUTABLE);
      Notification notification =
          new Notification.Builder(this, "processing")
              .setSmallIcon(app.cuplik.R.drawable.ic_cuplik)
              .setContentTitle("Cuplik memproses di perangkat")
              .setContentText("Buka Cuplik untuk melihat progres.")
              .setContentIntent(open)
              .addAction(new Notification.Action.Builder(null, "Batalkan", cancel).build())
              .setOngoing(true)
              .build();
      boolean media = !action.equals("model") && !action.equals("connection");
      startForeground(
          42,
          notification,
          Build.VERSION.SDK_INT >= 35 && media
              ? ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROCESSING
              : ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC);
      wake =
          ((PowerManager) getSystemService(POWER_SERVICE))
              .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "Cuplik:media");
      wake.acquire(3 * 60 * 60 * 1000L);
      executor.execute(
          () -> {
            String result = "done", message = null;
            try {
              check();
              switch (action) {
                case "model":
                  downloadModel();
                  break;
                case "import":
                  importVideo(payload);
                  break;
                case "analyze":
                  analyze(payload);
                  break;
                case "render":
                  render(payload);
                  break;
                case "connection":
                  connection();
                  break;
                default:
                  throw new IllegalArgumentException("Operasi tidak dikenal.");
              }
            } catch (Throwable error) {
              result = cancelled.get() || store.cancelled(requested) ? "cancelled" : "failed";
              message =
                  result.equals("cancelled")
                      ? "Proses dibatalkan. Checkpoint tetap tersimpan."
                      : safeError(error);
            } finally {
              String completion = result, failure = message;
              main.post(() -> finishExecution(startId, requested, completion, failure));
            }
          });
    } catch (Exception error) {
      finishExecution(startId, requested, "failed", safeError(error));
    }
    return START_NOT_STICKY;
  }

  private void finishExecution(int startId, String id, String result, String message) {
    if (!jobId.equals(id)) return;
    if (!terminal) store.finish(id, result, message);
    terminal = true;
    running = false;
    renderer = null;
    if (wake != null && wake.isHeld()) wake.release();
    stopForeground(STOP_FOREGROUND_REMOVE);
    stopSelf();
  }

  private synchronized void cancelNative() {
    if (renderer != null) renderer.cancel();
    if (whisperHandle != 0) Whisper.cancel(whisperHandle);
    if (activeConnection != null) activeConnection.disconnect();
  }

  private synchronized void closeWhisper(long handle) {
    whisperHandle = 0;
    Whisper.close(handle);
  }

  private void progress(String phase, double fraction, String note) {
    store.jobProgress(jobId, phase, fraction, note);
  }

  private void update(Store.Editor editor) {
    store.updateJob(jobId, editor);
  }

  @Override
  public void onTimeout(int startId, int foregroundServiceType) {
    cancelled.set(true);
    cancelNative();
    store.finish(
        jobId,
        "interrupted",
        "Batas waktu layanan Android tercapai. Checkpoint disimpan untuk dicoba ulang.");
    terminal = true;
    if (wake != null && wake.isHeld()) wake.release();
    stopForeground(STOP_FOREGROUND_REMOVE);
    stopSelf();
  }

  private String safeError(Throwable error) {
    String message = error.getMessage();
    if (message == null) return "Pemrosesan gagal: " + error.getClass().getSimpleName();
    return message.length() > 500 ? message.substring(0, 500) : message;
  }

  private void check() throws InterruptedException {
    if (cancelled.get() || !store.owns(jobId) || store.cancelled(jobId))
      throw new InterruptedException("Dibatalkan.");
  }

  private void importVideo(JSONObject options) throws Exception {
    progress("importing", 0, "Menyalin video ke penyimpanan aplikasi…");
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
      update(
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
      progress("ready", 1, "Model transkripsi sudah tersedia.");
      return;
    }
    if (getFilesDir().getUsableSpace() < 160_000_000)
      throw new IllegalStateException("Sediakan setidaknya 160 MB untuk model transkripsi.");
    File temporary = new File(store.model().getPath() + ".download");
    HttpsURLConnection connection =
        (HttpsURLConnection)
            new URL("https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.bin")
                .openConnection();
    activeConnection = connection;
    connection.setConnectTimeout(20000);
    connection.setReadTimeout(60000);
    MessageDigest digest = MessageDigest.getInstance("SHA-256");
    long bytes = 0, last = 0;
    progress("model", 0, "Mengunduh model Whisper tiny multibahasa, sekitar 78 MB…");
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
          progress("model", bytes / 77691713.0, "Mengunduh model: " + bytes / 1_000_000 + "/78 MB");
        }
      }
    } catch (Exception error) {
      temporary.delete();
      throw error;
    } finally {
      connection.disconnect();
      activeConnection = null;
    }
    StringBuilder hash = new StringBuilder();
    for (byte b : digest.digest())
      hash.append(String.format(java.util.Locale.ROOT, "%02x", b & 255));
    if (!hash.toString().equals(expected)) {
      temporary.delete();
      throw new IllegalStateException("Checksum model tidak cocok. Unduh ulang.");
    }
    check();
    if (!temporary.renameTo(store.model()))
      throw new IllegalStateException("Model tidak dapat disimpan.");
    progress("ready", 1, "Model siap. Transkripsi berikutnya diproses di perangkat.");
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
      progress("transcribing", 0, "Mendekode audio di perangkat…");
      AudioDecoder.decode(store.media(source.getString("file")), audio, cancelled);
    }
    JSONObject current = store.state();
    JSONArray sentences = current.optJSONArray("sentences");
    if (sentences == null) sentences = new JSONArray();
    if (!language.equals(current.optString("transcript_language", language))) {
      sentences = new JSONArray();
      update(
          s -> {
            s.put("next_chunk", 0);
            s.put("sentences", new JSONArray());
          });
    }
    int nextChunk = store.state().optInt("next_chunk", 0), chunkSamples = 30 * 16000;
    long samples = audio.length() / 4, chunks = (samples + chunkSamples - 1) / chunkSamples;
    long handle = Whisper.open(store.model().getPath());
    synchronized (this) {
      whisperHandle = handle;
    }
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
        progress(
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
        update(
            s -> {
              s.put("sentences", snapshot);
              s.put("next_chunk", completed);
              s.put("transcript_language", language);
            });
      }
    } finally {
      closeWhisper(handle);
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
        progress(
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
        if (response == null)
          response =
              new CloudLlm(secrets, connection -> activeConnection = connection)
                  .plan(window, mode, count, maximum);
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
    update(
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
    update(
        s -> {
          s.put("plan", reviewed);
          s.put("status", "rendering");
          s.remove("error");
        });
    renderer = new RenderEngine(this, store, jobId);
    renderer.render(
        store.media(source.getString("file")),
        reviewed,
        state.getJSONArray("sentences"),
        mode,
        settings.optString("layout", "source").equals("portrait"),
        settings.optBoolean("captions", true),
        cancelled);
    progress("done", 1, "Ekspor selesai di perangkat. Putar hasil dan periksa sebelum membagikan.");
  }

  private void connection() throws Exception {
    progress("connection", 0, "Memeriksa API dan daftar model akun…");
    JSONArray models =
        new CloudLlm(new Secrets(this), connection -> activeConnection = connection).models();
    update(
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
    cancelNative();
    if (!terminal)
      store.finish(
          jobId, "interrupted", "Layanan terhenti. Checkpoint disimpan untuk dicoba ulang.");
    running = false;
    if (wake != null && wake.isHeld()) wake.release();
    executor.shutdownNow();
    super.onDestroy();
  }
}
