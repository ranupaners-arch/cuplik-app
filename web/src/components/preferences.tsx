"use client";
import { Button } from "@mantine/core";
import { useEffect, useState } from "react";
import { api, post, type RuntimeConfig, type OutputPreferences } from "@/lib/api";
import { ClipControls, controlValues } from "@/components/clip-controls";

type GlossaryTerm = { id: string; wrong: string; correct: string };

export function Preferences() {
  const [config, setConfig] = useState<RuntimeConfig | null>(null);
  const [error, setError] = useState("");
  const [terms, setTerms] = useState<GlossaryTerm[]>([]);
  const [wrong, setWrong] = useState("");
  const [correct, setCorrect] = useState("");
  const [busy, setBusy] = useState(false);
  const [defaults, setDefaults] = useState<OutputPreferences | null>(null);
  const [saved, setSaved] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  useEffect(() => { api<RuntimeConfig>("/config").then(setConfig).catch(e => setError(e.message)); }, []);
  useEffect(() => { api<GlossaryTerm[]>("/glossary").then(setTerms).catch(e => setError(e.message)); }, []);
  useEffect(() => { api<OutputPreferences>("/preferences").then(setDefaults).catch(e => setError(e.message)); }, []);
  return <><p>Konfigurasi dasar dibaca dari server. Ubah .env dan restart aplikasi untuk mengganti provider atau resolusi.</p>{error && <p role="alert" className="error">{error}</p>}{config ? <dl><dt>Provider LLM</dt><dd>{config.provider}</dd><dt>Model</dt><dd>{config.model || "Belum diisi"}</dd><dt>Konfigurasi provider</dt><dd>{config.live_configured ? "Terisi" : "Belum lengkap"}</dd><dt>Tinggi render</dt><dd>{config.render_height}px</dd><dt>Batas unggah</dt><dd>{(config.max_upload_bytes/1024**3).toFixed(1)} GiB</dd></dl> : !error && <p>Memuat konfigurasi…</p>}
    <section><h2>Default output</h2><p>Berlaku pada output baru. Pengaturan klip yang sudah dibuat tetap dapat disunting sendiri.</p>{defaults?.clips && defaults.condense && <form onSubmit={async e => { e.preventDefault(); setBusy(true); setError(""); setSaved(""); try { setDefaults(await api("/preferences", { method: "PUT", body: JSON.stringify(defaults) })); setSaved("Preferensi tersimpan."); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } }}><fieldset disabled={busy}><legend>Default Klip</legend>
      <ClipControls value={controlValues(defaults.clips)} onChange={value => setDefaults({ ...defaults, caption_preset: value.retention.karaoke ? "karaoke" : "compact", clips: { ...defaults.clips, ...value } })} />
      <label>Jumlah klip bawaan<input type="number" min={1} max={12} required value={defaults.clips.clip_count} onChange={e => setDefaults({ ...defaults, clips: { ...defaults.clips, clip_count: Number(e.target.value) } })} /></label>
      <label>Minimum klip bawaan (detik)<input type="number" min={1} max={180} required value={defaults.clips.min_clip_seconds} onChange={e => setDefaults({ ...defaults, clips: { ...defaults.clips, min_clip_seconds: Number(e.target.value) } })} /></label>
      <label>Maksimum klip bawaan (detik)<input type="number" min={3} max={180} required value={defaults.clips.max_clip_seconds} onChange={e => setDefaults({ ...defaults, clips: { ...defaults.clips, max_clip_seconds: Number(e.target.value) } })} /></label>
      <label>Fokus Klip bawaan<textarea maxLength={1000} value={defaults.clips.focus} onChange={e => setDefaults({ ...defaults, clips: { ...defaults.clips, focus: e.target.value } })} /></label>
    </fieldset><fieldset disabled={busy}><legend>Default Ringkas</legend>
      <label>Target ringkasan bawaan (detik)<input type="number" min={3} max={3600} required value={defaults.condense.target_seconds} onChange={e => setDefaults({ ...defaults, condense: { ...defaults.condense, target_seconds: Number(e.target.value) } })} /></label>
      <label>Batas kecepatan bicara<input type="number" step={0.01} min={1} max={1.25} required value={defaults.condense.max_speech_speed} onChange={e => setDefaults({ ...defaults, condense: { ...defaults.condense, max_speech_speed: Number(e.target.value) } })} /></label>
      <label>Fokus Ringkas bawaan<textarea maxLength={1000} value={defaults.condense.focus} onChange={e => setDefaults({ ...defaults, condense: { ...defaults.condense, focus: e.target.value } })} /></label>
      <label><input type="checkbox" checked={defaults.condense.captions ?? true} onChange={e => setDefaults({ ...defaults, condense: { ...defaults.condense, captions: e.target.checked } })} />Caption Ringkas</label>
    </fieldset><Button type="submit" disabled={busy}>Simpan preferensi output</Button><p role="status">{saved}</p></form>}</section>
    <section><h2>Glosarium transkripsi</h2><p>Koreksi satu kata tanpa mengubah waktunya. Istilah juga menjadi petunjuk Whisper. Berlaku pada proyek baru; transkrip proyek yang sudah selesai tetap memakai cache.</p><form onSubmit={async e => { e.preventDefault(); setBusy(true); setError(""); try { if (editing) await api(`/glossary/${editing}`, { method: "PUT", body: JSON.stringify({ wrong, correct }) }); else await post("/glossary", { wrong, correct }); setTerms(await api("/glossary")); setWrong(""); setCorrect(""); setEditing(null); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } }}><fieldset disabled={busy}><legend>{editing ? "Ubah koreksi kata" : "Tambah koreksi kata"}</legend><label>Kata yang salah<input value={wrong} required maxLength={120} onChange={e => setWrong(e.target.value)} placeholder="nahu" /></label><label>Kata yang benar<input value={correct} required maxLength={120} onChange={e => setCorrect(e.target.value)} placeholder="nahwu" /></label><Button type="submit">Simpan istilah</Button>{editing && <Button type="button" onClick={() => { setEditing(null); setWrong(""); setCorrect(""); }}>Batal ubah istilah</Button>}</fieldset></form><ul>{terms.map(term => <li key={term.id}>{term.wrong} → {term.correct} <Button type="submit" disabled={busy} aria-label={`Ubah istilah ${term.wrong}`} onClick={() => { setEditing(term.id); setWrong(term.wrong); setCorrect(term.correct); }}>Ubah</Button> <Button type="submit" disabled={busy} aria-label={`Hapus istilah ${term.wrong}`} onClick={async () => { setBusy(true); setError(""); try { await api(`/glossary/${term.id}`, { method: "DELETE" }); setTerms(await api("/glossary")); if (editing === term.id) { setEditing(null); setWrong(""); setCorrect(""); } } catch (e) { setError((e as Error).message); } finally { setBusy(false); } }}>Hapus</Button></li>)}</ul></section>
  </>;
}
