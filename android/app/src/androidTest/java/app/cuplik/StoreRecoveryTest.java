package app.cuplik;

import static org.junit.Assert.*;

import android.content.Context;
import android.content.ContextWrapper;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import java.io.File;
import java.nio.file.Files;
import java.util.UUID;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;

@RunWith(AndroidJUnit4.class)
public class StoreRecoveryTest {
  private Context isolated() {
    Context base = InstrumentationRegistry.getInstrumentation().getTargetContext();
    File directory = new File(base.getCacheDir(), "store-test-" + UUID.randomUUID());
    assertTrue(directory.mkdirs());
    return new ContextWrapper(base) {
      @Override
      public File getFilesDir() {
        return directory;
      }
    };
  }

  @Test
  public void processRestartPreservesCheckpointAndCompletedFiles() throws Exception {
    Context context = isolated();
    Store original = new Store(context);
    original.update(
        s -> {
          s.put("source", Json.obj("file", "source-a.mp4"));
          s.put("next_chunk", 4);
          s.put("sentences", new JSONArray().put(Json.obj("id", "s1", "text", "saved")));
        });
    Files.write(original.media("source-a.mp4").toPath(), new byte[] {1});
    Files.write(original.media("export-done.mp4").toPath(), new byte[] {2});
    Files.write(original.media("partial-aborted.mp4").toPath(), new byte[] {3});
    JSONObject job = original.enqueue("analyze", Json.obj("mode", "clips"));
    original.claim(job.getString("id"));
    Store recovered = new Store(context);
    assertFalse(recovered.busy());
    assertTrue(recovered.retryable());
    assertEquals("interrupted", recovered.state().getString("status"));
    assertEquals(4, recovered.state().getInt("next_chunk"));
    assertTrue(recovered.media("source-a.mp4").isFile());
    assertTrue(recovered.media("export-done.mp4").isFile());
    assertFalse(recovered.media("partial-aborted.mp4").exists());
    String retry = recovered.retry().getString("id");
    assertThrows(
        IllegalStateException.class,
        () -> recovered.updateJob(job.getString("id"), s -> s.put("next_chunk", 0)));
    assertTrue(recovered.claim(retry));
    assertEquals(4, recovered.state().getInt("next_chunk"));
  }

  @Test
  public void atomicBackupAndCorruptStateNeverDeleteMedia() throws Exception {
    Context context = isolated();
    Store store = new Store(context);
    store.update(s -> s.put("note", "recover from backup"));
    File state = new File(context.getFilesDir(), "state.json"),
        backup = new File(context.getFilesDir(), "state.json.bak");
    assertTrue(state.renameTo(backup));
    Files.writeString(state.toPath(), "broken write");
    assertEquals("recover from backup", new Store(context).state().getString("note"));
    Files.write(store.media("export-keep.mp4").toPath(), new byte[] {1});
    Files.writeString(state.toPath(), "invalid JSON");
    Store fresh = new Store(context);
    assertTrue(fresh.media("export-keep.mp4").exists());
    assertEquals(
        1,
        context.getFilesDir().listFiles((dir, name) -> name.startsWith("state-corrupt-")).length);
  }
}
