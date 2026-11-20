package app.cuplik;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import java.security.KeyStore;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;
import org.json.JSONObject;

final class Secrets {
  private final SharedPreferences preferences;

  Secrets(Context context) {
    preferences = context.getSharedPreferences("ai-config", Context.MODE_PRIVATE);
  }

  private SecretKey key() throws Exception {
    KeyStore store = KeyStore.getInstance("AndroidKeyStore");
    store.load(null);
    if (!store.containsAlias("cuplik-api")) {
      KeyGenerator generator =
          KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
      generator.init(
          new KeyGenParameterSpec.Builder(
                  "cuplik-api", KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
              .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
              .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
              .build());
      generator.generateKey();
    }
    return ((KeyStore.SecretKeyEntry) store.getEntry("cuplik-api", null)).getSecretKey();
  }

  String apiKey() throws Exception {
    String encoded = preferences.getString("key", "");
    if (encoded.isEmpty()) return "";
    String[] parts = encoded.split(":");
    Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
    cipher.init(
        Cipher.DECRYPT_MODE,
        key(),
        new GCMParameterSpec(128, Base64.decode(parts[0], Base64.NO_WRAP)));
    return new String(
        cipher.doFinal(Base64.decode(parts[1], Base64.NO_WRAP)),
        java.nio.charset.StandardCharsets.UTF_8);
  }

  void save(JSONObject value) throws Exception {
    String provider = value.optString("provider", "gemini");
    if (!provider.equals("gemini") && !provider.equals("anthropic"))
      throw new IllegalArgumentException("Provider tidak dikenal.");
    SharedPreferences.Editor edit =
        preferences
            .edit()
            .putString("provider", provider)
            .putString("model", value.optString("model").trim())
            .putBoolean("consent", value.optBoolean("consent"));
    String secret = value.optString("api_key").trim();
    if (!secret.isEmpty()) {
      Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
      cipher.init(Cipher.ENCRYPT_MODE, key());
      edit.putString(
          "key",
          Base64.encodeToString(cipher.getIV(), Base64.NO_WRAP)
              + ":"
              + Base64.encodeToString(
                  cipher.doFinal(secret.getBytes(java.nio.charset.StandardCharsets.UTF_8)),
                  Base64.NO_WRAP));
    } else if (!provider.equals(preferences.getString("provider", "gemini"))) edit.remove("key");
    if (value.optBoolean("remove_key")) edit.remove("key");
    if (!edit.commit()) throw new IllegalStateException("Pengaturan tidak tersimpan.");
  }

  JSONObject publicConfig() {
    return Json.obj(
        "provider",
        preferences.getString("provider", "gemini"),
        "model",
        preferences.getString("model", ""),
        "consent",
        preferences.getBoolean("consent", false),
        "has_key",
        !preferences.getString("key", "").isEmpty());
  }
}
