package app.cuplik;

final class Whisper {
    static { System.loadLibrary("cuplik-whisper"); }
    static native long open(String path);
    static native byte[] transcribe(long context, float[] samples, String language);
    static native void close(long context);
    private Whisper() {}
}
