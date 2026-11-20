package app.cuplik;

import static org.junit.Assert.*;

import android.content.Context;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import java.io.File;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.concurrent.atomic.AtomicBoolean;
import org.json.JSONArray;
import org.junit.Test;
import org.junit.runner.RunWith;

@RunWith(AndroidJUnit4.class)
public class LocalPipelineTest {
  @Test
  public void captionGapsRenderTransparentFramesWithoutZeroSizedBitmaps() throws Exception {
    JSONArray sentences =
        new JSONArray().put(Json.obj("start_s", 2, "end_s", 4, "text", "Periksa hasil."));
    RenderEngine.Captions overlay = new RenderEngine.Captions(sentences, 0, 8, false);
    android.graphics.Bitmap gap = overlay.getBitmap(0);
    assertTrue(gap.getWidth() > 0 && gap.getHeight() > 0);
    assertEquals(0, android.graphics.Color.alpha(gap.getPixel(0, 0)));
    assertTrue(overlay.getBitmap(2_500_000).getWidth() > gap.getWidth());
    assertTrue(overlay.getBitmap(5_000_000).getWidth() > 0);
  }

  @Test
  public void transcribesAndRendersOnAndroidWithoutBackend() throws Exception {
    Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
    Context tests = InstrumentationRegistry.getInstrumentation().getContext();
    Store store = Store.get(context);
    File source = store.media("smoke-source.mp4"),
        model = new File(context.getCacheDir(), "smoke-model.bin"),
        pcm = new File(context.getCacheDir(), "smoke.f32");
    try (var input = tests.getAssets().open("source.mp4")) {
      Files.copy(input, source.toPath(), java.nio.file.StandardCopyOption.REPLACE_EXISTING);
    }
    try (var input = tests.getAssets().open("ggml-tiny.bin")) {
      Files.copy(input, model.toPath(), java.nio.file.StandardCopyOption.REPLACE_EXISTING);
    }
    AudioDecoder.decode(source, pcm, new AtomicBoolean(false));
    assertTrue(pcm.length() > 16000 * 4);
    byte[] bytes = Files.readAllBytes(pcm.toPath());
    float[] samples = new float[bytes.length / 4];
    ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN).asFloatBuffer().get(samples);
    long handle = Whisper.open(model.getPath());
    assertTrue(handle != 0);
    JSONArray transcript;
    try {
      transcript =
          new JSONArray(
              new String(Whisper.transcribe(handle, samples, "en"), StandardCharsets.UTF_8));
      Whisper.cancel(handle);
      assertThrows(InterruptedException.class, () -> Whisper.transcribe(handle, samples, "en"));
    } finally {
      Whisper.close(handle);
    }
    assertTrue("Actual speech must yield segments", transcript.length() > 0);
    for (int i = 0; i < transcript.length(); i++)
      transcript.getJSONObject(i).put("id", "s" + (i + 1));
    JSONArray plan =
        new JSONArray()
            .put(
                Json.obj(
                    "id",
                    "p1",
                    "title",
                    "Android smoke",
                    "start_s",
                    0,
                    "end_s",
                    8,
                    "keep",
                    true,
                    "required",
                    true,
                    "speed",
                    1.15));
    new RenderEngine(context, store)
        .render(source, plan, transcript, "condense", false, true, new AtomicBoolean(false));
    var output = store.state().getJSONArray("outputs").getJSONObject(0);
    assertTrue(store.media(output.getString("file")).length() > 1000);
    assertTrue(output.getBoolean("audio_present"));
    assertTrue(output.getBoolean("duration_matches"));
    File finalPcm = new File(context.getCacheDir(), "export.f32");
    AudioDecoder.decode(store.media(output.getString("file")), finalPcm, new AtomicBoolean(false));
    ByteBuffer decoded =
        ByteBuffer.wrap(Files.readAllBytes(finalPcm.toPath())).order(ByteOrder.LITTLE_ENDIAN);
    double energy = 0;
    int frames = 0;
    while (decoded.remaining() >= 4) {
      float value = decoded.getFloat();
      energy += value * value;
      frames++;
    }
    assertTrue(
        "Encoded output must retain audible samples", frames > 16000 && energy / frames > 1e-8);
    int exported = store.state().getJSONArray("outputs").length();
    new RenderEngine(context, store)
        .render(source, plan, transcript, "condense", false, true, new AtomicBoolean(false));
    assertEquals(
        "Retry must reuse the completed export",
        exported,
        store.state().getJSONArray("outputs").length());
  }
}
