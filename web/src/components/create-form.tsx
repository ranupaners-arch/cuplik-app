"use client";
import { Button } from "@mantine/core";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, post, uploadVideo, type Output, type RuntimeConfig, type Transcript, type Settings, type OutputPreferences } from "@/lib/api";

import { ClipControls, controlValues } from "@/components/clip-controls";
import { CondenseVisionControls } from "@/components/condense-vision-controls";
import { CondenseTimingControls } from "@/components/condense-timing-controls";

export function CreateForm({ projectId }: { projectId?: string }) {
  const [source, setSource] = useState("url");
  const [language, setLanguage] = useState("auto");
  const [createdProject, setCreatedProject] = useState<string | null>(null);
  const [mode, setMode] = useState("clips");
  const [url, setUrl] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [transcript, setTranscript] = useState<File | null>(null);
  const [defaults, setDefaults] = useState<OutputPreferences | null>(null);
  const clipSettings: Partial<Settings> = defaults?.clips ?? {};
  const condenseSettings: Partial<Settings> = defaults?.condense ?? {};
  const updateClips = (value: Partial<Settings>) => setDefaults(current => current ? { ...current, clips: { ...current.clips, ...value } } : current);
  const updateCondense = (value: Partial<Settings>) => setDefaults(current => current ? { ...current, condense: { ...current.condense, ...value } } : current);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [outputs, setOutputs] = useState<Output[]>([]);
  const [config, setConfig] = useState<RuntimeConfig | null>(null);
  const [probe, setProbe] = useState("");
  useEffect(() => {
    api<RuntimeConfig>("/config").then(setConfig).catch(e => setError(e.message));
    api<OutputPreferences>("/preferences").then(setDefaults).catch(e => setError(e.message));
  }, []);

  async function submit(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError(""); setOutputs([]);
    try {
      let id = projectId;
      if (!id) {
        let upload_id: string | undefined;
        let sidecar: Transcript | undefined;
        if (source === "upload") {
          if (!file) throw new Error("Pilih video terlebih dahulu.");
          upload_id = await uploadVideo(file, percent => setNote(`Mengunggah ${percent}%`));
        }
        if (transcript && source !== "demo") sidecar = JSON.parse(await transcript.text());
        setNote("Membuat proyek dan memasukkan tugas ke antrean…");
        const project = await post<{ id: string }>("/projects", { source_kind: source, language, ...(source === "url" ? { url } : {}), ...(upload_id ? { upload_id } : {}), ...(sidecar ? { transcript: sidecar } : {}) });
        id = project.id;
        setCreatedProject(id);
      }
      const created: Output[] = [];
      if (mode === "annotate") {
        setCreatedProject(id!); setNote("Sumber disiapkan untuk anotasi. Pemilihan LLM belum dijalankan."); return;
      }
      // Save every successful output immediately, even if creating the second mode fails.
      for (const selected of mode === "both" ? ["clips", "condense"] : [mode]) {
        const output = await post<Output>(`/projects/${id}/outputs`, { mode: selected, settings: selected === "clips" ? clipSettings : condenseSettings });
        created.push(output); setOutputs([...created]);
      }
      setNote("Tugas tersimpan. Buka output untuk melihat progres; tab ini boleh ditutup.");
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  return <>
    {config && <p className="notice">LLM: <strong>{config.provider}</strong> · {config.model}. {config.provider === "mock" ? "Hasil pemilihan dan skor adalah contoh deterministik untuk menguji workflow." : "Permintaan akan dikirim ke provider yang dikonfigurasi di server."}</p>}
    <form onSubmit={submit} className="create-grid" aria-label="Buat output video">
      {!projectId && <fieldset disabled={busy}><legend>Sumber video</legend>
        <label>Jenis sumber<select value={source} onChange={e => setSource(e.target.value)}><option value="demo">Video demo sintetis (48 detik)</option><option value="upload">Unggah video</option><option value="url">Link YouTube</option></select></label>
        {source === "demo" && <p>Demo berisi pola video, nada sintetis, dan transkrip contoh. Tidak ada rekaman percakapan asli.</p>}
        {source === "url" && <><label>Link YouTube<input type="url" name="source_url" autoCapitalize="none" autoCorrect="off" spellCheck={false} value={url} required onChange={e => setUrl(e.target.value)} placeholder="https://www.youtube.com/watch?v=…" /></label><Button type="button" onClick={async () => { setError(""); setBusy(true); try { const result = await post<{ title: string; duration_s: number }>("/probe", { url }); setProbe(`${result.title} · ${result.duration_s.toFixed(0)} detik`); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } }}>Periksa link</Button><p>{probe}</p></>}
        {source === "upload" && <label>Berkas video<input type="file" accept="video/*" required onChange={e => setFile(e.target.files?.[0] ?? null)} /></label>}
        {source !== "demo" && <><label>Transkrip JSON bertimestamp (opsional)<input type="file" accept="application/json,.json" onChange={e => setTranscript(e.target.files?.[0] ?? null)} /></label><small>Tanpa sidecar, worker memakai Whisper yang perlu dipasang. Format contoh tersedia di <code>examples/transcript.json</code>.</small></>}
        {source !== "demo" && <label>Bahasa transkripsi<select value={language} onChange={e => setLanguage(e.target.value)}><option value="auto">Deteksi otomatis</option><option value="id">Indonesia</option><option value="en">Inggris</option><option value="ar">Arab</option></select></label>}
      </fieldset>}
      <fieldset disabled={busy || !defaults}><legend>Output</legend>
        <label>Mode<select value={mode} onChange={e => setMode(e.target.value)}><option value="clips">Klip</option><option value="condense">Ringkas</option><option value="both">Klip dan Ringkas</option><option value="annotate">Siapkan sumber untuk anotasi</option></select></label>
        {(mode === "clips" || mode === "both") && <>
          <label>Jumlah klip<input type="number" min={1} max={12} required value={clipSettings.clip_count ?? 8} onChange={e => updateClips({ clip_count: Number(e.target.value) })} /></label>
          <ClipControls value={controlValues(clipSettings)} onChange={value => updateClips(value)} />
          <label>Durasi minimum klip (detik)<input type="number" min={1} max={clipSettings.max_clip_seconds ?? 60} required value={clipSettings.min_clip_seconds ?? 3} onChange={e => updateClips({ min_clip_seconds: Number(e.target.value) })} /></label>
          <label>Durasi maksimum klip (detik)<input type="number" min={clipSettings.min_clip_seconds ?? 3} max={180} required value={clipSettings.max_clip_seconds ?? 60} onChange={e => updateClips({ max_clip_seconds: Number(e.target.value) })} /></label>
          <small>Jumlah hasil dapat lebih sedikit jika kandidat tidak memenuhi durasi atau keragaman topik.</small>
          <label>Fokus momen Klip<textarea maxLength={1000} value={clipSettings.focus ?? ""} onChange={e => updateClips({ focus: e.target.value })} placeholder="Contoh: langkah pencatatan uang usaha" /></label>
        </>}
        {(mode === "condense" || mode === "both") && <>
          <label>Target ringkasan (detik)<input type="number" min={3} max={3600} required value={condenseSettings.target_seconds ?? 20} onChange={e => updateCondense({ target_seconds: Number(e.target.value) })} /></label>
          <label>Fokus Ringkas<textarea maxLength={1000} value={condenseSettings.focus ?? ""} onChange={e => updateCondense({ focus: e.target.value })} /></label>
          <label><input type="checkbox" checked={condenseSettings.captions ?? true} onChange={e => updateCondense({ captions: e.target.checked })} />Caption Ringkas</label>
          <CondenseVisionControls value={condenseSettings.condense_vision ?? { enabled: false, screen_tutorial: false, max_frames: 720 }} onChange={value => updateCondense({ condense_vision: value })} />
          <CondenseTimingControls value={condenseSettings} onChange={updateCondense} />
        </>}
        <Button type="submit" className="studio-primary" fullWidth loading={busy}>{busy ? "Mengirim…" : projectId ? "Buat output dari proyek ini" : "Mulai proses"}</Button>
      </fieldset>
    </form>
    <p role="status">{note}</p>{error && <p role="alert" className="error">{error}</p>}
    {createdProject && <p><Link href={`/projects/${createdProject}`}>Lihat progres sumber dan transkrip</Link></p>}
    {createdProject && mode === "annotate" && <p><Link href={`/projects/${createdProject}/evaluate`}>Buka anotasi setelah sumber siap</Link></p>}
    {outputs.length > 0 && <section><h2>Output dibuat</h2><ul>{outputs.map(output => <li key={output.id}><Link href={`/outputs/${output.id}`}>Buka output {output.mode === "clips" ? "Klip" : "Ringkas"}</Link></li>)}</ul></section>}
  </>;
}
