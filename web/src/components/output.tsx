"use client";

import Link from "next/link";
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
    <section aria-label="Progres output"><p>Status: <strong data-testid="output-status">{output.status}</strong> · Tahap: {output.stage}</p><progress max={1} value={output.progress ?? 0} aria-label="Progres pipeline" /><p role="status">{output.note}</p>{running && <small>{streaming ? "Progres tersambung melalui SSE." : "Memeriksa status berkala; SSE akan tersambung kembali."} Proses worker tetap berjalan ketika tab ditutup.</small>}{output.error && <p className="error">{output.error}</p>}{output.status === "failed" && <button disabled={busy} onClick={() => perform(() => post(`/outputs/${id}/retry`))}>Coba ulang dari cache</button>}</section>
    {error && <p role="alert" className="error">{error}</p>}
    {output.mode === "clips" && data.clips.map(clip => <ClipEditor key={`${clip.id}:${clip.render_fingerprint}`} clip={clip} data={data} disabled={busy || running} perform={perform} />)}
    {output.mode === "clips" && data.clips.length > 0 && <p><a href={`/api/projects/${project.id}/signals`} target="_blank" rel="noreferrer">Data Moment IQ (JSON)</a> · <a href={`/api/outputs/${id}/selection`} target="_blank" rel="noreferrer">Laporan pemilihan dan keragaman (JSON)</a></p>}
    {output.mode === "condense" && output.status === "awaiting_review" && <OutlineEditor data={data} disabled={busy} perform={perform} />}
    {output.mode === "condense" && output.status === "done" && <section><h2>Video ringkasan</h2><p>Durasi render: {output.actual_duration_s?.toFixed(2)} detik</p><video controls preload="metadata" src={`/api/outputs/${id}/file`} width={720} /><a href={`/api/outputs/${id}/file`} download>Unduh ringkasan MP4</a></section>}
    {output.status === "done" && <p><a href={`/api/outputs/${id}/export.zip`} download>Unduh semua hasil (ZIP)</a></p>}
    <p><Link href={`/projects/${project.id}`}>Buat output lain memakai sumber dan transkrip ini</Link></p>
  </>;
}

type Perform = (action: () => Promise<unknown>) => Promise<void>;

function OutlineEditor({ data, disabled, perform }: { data: Detail; disabled: boolean; perform: Perform }) {
  const [target, setTarget] = useState(Number(data.output.settings?.target_seconds ?? 20));
  const [choices, setChoices] = useState<Record<string, boolean>>(() => Object.fromEntries(data.chapters.map(c => [c.id, c.required ?? true])));
  const [plan, setPlan] = useState<{ actual_duration_s: number; within_tolerance: boolean } | null>(null);
  const chapters = data.chapters.map(c => ({ id: c.id, required: choices[c.id] }));
  return <section><h2>Tinjau bab Ringkas</h2><p>Fondasi Ringkas memakai transkrip percakapan. Analisis visual untuk tutorial tanpa suara belum tersedia.</p><form onSubmit={e => { e.preventDefault(); void perform(() => api(`/outputs/${data.output.id}/outline`, { method: "PUT", body: JSON.stringify({ chapters, target_seconds: target }) })); }}><fieldset disabled={disabled}><legend>Bab wajib dan durasi</legend>
    {data.chapters.map(chapter => <label key={chapter.id}><input type="checkbox" checked={choices[chapter.id]} onChange={e => setChoices({ ...choices, [chapter.id]: e.target.checked })} />{chapter.title} · {chapter.goal}</label>)}
    <label>Target durasi (detik)<input type="number" min={3} max={3600} value={target} onChange={e => setTarget(Number(e.target.value))} /></label>
    <div className="row"><button type="button" onClick={() => perform(async () => setPlan(await post(`/outputs/${data.output.id}/solve`, { target_seconds: target, chapters })))}>Hitung durasi tanpa render</button><button type="submit">Setujui bab dan render Ringkas</button></div>
    {plan && <p role="status">Rencana hasil: {plan.actual_duration_s.toFixed(2)} detik. {plan.within_tolerance ? "Dalam toleransi target ±3%." : "Durasi terdekat lebih pendek dari target; semua konten terpilih tetap dipertahankan."}</p>}
  </fieldset></form>
  <details><summary>Keputusan per kalimat</summary>{data.beats.map(beat => <div key={beat.id}><p>{beat.sentence_id}: {beat.text}{beat.required ? " · penanda wajib bab" : ""}</p><label>Keputusan {beat.sentence_id}<select disabled={disabled} value={beat.decision} onChange={e => { const decision = e.target.value; void perform(() => patch(`/beats/${beat.id}`, { decision, speed: 1.15, locked: true })); }}><option value="keep">Normal</option><option value="speed">Percepat 1,15×</option><option value="drop" disabled={beat.required && choices[beat.chapter_id]}>Buang</option></select></label>{beat.locked && <button disabled={disabled} onClick={() => perform(() => patch(`/beats/${beat.id}`, { decision: beat.decision, speed: beat.speed, locked: false }))}>Buka kunci {beat.sentence_id}</button>}</div>)}</details>
  </section>;
}
