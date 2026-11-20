"use client";
import { Button } from "@mantine/core";

import Link from "next/link";
import { CondenseTimingControls } from "@/components/condense-timing-controls";
import { useEffect, useState } from "react";
import { api, patch, post, type Detail } from "@/lib/api";
import { ClipEditor } from "@/components/clip-editor";

export function OutputPage({ id }: { id: string }) {
  const [data, setData] = useState<Detail | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    let active = true, pending = false, repeat = false;
    const stream = new EventSource(`/api/outputs/${id}/events`);
    const load = async () => {
      if (pending) { repeat = true; return; }
      pending = true;
      try {
        const value = await api<Detail>(`/outputs/${id}`);
        if (active) setData(value);
        if (["done", "failed", "awaiting_review"].includes(value.output.status ?? "")) {
          stream.close(); clearInterval(timer); if (active) setStreaming(false);
        }
      } catch (e) { if (active) setError((e as Error).message); }
      finally { pending = false; if (repeat && active) { repeat = false; void load(); } }
    };
    stream.onopen = () => { if (active) setStreaming(true); };
    stream.addEventListener("progress", () => void load());
    stream.addEventListener("complete", () => { stream.close(); void load(); });
    stream.onerror = () => { if (active) setStreaming(false); };
    const timer = setInterval(() => void load(), 4000);
    void load();
    return () => { active = false; stream.close(); clearInterval(timer); };
  }, [id, revision]);

  async function perform(action: () => Promise<unknown>) {
    setBusy(true); setError("");
    try { await action(); setRevision(v => v+1); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  if (!data) return <>{error ? <p role="alert" className="error">{error}</p> : <p>Memuat output…</p>}</>;
  const { output, project } = data;
  const running = ["queued", "running"].includes(output.status ?? "");
  return <>
    <h1>Output {output.mode === "clips" ? "Klip" : "Ringkas"}</h1>
    <p><Link href={`/projects/${project.id}`}>{project.title}</Link> · Provider: <strong>{output.provider}</strong></p>
    {project.source_kind === "demo" && <p className="notice">Sumber demo sintetis: pola video dan nada uji dengan transkrip contoh.</p>}
    {project.transcript_status !== "done" && <p role="status">Sumber: {project.stage} · {project.note} <Link href={`/projects/${project.id}`}>Lihat progres sumber</Link></p>}
    {output.provider === "mock" && <p className="notice">Pemilihan momen, bab, dan skor memakai fixture deterministik. MP4 dirender oleh FFmpeg.</p>}
    <section aria-label="Progres output"><p>Status: <strong data-testid="output-status">{output.status}</strong> · Tahap: {output.stage}</p><progress max={1} value={output.progress ?? 0} aria-label="Progres pipeline" /><p role="status">{output.note}</p>{running && <small>{streaming ? "Progres tersambung melalui SSE." : "Memeriksa status berkala; SSE akan tersambung kembali."} Proses worker tetap berjalan ketika tab ditutup.</small>}{output.error && <p className="error">{output.error}</p>}{output.status === "failed" && <Button type="submit" disabled={busy} onClick={() => perform(() => post(`/outputs/${id}/retry`))}>Coba ulang dari cache</Button>}</section>
    {error && <p role="alert" className="error">{error}</p>}
    {output.mode === "clips" && data.clips.map(clip => <ClipEditor key={`${clip.id}:${clip.render_fingerprint}`} clip={clip} data={data} disabled={busy || running} perform={perform} />)}
    {output.mode === "clips" && data.clips.length > 0 && <p><a href={`/api/projects/${project.id}/signals`} target="_blank" rel="noreferrer">Data Moment IQ (JSON)</a> · <a href={`/api/outputs/${id}/selection`} target="_blank" rel="noreferrer">Laporan pemilihan dan keragaman (JSON)</a></p>}
    {data.vision_report && <details><summary>Bukti visual Ringkas</summary>
      <p>{data.vision_report.provider} · {data.vision_report.vision_model} · {data.vision_report.frame_count} frame · {data.vision_report.speech_beats} beat bicara · {data.vision_report.visual_beats} beat visual.</p>
      <ul>{data.vision_report.notes.map((note, index) => <li key={index}>{note}</li>)}</ul>
      <p><a href={`/api/outputs/${id}/vision`} target="_blank" rel="noreferrer">Laporan seluruh frame (JSON)</a></p>
      <ol>{data.vision_report.frames.slice(0, 12).map(frame => <li key={frame.id}>
        <p>{frame.id} · {frame.time_s.toFixed(2)} detik sumber · {frame.beat_id}{frame.uncertain ? " · perlu ditinjau" : ""}</p>
        <a href={frame.url} target="_blank" rel="noreferrer"><img src={frame.url} alt={frame.action} width={frame.width} height={frame.height} loading="lazy" style={{ maxWidth: "100%", height: "auto" }} /></a>
        <p>{frame.action}</p>{frame.screen_text && <p>Teks terlihat: {frame.screen_text}</p>}
        {(frame.objects?.length ?? 0) > 0 && <p>Objek menurut provider: {frame.objects?.join(", ")}</p>}
        {frame.hands_visible != null && <p>Tangan menurut provider: {frame.hands_visible ? "terlihat" : "tidak terlihat"}.</p>}
      </li>)}</ol>
      {data.vision_report.frame_count > 12 && <p>Menampilkan 12 frame pertama. Seluruh bukti tersedia pada laporan JSON.</p>}
    </details>}
    {data.coherence_report && <CoherenceReview data={data} />}
    {output.mode === "condense" && output.status === "awaiting_review" && <OutlineEditor data={data} disabled={busy} perform={perform} />}
    {output.mode === "condense" && output.status === "done" && <section>
      <h2>Video ringkasan</h2><p>Durasi render: {output.actual_duration_s?.toFixed(2)} detik</p>
      <video controls playsInline preload="metadata" src={`/api/outputs/${id}/file`} width={960} />
      <a href={`/api/outputs/${id}/file`} download>Unduh ringkasan MP4</a>
      {data.condense_qc && <CondenseQuality report={data.condense_qc} id={id} />}
      {data.chapter_export && <details>
        <summary>Daftar bab dan unduhan</summary>
        <p>{data.chapter_export.timing_source === "encoded_parts" ? "Waktu bab mengikuti durasi segmen hasil render." : "Indeks lama memakai durasi rencana; waktu terhadap video belum diverifikasi."}</p>
        <p>{data.chapter_export.youtube_valid ? "Format timestamp memenuhi pemeriksaan untuk deskripsi YouTube." : "Indeks bab tersedia untuk tinjauan. Versi YouTube belum memenuhi pemeriksaan format."}</p>
        {(data.chapter_export.reasons?.length ?? 0) > 0 && <ul>{(data.chapter_export.reasons ?? []).map((reason, index) => <li key={index}>{reason}</li>)}</ul>}
        {data.chapter_export.index_text && <>
          <pre tabIndex={0} role="region" aria-label="Indeks bab hasil render">{data.chapter_export.index_text}</pre>
          <p><a href={`/api/outputs/${id}/chapters.txt`} download>Unduh indeks bab (TXT)</a></p>
        </>}
        {data.chapter_export.youtube_valid && <p><a href={`/api/outputs/${id}/chapters.txt?format=youtube`} download>Unduh bab untuk YouTube (TXT)</a></p>}
        <p><a href={`/api/outputs/${id}/chapters`} target="_blank" rel="noreferrer">Laporan pemeriksaan bab (JSON)</a></p>
      </details>}
    </section>}
    {output.status === "done" && <p><a href={`/api/outputs/${id}/export.zip`} download>Unduh semua hasil (ZIP)</a></p>}
    <p><Link href={`/projects/${project.id}`}>Buat output lain memakai sumber dan transkrip ini</Link></p>
  </>;
}

type Perform = (action: () => Promise<unknown>) => Promise<void>;

function CondenseQuality({ report, id }: { report: Record<string, unknown>; id: string }) {
  const checks = (report.checks ?? {}) as Record<string, boolean>;
  const levels = (report.loudness ?? {}) as Record<string, number | null>;
  const labels: Record<string, string> = { duration: "Durasi rencana", target_duration: "Target durasi", stream_alignment: "Waktu stream audio/video", chapter_timeline: "Timestamp bab", black_frames: "Gambar hitam", silence: "Hening tidak disengaja", loudness: "Volume suara", true_peak: "Puncak audio" };
  return <details open={report.passed === false}><summary>Pemeriksaan kualitas Ringkas · {report.passed ? "lolos" : "perlu ditinjau"}</summary>
    <ul>{Object.entries(checks).map(([key, passed]) => <li key={key}>{labels[key] ?? key}: {passed ? "lolos" : "perlu ditinjau"}</li>)}</ul>
    <p>Loudness: {levels.input_i == null ? "tidak terukur" : `${levels.input_i.toFixed(1)} LUFS`}. Hening timelapse yang sudah disetujui diperhitungkan sesuai rentangnya.</p>
    <p>{String(report.limitations ?? "")}</p><a href={`/api/outputs/${id}/qc`} target="_blank" rel="noreferrer">Laporan QC Ringkas (JSON)</a>
  </details>;
}

function CoherenceReview({ data }: { data: Detail }) {
  const report = data.coherence_report!;
  const excerpt = (id: string) => {
    const beat = data.beats.find(b => b.id === id);
    return beat ? `${beat.start_s.toFixed(2)}–${beat.end_s.toFixed(2)} detik: ${beat.text || beat.visual_desc || id}` : id;
  };
  return <details open={report.status === "needs_review"}><summary>Pemeriksaan koherensi Ringkas</summary>
    <p>{report.provider} · {report.model} · {report.rounds} putaran.</p>
    <p>{report.stale ? "Rencana sudah berubah. Laporan ini berasal dari pilihan sebelumnya; pemeriksaan akan diulang saat render jika diaktifkan." : report.provider === "mock" ? "Hasil fixture untuk menguji alur; kualitas koherensi belum dinilai oleh model nyata." : report.status === "passed" ? "Tidak ada masalah ditemukan dalam jendela naskah yang diperiksa." : "Rencana membutuhkan tinjauan sebelum render."}</p>
    <p>{report.note}</p>
    {report.min_duration_s != null && <p>Durasi minimum yang dibutuhkan: {report.min_duration_s.toFixed(2)} detik.</p>}
    {report.restored_ids.length > 0 && <><p>Konteks dipulihkan:</p><ul>{report.restored_ids.map(id => <li key={id}>{excerpt(id)}</li>)}</ul></>}
    {report.dropped_ids.length > 0 && <><p>Bagian yang dilepas setelah perhitungan ulang:</p><ul>{report.dropped_ids.map(id => <li key={id}>{excerpt(id)}</li>)}</ul></>}
    <ul>{report.issues.map((issue, index) => <li key={index}>{excerpt(issue.at_id)} — {issue.note}{(issue.restore_ids?.length ?? 0) > 0 && <p>Konteks yang diperlukan: {issue.restore_ids?.map(excerpt).join("; ")}</p>}</li>)}</ul>
    <a href={`/api/outputs/${data.output.id}/coherence`} target="_blank" rel="noreferrer">Laporan koherensi (JSON)</a>
  </details>;
}

function OutlineEditor({ data, disabled, perform }: { data: Detail; disabled: boolean; perform: Perform }) {
  const [target, setTarget] = useState(Number(data.output.settings?.target_seconds ?? 20));
  const [choices, setChoices] = useState<Record<string, boolean>>(() => Object.fromEntries(data.chapters.map(c => [c.id, c.required ?? true])));
  const [plan, setPlan] = useState<{ actual_duration_s: number; within_tolerance: boolean } | null>(null);
  const [approvals, setApprovals] = useState<Record<string, boolean>>({});
  useEffect(() => {
    setApprovals(current => {
      const next = { ...current };
      let changed = false;
      for (const beat of data.beats) {
        if (next[beat.id] !== undefined && next[beat.id] === beat.timelapse_approved) { delete next[beat.id]; changed = true; }
      }
      return changed ? next : current;
    });
  }, [data.beats]);
  const [timing, setTiming] = useState({ max_speech_speed: Number(data.output.settings?.max_speech_speed ?? 1.15), timelapse_enabled: data.output.settings?.timelapse_enabled === true, max_visual_speed: Number(data.output.settings?.max_visual_speed ?? 8), coherence_enabled: data.output.settings?.coherence_enabled === true, chapter_cards: data.output.settings?.chapter_cards === true });
  const chapters = data.chapters.map(c => ({ id: c.id, required: choices[c.id] }));
  const usingVision = Boolean(data.vision_report) || data.beats.some(beat => Array.isArray(beat.evidence?.frame_ids));
  return <section><h2>Tinjau bab Ringkas</h2><p>{usingVision ? "Outline menggabungkan transkrip dan sampel visual. Tonton sumber dan periksa spesifikasi serta langkah yang belum jelas sebelum menyetujui." : "Outline memakai transkrip. Pilih vision pada output baru untuk memasukkan jeda demonstrasi di luar kalimat."}</p><p><a href={`/api/projects/${data.project.id}/source`} target="_blank" rel="noreferrer">Tonton sumber asli untuk meninjau langkah</a></p>{usingVision && !data.vision_report && <p>Laporan frame tidak tersedia. Periksa bukti per beat dan sumber asli sebelum menyetujui.</p>}<form onSubmit={e => { e.preventDefault(); void perform(() => api(`/outputs/${data.output.id}/outline`, { method: "PUT", body: JSON.stringify({ chapters, target_seconds: target, ...timing }) })); }}><fieldset disabled={disabled}><legend>Bab wajib dan durasi</legend>
    {data.chapters.map(chapter => <label key={chapter.id}><input type="checkbox" checked={choices[chapter.id]} onChange={e => setChoices({ ...choices, [chapter.id]: e.target.checked })} />{chapter.title} · {chapter.goal}</label>)}
    <label>Target durasi (detik)<input type="number" min={3} max={3600} value={target} onChange={e => setTarget(Number(e.target.value))} /></label>
    <CondenseTimingControls value={timing} onChange={value => setTiming(current => ({ ...current, ...value }))} />
    <p>Hitung durasi untuk menerapkan batas kecepatan sebelum memilih percepatan per beat.</p>
    <div className="row"><Button type="button" onClick={() => perform(async () => setPlan(await post(`/outputs/${data.output.id}/solve`, { target_seconds: target, chapters, ...timing })))}>Hitung durasi tanpa render</Button><Button type="submit">Setujui bab dan render Ringkas</Button></div>
    {plan && <p role="status">Rencana hasil: {plan.actual_duration_s.toFixed(2)} detik. {plan.within_tolerance ? "Dalam toleransi target ±3%." : "Durasi terdekat lebih pendek dari target; semua konten terpilih tetap dipertahankan."}</p>}
  </fieldset></form>
  <details><summary>Keputusan per beat</summary>{data.beats.map(beat => {
    const name = typeof beat.evidence?.id === "string" ? beat.evidence.id : beat.sentence_id || beat.id.slice(0, 8);
    const specs = Array.isArray(beat.evidence?.specs) ? beat.evidence.specs : [];
    const eligible = beat.kind === "visual" && ["manual", "idle", "repeat"].includes(beat.label ?? "") && specs.length === 0;
    const speech = Number(data.output.settings?.max_speech_speed ?? 1.15);
    const duration = beat.end_s - beat.start_s;
    const cap = data.output.settings?.timelapse_enabled !== true ? speech : beat.kind === "visual" && (specs.length || beat.label === "spec") ? 1 : beat.label === "result" ? Math.max(1, Math.min(speech, duration / 2)) : eligible && beat.timelapse_approved && data.output.settings?.timelapse_enabled === true && duration >= 2.4 ? Math.min(Number(data.output.settings?.max_visual_speed ?? 8), duration / 1.2) : speech;
    const speeds = [...new Set([Math.min(speech, cap), ...[2, 4, 8].filter(rate => rate <= cap), ...(beat.decision === "speed" ? [beat.speed ?? 1] : [])])].filter(rate => rate > 1).sort((a, b) => a-b);
    return <div key={beat.id}>
      <p>{name} · {beat.start_s.toFixed(2)}–{beat.end_s.toFixed(2)} detik · {beat.kind} · {beat.label}{beat.required ? " · penanda wajib bab" : ""}{beat.evidence?.uncertain === true ? " · perlu ditinjau" : ""}</p>
      {beat.text && <p>{beat.text}</p>}{beat.visual_desc && <p>Visual: {beat.visual_desc}</p>}{specs.length > 0 && <p>Spesifikasi: {specs.join(", ")}</p>}{beat.evidence?.coherence_required === true && <p>Konteks dipulihkan oleh pemeriksaan koherensi. Memilih Buang menghapus penanda ini.</p>}
      {eligible && <div><input id={`timelapse-${beat.id}`} type="checkbox" checked={approvals[beat.id] ?? beat.timelapse_approved ?? false} disabled={disabled} onChange={e => { const approved = e.target.checked; setApprovals(current => ({ ...current, [beat.id]: approved })); void perform(async () => { try { await patch(`/beats/${beat.id}`, { decision: approved ? beat.decision : "keep", speed: approved ? beat.speed : 1, locked: beat.locked, timelapse_approved: approved }); } catch (error) { setApprovals(current => { const next = { ...current }; delete next[beat.id]; return next; }); throw error; } }); }} /><label htmlFor={`timelapse-${beat.id}`}>Saya sudah meninjau {name}: izinkan timelapse dan audio hening</label></div>}
      <label htmlFor={`decision-${beat.id}`}>Keputusan {name}</label><select id={`decision-${beat.id}`} disabled={disabled} value={beat.decision === "speed" ? `speed:${beat.speed}` : beat.decision} onChange={e => { const [decision, rate] = e.target.value.split(":"); void perform(() => patch(`/beats/${beat.id}`, { decision, speed: decision === "speed" ? Number(rate) : 1, locked: true })); }}><option value="keep">Normal</option>{speeds.map(rate => <option key={rate} value={`speed:${rate}`}>Percepat {rate.toLocaleString("id-ID", { maximumFractionDigits: 3 })}×{rate > speech ? " (audio hening)" : ""}</option>)}<option value="drop" disabled={beat.required && choices[beat.chapter_id]}>Buang</option></select>
      {beat.locked && <Button type="button" disabled={disabled} onClick={() => perform(() => patch(`/beats/${beat.id}`, { decision: beat.decision, speed: beat.speed, locked: false }))}>Buka kunci {name}</Button>}
    </div>;
  })}</details>
  </section>;
}
