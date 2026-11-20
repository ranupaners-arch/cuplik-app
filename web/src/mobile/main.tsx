import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { Badge, Button, Container, Group, MantineProvider } from "@mantine/core";
import { studioTheme } from "../design/theme";
import "@mantine/core/styles.css";
import "@fontsource-variable/plus-jakarta-sans";
import "@fontsource-variable/jetbrains-mono";
import "../../../02-design-system/tokens.css";
import "../app/globals.css";
import "./mobile.css";

type Plan = { id: string; title: string; start_s: number; end_s: number; required: boolean; keep: boolean; locked: boolean; speed: number; text: string; score: number };
type Config = { provider: string; model: string; consent: boolean; has_key?: boolean };
type Output = { file: string; title: string; duration_s: number; duration_matches: boolean; audio_present: boolean; url: string };
type State = { status: string; note: string; progress: number; busy: boolean; retryable?: boolean; active_job?: { status: string; action: string; attempt: number }; model_ready: boolean; source?: { name: string; duration_s: number; url: string }; plan: Plan[]; sentences: unknown[]; outputs: Output[]; models?: string[]; config: Config; error?: string; mode?: string; analysis_provider?: string };
type Bridge = { getState(): string; chooseVideo(): void; saveConfig(json: string): void; testConnection(): void; downloadModel(): void; analyze(json: string): void; solve(json: string): void; render(json: string): void; cancel(): void; retryJob(): void; saveTranscript(json: string): void; saveOutput(file: string): void; clearCache(): void };
declare global { interface Window { CuplikNative?: Bridge } }
const empty: State = { status: "idle", note: "Pilih video dari perangkat.", progress: 0, busy: false, model_ready: false, plan: [], sentences: [], outputs: [], config: { provider: "gemini", model: "", consent: false } };

function App() {
  const initial = useRef<State>(window.CuplikNative ? JSON.parse(window.CuplikNative.getState()) : empty).current;
  const [state, setState] = useState(initial), [plan, setPlan] = useState(initial.plan);
  const [config, setConfig] = useState(initial.config), [key, setKey] = useState("");
  const [error, setError] = useState("");
  const [mode, setMode] = useState(initial.mode ?? "clips"), [language, setLanguage] = useState("id");
  const [count, setCount] = useState(3), [maximum, setMaximum] = useState(60), [target, setTarget] = useState(60);
  const [layout, setLayout] = useState("source"), [captions, setCaptions] = useState(true), [transcript, setTranscript] = useState("");
  const canonicalPlan = useRef(JSON.stringify(initial.plan));
  const refresh = () => {
    if (!window.CuplikNative) return;
    try { const next: State = JSON.parse(window.CuplikNative.getState()); setState(next); const stamp = JSON.stringify(next.plan); if (stamp !== canonicalPlan.current) { canonicalPlan.current = stamp; setPlan(next.plan); } }
    catch (e) { setError((e as Error).message); }
  };
  useEffect(() => { const timer = setInterval(refresh, 1000); return () => clearInterval(timer); }, []);
  const run = (action: (bridge: Bridge) => void) => { setError(""); if (!window.CuplikNative) { setError("Fitur perangkat tersedia di APK Android."); return; } try { action(window.CuplikNative); refresh(); } catch (e) { setError((e as Error).message); } };
  const update = (id: string, changes: Partial<Plan>) => setPlan(current => current.map(row => row.id === id ? { ...row, ...changes } : row));
  const duration = plan.reduce((total, row) => total + (row.keep ? (row.end_s - row.start_s) / row.speed : 0), 0);
  const analyze = (manual: boolean) => run(bridge => bridge.analyze(JSON.stringify({ mode, language, clip_count: count, max_clip_seconds: maximum, target_seconds: target, layout, captions, manual })));
  return <MantineProvider theme={studioTheme} forceColorScheme="dark"><Container size="lg" component="main" className="studio-main android-main">
    <Group justify="space-between"><div><p className="eyebrow">STUDIO VIDEO DI PERANGKATMU</p><h1>cuplik<span className="android-dot">.</span></h1></div><Badge color="turmeric" variant="outline">Android</Badge></Group>
    <p>Video diproses di hape. Analisis AI dapat memakai teks transkrip melalui API.</p>
    {!window.CuplikNative && <p className="notice">Pratinjau UI Android. Buka APK untuk memilih, mentranskrip dan merender video di perangkat.</p>}
    <details><summary>Pengaturan API AI dan model transkripsi</summary>
      <form aria-label="Pengaturan AI Android" onSubmit={event => { event.preventDefault(); run(bridge => bridge.saveConfig(JSON.stringify({ ...config, api_key: key }))); setKey(""); }}><fieldset disabled={state.busy}><legend>API analisis teks</legend>
        <label htmlFor="ai-provider">Provider</label><select id="ai-provider" name="provider" value={config.provider} onChange={e => { setConfig({ ...config, provider: e.target.value, model: "" }); setKey(""); }}><option value="gemini">Gemini</option><option value="anthropic">Anthropic</option></select>
        <label htmlFor="ai-key">Kunci API{state.config.has_key ? " (sudah tersimpan)" : ""}</label><input id="ai-key" name="api_key" type="password" autoComplete="new-password" autoCapitalize="none" spellCheck={false} value={key} onChange={e => setKey(e.target.value)} />
        <label htmlFor="ai-model">Model</label><input id="ai-model" name="model" list="available-models" value={config.model} onChange={e => setConfig({ ...config, model: e.target.value })} placeholder="Periksa koneksi untuk melihat model akun" /><datalist id="available-models">{state.models?.map(model => <option key={model} value={model} />)}</datalist>
        <label><input type="checkbox" checked={config.consent} onChange={e => setConfig({ ...config, consent: e.target.checked })} />Izinkan pengiriman teks transkrip ke provider ini</label>
        <p className="notice">Kunci disimpan terenkripsi di perangkat. Video dan audio tetap diproses di hape. Tanpa API, kamu bisa menyusun pilihan secara manual.</p>
        <div className="row"><Button type="submit">Simpan pengaturan AI</Button><Button type="button" onClick={() => run(bridge => bridge.testConnection())}>Periksa koneksi dan model</Button><Button type="button" color="red" onClick={() => { run(bridge => bridge.saveConfig(JSON.stringify({ ...config, remove_key: true }))); setKey(""); }}>Hapus kunci tersimpan</Button></div>
      </fieldset></form>
      <fieldset disabled={state.busy}><legend>Transkripsi di perangkat</legend><p>Whisper tiny multibahasa, sekitar 78 MB. Diunduh sekali; audio ditranskrip di perangkat. Kualitas dan waktu proses bergantung pada rekaman serta kemampuan hape.</p><Button type="button" disabled={state.model_ready} onClick={() => run(bridge => bridge.downloadModel())}>{state.model_ready ? "Model transkripsi siap" : "Unduh model transkripsi"}</Button></fieldset>
      <p>Simpan MP4 ke lokasi pilihanmu sebelum membersihkan penyimpanan aplikasi.</p><Button type="button" disabled={state.busy} onClick={() => run(bridge => bridge.clearCache())}>Bersihkan video dan cache lokal</Button>
    </details>
    <div className="create-grid"><section><h2>Sumber video</h2><Button type="button" className="studio-primary" disabled={state.busy} onClick={() => run(bridge => bridge.chooseVideo())}>Pilih video dari hape</Button>
      {state.source && <><p>{state.source.name} · {state.source.duration_s.toFixed(1)} detik</p><video controls playsInline preload="metadata" src={state.source.url} /></>}
      <small>Berkas lokal maksimal satu jam / 2 GB. Pertahankan ruang kosong untuk audio, model dan hasil ekspor.</small>
    </section>
    <form aria-label="Proses video Android" onSubmit={event => { event.preventDefault(); analyze(false); }}><fieldset disabled={state.busy}><legend>Output</legend>
      <label htmlFor="android-mode">Mode</label><select id="android-mode" name="mode" value={mode} onChange={e => setMode(e.target.value)}><option value="clips">Klip</option><option value="condense">Ringkas</option></select>
      <label htmlFor="android-language">Bahasa ucapan</label><select id="android-language" name="language" value={language} onChange={e => setLanguage(e.target.value)}><option value="id">Indonesia</option><option value="en">Inggris</option><option value="ar">Arab</option><option value="auto">Deteksi otomatis</option></select>
      {mode === "clips" && <><label htmlFor="android-count">Jumlah klip</label><input id="android-count" name="clip_count" type="number" min={1} max={12} required value={count} onChange={e => setCount(Number(e.target.value))} /><label htmlFor="android-max">Durasi maksimum klip (detik)</label><input id="android-max" name="max_clip_seconds" type="number" min={3} max={180} required value={maximum} onChange={e => setMaximum(Number(e.target.value))} /></>}
      <label htmlFor="android-layout">Bingkai hasil</label><select id="android-layout" name="layout" value={layout} onChange={e => setLayout(e.target.value)}><option value="source">Bingkai sumber utuh</option><option value="portrait">Vertikal 9:16, muat video utuh</option></select>
      <label><input type="checkbox" checked={captions} onChange={e => setCaptions(e.target.checked)} />Caption frasa pendek</label>
      <div className="row"><Button type="submit" disabled={!state.source || !state.model_ready} className="studio-primary">Transkripsi dan susun rencana</Button><Button type="button" disabled={!state.source} onClick={() => analyze(true)}>Susun rencana manual</Button></div>
      {!state.model_ready && <small>Unduh model di Pengaturan untuk memakai transkripsi. Rencana manual dapat dipakai langsung.</small>}
    </fieldset></form></div>
    <section aria-label="Progres Android"><p>Status: <strong data-testid="android-status">{state.status}</strong></p><progress max={1} value={state.busy && state.progress <= 0 ? undefined : Math.max(0, Math.min(1, state.progress))} aria-label="Progres video Android" /><p role="status">{state.note}</p>{(error || state.error) && <p role="alert" className="error">{error || state.error}</p>}{state.busy && <Button type="button" disabled={state.active_job?.status === "cancelling"} onClick={() => run(bridge => bridge.cancel())}>{state.active_job?.status === "cancelling" ? "Menunggu pembatalan…" : "Batalkan proses"}</Button>}{state.retryable && <><p>Pekerjaan sebelumnya dapat dicoba ulang dengan sumber dan pengaturan semula. Checkpoint serta hasil selesai akan digunakan kembali.</p><Button type="button" onClick={() => run(bridge => bridge.retryJob())}>Coba ulang pekerjaan sebelumnya</Button></>}</section>
    {state.sentences.length > 0 && <details><summary>Tinjau dan koreksi transkrip</summary><p>Waktu caption berasal dari segmen transkripsi. Periksa kecocokan dengan audio sebelum ekspor.</p><Button type="button" onClick={() => setTranscript(JSON.stringify(state.sentences, null, 2))}>Muat transkrip untuk diedit</Button><label htmlFor="android-transcript">Transkrip JSON</label><textarea id="android-transcript" name="transcript" value={transcript} onChange={e => setTranscript(e.target.value)} /><Button type="button" disabled={state.busy || !transcript} onClick={() => run(bridge => bridge.saveTranscript(transcript))}>Simpan koreksi transkrip</Button></details>}
    {plan.length > 0 && <section><h2>Tinjau pilihan {state.mode === "condense" ? "Ringkas" : "Klip"}</h2><p>{state.analysis_provider === "manual" ? "Pilihan manual; belum dinilai oleh AI." : `Analisis teks oleh ${state.analysis_provider}. Tinjau sumber, konteks dan langkah yang tidak diucapkan.`}</p>
      <form aria-label="Tinjau rencana Android" onSubmit={event => { event.preventDefault(); run(bridge => bridge.render(JSON.stringify({ plan }))); }}><fieldset disabled={state.busy}><legend>Keputusan sebelum ekspor</legend>
        {plan.map(row => <fieldset key={row.id}><legend>{row.title}</legend><p>{row.text}</p>
          {state.mode === "condense" && <label><input type="checkbox" checked={row.required} disabled={row.locked} onChange={e => update(row.id, { required: e.target.checked, keep: e.target.checked || row.keep })} />Bab wajib</label>}
          <label><input type="checkbox" checked={row.keep} disabled={row.required || row.locked} onChange={e => update(row.id, { keep: e.target.checked })} />Sertakan bagian ini</label>
          {state.mode === "clips" ? <><label htmlFor={`start-${row.id}`}>Awal {row.id} (detik)</label><input id={`start-${row.id}`} name={`start-${row.id}`} type="number" step="any" min={0} max={state.source?.duration_s} required disabled={row.locked} value={row.start_s} onChange={e => update(row.id, { start_s: Number(e.target.value) })} /><label htmlFor={`end-${row.id}`}>Akhir {row.id} (detik)</label><input id={`end-${row.id}`} name={`end-${row.id}`} type="number" step="any" min={0} max={state.source?.duration_s} required disabled={row.locked} value={row.end_s} onChange={e => update(row.id, { end_s: Number(e.target.value) })} /></> : <p>{row.start_s.toFixed(2)}–{row.end_s.toFixed(2)} detik sumber</p>}
          <label htmlFor={`speed-${row.id}`}>Kecepatan {row.id}</label><select id={`speed-${row.id}`} name={`speed-${row.id}`} disabled={row.locked} value={row.speed} onChange={e => update(row.id, { speed: Number(e.target.value) })}>{[...new Set([1, 1.1, 1.15, 1.25, row.speed])].sort((a, b) => a-b).map(speed => <option key={speed} value={speed}>{speed.toLocaleString("id-ID", { maximumFractionDigits: 3 })}×</option>)}</select>
          <label><input type="checkbox" checked={row.locked} onChange={e => update(row.id, { locked: e.target.checked })} />Kunci keputusan ini</label>
        </fieldset>)}
        {state.mode === "condense" && <><label htmlFor="android-target">Target durasi Ringkas (detik)</label><input id="android-target" name="target_seconds" type="number" min={3} max={3600} required value={target} onChange={e => setTarget(Number(e.target.value))} /><Button type="button" onClick={() => run(bridge => bridge.solve(JSON.stringify({ plan, target_seconds: target })))}>Hitung durasi tanpa render</Button></>}
        <p role="status">Estimasi: {duration.toFixed(2)} detik. {state.mode === "clips" ? "Durasi setiap klip diperiksa terpisah." : "Perubahan perhitungan perlu ditinjau sebelum ekspor."}</p><Button type="submit" className="studio-primary">Setujui dan ekspor di hape</Button>
      </fieldset></form>
    </section>}
    {state.outputs.length > 0 && <section><h2>Hasil di perangkat</h2>{state.outputs.map(output => <article key={output.file}><h3>{output.title}</h3><video controls playsInline preload="metadata" src={output.url} /><p>{output.duration_s.toFixed(2)} detik · Durasi: {output.duration_matches ? "sesuai rencana" : "perlu ditinjau"} · Audio: {output.audio_present ? "tersedia" : "perlu ditinjau"}</p><Button type="button" onClick={() => run(bridge => bridge.saveOutput(output.file))}>Simpan MP4 ke perangkat</Button></article>)}</section>}
    <footer className="studio-footer"><small>Cuplik Android · Video lokal, analisis teks online.</small></footer>
  </Container></MantineProvider>;
}

createRoot(document.getElementById("root")!).render(<React.StrictMode><App /></React.StrictMode>);
