package app.cuplik;

import android.media.AudioFormat;
import android.media.MediaCodec;
import android.media.MediaExtractor;
import android.media.MediaFormat;
import java.io.BufferedOutputStream;
import java.io.DataOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.concurrent.atomic.AtomicBoolean;

final class AudioDecoder {
    static void decode(File input, File output, AtomicBoolean cancelled) throws Exception {
        MediaExtractor extractor = new MediaExtractor();
        MediaCodec codec = null;
        File temporary = new File(output.getPath()+".tmp");
        try (DataOutputStream stream = new DataOutputStream(new BufferedOutputStream(new FileOutputStream(temporary)))) {
            extractor.setDataSource(input.getPath());
            MediaFormat format = null;
            for (int i=0;i<extractor.getTrackCount();i++) {
                MediaFormat candidate = extractor.getTrackFormat(i);
                if (candidate.getString(MediaFormat.KEY_MIME).startsWith("audio/")) { extractor.selectTrack(i); format=candidate; break; }
            }
            if (format == null) throw new IllegalArgumentException("Video tidak memiliki audio untuk transkripsi.");
            codec = MediaCodec.createDecoderByType(format.getString(MediaFormat.KEY_MIME));
            codec.configure(format, null, null, 0); codec.start();
            MediaCodec.BufferInfo info = new MediaCodec.BufferInfo();
            boolean inputDone=false, outputDone=false;
            int channels=format.getInteger(MediaFormat.KEY_CHANNEL_COUNT), rate=format.getInteger(MediaFormat.KEY_SAMPLE_RATE), encoding=AudioFormat.ENCODING_PCM_16BIT;
            long frame=0; double next=0; float previous=0;
            while (!outputDone) {
                if (cancelled.get()) throw new InterruptedException("Dibatalkan.");
                if (!inputDone) {
                    int index = codec.dequeueInputBuffer(10000);
                    if (index>=0) {
                        ByteBuffer buffer=codec.getInputBuffer(index);
                        int size=extractor.readSampleData(buffer, 0);
                        if (size<0) { codec.queueInputBuffer(index,0,0,0,MediaCodec.BUFFER_FLAG_END_OF_STREAM); inputDone=true; }
                        else { codec.queueInputBuffer(index,0,size,extractor.getSampleTime(),0); extractor.advance(); }
                    }
                }
                int index=codec.dequeueOutputBuffer(info, 10000);
                if (index==MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                    MediaFormat decoded=codec.getOutputFormat();
                    channels=decoded.getInteger(MediaFormat.KEY_CHANNEL_COUNT); rate=decoded.getInteger(MediaFormat.KEY_SAMPLE_RATE);
                    if (decoded.containsKey(MediaFormat.KEY_PCM_ENCODING)) encoding=decoded.getInteger(MediaFormat.KEY_PCM_ENCODING);
                    if (encoding!=AudioFormat.ENCODING_PCM_16BIT && encoding!=AudioFormat.ENCODING_PCM_FLOAT) throw new IllegalArgumentException("Format PCM audio belum didukung.");
                } else if (index>=0) {
                    ByteBuffer buffer=codec.getOutputBuffer(index).order(ByteOrder.LITTLE_ENDIAN);
                    buffer.position(info.offset); buffer.limit(info.offset+info.size);
                    int sampleBytes=encoding==AudioFormat.ENCODING_PCM_FLOAT?4:2;
                    while (buffer.remaining()>=channels*sampleBytes) {
                        float sample=0;
                        for(int ch=0;ch<channels;ch++) sample+=encoding==AudioFormat.ENCODING_PCM_FLOAT?buffer.getFloat():buffer.getShort()/32768f;
                        sample/=channels;
                        while (next<=frame) {
                            float mixed=frame==0?sample:previous+(sample-previous)*(float)(next-(frame-1));
                            stream.writeInt(Integer.reverseBytes(Float.floatToIntBits(Math.max(-1,Math.min(1,mixed)))));
                            next+=rate/16000.0;
                        }
                        previous=sample; frame++;
                    }
                    outputDone=(info.flags & MediaCodec.BUFFER_FLAG_END_OF_STREAM)!=0;
                    codec.releaseOutputBuffer(index,false);
                }
            }
        } finally { extractor.release(); if(codec!=null){codec.stop();codec.release();} }
        if (!temporary.renameTo(output)) throw new IllegalStateException("Audio tidak dapat disimpan.");
    }
}
