package app.cuplik;

import android.content.Context;
import android.graphics.Color;
import android.media.MediaMetadataRetriever;
import android.net.Uri;
import android.os.Handler;
import android.os.Looper;
import android.text.SpannableString;
import android.text.Spanned;
import android.text.style.AbsoluteSizeSpan;
import android.text.style.BackgroundColorSpan;
import android.text.style.ForegroundColorSpan;
import androidx.media3.common.C;
import androidx.media3.common.Effect;
import androidx.media3.common.MediaItem;
import androidx.media3.common.MimeTypes;
import androidx.media3.common.OverlaySettings;
import androidx.media3.common.SpeedParameters;
import androidx.media3.common.audio.SpeedProvider;
import androidx.media3.effect.OverlayEffect;
import androidx.media3.effect.Presentation;
import androidx.media3.effect.StaticOverlaySettings;
import androidx.media3.effect.TextOverlay;
import androidx.media3.transformer.Composition;
import androidx.media3.transformer.EditedMediaItem;
import androidx.media3.transformer.EditedMediaItemSequence;
import androidx.media3.transformer.Effects;
import androidx.media3.transformer.ExportException;
import androidx.media3.transformer.ExportResult;
import androidx.media3.transformer.ProgressHolder;
import androidx.media3.transformer.Transformer;
import com.google.common.collect.ImmutableList;
import java.io.File;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import org.json.JSONArray;
import org.json.JSONObject;

@androidx.annotation.OptIn(
    markerClass = {
      androidx.media3.common.util.UnstableApi.class,
      androidx.media3.common.util.ExperimentalApi.class
    })
final class RenderEngine {
  private final Context context;
  private final Store store;
  private final Handler main = new Handler(Looper.getMainLooper());
  private volatile Transformer transformer;
  private final String owner;

  RenderEngine(Context context, Store store) {
    this(context, store, null);
  }

  RenderEngine(Context context, Store store, String owner) {
    this.context = context;
    this.store = store;
    this.owner = owner;
  }

  private void check(AtomicBoolean cancelled) throws InterruptedException {
    if (cancelled.get() || (owner != null && (!store.owns(owner) || store.cancelled(owner))))
      throw new InterruptedException("Ekspor dibatalkan.");
  }

  private void progress(double fraction, String note) {
    if (owner == null) store.progress("rendering", fraction, note);
    else store.jobProgress(owner, "rendering", fraction, note);
  }

  void cancel() {
    main.post(
        () -> {
          if (transformer != null) transformer.cancel();
        });
  }

  void render(
      File source,
      JSONArray plan,
      JSONArray sentences,
      String mode,
      boolean portrait,
      boolean captions,
      AtomicBoolean cancelled)
      throws Exception {
    MediaMetadataRetriever sourceMetadata = new MediaMetadataRetriever();
    boolean sourceAudio;
    try {
      sourceMetadata.setDataSource(source.getPath());
      sourceAudio =
          "yes"
              .equals(
                  sourceMetadata.extractMetadata(MediaMetadataRetriever.METADATA_KEY_HAS_AUDIO));
    } finally {
      sourceMetadata.release();
    }
    List<List<JSONObject>> exports = new ArrayList<>();
    List<JSONObject> kept = new ArrayList<>();
    for (int i = 0; i < plan.length(); i++)
      if (plan.getJSONObject(i).optBoolean("keep")) kept.add(plan.getJSONObject(i));
    if (kept.isEmpty()) throw new IllegalArgumentException("Pilih setidaknya satu bagian.");
    if (mode.equals("clips")) for (JSONObject row : kept) exports.add(List.of(row));
    else exports.add(kept);
    JSONArray outputs = store.state().optJSONArray("outputs");
    if (outputs == null) outputs = new JSONArray();
    for (int outputIndex = 0; outputIndex < exports.size(); outputIndex++) {
      check(cancelled);
      String inputKey =
          Json.hash(
              Json.obj(
                      "version",
                      2,
                      "source",
                      source.getName(),
                      "parts",
                      new JSONArray(exports.get(outputIndex)),
                      "sentences",
                      sentences,
                      "portrait",
                      portrait,
                      "captions",
                      captions)
                  .toString());
      boolean reused = false;
      for (int previous = 0; previous < outputs.length(); previous++) {
        JSONObject cached = outputs.getJSONObject(previous);
        if (inputKey.equals(cached.optString("input_key"))
            && store.media(cached.optString("file")).isFile()) {
          if (cached.optJSONObject("qc") == null) {
            cached.put(
                "qc",
                measure(
                    store.media(cached.getString("file")),
                    cached.getDouble("duration_s"),
                    cached.getDouble("expected_duration_s"),
                    cached.optBoolean("audio_present"),
                    sourceAudio,
                    cancelled));
            JSONArray snapshot = new JSONArray(outputs.toString());
            if (owner == null) store.update(state -> state.put("outputs", snapshot));
            else store.updateJob(owner, state -> state.put("outputs", snapshot));
          }
          reused = true;
          break;
        }
      }
      if (reused) continue;
      List<EditedMediaItem> items = new ArrayList<>();
      double expected = 0;
      for (JSONObject row : exports.get(outputIndex)) {
        double start = row.getDouble("start_s"),
            end = row.getDouble("end_s"),
            speed = row.optDouble("speed", 1);
        expected += (end - start) / speed;
        MediaItem media =
            new MediaItem.Builder()
                .setUri(Uri.fromFile(source))
                .setClippingConfiguration(
                    new MediaItem.ClippingConfiguration.Builder()
                        .setStartPositionMs(Math.round(start * 1000))
                        .setEndPositionMs(Math.round(end * 1000))
                        .build())
                .build();
        List<Effect> effects = new ArrayList<>();
        if (portrait)
          effects.add(
              Presentation.createForWidthAndHeight(720, 1280, Presentation.LAYOUT_SCALE_TO_FIT));
        else effects.add(Presentation.createForHeight(720));
        if (captions)
          effects.add(
              new OverlayEffect(ImmutableList.of(new Captions(sentences, start, end, portrait))));
        EditedMediaItem.Builder item =
            new EditedMediaItem.Builder(media).setEffects(new Effects(ImmutableList.of(), effects));
        if (speed > 1.0001)
          item.setSpeed(
              new SpeedParameters(
                  new SpeedProvider() {
                    public float getSpeed(long timeUs) {
                      return (float) speed;
                    }

                    public long getNextSpeedChangeTimeUs(long timeUs) {
                      return C.TIME_UNSET;
                    }
                  },
                  true));
        items.add(item.build());
      }
      String token = java.util.UUID.randomUUID().toString();
      String name = "export-" + token + ".mp4";
      File file = store.media("partial-" + token + ".mp4");
      CountDownLatch finished = new CountDownLatch(1);
      Exception[] failure = new Exception[1];
      AtomicBoolean complete = new AtomicBoolean(false);
      java.util.concurrent.atomic.AtomicInteger measuredProgress =
          new java.util.concurrent.atomic.AtomicInteger(-1);
      Composition composition =
          new Composition.Builder(EditedMediaItemSequence.withAudioAndVideoFrom(items)).build();
      main.post(
          () -> {
            try {
              transformer =
                  new Transformer.Builder(context)
                      .setVideoMimeType(MimeTypes.VIDEO_H264)
                      .setAudioMimeType(MimeTypes.AUDIO_AAC)
                      .addListener(
                          new Transformer.Listener() {
                            @Override
                            public void onCompleted(Composition done, ExportResult result) {
                              complete.set(true);
                              finished.countDown();
                            }

                            @Override
                            public void onError(
                                Composition done, ExportResult result, ExportException error) {
                              failure[0] = error;
                              complete.set(true);
                              finished.countDown();
                            }
                          })
                      .build();
              transformer.start(composition, file.getPath());
            } catch (Exception error) {
              failure[0] = error;
              finished.countDown();
            }
          });
      long started = System.nanoTime();
      while (!finished.await(500, TimeUnit.MILLISECONDS)) {
        if (cancelled.get() || (owner != null && (!store.owns(owner) || store.cancelled(owner)))) {
          cancel();
          file.delete();
          throw new InterruptedException("Dibatalkan.");
        }
        if (TimeUnit.NANOSECONDS.toMinutes(System.nanoTime() - started) > 45) {
          cancel();
          file.delete();
          throw new IllegalStateException("Ekspor melewati 45 menit; gunakan video lebih pendek.");
        }
        final int part = outputIndex;
        main.post(
            () -> {
              if (transformer != null && !complete.get() && !cancelled.get()) {
                ProgressHolder progress = new ProgressHolder();
                int state = transformer.getProgress(progress);
                if (state == Transformer.PROGRESS_STATE_AVAILABLE)
                  measuredProgress.set(progress.progress);
              }
            });
        if (measuredProgress.get() >= 0)
          progress(
              (part + measuredProgress.get() / 100.0) / exports.size(),
              "Merender " + (part + 1) + "/" + exports.size() + " di perangkat…");
      }
      if (failure[0] != null) {
        file.delete();
        throw failure[0];
      }
      try {
        check(cancelled);
        MediaMetadataRetriever metadata = new MediaMetadataRetriever();
        double actual;
        boolean audio;
        int width, height;
        try {
          metadata.setDataSource(file.getPath());
          actual =
              Double.parseDouble(
                      metadata.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION))
                  / 1000.0;
          audio =
              "yes".equals(metadata.extractMetadata(MediaMetadataRetriever.METADATA_KEY_HAS_AUDIO));
          width =
              Integer.parseInt(
                  metadata.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_WIDTH));
          height =
              Integer.parseInt(
                  metadata.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_HEIGHT));
          String rotation =
              metadata.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_ROTATION);
          if ("90".equals(rotation) || "270".equals(rotation)) {
            int swap = width;
            width = height;
            height = swap;
          }
        } finally {
          metadata.release();
        }
        check(cancelled);
        progress(
            (outputIndex + .98) / exports.size(), "Memeriksa sampel audio dan durasi MP4 akhir…");
        JSONObject qc = measure(file, actual, expected, audio, sourceAudio, cancelled);
        check(cancelled);
        if (!file.renameTo(store.media(name)))
          throw new IllegalStateException("Ekspor selesai belum dapat disimpan.");
        outputs.put(
            Json.obj(
                "file",
                name,
                "input_key",
                inputKey,
                "title",
                mode.equals("clips")
                    ? exports.get(outputIndex).get(0).optString("title")
                    : "Ringkasan video",
                "duration_s",
                actual,
                "expected_duration_s",
                expected,
                "width",
                width,
                "height",
                height,
                "audio_present",
                audio,
                "qc",
                qc,
                "duration_matches",
                Math.abs(actual - expected) <= Math.max(.15, expected * .03),
                "url",
                "https://appassets.androidplatform.net/media/" + name));
        JSONArray snapshot = new JSONArray(outputs.toString());
        if (owner == null) store.update(s -> s.put("outputs", snapshot));
        else store.updateJob(owner, s -> s.put("outputs", snapshot));
      } finally {
        file.delete();
      }
    }
  }

  private JSONObject measure(
      File file,
      double actual,
      double expected,
      boolean audio,
      boolean sourceAudio,
      AtomicBoolean cancelled)
      throws Exception {
    JSONObject levels = null;
    if (audio) {
      try {
        levels = AudioDecoder.levels(file, cancelled);
      } catch (InterruptedException stopped) {
        throw stopped;
      } catch (Exception unavailable) {
        /* A completed export remains available for manual review. */
      }
    }
    check(cancelled);
    return OutputQc.report(actual, expected, audio, sourceAudio, levels);
  }

  static final class Captions extends TextOverlay {
    private final JSONArray sentences;
    private final double start, end;
    private final boolean portrait;
    private CaptionTimeline timeline;
    private int fontPixels;
    private double maxWidth;
    private SpannableString cachedText;

    Captions(JSONArray sentences, double start, double end, boolean portrait) {
      this.sentences = sentences;
      this.start = start;
      this.end = end;
      this.portrait = portrait;
      configure(new androidx.media3.common.util.Size(portrait ? 720 : 1280, portrait ? 1280 : 720));
    }

    @Override
    public void configure(androidx.media3.common.util.Size videoSize) {
      super.configure(videoSize);
      cachedText = null;
      int width = Math.max(1, videoSize.getWidth()), height = Math.max(1, videoSize.getHeight());
      boolean compact = portrait || width < height * .9;
      fontPixels = Math.max(8, (int) Math.min(36, Math.min(width * .044, height * .036)));
      maxWidth = width * .82;
      android.text.TextPaint paint = new android.text.TextPaint();
      paint.setTextSize(fontPixels);
      timeline =
          new CaptionTimeline(sentences, start, end, compact ? 3 : 5, maxWidth, paint::measureText);
    }

    @Override
    public SpannableString getText(long timeUs) {
      String text = timeline.at(start + timeUs / 1_000_000.0);
      String content = text.isEmpty() ? "\u00a0" : text;
      if (cachedText != null && content.contentEquals(cachedText)) return cachedText;
      // Media3 TextOverlay cannot allocate a bitmap for an empty string.
      // A transparent non-breaking space preserves valid geometry during caption gaps.
      boolean visible = !text.isEmpty();
      SpannableString result = new SpannableString(visible ? text : "\u00a0");
      android.text.TextPaint paint = new android.text.TextPaint();
      paint.setTextSize(fontPixels);
      int fittedSize =
          Math.max(
              1,
              (int)
                  Math.min(
                      fontPixels,
                      fontPixels * maxWidth / Math.max(1, paint.measureText(result.toString()))));
      result.setSpan(
          new AbsoluteSizeSpan(fittedSize), 0, result.length(), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
      result.setSpan(
          new ForegroundColorSpan(visible ? Color.WHITE : Color.TRANSPARENT),
          0,
          result.length(),
          Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
      result.setSpan(
          new BackgroundColorSpan(visible ? 0xCC000000 : Color.TRANSPARENT),
          0,
          result.length(),
          Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
      cachedText = result;
      return result;
    }

    @Override
    public OverlaySettings getOverlaySettings(long timeUs) {
      return new StaticOverlaySettings.Builder()
          .setBackgroundFrameAnchor(0, -.78f)
          .setOverlayFrameAnchor(0, -1)
          .build();
    }
  }
}
