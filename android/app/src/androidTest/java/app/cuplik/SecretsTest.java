package app.cuplik;

import static org.junit.Assert.*;

import android.content.Context;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import org.junit.Test;
import org.junit.runner.RunWith;

@RunWith(AndroidJUnit4.class)
public class SecretsTest {
  @Test
  public void storesEncryptedKeyWithoutExposingItToUiState() throws Exception {
    Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
    Secrets secrets = new Secrets(context);
    String fixture = "fixture-key-never-sent-to-a-provider";
    try {
      secrets.save(
          Json.obj(
              "provider", "gemini", "model", "fixture-model", "api_key", fixture, "consent", true));
      assertEquals(fixture, secrets.apiKey());
      assertTrue(secrets.publicConfig().getBoolean("has_key"));
      assertFalse(secrets.publicConfig().toString().contains(fixture));
      assertFalse(
          context
              .getSharedPreferences("ai-config", Context.MODE_PRIVATE)
              .getString("key", "")
              .contains(fixture));
      secrets.save(Json.obj("provider", "anthropic", "model", "fixture-model"));
      assertEquals("", secrets.apiKey());
    } finally {
      secrets.save(Json.obj("provider", "gemini", "remove_key", true, "consent", false));
    }
  }
}
