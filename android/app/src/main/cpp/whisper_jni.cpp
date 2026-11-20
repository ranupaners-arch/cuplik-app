#include <jni.h>
#include <algorithm>
#include <cstdio>
#include <sstream>
#include <string>
#include <thread>
#include "whisper.h"

static std::string quote(const char *value) {
    std::string result = "\"";
    for (const unsigned char *p = reinterpret_cast<const unsigned char *>(value); *p; ++p) {
        if (*p == '"' || *p == '\\') { result += '\\'; result += *p; }
        else if (*p < 32) { char escaped[7]; snprintf(escaped, sizeof(escaped), "\\u%04x", *p); result += escaped; }
        else result += *p;
    }
    return result + "\"";
}

extern "C" JNIEXPORT jlong JNICALL Java_app_cuplik_Whisper_open(JNIEnv *env, jclass, jstring path) {
    const char *file = env->GetStringUTFChars(path, nullptr);
    auto params = whisper_context_default_params();
    params.use_gpu = false;
    auto *context = whisper_init_from_file_with_params(file, params);
    env->ReleaseStringUTFChars(path, file);
    return reinterpret_cast<jlong>(context);
}

extern "C" JNIEXPORT jbyteArray JNICALL Java_app_cuplik_Whisper_transcribe(JNIEnv *env, jclass, jlong handle, jfloatArray samples, jstring language) {
    auto *context = reinterpret_cast<whisper_context *>(handle);
    if (!context) return nullptr;
    const char *lang = env->GetStringUTFChars(language, nullptr);
    auto params = whisper_full_default_params(WHISPER_SAMPLING_GREEDY);
    params.n_threads = std::min(4u, std::max(1u, std::thread::hardware_concurrency()));
    params.language = lang;
    params.translate = false;
    params.no_context = true;
    params.print_realtime = false;
    params.print_progress = false;
    params.print_timestamps = false;
    params.suppress_blank = true;
    params.no_speech_thold = 0.6f;
    float *audio = env->GetFloatArrayElements(samples, nullptr);
    int result = whisper_full(context, params, audio, env->GetArrayLength(samples));
    env->ReleaseFloatArrayElements(samples, audio, JNI_ABORT);
    env->ReleaseStringUTFChars(language, lang);
    if (result != 0) { env->ThrowNew(env->FindClass("java/lang/IllegalStateException"), "Transkripsi Whisper gagal."); return nullptr; }
    std::ostringstream json;
    json << "[";
    for (int i = 0; i < whisper_full_n_segments(context); ++i) {
        if (i) json << ",";
        json << "{\"start_s\":" << whisper_full_get_segment_t0(context, i) / 100.0
             << ",\"end_s\":" << whisper_full_get_segment_t1(context, i) / 100.0
             << ",\"text\":" << quote(whisper_full_get_segment_text(context, i)) << "}";
    }
    json << "]";
    auto text = json.str();
    auto bytes = env->NewByteArray(text.size());
    env->SetByteArrayRegion(bytes, 0, text.size(), reinterpret_cast<const jbyte *>(text.data()));
    return bytes;
}

extern "C" JNIEXPORT void JNICALL Java_app_cuplik_Whisper_close(JNIEnv *, jclass, jlong handle) {
    if (handle) whisper_free(reinterpret_cast<whisper_context *>(handle));
}
