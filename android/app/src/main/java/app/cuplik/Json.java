package app.cuplik;

import org.json.JSONObject;

final class Json {
  static JSONObject obj(Object... pairs) {
    JSONObject result = new JSONObject();
    try {
      for (int i = 0; i < pairs.length; i += 2) result.put((String) pairs[i], pairs[i + 1]);
    } catch (Exception error) {
      throw new IllegalArgumentException(error);
    }
    return result;
  }

  static String hash(String text) {
    try {
      StringBuilder result = new StringBuilder();
      for (byte b :
          java.security.MessageDigest.getInstance("SHA-256")
              .digest(text.getBytes(java.nio.charset.StandardCharsets.UTF_8)))
        result.append(String.format(java.util.Locale.ROOT, "%02x", b & 255));
      return result.toString();
    } catch (Exception error) {
      throw new IllegalStateException(error);
    }
  }

  private Json() {}
}
