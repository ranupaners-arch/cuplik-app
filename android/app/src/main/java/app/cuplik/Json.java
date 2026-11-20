package app.cuplik;

import org.json.JSONObject;

final class Json {
    static JSONObject obj(Object... pairs) {
        JSONObject result = new JSONObject();
        try { for (int i=0; i<pairs.length; i+=2) result.put((String)pairs[i], pairs[i+1]); }
        catch (Exception error) { throw new IllegalArgumentException(error); }
        return result;
    }
    private Json() {}
}
